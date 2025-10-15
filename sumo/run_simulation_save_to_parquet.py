from contextlib import contextmanager
from pathlib import Path
from typing import cast

import sumolib
import traci
import numpy as np
import polars as pl

from pyproj import Geod

ROOT_PATH = Path(".").resolve().absolute()
BASE_PATH = ROOT_PATH / "sumo/simulations/ohare-chicago"
NETWORK_PATH = BASE_PATH / "network.net.xml"
SIMULATION_PATH = BASE_PATH / "simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "output"
NOISE_METERS_STD: float | None = 5
RANDOM_SEED = 42


type Node = sumolib.net.node.Node
type Edge = sumolib.net.edge.Edge
type Net = sumolib.net.Net
type Lane = sumolib.net.lane.Lane
type Conn = sumolib.net.connection.Connection


def map_internal_lanes_to_osm_edges(network_path: Path) -> dict[str, str]:
    """
    Scans a SUMO network file and creates a mapping from each internal LANE ID
    (e.g., ':cluster_..._4_0') to its original OpenStreetMap edge/way ID.

    Args:
        network_path: The path to the .net.xml file.

    Returns:
        A dictionary mapping internal lane IDs to original OSM edge IDs.
    """
    print(f"Loading network from {network_path}...")
    net: Net = sumolib.net.readNet(network_path, withInternal=True)

    internal_lane_to_osm_edge: dict[str, str] = {}

    try:
        cluster_osm_maps: dict[str, dict[str, str]] = {}
        for node in net.getNodes():
            junction_id = node.getID()
            if not junction_id.startswith("cluster"):
                continue

            params = node.getParams()
            orig_ids_str = params.get("origId")
            orig_edge_ids_str = params.get("origEdgeIds")

            if orig_ids_str and orig_edge_ids_str:
                orig_ids_list = orig_ids_str.split()
                orig_edge_ids_list = orig_edge_ids_str.split()
                cluster_osm_maps[junction_id] = dict(
                    zip(orig_ids_list, orig_edge_ids_list)
                )

        edges: list[Edge] = net.getEdges()
        lanes: list[Lane] = []
        for edge in edges:
            lanes.extend(edge.getLanes())

        for lane in lanes:
            internal_lane_id = lane.getID()
            if not internal_lane_id.startswith(":"):
                continue

            incoming_conns = lane.getIncomingConnections()
            if not incoming_conns:
                continue

            connection = incoming_conns[0]
            from_edge = connection.getFromLane().getEdge()

            orig_to_node = from_edge.getParams().get("origTo")
            if not orig_to_node:
                continue

            base_cluster_id = lane.getEdge().getToNode().getID()
            osm_map = cluster_osm_maps.get(base_cluster_id)

            if osm_map and (orig_eid := osm_map.get(orig_to_node)):
                internal_lane_to_osm_edge[internal_lane_id] = orig_eid

    except Exception as e:
        print(f"An error occurred while processing the network file: {e}")
        raise

    return internal_lane_to_osm_edge


@contextmanager
def traci_session(cmd: list[str]):
    traci.start(cmd)
    try:
        yield traci
    finally:
        traci.close()


def write_parquet_with_options(
    df: pl.DataFrame,
    output_path: Path,
) -> None:
    df.write_parquet(
        output_path,
        mkdir=True,
        compression="zstd",
        compression_level=3,
        row_group_size=100_000,
        statistics=True,
    )


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    jid_to_osmid = map_internal_lanes_to_osm_edges(NETWORK_PATH)

    vehicle_ids = pl.Series(dtype=pl.Int32)
    geo_positions = pl.Series(dtype=pl.Array(pl.Float64, shape=2))
    times = pl.Series(dtype=pl.Float64)
    lanes = pl.Series(dtype=pl.String)

    with traci_session(cmd) as session:
        while cast(int, session.simulation.getMinExpectedNumber()) > 0:
            session.simulation.step()

            current_vehicles = pl.Series(
                session.vehicle.getIDList(), dtype=pl.String
            ).cast(pl.Categorical)

            if len(current_vehicles) == 0:
                continue

            current_pos = current_vehicles.map_elements(
                traci.vehicle.getPosition,
                return_dtype=pl.Array(pl.Float64, shape=2),
            )

            current_geo = current_pos.map_elements(
                lambda pos: traci.simulation.convertGeo(pos[0], pos[1]),
                return_dtype=pl.List(pl.Float64),
            ).cast(pl.Array(pl.Float64, shape=2))

            current_lanes = current_vehicles.map_elements(
                session.vehicle.getLaneID, return_dtype=pl.String
            )

            current_time = pl.Series(
                np.full(len(current_vehicles), session.simulation.getTime()),
                dtype=pl.Float64,
            )

            vehicle_ids.append(current_vehicles.cast(pl.Int32))
            geo_positions.append(current_geo)
            times.append(current_time)
            lanes.append(current_lanes)

    lf = pl.LazyFrame(
        (
            vehicle_ids.alias("vehicle_id"),
            geo_positions.alias("geo_position"),
            times.alias("time"),
            lanes.alias("raw_lane_id").cast(pl.Categorical),
        )
    )

    lf = lf.with_columns(
        pl.col("raw_lane_id")
        .replace_strict(
            jid_to_osmid, default=pl.col("raw_lane_id"), return_dtype=pl.String
        )
        .cast(pl.Categorical)
        .alias("mapped_lane_id")
    )

    lf = lf.with_columns(
        pl.col("mapped_lane_id")
        .cast(pl.String)
        .str.extract(r"(-?\d+)(?:.*)", 1)
        .alias("edge_id")
    )

    lf = lf.with_columns(
        pl.col("edge_id").str.starts_with("-").alias("reversed"),
        pl.col("edge_id").str.replace("-", "").cast(pl.Categorical),
    )

    lf = lf.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    df = lf.collect()

    write_parquet_with_options(df, OUTPUT_PATH / "fcd.parquet")

    print("Simulation data saved to", OUTPUT_PATH / "fcd.parquet")
    print(df)

    if NOISE_METERS_STD is not None:
        geod = Geod(ellps="WGS84")
        rng = np.random.default_rng(RANDOM_SEED)

        lon = df["lon"].to_numpy()
        lat = df["lat"].to_numpy()

        noise = rng.normal(0, NOISE_METERS_STD, size=(2, len(df)))
        noise_east = noise[0]
        noise_north = noise[1]

        azimuth_east = np.full(len(df), 90)
        azimuth_north = np.full(len(df), 0)

        lon_temp, lat_temp, _ = geod.fwd(lon, lat, azimuth_east, noise_east)
        lon_noisy, lat_noisy, _ = geod.fwd(
            lon_temp, lat_temp, azimuth_north, noise_north
        )

        geo_positions_noisy = np.column_stack((lon, lat))

        noise_df = df.with_columns(
            pl.Series(
                geo_positions_noisy,
                dtype=pl.Array(pl.Float64, shape=2),
            ).alias("geo_position"),
            pl.Series(lat_noisy, dtype=pl.Float64).alias("lat"),
            pl.Series(lon_noisy, dtype=pl.Float64).alias("lon"),
        )

        write_parquet_with_options(
            noise_df,
            OUTPUT_PATH / "fcd_noisy.parquet",
        )

        print("Noisy simulation data saved to", OUTPUT_PATH / "fcd_noisy.parquet")
        print(noise_df)


if __name__ == "__main__":
    main()

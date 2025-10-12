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

    # The final dictionary now maps internal LANE IDs to OSM edge IDs
    internal_lane_to_osm_edge: dict[str, str] = {}

    try:
        # Step 1: Pre-compute the lookup maps for each cluster. This part is efficient and correct.
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
                cluster_osm_maps[junction_id] = dict(zip(orig_ids_list, orig_edge_ids_list))

        # Step 2: Iterate through all LANES to build the map, as this is the ID you receive.
        edges: list[Edge] = net.getEdges()
        lanes :list[Lane] = []
        for edge in edges:
            lanes.extend(edge.getLanes())

        for lane in lanes:
            internal_lane_id = lane.getID()
            if not internal_lane_id.startswith(":"):
                continue

            # Your traceback logic is correct.
            incoming_conns = lane.getIncomingConnections()
            if not incoming_conns:
                continue

            connection = incoming_conns[0]
            from_edge = connection.getFromLane().getEdge()
            
            orig_to_node = from_edge.getParams().get("origTo")
            if not orig_to_node:
                continue

            # **IMPROVEMENT**: Get the cluster ID reliably from the lane's parent edge.
            # This is safer than splitting the string.
            base_cluster_id = lane.getEdge().getToNode().getID()
            osm_map = cluster_osm_maps.get(base_cluster_id)

            if osm_map and (orig_eid := osm_map.get(orig_to_node)):
                internal_lane_to_osm_edge[internal_lane_id] = orig_eid

    except Exception as e:
        print(f"An error occurred while processing the network file: {e}")
        raise

    return internal_lane_to_osm_edge


@contextmanager
def run_traci(cmd: list[str]):
    traci.start(cmd)
    try:
        yield
    finally:
        traci.close()


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    jid_to_osmid = map_internal_lanes_to_osm_edges(NETWORK_PATH)

    vehicle_ids = pl.Series(dtype=pl.Categorical)
    geo_positions = pl.Series(dtype=pl.Array(pl.Float64, shape=2))
    times = pl.Series(dtype=pl.Float64)
    edges = pl.Series(dtype=pl.Categorical)


    with run_traci(cmd):
        while cast(int, traci.simulation.getMinExpectedNumber()) > 0:
            traci.simulation.step()

            current_vehicles = pl.Series(traci.vehicle.getIDList(), dtype=pl.Categorical)
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

            current_edges = current_vehicles.map_elements(
                traci.vehicle.getLaneID, return_dtype=pl.String
            ).cast(pl.Categorical)

            current_time = pl.Series(
                np.full(len(current_vehicles), traci.simulation.getTime()), dtype=pl.Float64
            )

            vehicle_ids.append(current_vehicles)
            geo_positions.append(current_geo)
            times.append(current_time)
            edges.append(current_edges)

    lf = pl.LazyFrame(
        (
            vehicle_ids.alias("vehicle_id"),
            geo_positions.alias("geo_position"),
            times.alias("time"),
            edges.alias("raw_edge_id"),
        )
    )

    lf = lf.with_columns(
        pl.col("raw_edge_id")
        .replace(jid_to_osmid, return_dtype=pl.String)
        .alias("refined_edge_id")
        .cast(pl.Categorical)
    )

    lf = lf.with_columns(
        pl.col("refined_edge_id")
        .cast(pl.String)
        .str.extract(r"^\D*(\d+).*$", 1)
        .alias("edge_id")
    )

    lf = lf.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    df = lf.collect()
    df.write_parquet(OUTPUT_PATH / "fcd.parquet", mkdir=True, compression="zstd")

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

        noise_df.write_parquet(
            OUTPUT_PATH / "fcd_noisy.parquet", mkdir=True, compression="zstd"
        )

        print("Noisy simulation data saved to", OUTPUT_PATH / "fcd_noisy.parquet")
        print(noise_df)


if __name__ == "__main__":
    main()

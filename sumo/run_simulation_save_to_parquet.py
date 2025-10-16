from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import cast

import sumolib
import traci

import geopandas as gpd
import numpy as np
import osmnx as ox
import polars as pl

from pyproj import Geod

ROOT_PATH = Path(".").resolve().absolute()
BASE_PATH = ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless"
ROAD_NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"
SUMO_NETWORK_PATH = BASE_PATH / "network.net.xml"
SIMULATION_PATH = BASE_PATH / "simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "output"
NOISE_METERS_STD: float | None = 5
RANDOM_SEED = 42


type Node = sumolib.net.node.Node
type Edge = sumolib.net.edge.Edge
type Net = sumolib.net.Net
type Lane = sumolib.net.lane.Lane
type Conn = sumolib.net.connection.Connection


type NodeOSMID = str
type ResolvePair = tuple[Edge, NodeOSMID]


@lru_cache(maxsize=None)
def resolve_lane_dest_node(net: Net, start_lane_id: str) -> ResolvePair | None:
    """
    Given a SUMO network and an internal lane ID, this function finds the
    'to' edge ID that the internal lane connects to.

    Args:
        net: The loaded sumolib network object.
        start_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').

    Returns:
        The ID of the 'to' edge if found, otherwise None.
    """
    try:
        current_lane: Lane = net.getLane(start_lane_id)
        outgoing_connections: list[Conn] = current_lane.getOutgoing()

        if not outgoing_connections:
            return None

        if len(outgoing_connections) > 1:
            print(
                f"Warning: Lane {start_lane_id} has multiple outgoing connections. Using the first one."
            )

        next_connection = outgoing_connections[0]
        destination_lane = next_connection.getToLane()
        destination_lane_id = destination_lane.getID()

        if destination_lane_id.startswith(":"):
            return resolve_lane_dest_node(net, destination_lane_id)

        destination_edge = destination_lane.getEdge()

        # the "from" node of the destination edge is the "to" node of the current edge
        to_node_id = destination_edge.getParams().get("origFrom", "Unknown")

        return destination_edge, to_node_id

    except KeyError:
        return None


@lru_cache(maxsize=None)
def resolve_lane_origin_node(net: Net, start_lane_id: str) -> ResolvePair | None:
    """
    Given a SUMO network and an internal lane ID, this function finds the
    'from' edge ID that the internal lane connects from.

    Args:
        net: The loaded sumolib network object.
        start_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').
    Returns:
        The ID of the 'from' edge if found, otherwise None.
    """
    try:
        current_lane: Lane = net.getLane(start_lane_id)
        incoming_connections: list[Conn] = current_lane.getIncomingConnections()

        if not incoming_connections:
            return None

        if len(incoming_connections) > 1:
            print(
                f"Warning: Lane {start_lane_id} has multiple incoming connections. Using the first one."
            )

        previous_connection = incoming_connections[0]
        incoming_lane = previous_connection.getFromLane()
        incoming_lane_id = incoming_lane.getID()

        if incoming_lane_id.startswith(":"):
            return resolve_lane_origin_node(net, incoming_lane_id)

        incoming_edge = incoming_lane.getEdge()

        # the "to" node of the incoming edge is the "from" node of the current edge
        from_node_id = incoming_edge.getParams().get("origTo", "Unknown")

        return incoming_edge, from_node_id

    except KeyError:
        return None


def resolve_lane_edges(
    net: Net, start_lane_id: str
) -> tuple[ResolvePair, ResolvePair] | None:
    """
    Given a SUMO network and an internal lane ID, this function finds both the
    'from' and 'to' edge IDs that the internal lane connects.

    Args:
        net: The loaded sumolib network object.
        start_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').
    Returns:
        A tuple containing the Nodes of the 'from' and 'to' edges if found, otherwise None.
    """
    from_pair = resolve_lane_origin_node(net, start_lane_id)
    to_pair = resolve_lane_dest_node(net, start_lane_id)

    if not (from_pair and to_pair):
        return None
    return from_pair, to_pair


def map_lane_to_edge(net: Net) -> dict[str, tuple[NodeOSMID, NodeOSMID]]:
    """
    Creates a mapping from internal lane IDs to their corresponding 'from' and 'to' edge IDs.

    Args:
        net: The loaded sumolib network object.
    Returns:
        A dictionary mapping internal lane IDs to tuples of ('from' edge ID, 'to' edge ID).
    """
    junction_to_osm_id: dict[str, tuple[str, str]] = {}

    edges: list[Edge] = net.getEdges()
    for edge in edges:
        lanes: list[Lane] = edge.getLanes()
        for lane in lanes:
            lane_id = lane.getID()
            if not lane_id.startswith(":cluster"):
                continue

            edge_ids = resolve_lane_edges(net, lane_id)
            if not edge_ids:
                print(f"Could not find edge IDs for lane {lane_id}")
                continue
            (_, from_osmid), (_, to_osmid) = edge_ids
            junction_to_osm_id[lane_id] = (from_osmid, to_osmid)

    return junction_to_osm_id


def map_lane_to_edge_ids(net: Net, edges_gdf: gpd.GeoDataFrame) -> dict[str, str]:
    """
    Creates a mapping from internal lane IDs to their corresponding OSM edge IDs.

    Args:
        net: The loaded sumolib network object.
        edges_gdf: A GeoDataFrame containing OSM edges with 'osmid' attribute.
    Returns:
        A dictionary mapping internal lane IDs to OSM edge IDs.
    """
    lane_to_edge_map = map_lane_to_edge(net)

    lane_to_edge_id_map: dict[str, str] = {}

    for lane_id, (from_osmid, to_osmid) in lane_to_edge_map.items():
        if from_osmid == to_osmid:
            lane_to_edge_id_map[lane_id] = f"node_{from_osmid}"
            continue

        int_from_osmid, int_to_osmid = int(from_osmid), int(to_osmid)
        key = (int_from_osmid, int_to_osmid, 0)
        reverse_key = (int_to_osmid, int_from_osmid, 0)

        if key in edges_gdf.index:
            lane_to_edge_id_map[lane_id] = str(edges_gdf.loc[key, "osmid"])
        elif reverse_key in edges_gdf.index:
            lane_to_edge_id_map[lane_id] = str(edges_gdf.loc[reverse_key, "osmid"])
        else:
            print(f"Could not find OSM edge ID for lane {lane_id} with key {key}")

    return lane_to_edge_id_map


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

            vehicle_ids.extend(current_vehicles.cast(pl.Int32))
            geo_positions.extend(current_geo)
            times.extend(current_time)
            lanes.extend(current_lanes)

    net = sumolib.net.readNet(SUMO_NETWORK_PATH, withInternal=True)

    G = ox.load_graphml(ROAD_NETWORK_PATH)
    edges_gdf = ox.graph_to_gdfs(G, nodes=False, fill_edge_geometry=True)

    jid_to_osmid = map_lane_to_edge_ids(net, edges_gdf)

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
        pl.col("edge_id").str.replace("-", ""),
    )

    is_node = pl.col("edge_id").cast(pl.Int64).is_in(G.nodes())

    lf = lf.with_columns(
        pl.when(is_node)
        .then(pl.lit("node_") + pl.col("edge_id"))
        .otherwise(pl.col("edge_id"))
        .cast(pl.Categorical)
        .alias("edge_id")
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

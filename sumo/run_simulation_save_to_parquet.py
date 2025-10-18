from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import cast

import networkx as nx
import sumolib
import traci

import geopandas as gpd
import numpy as np
import osmnx as ox
import polars as pl

from pyproj import Geod
from gloe import transformer, partial_transformer

ROOT_PATH = Path(".").resolve().absolute()
BASE_PATH = ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless"
ROAD_NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"
SUMO_NETWORK_PATH = BASE_PATH / "network.net.xml"
SIMULATION_PATH = BASE_PATH / "simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "output"
NOISE_METERS_STD: float  = 5
RANDOM_SEED = 42


type Node = sumolib.net.node.Node
type Edge = sumolib.net.edge.Edge
type Net = sumolib.net.Net
type Lane = sumolib.net.lane.Lane
type Conn = sumolib.net.connection.Connection


type NodeOSMID = str
type ResolvePair = tuple[Edge, NodeOSMID]


@contextmanager
def traci_session(cmd: list[str]):
    traci.start(cmd)
    try:
        yield traci
    finally:
        traci.close()


@lru_cache(maxsize=None)
def resolve_lane_dest_node(net: Net, start_lane_id: str) -> ResolvePair | None:
    """
    Given a SUMO network and an internal lane ID, this function finds the
    'to' edge ID that the internal lane connects to.
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
    """

    from_pair = resolve_lane_origin_node(net, start_lane_id)
    to_pair = resolve_lane_dest_node(net, start_lane_id)

    if not (from_pair and to_pair):
        return None
    return from_pair, to_pair


def map_lane_to_edge(net: Net) -> dict[str, tuple[NodeOSMID, NodeOSMID]]:
    """
    Creates a mapping from internal lane IDs to their corresponding 'from' and 'to' edge IDs.
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
            lane_to_edge_id_map[lane_id] = f"node_{int_from_osmid}"
        else:
            print(f"Could not find OSM edge ID for lane {lane_id} with key {key}")

    return lane_to_edge_id_map


@partial_transformer
def map_internal_junctions_to_edges(
    lf: pl.LazyFrame, G_road: nx.MultiDiGraph, net: Net
) -> pl.LazyFrame:
    """
    Maps internal junction lane IDs to edge IDs using the SUMO network and OSM road graph.
    """
    edges_gdf = ox.graph_to_gdfs(G_road, nodes=False, fill_edge_geometry=True)

    jid_to_osmid = map_lane_to_edge_ids(net, edges_gdf)

    lf = lf.with_columns(
        pl.col("raw_lane_id")
        .replace_strict(
            jid_to_osmid, default=pl.col("raw_lane_id"), return_dtype=pl.String
        )
        .alias("mapped_lane_id")
    )

    return lf


@transformer
def map_remaining_lanes_to_edges(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Maps remaining lane IDs that are not internal junctions to edge IDs by extracting numeric parts.
    """
    lf = lf.with_columns(
        pl.col("mapped_lane_id").str.extract(r"(-?\d+)(?:.*)", 1).alias("edge_id")
    )

    return lf

@transformer
def mark_reversed_edge_ids(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Marks edge IDs that are reversed (start with '-') and removes the '-' prefix."""
    lf = lf.with_columns(
        pl.col("edge_id").str.starts_with("-").alias("reversed"),
        pl.col("edge_id").str.replace("-", ""),
    )

    return lf

@partial_transformer
def label_unmapped_edges_as_nodes(
    lf: pl.LazyFrame, G_road: nx.MultiDiGraph
) -> pl.LazyFrame:
    """ 
    Labels edge IDs that are actually node IDs by prefixing them with 'node_'.
    After this transformation, all edge IDs that correspond to nodes in the road graph
    will be clearly identified.
    """
    is_node = pl.col("edge_id").cast(pl.Int64).is_in(G_road.nodes())

    lf = lf.with_columns(
        pl.when(is_node)
        .then(pl.lit("node_") + pl.col("edge_id"))
        .otherwise(pl.col("edge_id"))
        .alias("edge_id")
    )

    return lf


@transformer
def convert_strings_to_categorical(lf: pl.LazyFrame) -> pl.LazyFrame:
    """ 
    Converts string columns to categorical data types for efficiency.
    Specifically, converts 'raw_lane_id', 'mapped_lane_id', and 'edge_id' to categorical types.
    """
    lf = lf.with_columns(
        pl.col("raw_lane_id").cast(pl.Categorical),
        pl.col("mapped_lane_id").cast(pl.Categorical),
        pl.col("edge_id").cast(pl.Categorical),
    )

    lf = lf.with_columns(pl.col("edge_id").alias("node_mapped_id"))

    return lf


@transformer
def fill_edge_ids_backward(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Fill edge IDs that are actually node IDs by propagating the last valid edge ID backward (from future to past)
    within each vehicle's trajectory."
    """

    lf = lf.with_columns(
        pl.when(~pl.col("edge_id").cat.starts_with("node_"))
        .then(pl.col("edge_id"))
        .otherwise(None)
        .alias("edge_id_valid")
    )

    lf = lf.with_columns(
        pl.col("edge_id_valid").backward_fill().over("vehicle_id").alias("edge_id")
    )

    lf = lf.drop("edge_id_valid")

    return lf


@transformer
def extract_coordinates_from_geo(lf: pl.LazyFrame) -> pl.LazyFrame:
    """ Extracts longitude and latitude from the 'geo_position' array column."""
    lf = lf.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    lf = lf.sort("time", "vehicle_id")

    return lf


@transformer
def run_simulation() -> pl.LazyFrame:
    """Runs the SUMO simulation and collects vehicle data for each step and gathers it into a Polars DataFrame."""
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    vehicle_ids = []
    geo_positions = []
    times = []
    lanes = []

    with traci_session(cmd) as session:
        while cast(int, session.simulation.getMinExpectedNumber()) > 0:
            session.simulation.step()

            current_vehicles = np.array(session.vehicle.getIDList())

            if len(current_vehicles) == 0:
                continue

            current_pos = np.array(
                [session.vehicle.getPosition(veh_id) for veh_id in current_vehicles]
            )

            current_geo = np.array(
                [traci.simulation.convertGeo(x, y) for (x, y) in current_pos]
            )

            current_lanes = np.array(
                [session.vehicle.getLaneID(veh_id) for veh_id in current_vehicles]
            )

            current_time = np.full(len(current_vehicles), session.simulation.getTime())

            vehicle_ids.append(current_vehicles)
            geo_positions.append(current_geo)
            times.append(current_time)
            lanes.append(current_lanes)

    df = pl.DataFrame(
        (
            pl.Series(np.concatenate(vehicle_ids)).cast(pl.Int64).alias("vehicle_id"),
            pl.Series(np.concatenate(geo_positions))
            .alias("geo_position")
            .cast(pl.Array(pl.Float64, shape=2)),
            pl.Series(np.concatenate(times)).cast(pl.Float64).alias("time"),
            pl.Series(np.concatenate(lanes)).cast(pl.Categorical).alias("raw_lane_id"),
        )
    )

    return df.lazy()


@partial_transformer
def apply_noise(
    df: pl.DataFrame, noise_std_meters: float | None = None
) -> pl.DataFrame:
    """Applies Gaussian noise to the latitude and longitude coordinates in the DataFrame."""
    if noise_std_meters is None:
        return df

    geod = Geod(ellps="WGS84")
    rng = np.random.default_rng(RANDOM_SEED)

    lon = df["lon"].to_numpy()
    lat = df["lat"].to_numpy()

    noise = rng.normal(0, noise_std_meters, size=(2, len(df)))
    noise_east = noise[0]
    noise_north = noise[1]

    azimuth_east = np.full(len(df), 90)
    azimuth_north = np.full(len(df), 0)

    lon_temp, lat_temp, _ = geod.fwd(lon, lat, azimuth_east, noise_east)
    lon_noisy, lat_noisy, _ = geod.fwd(lon_temp, lat_temp, azimuth_north, noise_north)

    geo_positions_noisy = np.column_stack((lon, lat))

    noise_df = df.with_columns(
        pl.Series(
            geo_positions_noisy,
            dtype=pl.Array(pl.Float64, shape=2),
        ).alias("geo_position"),
        pl.Series(lat_noisy, dtype=pl.Float64).alias("lat"),
        pl.Series(lon_noisy, dtype=pl.Float64).alias("lon"),
    )

    return noise_df


@transformer
def collect_lazyframe(lf: pl.LazyFrame) -> pl.DataFrame:
    return lf.collect()

@partial_transformer
def write_parquet(df: pl.DataFrame, path: Path) -> pl.DataFrame:
    df.write_parquet(
        path,
        mkdir=True,
        compression="zstd",
        compression_level=3,
        row_group_size=100_000,
        statistics=True,
    )

    return df


def main() -> None:
    net = sumolib.net.readNet(str(SUMO_NETWORK_PATH))
    G_road = ox.load_graphml(ROAD_NETWORK_PATH)

    pipeline = (
        run_simulation
        >> map_internal_junctions_to_edges(G_road, net)
        >> map_remaining_lanes_to_edges
        >> mark_reversed_edge_ids
        >> label_unmapped_edges_as_nodes(G_road)
        >> convert_strings_to_categorical
        >> fill_edge_ids_backward
        >> extract_coordinates_from_geo
        >> collect_lazyframe >> (
            write_parquet(OUTPUT_PATH / "fcd_raw.parquet"),
            apply_noise(NOISE_METERS_STD) >> write_parquet(OUTPUT_PATH / "fcd_noisy_raw.parquet")
        )
    )

    df, df_noisy = pipeline()
    print("Raw simulation data saved to", OUTPUT_PATH / "fcd_raw.parquet")
    print(df)

    print("Noisy raw simulation data saved to", OUTPUT_PATH / "fcd_noisy_raw.parquet")
    print(df_noisy)


if __name__ == "__main__":
    main()

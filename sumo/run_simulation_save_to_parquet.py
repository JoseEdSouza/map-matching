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

from gloe import transformer, partial_transformer
from gloe.experimental import bridge
from gloe.utils import attach, forward
from pyproj import Geod


ROOT_PATH = Path(__file__).parent.parent.resolve()
BASE_PATH = ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless"
ROAD_NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"
SUMO_NETWORK_PATH = BASE_PATH / "network.net.xml"
SIMULATION_PATH = BASE_PATH / "simulation.sumocfg"
SIMULATION_MAX_STEPS: int | None = None
OUTPUT_PATH = BASE_PATH / "output" / "teste"
NOISE_METERS_STD: float = 5
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

        # the "to" node of the origin edge is the "from" node of the current edge
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
            # It means a junction internal lane is reversely mapped to a road edge.
            # This lane is a simplification of a U-turn maneuver.
            # It is treated as a node lane, so the pathfinding step can handle it properly.
            # it will be filled later with one or more valid edges ids connecting the two edges.
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
    within each vehicle's trajectory.
    This ensures that any internal junction lanes (marked as nodes) are replaced with the last known valid edge ID.
    As a fallback, it also fills forward to cover cases where the first few entries are nodes.
    This solves when a trajectory starts or ends on a node lane and ensures continuity in edge IDs.
    """

    lf = lf.with_columns(
        pl.when(~pl.col("edge_id").cat.starts_with("node_"))
        .then(pl.col("edge_id"))
        .otherwise(None)
        .alias("edge_id_valid")
    )
    
    # if a row has any valid edge_id in the vehicle trajectory, mark it
    lf = lf.with_columns(
        (pl.col("edge_id_valid").is_not_null().any().over("vehicle_id"))
        .alias("has_valid_edges")
    )
    
    # bidirectional fill: first backward fill, then forward fill as fallback
    lf = lf.with_columns(
        pl.when(pl.col("has_valid_edges"))
        .then(
            pl.coalesce(
                pl.col("edge_id_valid").backward_fill().over("vehicle_id"),
                pl.col("edge_id_valid").forward_fill().over("vehicle_id")
            )
        )
        .otherwise(None)
        .alias("edge_id")
    )
    
    lf = lf.drop("edge_id_valid", "has_valid_edges")

    return lf



@transformer
def extract_lon_lat_from_geo(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Extracts longitude and latitude from the 'geo_position' array column."""
    lf = lf.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    return lf


@partial_transformer
def apply_noise(lf: pl.LazyFrame, noise_std: float | None = None) -> pl.LazyFrame:
    """Applies Gaussian noise to the latitude and longitude coordinates in the DataFrame."""
    if noise_std is None:
        return lf

    df = lf.collect()

    geod = Geod(ellps="WGS84")
    rng = np.random.default_rng(RANDOM_SEED)

    lon = df["lon"].to_numpy()
    lat = df["lat"].to_numpy()

    noise = rng.normal(0, noise_std, size=(2, len(df)))
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

    return noise_df.lazy()


@transformer
def select_and_prepare_node_passages(trajectories_lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Filters for trajectories passing through a node and cleans required columns.
    It prepares the data by casting and creating 'next_edge_id' and 'node_osmid'.
    """
    node_filtered_lf = trajectories_lf.filter(
        pl.col("node_mapped_id").cat.starts_with("node_")
    )

    cleaned_lf = node_filtered_lf.with_columns(
        pl.col("edge_id")
        .cast(pl.String)
        .cast(pl.Int64, strict=False)
        .alias("next_edge_id"),
        pl.col("node_mapped_id")
        .cast(pl.String)
        .str.replace("node_", "")
        .cast(pl.Int64, strict=False)
        .alias("node_osmid"),
    ).drop_nulls(["next_edge_id", "node_osmid"])

    return cleaned_lf


@partial_transformer
def identify_disconnected_pairs(
    cleaned_node_lf: pl.LazyFrame,
    G_road: nx.MultiDiGraph,
) -> pl.LazyFrame:
    """
    Identifies unique (next_edge, current_node) pairs that are not directly connected in the graph.
    """
    osm_edges_lf = build_osm_edges_lazyframe(G_road)

    paired_filtered_trajectories = cleaned_node_lf.with_columns(
        pl.concat_list(
            pl.col("next_edge_id"),
            pl.col("node_osmid"),
        ).alias("pairs")
    )

    unique_pairs = paired_filtered_trajectories.select("pairs").unique()

    unique_pairs = unique_pairs.with_columns(
        pl.col("pairs").list.get(0).alias("next_edge_id"),
    )

    pairs_w_edges = unique_pairs.join(
        osm_edges_lf, left_on="next_edge_id", right_on="osmid", how="left"
    )

    pairs_w_edges = pairs_w_edges.with_columns(
        pl.col("pairs").list.get(0).alias("next_edge_id"),
        pl.col("pairs").list.get(1).alias("node_osmid"),
    )

    # Explodes the dataframe so each node of an edge gets its own row
    exploded_pairs = pairs_w_edges.explode("edges")
    exploded_pairs = exploded_pairs.with_columns(
        pl.col("edges").list.contains(pl.col("node_osmid")).alias("connected")
        # it means one of the nodes of the edge is the node_osmid
    )

    # Groups back by pair and checks if *any* of the edge's nodes matched
    # aggregate to get whether there is any connection with the node_osmid and one of the edges
    pairs_w_connectivity_status = exploded_pairs.group_by("pairs").agg(
        pl.col("connected").any().alias("has_connection")
    )

    # join back then filter out disconnected pairs
    disconnected_pairs_lf = (
        pairs_w_edges.join(pairs_w_connectivity_status, on="pairs", how="left")
        .filter(pl.col("has_connection").not_())
        .drop("has_connection")
    )

    return disconnected_pairs_lf


@lru_cache(maxsize=None)
def find_pathway(G_road: nx.MultiDiGraph, source: int, target: int) -> list[int] | None:
    try:
        path = nx.shortest_path(G_road, source=source, target=target, weight="length")
        edges_path = list((x, y, 0) for x, y in zip(path[:-1], path[1:]))
        edge_data = list(G_road.edges[edge]["osmid"] for edge in edges_path)

        res = []
        for ed in edge_data:
            if ed not in res:
                res.append(ed)
        return res

    except nx.NetworkXNoPath:
        return None


@partial_transformer
def find_connection_pathways(
    disconnected_pairs_lf: pl.LazyFrame, G: nx.MultiDiGraph
) -> pl.LazyFrame:
    """
    For each disconnected pair, finds a valid connection pathway in the graph G.
    """
    pairs_w_neighbors_lf = disconnected_pairs_lf.with_columns(
        pl.col("node_osmid")
        .map_elements(
            lambda node: list(G.neighbors(node)), return_dtype=pl.List(pl.Int64)
        )
        .alias("node_neighbors")
    )

    pairs_w_target_node_lf = pairs_w_neighbors_lf.with_columns(
        pl.struct(["edges", "node_neighbors"])
        .map_elements(
            lambda x: next(
                (u for u, v in x["edges"] if u in x["node_neighbors"]),
                x["edges"][0][0],  # Fallback
            ),
            return_dtype=pl.Int64,
        )
        .alias("node_to_connect")
    )

    pairs_w_pathway_lf = pairs_w_target_node_lf.with_columns(
        pl.struct(["node_osmid", "node_to_connect"])
        .map_elements(
            lambda x: find_pathway(G, x["node_osmid"], x["node_to_connect"]),
            return_dtype=pl.List(pl.Int64),
        )
        .alias("connection_pathway")
    ).filter(
        (pl.col("connection_pathway").is_not_null())
        & (pl.col("connection_pathway").list.len() > 0)
    )

    return pairs_w_pathway_lf.select("next_edge_id", "node_osmid", "connection_pathway")


@transformer
def generate_path_correction_rows(
    pathways_lf: pl.LazyFrame, cleaned_node_lf: pl.LazyFrame
) -> pl.LazyFrame:
    """
    Generates new trajectory rows based on the calculated connection pathways.
    """

    row_identifier = ["vehicle_id", "time", "next_edge_id", "node_osmid"]

    disconnected_trajectories_w_pathway = cleaned_node_lf.join(
        pathways_lf,
        on=["next_edge_id", "node_osmid"],
        how="inner",
    )

    newly_created_rows_lf = (
        disconnected_trajectories_w_pathway
        # 1. Explode the list of edges into separate rows
        .explode("connection_pathway")
        .with_columns(
            # 2. Create an index (0, 1, 2...) for each step in the path
            pl.cum_count("connection_pathway")
            .over(row_identifier)
            .alias("path_step_index")
        )
        .with_columns(
            # 3. Use the index to create the incremental timestamp
            (pl.col("time") + (pl.col("path_step_index") * 0.01)).alias("new_time"),
            # 4. Rename 'connection_pathway' to 'edge_id' to match the original schema
            pl.col("connection_pathway").alias("new_edge_id"),
        )
        # 5. Select and rename columns to build the final, clean DataFrame of new rows
        .select(
            pl.col("vehicle_id"),
            pl.col("new_time").alias("time"),
            pl.col("new_edge_id").alias("edge_id"),  # corrected edge
            pl.col("geo_position"),
            pl.col("raw_lane_id"),
            pl.col("node_mapped_id"),
            pl.col("mapped_lane_id"),
            pl.col("lat"),
            pl.col("lon"),
            pl.col("reversed"),
        )
    )

    return newly_created_rows_lf


@transformer
def combine_and_finalize_trajectories(
    new_rows_lf: pl.LazyFrame,
    original_lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Combines the original 'good' trajectories with the newly generated correction rows.
    """

    # Cast edge_id in original_lf to join properly
    original_lf = original_lf.with_columns(
        pl.col("edge_id").cast(pl.String).cast(pl.Int64, strict=False)
    )

    # Use an anti-join to get all original rows that didn't need correction
    good_rows_lf = original_lf.join(
        new_rows_lf, on=["vehicle_id", "node_mapped_id", "raw_lane_id"], how="anti"
    )

    # Align schemas before concatenation
    new_rows_lf = new_rows_lf.select(good_rows_lf.collect_schema().names())

    # Combine good rows with the new path rows
    corrected_trajectories_lf = pl.concat([good_rows_lf, new_rows_lf]).lazy()

    # Sort to ensure trajectory integrity and collect the final result
    final_lf = corrected_trajectories_lf.sort("vehicle_id", "time").with_columns(
        pl.col("edge_id").cast(pl.String).cast(pl.Categorical)
    )

    return final_lf


def build_osm_edges_lazyframe(G_road: nx.MultiDiGraph) -> pl.LazyFrame:
    edges_gdf = ox.graph_to_gdfs(G_road, nodes=False, fill_edge_geometry=True).to_crs(
        epsg=4326
    )
    edges_by_osmid = edges_gdf.reset_index().set_index("osmid")
    edges_by_osmid = edges_by_osmid[["u", "v"]]

    edges_pl = pl.from_pandas(edges_by_osmid, include_index=True)
    edges_pl = edges_pl.group_by("osmid").agg(
        pl.concat_list(pl.col("u"), pl.col("v")).alias("edges")
    )
    edges_pl_lazy = edges_pl.lazy()
    return edges_pl_lazy


@contextmanager
def traci_session(cmd: list[str]):
    traci.start(cmd)
    try:
        yield traci
    finally:
        traci.close()


@partial_transformer
def run_simulation(_, max_steps: int | None = None) -> pl.LazyFrame:
    """Runs the SUMO simulation and collects vehicle data for each step and gathers it into a Polars DataFrame."""
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    vehicle_ids = []
    geo_positions = []
    times = []
    lanes = []

    with traci_session(cmd) as session:
        step_count = 0
        while cast(int, session.simulation.getMinExpectedNumber()) > 0:
            if max_steps is not None and step_count >= max_steps:
                break
            step_count += 1

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

    lf = pl.LazyFrame(
        (
            pl.Series(np.concatenate(vehicle_ids)).cast(pl.Int64).alias("vehicle_id"),
            pl.Series(np.concatenate(geo_positions))
            .alias("geo_position")
            .cast(pl.Array(pl.Float64, shape=2)),
            pl.Series(np.concatenate(times)).cast(pl.Float64).alias("time"),
            pl.Series(np.concatenate(lanes)).cast(pl.Categorical).alias("raw_lane_id"),
        )
    )
    return lf


@transformer
def find_incomplete_vehicle_trajectories(
    lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Identifies vehicles with incomplete trajectories (i.e., those that do not start and end on valid edges).
    """
    incomplete_vids_lf = (
        lf.filter(pl.col("edge_id").is_null()).select(pl.col("vehicle_id")).unique()
    )

    return incomplete_vids_lf


@transformer
def sort_by_vehicle_and_time(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Sorts the trajectories by vehicle ID and time to ensure proper ordering.
    """
    lf = lf.sort(["vehicle_id", "time"])
    return lf


def remove_incomplete_vehicle_trajectories(
    lf: pl.LazyFrame,
    incomplete_vids_lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Filters out vehicles with incomplete trajectories from the main DataFrame.
    """
    complete_trajectories_lf = lf.join(
        incomplete_vids_lf,
        on="vehicle_id",
        how="anti",
    )

    return complete_trajectories_lf


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
    net: Net = sumolib.net.readNet(SUMO_NETWORK_PATH, withInternal=True)
    G_road = ox.load_graphml(ROAD_NETWORK_PATH)

    map_lanes_to_osmid = (
        map_internal_junctions_to_edges(G_road, net)
        >> map_remaining_lanes_to_edges
        >> mark_reversed_edge_ids
        >> label_unmapped_edges_as_nodes(G_road)
        >> convert_strings_to_categorical
        >> fill_edge_ids_backward
    )

    pathway_bridge = bridge[pl.LazyFrame]("pathway_bridge")

    ensure_pathway_connection = (
        forward[pl.LazyFrame]()
        >> pathway_bridge.pick()
        >> select_and_prepare_node_passages
        >> attach(
            identify_disconnected_pairs(G_road) >> find_connection_pathways(G_road)
        )
        >> generate_path_correction_rows
        >> pathway_bridge.drop()
        >> combine_and_finalize_trajectories
    )

    pipeline = (
        run_simulation(max_steps=SIMULATION_MAX_STEPS)
        >> map_lanes_to_osmid
        >> extract_lon_lat_from_geo
        >> sort_by_vehicle_and_time
        >> (
            forward[pl.LazyFrame](),
            apply_noise(noise_std=NOISE_METERS_STD),
            ensure_pathway_connection >> attach(find_incomplete_vehicle_trajectories),
        )
    )

    lf_raw, lf_noisy, (incomplete_vehicles, lf_resolved) = pipeline()

    print("Incomplete vehicle trajectories:", incomplete_vehicles.collect())

    for filename, lf in [
        ("fcd_raw_2", lf_raw),
        ("fcd_noisy_2", lf_noisy),
        ("fcd_resolved_2", lf_resolved),
    ]:
        lf = remove_incomplete_vehicle_trajectories(lf, incomplete_vehicles)
        df = lf.collect()
        output_file = OUTPUT_PATH / f"{filename}.parquet"
        write_parquet(df, output_file)
        print(f"Saved output to {output_file}")
        print(df)


if __name__ == "__main__":
    main()

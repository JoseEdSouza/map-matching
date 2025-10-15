from functools import lru_cache
from pathlib import Path

import sumolib

import geopandas as gpd
import osmnx as ox


type Net = sumolib.net.Net
type Lane = sumolib.net.lane.Lane
type Conn = sumolib.net.connection.Connection
type Edge = sumolib.net.edge.Edge


@lru_cache(maxsize=None)
def resolve_lane_dest_node(net: Net, start_lane_id: str) -> tuple[str, str] | None:
    """
    Given a SUMO network and an internal lane ID, this function finds the
    'to' edge ID that the internal lane connects to.

    Args:
        net: The loaded sumolib network object.
        internal_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').

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

        if not destination_lane_id.startswith(":"):
            destination_edge = destination_lane.getEdge()
            # the "from" node of the destination edge is the "to" node of the current edge
            to_node_id = destination_edge.getParams().get("origFrom", "Unknown")
            return destination_edge.getID(), to_node_id

        return resolve_lane_dest_node(net, destination_lane_id)

    except KeyError:
        return None


@lru_cache(maxsize=None)
def resolve_lane_origin_node(net: Net, start_lane_id: str) -> tuple[str, str] | None:
    """
    Given a SUMO network and an internal lane ID, this function finds the
    'from' edge ID that the internal lane connects from.

    Args:
        net: The loaded sumolib network object.
        internal_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').
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

        if not incoming_lane_id.startswith(":"):
            incoming_edge = incoming_lane.getEdge()
            # the "to" node of the incoming edge is the "from" node of the current edge
            from_node_id = incoming_edge.getParams().get("origTo", "Unknown")
            return incoming_edge.getID(), from_node_id

        return resolve_lane_origin_node(net, incoming_lane_id)

    except KeyError:
        return None


def resolve_lane_nodes(
    net: Net, start_lane_id: str
) -> tuple[tuple[str, str], tuple[str, str]] | None:
    """
    Given a SUMO network and an internal lane ID, this function finds both the
    'from' and 'to' edge IDs that the internal lane connects.

    Args:
        net: The loaded sumolib network object.
        internal_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').
    Returns:
        A tuple containing the Nodes of the 'from' and 'to' edges if found, otherwise None.
    """
    from_edge_id = resolve_lane_origin_node(net, start_lane_id)
    to_edge_id = resolve_lane_dest_node(net, start_lane_id)

    if from_edge_id and to_edge_id:
        return from_edge_id, to_edge_id
    return None


def create_junction_to_node_osmid_map(net: Net) -> dict[str, tuple[str, str]]:
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
        for lane in edge.getLanes():
            lane_id = lane.getID()
            if not lane_id.startswith(":cluster"):
                continue

            edge_ids = resolve_lane_nodes(net, lane_id)
            if not edge_ids:
                print(f"Could not find edge IDs for lane {lane_id}")
                continue
            (from_id, from_osmid), (to_id, to_osmid) = edge_ids
            junction_to_osm_id[lane_id] = (from_osmid, to_osmid)

    return junction_to_osm_id


def lane_id_to_osm_edge_id(
    net: Net, lane_id: str, edges_gdf: gpd.GeoDataFrame
) -> str | None:
    """
    Given a SUMO network and an internal lane ID, this function finds the
    corresponding 'from' and 'to' OSM edge IDs.

    Args:
        net: The loaded sumolib network object.
        lane_id: The ID of the internal lane (e.g., ':cluster_..._0').
    Returns:
        A tuple containing the 'from' and 'to' OSM edge IDs if found, otherwise None.
    """
    edge_ids = resolve_lane_nodes(net, lane_id)
    if not edge_ids:
        print(f"Could not find edge IDs for lane {lane_id}")
        return None
    (from_id, from_osmid), (to_id, to_osmid) = edge_ids

    key = (int(from_osmid), int(to_osmid), 0)
    try:
        return str(edges_gdf.loc[key, "osmid"])
    except KeyError:
        return None


def create_junction_to_edge_osmid_map(
    net: Net, edges_gdf: gpd.GeoDataFrame
) -> dict[str, str]:
    """
    Creates a mapping from internal lane IDs to their corresponding OSM edge IDs.

    Args:
        net: The loaded sumolib network object.
    Returns:
        A dictionary mapping internal lane IDs to OSM edge IDs.
    """
    jid_to_node_osmid = create_junction_to_node_osmid_map(net)

    jid_to_edge_osmid: dict[str, str] = {}

    for lane_id, (from_osmid, to_osmid) in jid_to_node_osmid.items():
        key = (int(from_osmid), int(to_osmid), 0)
        try:
            jid_to_edge_osmid[lane_id] = str(edges_gdf.loc[key, "osmid"])
        except KeyError:
            print(f"Could not find OSM edge ID for lane {lane_id} with key {key}")
            continue

    return jid_to_edge_osmid


if __name__ == "__main__":
    net_file = Path("./sumo/simulations/ohare-chicago-junctionless/network.net.xml")
    road_graph_file = Path("./networks/graphml/ohare_network.graphml")

    G = ox.load_graphml(road_graph_file)
    edges_gdf = ox.graph_to_gdfs(G, nodes=False, fill_edge_geometry=False).to_crs(
        epsg=4326
    )

    network = sumolib.net.readNet(net_file, withInternal=True)

    jid_to_edge_osmid_map = create_junction_to_edge_osmid_map(network, edges_gdf)
    for lane_id, osm_edge_id in jid_to_edge_osmid_map.items():
        print(f"{lane_id}: OSM edge ID {osm_edge_id}")

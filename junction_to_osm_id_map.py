#
# Remember to install sumolib if you haven't:
# pip install sumolib
#
from pathlib import Path

import sumolib

import networkx as nx
import osmnx as ox


# Path to your network file
ROOT_PATH = Path(".").resolve().absolute()
net_file = ROOT_PATH / "sumo/simulations/ohare-chicago/network.net.xml"


internal_lane_id = ":cluster_12085592677_12085592678_12085592680_4686227139_0_0"
internal_edge_id = ":cluster_3789211013_4199053335_4"

type Node = sumolib.net.node.Node
type Edge = sumolib.net.edge.Edge
type Net = sumolib.net.Net
type Lane = sumolib.net.lane.Lane
type Conn = sumolib.net.connection.Connection


def map_internal_edges_to_osm_edges(
    sumo_network_path: Path, road_network_graph: nx.MultiDiGraph
) -> dict[str, str]:
    """
    Scans a SUMO network file and creates a mapping from each internal edge ID
    (e.g., ':cluster_..._4') to its original OpenStreetMap edge/way ID.

    Args:
        network_path: The path to the .net.xml file.

    Returns:
        A dictionary mapping internal edge IDs to original OSM edge IDs.
    """
    internal_to_osm_edge: dict[str, str] = {}

    print(f"Loading network from {sumo_network_path}...")
    net: Net = sumolib.net.readNet(sumo_network_path, withInternal=True)

    _, osm_edges = ox.graph_to_gdfs(road_network_graph)

    try:
        edges: list[Edge] = net.getEdges()
        for edge in edges:
            if not edge.getID().startswith(":cluster"):
                continue

            lanes: list[Lane] = edge.getLanes()
            if not lanes:
                continue

            for lane in lanes:
                out_conns: list[Conn] = lane.getOutgoing()
                in_conns: list[Conn] = lane.getIncomingConnections()

                for in_conn in in_conns:  # Geralmente só haverá uma
                    from_edge = in_conn.getFrom()
                    for out_conn in out_conns:
                        to_edge = out_conn.getTo()
                        print(
                            f"{from_edge.getID()} -> {lane.getID()} -> {to_edge.getID()}"
                        )

                #     from_edge: Edge = conn.getFrom()
                #     # to_edge: Edge = conn.getTo()
                #     to_lane: Lane = conn.getToLane()
                #     conn: Conn = to_lane.getIncomingConnections()[0]
                #     conn.getTLLinkIndex

                #     from_params = from_edge.getParams()
                #     to_params = to_edge.getParams()

                #     print(f"From edge: {from_edge.getID()} with params {from_params}")
                #     print(f"To edge: {to_edge.getID()} with params {to_params}")

                #     to_osmid = from_params.get("origTo")
                #     from_osmid = to_params.get("origFrom")

                # if to_osmid and from_osmid:
                #     key = (to_osmid, from_osmid, 0)
                #     print(f"Looking for edge key: {key}")
                #     osm_edges.loc[key, "osmid"]

    except Exception as e:
        print(f"An error occurred while processing the network file: {e}")
        raise

    return internal_to_osm_edge


if __name__ == "__main__":
    G = ox.load_graphml(ROOT_PATH / "networks/graphml/ohare_network.graphml")
    map_internal_edges_to_osm_edges(net_file, G)
    # for jid, osmid in jid_to_osmid.items():
    #     print(f"{jid} -> {osmid}")

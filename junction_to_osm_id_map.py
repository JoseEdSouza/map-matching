#
# Remember to install sumolib if you haven't:
# pip install sumolib
#
from pathlib import Path
import sumolib

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


def map_internal_edges_to_osm_edges(network_path: Path) -> dict[str, str]:
    """
    Scans a SUMO network file and creates a mapping from each internal edge ID
    (e.g., ':cluster_..._4') to its original OpenStreetMap edge/way ID.

    Args:
        network_path: The path to the .net.xml file.

    Returns:
        A dictionary mapping internal edge IDs to original OSM edge IDs.
    """
    print(f"Loading network from {network_path}...")
    net: Net = sumolib.net.readNet(network_path, withInternal=True)

    internal_to_osm_edge: dict[str, str] = {}

    try:
        cluster_osm_maps: dict[str, dict[str, str]] = {}
        nodes: list[Node] = net.getNodes()
        for node in nodes:
            junction_id = node.getID()
            if not junction_id.startswith("cluster"):
                continue

            params = node.getParams()
            orig_ids_str = params.get("origId")
            orig_edge_ids_str = params.get("origEdgeIds")

            if orig_ids_str and orig_edge_ids_str:
                orig_ids_list = orig_ids_str.split()
                orig_edge_ids_list = orig_edge_ids_str.split()
                # Create the specific mapping for this cluster
                cluster_osm_maps[junction_id] = dict(
                    zip(orig_ids_list, orig_edge_ids_list)
                )

        edges: list[Edge] = net.getEdges()
        for edge in edges:
            internal_edge_id = edge.getID()
            if not internal_edge_id.startswith(":cluster"):
                continue

            # Assumption: All lanes of an internal edge come from the same "real" edge.
            # So, we only need to check the first lane to find the origin.
            first_lane = edge.getLanes()[0]

            incoming_conns: list[Conn] = first_lane.getIncomingConnections()
            if not incoming_conns:
                # This can happen for entry/exit points, safe to skip
                continue

            # Trace back to the original incoming edge
            connection = incoming_conns[
                0
            ]  # there is only one incoming connection and only one
            from_lane: Lane = connection.getFromLane()
            from_edge: Edge = from_lane.getEdge()

            orig_to_node = from_edge.getParams().get("origTo")
            if not orig_to_node:
                continue
            # Start by assuming the original edge ID is the node ID (fallback)
            internal_to_osm_edge[internal_edge_id] = orig_to_node

            base_cluster_id = internal_edge_id.removeprefix(":").rsplit("_", 1)[0]
            osm_map = cluster_osm_maps.get(base_cluster_id)

            if osm_map and (orig_eid := osm_map.get(orig_to_node)):
                internal_to_osm_edge[internal_edge_id] = orig_eid

    except Exception as e:
        print(f"An error occurred while processing the network file: {e}")
        raise

    return internal_to_osm_edge


if __name__ == "__main__":
    jid_to_osmid = map_internal_edges_to_osm_edges(net_file)
    for jid, osmid in jid_to_osmid.items():
        print(f"{jid} -> {osmid}")

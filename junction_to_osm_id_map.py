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

def cluster_id_to_osm_id(network_path: Path) -> dict[str, str]:
    print(f"Loading network from {net_file}...")
    net: Net = sumolib.net.readNet(network_path, withInternal=True)
    jid_to_osmid: dict[str, str] = {}
    edges: list[Edge] = net.getEdges()
    try:
        for edge in edges:
            if not edge.getID().startswith(":cluster"):
                continue
            lanes: list[Lane] = edge.getLanes()
            for lane in lanes:
                incoming_conns: list[Conn] = lane.getIncomingConnections()
                conn = incoming_conns[0] if incoming_conns else None
                if not conn:
                    raise ValueError(
                        f"No incoming connection found for lane {lane.getID()}"
                    )
                from_lane: Lane = conn.getFromLane()
                from_edge: Edge = from_lane.getEdge()
                params = from_edge.getParams()
                origTo = params.get("origTo")
                if not origTo:
                    print(f"No origTo found for edge {from_edge.getID()}")
                    continue

                jid_to_osmid[edge.getID()] = origTo
    except KeyError as e:
        print(
            f"Error: Lane with ID '{internal_lane_id}' not found in the network file."
        )
        raise KeyError(f"Lane with ID {internal_lane_id} not found") from e

    return jid_to_osmid

if __name__ == "__main__":
    jid_to_osmid = cluster_id_to_osm_id(net_file)
    for jid, osmid in jid_to_osmid.items():
        print(f"{jid} -> {osmid}")

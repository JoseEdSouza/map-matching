from pathlib import Path

import sumolib


type Net = sumolib.net.Net
type Lane = sumolib.net.lane.Lane
type Conn = sumolib.net.connection.Connection
type Edge = sumolib.net.edge.Edge


def resolve_outgoing_from_lane(
    net: Net, start_lane_id: str
) -> tuple[str, str] | None:
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
            return None  # No outgoing connections

        # Assuming we want the first outgoing connection
        if len(outgoing_connections) > 1:
            print(
                f"Warning: Lane {start_lane_id} has multiple outgoing connections. Using the first one."
            )
        next_connection = outgoing_connections[0]
        destination_lane = next_connection.getToLane()
        destination_lane_id = destination_lane.getID()

        if not destination_lane_id.startswith(":"):
            destination_edge = destination_lane.getEdge()
            return destination_edge.getID(), destination_edge.getParams().get(
                "origFrom", "Unknown"
            )

        return resolve_outgoing_from_lane(net, destination_lane_id)

    except KeyError:
        # Handle case where the lane ID is invalid
        return None


def resolve_incoming_from_lane(
    net: Net, start_lane_id: str
) -> tuple[str, str] | None:
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
            return None  # No incoming connections

        # Assuming we want the first incoming connection
        if len(incoming_connections) > 1:
            print(
                f"Warning: Lane {start_lane_id} has multiple incoming connections. Using the first one."
            )
        previous_connection = incoming_connections[0]
        incoming_lane = previous_connection.getFromLane()
        incoming_lane_id = incoming_lane.getID()

        if not incoming_lane_id.startswith(":"):
            incoming_edge = incoming_lane.getEdge()
            return incoming_edge.getID(), incoming_edge.getParams().get(
                "origTo", "Unknown"
            )

        return resolve_incoming_from_lane(net, incoming_lane_id)

    except KeyError:
        # Handle case where the lane ID is invalid
        return None


def resolve_edges_from_lane(
    net: Net, start_lane_id: str
) -> tuple[tuple[str, str], tuple[str, str]] | None:
    """
    Given a SUMO network and an internal lane ID, this function finds both the
    'from' and 'to' edge IDs that the internal lane connects.

    Args:
        net: The loaded sumolib network object.
        internal_lane_id: The ID of the internal lane (e.g., ':cluster_..._0').
    Returns:
        A tuple containing the IDs of the 'from' and 'to' edges if found, otherwise None.
    """
    from_edge_id = resolve_outgoing_from_lane(net, start_lane_id)
    to_edge_id = resolve_incoming_from_lane(net, start_lane_id)
    if from_edge_id and to_edge_id:
        return from_edge_id, to_edge_id
    return None


def create_junction_to_osm_id_map(net: Net) -> dict[str, tuple[str, str]]:
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

            edge_ids = resolve_edges_from_lane(net, lane_id)
            if not edge_ids:
                print(f"Could not find edge IDs for lane {lane_id}")
                continue
            (from_id, from_osmid), (to_id, to_osmid) = edge_ids
            junction_to_osm_id[lane_id] = (from_osmid, to_osmid)

    return junction_to_osm_id


if __name__ == "__main__":
    net_file = Path("./sumo/simulations/ohare-chicago/network.net.xml")
    network = sumolib.net.readNet(net_file, withInternal=True)
    junction_to_osmid_map = create_junction_to_osm_id_map(network)
    for lane_id, (from_osmid, to_osmid) in junction_to_osmid_map.items():
        print(f"{lane_id}: from OSM ID {from_osmid} to OSM ID {to_osmid}")

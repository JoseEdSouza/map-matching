from functools import lru_cache
from pathlib import Path

import networkx as nx
import polars as pl

import osmnx as ox


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


def resolve(
    lf: pl.LazyFrame, indexed_osm_edges: pl.LazyFrame, G_road: nx.MultiDiGraph
) -> pl.LazyFrame:

    trajectories = lf

    node_filtered_trajectories = trajectories.filter(
        pl.col("node_mapped_id").cat.starts_with("node_")
    )

    # clean step
    node_filtered_trajectories = node_filtered_trajectories.with_columns(
        pl.col("edge_id")
        .cast(pl.String)
        .cast(pl.Int64, strict=False)
        .alias("next_edge_id"),
        pl.col("node_mapped_id")
        .cast(pl.String)
        .str.replace("node_", "")
        .cast(pl.Int64, strict=False)
        .alias("node_osmid"),
    )

    cleaned_node_filtered_trajectories = node_filtered_trajectories.drop_nulls(
        ["next_edge_id", "node_osmid"]
    )

    # Creates pairs of [next_edge_id, node_osmid] to check for connectivity
    # pairs each node_osmid, which should be an edge_id, with the edge_id (which is being treated as the next_edge_id in the sequence, set in previous algorithm)
    paired_filtered_trajectories = cleaned_node_filtered_trajectories.with_columns(
        pl.concat_list(
            pl.col("next_edge_id"),
            pl.col("node_osmid"),
        ).alias("pairs")
    )

    unique_pairs = paired_filtered_trajectories.select("pairs").unique()

    unique_pairs = unique_pairs.with_columns(
        pl.col("pairs").list.get(0).alias("next_edge_id"),
    )

    # join with edges to get the u,v nodes of the edge to check for connectivity status
    pairs_w_edges = unique_pairs.join(
        indexed_osm_edges, left_on="next_edge_id", right_on="osmid", how="left"
    )

    pairs_w_edges = pairs_w_edges.with_columns(
        pl.col("pairs").list.get(0).alias("next_edge_id"),
        pl.col("pairs").list.get(1).alias("node_osmid"),
    )
    # Explodes the dataframe so each node of an edge gets its own row
    exploded_pairs = pairs_w_edges.explode("edges")
    exploded_pairs = exploded_pairs.with_columns(
        pl.col("edges")
        .list.contains(pl.col("node_osmid"))
        .alias("connected")
        # it means one of the nodes of the edge is the node_osmid
    )

    # Groups back by pair and checks if *any* of the edge's nodes matched
    # aggregate to get whether there is any connection with the node_osmid and one of the edges
    pairs_w_connectivity_status = exploded_pairs.group_by("pairs").agg(
        pl.col("connected").any().alias("has_connection")
    )

    # re-join with the original data
    pairs_w_edges = pairs_w_edges.join(
        pairs_w_connectivity_status, on="pairs", how="left"
    )

    # filter out the rows where there is no connection
    disconnected_pairs = pairs_w_edges.filter(pl.col("has_connection").not_()).drop(
        "has_connection"
    )

    # for each disconnected node, get its direct neighbors from the graph G
    disconnected_pairs_w_neighbors = disconnected_pairs.with_columns(
        pl.col("node_osmid")
        .map_elements(G.neighbors, return_dtype=pl.List(pl.Int64))
        .alias("node_neighbors")
    )

    # identifies the best target node to connect to
    disconnected_pairs_w_target_node = disconnected_pairs_w_neighbors.with_columns(
        [
            pl.struct("edges", "node_neighbors")
            .map_elements(
                lambda x: next(
                    (u for u, v in x["edges"] if u in x["node_neighbors"]),
                    x["edges"][0][0],
                ),
                return_dtype=pl.Int64,
            )
            .alias("node_to_connect")
        ]
    )

    # try to find a connection pathway from the disconnected node to the target node
    disconnected_pairs_w_pathway = disconnected_pairs_w_target_node.with_columns(
        pl.struct("node_osmid", "node_to_connect")
        .map_elements(
            lambda x: find_pathway(G, x["node_osmid"], x["node_to_connect"]),
            return_dtype=pl.List(pl.Int64),
        )
        .alias("connection_pathway")
    )

    # filter out the rows where there is no connection pathway
    disconnected_pairs_w_pathway = disconnected_pairs_w_pathway.filter(
        (pl.col("connection_pathway").is_not_null())
        & (pl.col("connection_pathway").list.len() > 0)
    )

    disconnected_pairs_w_pathway = disconnected_pairs_w_pathway.select(
        "next_edge_id", "node_osmid", "connection_pathway"
    )

    disconnected_trajectories_w_pathway = cleaned_node_filtered_trajectories.join(
        disconnected_pairs_w_pathway,
        on=["next_edge_id", "node_osmid"],
        how="inner",
    )

    row_identifier = ["vehicle_id", "time", "next_edge_id", "node_osmid"]

    newly_created_path_rows = (
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
            pl.col("new_edge_id").alias("edge_id"),  # This is the corrected edge
            pl.col("geo_position"),
            pl.col("raw_lane_id"),
            pl.col("node_mapped_id"),
            pl.col("mapped_lane_id"),
            pl.col("lat"),
            pl.col("lon"),
            pl.col("reversed"),
        )
    )

    original = lf
    original = original.with_columns(
        pl.col("edge_id").cast(pl.String).cast(pl.Int64, strict=False),
    )
    good = original.join(
        newly_created_path_rows,
        on=["vehicle_id", "node_mapped_id", "raw_lane_id"],
        how="anti",
    )

    newly_created_path_rows = newly_created_path_rows.select(
        good.collect_schema().names()
    )
    # Concatenate the original good rows with the newly generated path rows
    corrected_trajectories_df = pl.concat([good, newly_created_path_rows])

    # Sort the final DataFrame to ensure trajectory integrity
    corrected_trajectories_df = corrected_trajectories_df.sort("vehicle_id", "time")

    # Now, execute the full lazy plan
    final_result = corrected_trajectories_df.with_columns(
        pl.col("edge_id").cast(pl.String).cast(pl.Categorical)
    )

    return final_result


if __name__ == "__main__":
    ROOT_PATH = Path(".").resolve().absolute()
    DATASET_PATH = (
        ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless/output/fcd.parquet"
    )
    NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"
    lf = pl.scan_parquet(DATASET_PATH)

    G = ox.load_graphml(NETWORK_PATH)
    edges_gdf = ox.graph_to_gdfs(G, nodes=False, fill_edge_geometry=True).to_crs(
        epsg=4326
    )

    indexed_osm_edges = edges_gdf.reset_index().set_index("osmid")
    indexed_osm_edges = indexed_osm_edges[["u", "v"]]

    indexed_osm_edges = pl.from_pandas(indexed_osm_edges, include_index=True)

    indexed_osm_edges = (
        indexed_osm_edges.group_by("osmid")
        .agg(pl.concat_list(pl.col("u"), pl.col("v")).alias("edges"))
        .lazy()
    )

    result = resolve(lf, indexed_osm_edges, G)
    result.collect().write_parquet(ROOT_PATH / "resolved_output.parquet")

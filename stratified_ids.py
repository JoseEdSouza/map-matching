import duckdb
import pandas as pd
import osmnx as ox
from pathlib import Path

# Configuration
NUM_QUANTILES = 4
SAMPLES_PER_QUANTILE = 5
RANDOM_SEED = 42

ROOT_PATH = Path.cwd()
GROUND_TRUTH_PATH = (
    ROOT_PATH
    / "sumo/simulations/ohare-chicago-junctionless/output/teste/fcd_resolved_2.parquet"
)
NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"


def main():
    print("Loading network...")
    G = ox.load_graphml(NETWORK_PATH)
    edges_df = ox.graph_to_gdfs(G, nodes=False)

    edge_lengths = {}
    if "osmid" in edges_df.columns:
        # In OSMnx, osmid can be a single ID or a list of IDs if edges were simplified.
        # We explode it to ensure we cover all IDs from the parquet.
        exploded_edges = edges_df.explode("osmid")
        exploded_edges["osmid"] = exploded_edges["osmid"].astype(str)
        edge_lengths = exploded_edges.groupby("osmid")["length"].sum().to_dict()
    elif "edge_id" in edges_df.columns:
        edge_lengths = edges_df.set_index("edge_id")["length"].to_dict()
    elif "id" in edges_df.columns:
        edge_lengths = edges_df.set_index("id")["length"].to_dict()

    print("Loading trajectory data via DuckDB...")

    query = f"""
    SELECT 
        vehicle_id, 
        list(DISTINCT edge_id) as edge_ids
    FROM '{GROUND_TRUTH_PATH}'
    GROUP BY vehicle_id
    """
    df_vehicles = duckdb.query(query).to_df()

    print(f"Total vehicles found: {len(df_vehicles)}")

    def calculate_total_length(edge_list):
        total = 0.0
        for eid in edge_list:
            total += edge_lengths.get(str(eid), 0.0)
        return total

    print("Calculating total lengths...")
    df_vehicles["length_m"] = df_vehicles["edge_ids"].apply(calculate_total_length)

    # Remove vehicles with 0 length (in case edge_ids were not found in the network)
    initial_count = len(df_vehicles)
    df_vehicles = df_vehicles[df_vehicles["length_m"] > 0].copy()
    if len(df_vehicles) < initial_count:
        print(
            f"Warning: {initial_count - len(df_vehicles)} vehicles removed for having 0 length (edges not found)."
        )

    if df_vehicles.empty:
        print("Error: No vehicles with valid length found.")
        return

    # Split into quantiles
    print(f"Splitting into {NUM_QUANTILES} quantiles...")
    try:
        df_vehicles["quantile"] = pd.qcut(
            df_vehicles["length_m"],
            q=NUM_QUANTILES,
            labels=[f"Q{i + 1}" for i in range(NUM_QUANTILES)],
        )
    except ValueError as e:
        print(
            f"Error creating quantiles: {e}. Likely insufficient or duplicate values."
        )
        # Fallback to rank if qcut fails
        df_vehicles["quantile"] = pd.qcut(
            df_vehicles["length_m"].rank(method="first"),
            q=NUM_QUANTILES,
            labels=[f"Q{i + 1}" for i in range(NUM_QUANTILES)],
        )

    print(f"Sampling {SAMPLES_PER_QUANTILE} vehicles from each quantile...")

    samples_by_quantile = {}

    for q in sorted(df_vehicles["quantile"].unique()):
        quantile_df = df_vehicles[df_vehicles["quantile"] == q]
        n_samples = min(len(quantile_df), SAMPLES_PER_QUANTILE)
        sample = quantile_df.sample(n=n_samples, random_state=RANDOM_SEED)
        vids = sample["vehicle_id"].tolist()
        samples_by_quantile[q] = vids

        print(
            f"\t{q}: range({quantile_df['length_m'].min():.2f}m - {quantile_df['length_m'].max():.2f}m), selected {n_samples}/{len(quantile_df)}"
        )

    print("\nSummary of Sampled IDs (by quantile):")
    for q, ids in samples_by_quantile.items():
        print(f"\t{q}: {ids}")

    all_sampled_ids = [vid for vids in samples_by_quantile.values() for vid in vids]
    print(f"\nFull list of IDs ({len(all_sampled_ids)}):")
    print(all_sampled_ids)


if __name__ == "__main__":
    main()

import polars as pl
from sumo.run_simulation_save_to_parquet import main, OUTPUT_PATH


def verification():
    print("Running verification...")
    # Read the output parquet
    try:
        resolved_df = pl.read_parquet(OUTPUT_PATH / "fcd_resolved_2.parquet")
    except FileNotFoundError:
        print("Output file not found. Run simulation first.")
        return

    # Check for gaps
    print(f"Total rows: {resolved_df.height}")

    # Identify transitions where edge_id changes without a common node
    # This is complex to check without the graph.
    # But we can check if 'edge_id' has any remaining nulls or 'node_' values (if they were not filled).

    null_edges = resolved_df.filter(pl.col("edge_id").is_null()).height
    print(f"Null edge_ids: {null_edges}")

    node_edges = resolved_df.filter(
        pl.col("edge_id").cast(pl.String).str.starts_with("node_")
    ).height
    print(f"Node edge_ids (unresolved): {node_edges}")

    if null_edges == 0 and node_edges == 0:
        print("SUCCESS: All edges are resolved and filled.")
    else:
        print("FAILURE: Some edges remain unresolved.")


if __name__ == "__main__":
    verification()

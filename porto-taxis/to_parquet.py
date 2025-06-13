import os

from pathlib import Path
import polars as pl

os.environ["POLARS_VERBOSE"] = "1"

data_path = Path(__file__).parent / "data"

lf = pl.scan_csv(
    data_path / "porto_trajectories_all.csv",
    separator=",",
    has_header=True,
    schema_overrides={"timestamp": pl.Datetime()},
    low_memory=True,
)

lf.collect(engine="streaming").write_parquet(
    data_path / "porto_trajectories_all.parquet", compression="zstd"
)

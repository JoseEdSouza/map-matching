import os

from pathlib import Path
import polars as pl

os.environ["POLARS_VERBOSE"] = "1"

path = Path(__file__).parent / "data"

lf = pl.scan_csv(
    path / "fcd_gps_01_2022.txt",
    separator="\t",
    has_header=False,
    schema_overrides={"recorded_timestamp": pl.Datetime()},
    low_memory=True,
    new_columns=[
        "recorded_timestamp",
        "lon",
        "lat",
        "altitude",
        "speed",
        "orientation",
    ],
)

lf.collect(engine="streaming").write_parquet(
    path / "fcd_gps_01_2022.parquet", compression="zstd"
)

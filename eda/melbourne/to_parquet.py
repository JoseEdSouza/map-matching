from pathlib import Path
import polars as pl

DATA_BASE_PATH = Path(__file__).parent / "data"

# GPS DATA
lf = pl.scan_csv(
    DATA_BASE_PATH / "gps_track.txt",
    separator=" ",
    has_header=False,
    skip_rows=1,
    new_columns=["unix_ts", "lat", "lon"],
    schema_overrides={"unix_ts": pl.Float64, "lat": pl.Float64, "lon": pl.Float64},
    low_memory=True,
)

lf = lf.with_columns(
    pl.from_epoch("unix_ts", time_unit="s").alias("recorded_timestamp")
).select("recorded_timestamp", "lon", "lat")

lf.collect(engine="streaming").write_parquet(
    DATA_BASE_PATH / "gps_track.parquet", compression="zstd"
)

# GROUND TRUTH DATA
lf = pl.scan_csv(
    DATA_BASE_PATH / "groundtruth.txt",
    separator=" ",
    has_header=False,
    skip_rows=1,
    new_columns=["edge_id"],
    low_memory=True,
)

lf.collect(engine="streaming").write_parquet(
    DATA_BASE_PATH / "groundtruth.parquet", compression="zstd"
)

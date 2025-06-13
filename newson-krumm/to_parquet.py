from pathlib import Path
import polars as pl

DATA_BASE_PATH = Path(__file__).parent / "data"

# Leitura do arquivo com schema explícito
lf = pl.scan_csv(
    DATA_BASE_PATH / "gps_data.txt",
    separator="\t",
    has_header=True,
    low_memory=True,
    new_columns=["date", "time", "lat", "lon"],
    schema_overrides={"date": pl.Utf8, "time": pl.Utf8},  # será convertido depois
).select("date", "time", "lon", "lat")

lf = lf.with_columns(
    pl.col("date").str.strptime(pl.Date, "%d-%b-%Y"),
    pl.col("time").str.strptime(pl.Time, "%H:%M:%S"),
)

# Conversão para Date e Time, e combinação
lf = lf.with_columns(
    pl.datetime(
        year=pl.col("date").dt.year(),
        month=pl.col("date").dt.month(),
        day=pl.col("date").dt.day(),
        hour=pl.col("time").dt.hour(),
        minute=pl.col("time").dt.minute(),
        second=pl.col("time").dt.second(),
    ).alias("recorded_timestamp")
).select("recorded_timestamp","lon", "lat")


# Exportação para Parquet
lf.collect(engine="streaming").write_parquet(
    DATA_BASE_PATH / "gps_data.parquet", compression="zstd"
)

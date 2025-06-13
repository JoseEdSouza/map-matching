from pathlib import Path
import polars as pl

DATA_BASE_PATH = Path(__file__).parent / "data"

# Leitura do arquivo com schema explícito
lf = pl.scan_csv(
    DATA_BASE_PATH / "gps_data.txt",
    separator="\t",
    has_header=True,
    low_memory=True,
    new_columns=["date", "time", "lon", "lat"],
    schema_overrides={"date": pl.Utf8, "time": pl.Utf8},  # será convertido depois
)

# Conversão para Date e Time, e combinação
lf = lf.with_columns(
    pl.datetime(
        year=pl.col("date").str.strptime(pl.Date, "%d-%b-%Y").dt.year(),
        month=pl.col("date").str.strptime(pl.Date, "%d-%b-%Y").dt.month(),
        day=pl.col("date").str.strptime(pl.Date, "%d-%b-%Y").dt.day(),
        hour=pl.col("time").str.strptime(pl.Time, "%H:%M:%S").dt.hour(),
        minute=pl.col("time").str.strptime(pl.Time, "%H:%M:%S").dt.minute(),
        second=pl.col("time").str.strptime(pl.Time, "%H:%M:%S").dt.second(),
    ).alias("recorded_timestamp")
)


# Exportação para Parquet
lf.collect(engine="streaming").write_parquet(
    DATA_BASE_PATH / "gps_data.parquet", compression="zstd"
)

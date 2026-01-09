from pathlib import Path
import polars as pl

DATA_BASE_PATH = Path(__file__).parent / "data"

RAW_DATA_PATH = DATA_BASE_PATH / "raw"


# GPS DATA

# Leitura do arquivo com schema explícito
lf = pl.scan_csv(
    RAW_DATA_PATH / "gps_data.txt",
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
).select("recorded_timestamp", "lon", "lat")

# Exportação para Parquet
lf.collect(engine="streaming").write_parquet(
    DATA_BASE_PATH / "gps_data.parquet", compression="zstd"
)


# Ground Truth Data

lf = pl.scan_csv(
    RAW_DATA_PATH / "ground_truth_route.txt",
    separator="\t",
    has_header=True,
    low_memory=True,
    new_columns=["edge_id", "traversed"],
)

lf = lf.with_columns(
    # Ajuste do edge_id para caber num int32
    pl.col("edge_id").cast(pl.Int64) - 883000000000
)


lf.collect(engine="streaming").write_parquet(
    DATA_BASE_PATH / "ground_truth_route.parquet", compression="zstd"
)

# road_network_data

df = pl.read_excel(
    RAW_DATA_PATH / "road_network.xlsx",
    has_header=True,
)

df = df.rename(
    {
        "Edge ID": "edge_id",
        "From Node ID": "from_node_id",
        "To Node ID": "to_node_id",
        "Two Way": "two_way",
        " Speed (m/s)": "speed",
        "Vertex Count": "vertex_count",
        "LINESTRING()": "linestring",
    }
)

df = df.with_columns(
    # Ajuste do edge_id para caber num int32
    pl.col("edge_id").cast(pl.Int64) - 883000000000
)

df.write_parquet(DATA_BASE_PATH / "road_network.parquet", compression="zstd")

from glob import glob
from io import BytesIO
from zipfile import ZipFile


from pathlib import Path
from gloe import partial_transformer, transformer
from gloe.collection import Map
import polars as pl


DATA_PATH = Path(__file__).parent / "data/release/taxi_log_2008_by_id"
OUTPUT_PATH = Path(__file__).parent / "data" / "beijing_taxi_logs.parquet.zip"


@transformer
def get_subpaths(path: str | Path) -> list[str]:
    """
    Get all taxi log file paths in the specified directory.
    """
    return glob(f"{path}/*")


@transformer
def load_lazyframe(path: str) -> pl.LazyFrame:
    try:
        return pl.scan_csv(
            path,
            separator=",",
            has_header=False,
            schema_overrides={"recorded_timestamp": pl.Datetime()},
            low_memory=True,
            new_columns=["taxi_id", "recorded_timestamp", "lon", "lat"],
        )
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return pl.LazyFrame()


@transformer
def to_parquet(lf: pl.LazyFrame) -> BytesIO:
    buffer = BytesIO()

    lf.collect(engine="streaming").write_parquet(buffer, compression="zstd")
    buffer.seek(0)

    return buffer


@partial_transformer
def save_in_zip(buffers: list[BytesIO], output_path: Path) -> None:
    with ZipFile(output_path, "w") as zip_file:
        for i, buffer in enumerate(buffers):
            buffer.seek(0)
            zip_file.writestr(f"taxi_log_{i}.parquet", buffer.read())


def main():
    pipeline = (
        get_subpaths
        >> Map(load_lazyframe >> to_parquet)
        >> save_in_zip(output_path=OUTPUT_PATH)
    )

    pipeline(DATA_PATH)


if __name__ == "__main__":
    main()

import os
from glob import glob
from pathlib import Path
import shutil
import kagglehub

OUTPUT_PATH = Path(__file__).parent / "data"
KAGGLE_HANDLE = "luca71/fcd-data"


def move_or_replace(source: Path, destination: Path):
    """
    Replace the destination file with the source file.
    If the destination exists, it will be overwritten.
    """
    if destination.exists():
        if destination.is_file():
            destination.unlink()
        else:
            shutil.rmtree(destination)
    shutil.move(str(source), str(destination))


# Download latest version
downloaded = kagglehub.dataset_download(KAGGLE_HANDLE, force_download=True)

downloaded_files = glob(f"{downloaded}/*", recursive=True)

# Move the downloaded files to the output path
os.makedirs(OUTPUT_PATH, exist_ok=True)

for downloaded_file in downloaded_files:
    source = Path(downloaded_file)
    destination = OUTPUT_PATH / source.name
    move_or_replace(source, destination)

print(f"Successfully downloaded files to {OUTPUT_PATH}")

import asyncio
import requests
from pathlib import Path

DATA_BASE_PATH = Path(__file__).parent / "data" / "raw"
BASE_URL = "https://www.microsoft.com/en-us/research/wp-content/uploads/2017/07/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


async def download_file(filename: str) -> None:
    """
    Download a file from the specified URL and save it to the data directory.
    """

    response = requests.get(f"{BASE_URL}/{filename}", headers=HEADERS)

    if response.status_code == 200:
        with open(DATA_BASE_PATH / filename, "wb") as file:
            file.write(response.content)
        print(f"Downloaded {filename} successfully.")
    else:
        print(f"Failed to download {filename}. Status code: {response.status_code}")


async def main():
    """
    Main function to download the required files.
    """
    DATA_BASE_PATH.mkdir(parents=True, exist_ok=True)

    files_to_download = [
        "gps_data.txt",
        "road_network.xlsx",
        "ground_truth_route.txt",
    ]

    asyncio.gather(*(download_file(filename) for filename in files_to_download))


if __name__ == "__main__":
    asyncio.run(main())

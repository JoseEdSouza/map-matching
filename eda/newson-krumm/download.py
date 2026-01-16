import asyncio
import aiohttp
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
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(f"{BASE_URL}/{filename}") as response:
            if response.status == 200:
                content = await response.read()
                with open(DATA_BASE_PATH / filename, "wb") as file:
                    file.write(content)
                print(f"Downloaded {filename} successfully.")
            else:
                print(f"Failed to download {filename}. Status code: {response.status}")


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

    await asyncio.gather(*(download_file(filename) for filename in files_to_download))


if __name__ == "__main__":
    asyncio.run(main())

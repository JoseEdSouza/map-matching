import asyncio
import httpx
import zipfile

from pathlib import Path


DATA_PATH = Path(__file__).parent / "data"
MAP_TXT_URL = "https://web.archive.org/web/20170301001019/http://people.eng.unimelb.edu.au/henli/projects/map-matching/complete-osm-map.zip"
MAP_OSM_URL = "https://web.archive.org/web/20170301001019/http://people.eng.unimelb.edu.au/henli/projects/map-matching/melbourne.osm.zip"
GPS_TRACK_URL = "https://web.archive.org/web/20170301001019/http://people.eng.unimelb.edu.au/henli/projects/map-matching/gps_track.txt"
GROUND_TRUTH_URL = "https://web.archive.org/web/20170301001019/http://people.eng.unimelb.edu.au/henli/projects/map-matching/groundtruth.txt"


async def _download_and_extract_zip(
    url: str, dest_path: Path, client: httpx.AsyncClient
):
    print(f"Downloading from {url}...")
    response = await client.get(url)
    with open(dest_path, "wb") as f:
        f.write(response.content)
    print(f"Downloaded to {dest_path}")

    print(f"Unzipping {dest_path}...")
    with zipfile.ZipFile(dest_path, "r") as zip_ref:
        zip_ref.extractall(dest_path.parent)
    print(f"Extracted to {dest_path.parent}")
    dest_path.unlink()


async def _download_txt(url: str, dest_path: Path, client: httpx.AsyncClient):
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    print(f"Downloading from {url}...")
    response = await client.get(url)
    with open(dest_path, "wb") as f:
        f.write(response.content)
    print(f"Downloaded to {dest_path}")


# download then unizp the file into data path
async def download_txt_map(client: httpx.AsyncClient):
    zip_path = DATA_PATH / "melbourne_map.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading TXT map from {MAP_TXT_URL}...")
    await _download_and_extract_zip(MAP_TXT_URL, zip_path, client)


async def download_osm_map(client: httpx.AsyncClient):
    zip_path = DATA_PATH / "melbourne_osm_map.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading OSM map from {MAP_OSM_URL}...")
    await _download_and_extract_zip(MAP_OSM_URL, zip_path, client)


async def download_gps_track(client: httpx.AsyncClient):
    gps_track_path = DATA_PATH / "gps_track.txt"
    gps_track_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading GPS track from {GPS_TRACK_URL}...")
    await _download_txt(GPS_TRACK_URL, gps_track_path, client)


async def download_ground_truth(client: httpx.AsyncClient):
    ground_truth_path = DATA_PATH / "groundtruth.txt"
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading ground truth from {GROUND_TRUTH_URL}...")
    await _download_txt(GROUND_TRUTH_URL, ground_truth_path, client)


async def main():
    async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
        tasks = [
            download_txt_map(client),
            download_osm_map(client),
            download_gps_track(client),
            download_ground_truth(client),
        ]

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

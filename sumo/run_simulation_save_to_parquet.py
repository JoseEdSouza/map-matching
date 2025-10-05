from pathlib import Path
import re
from typing import cast

import traci
import numpy as np
import polars as pl
from pyproj import Geod

BASE_PATH = Path(__file__).parent.absolute()
SIMULATION_PATH = BASE_PATH / "simulations/ohare-chicago/simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "simulations/ohare-chicago/output"
NOISE_METERS_STD: float | None = 5
RANDOM_SEED = 42


def clean_edge_id(edge_ids: np.ndarray) -> np.ndarray:
    regex = r"^\D*(\d+).*$"
    cleaned = [""] * len(edge_ids)
    for i, eid in enumerate(edge_ids):
        eid_str = str(eid).strip()
        matched = re.match(regex, eid_str)
        if matched:
            cleaned[i] = matched.group(1)
        else:
            cleaned[i] = eid
    return np.array(cleaned, dtype=np.str_)


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    vehicle_ids = []
    geo_positions = []
    times = []
    edges = []

    traci.start(cmd)
    while cast(int, traci.simulation.getMinExpectedNumber()) > 0:
        traci.simulation.step()

        current_vehicles = np.array(traci.vehicle.getIDList())
        if len(current_vehicles) == 0:
            continue

        current_pos = np.array(
            [traci.vehicle.getPosition(vid) for vid in current_vehicles]
        )
        current_geo = np.array(
            [traci.simulation.convertGeo(x, y) for x, y in current_pos]
        )
        current_edges = np.array(
            [str(traci.vehicle.getRoadID(vid)) for vid in current_vehicles]
        )

        current_time = np.array([traci.simulation.getTime()] * len(current_vehicles))

        vehicle_ids.append(current_vehicles)
        geo_positions.append(current_geo)
        times.append(current_time)
        edges.append(current_edges)

    traci.close()

    edges = np.concatenate(edges, dtype=np.str_)

    df = pl.DataFrame(
        {
            "vehicle_id": pl.Series(
                np.concatenate(vehicle_ids, dtype=np.str_), dtype=pl.Categorical
            ),
            "geo_position": np.concatenate(geo_positions, dtype=np.float64),
            "time": np.concatenate(times, dtype=np.float64),
            "edge_id": pl.Series(clean_edge_id(edges), dtype=pl.Categorical),
            "raw_edge_id": pl.Series(edges, dtype=pl.Categorical),
        }
    )

    df = df.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    df.write_parquet(OUTPUT_PATH / "fcd.parquet", mkdir=True, compression="zstd")

    print("Simulation data saved to", OUTPUT_PATH / "fcd.parquet")
    print(df)

    if NOISE_METERS_STD is not None:
        geod = Geod(ellps="WGS84")
        rng = np.random.default_rng(RANDOM_SEED)

        lon = df["lon"].to_numpy()
        lat = df["lat"].to_numpy()

        noise = rng.normal(0, NOISE_METERS_STD, size=(2, len(df)))
        noise_east = noise[0]
        noise_north = noise[1]

        azimuth_east = np.full(len(df), 90)
        azimuth_north = np.full(len(df), 0)

        lon_temp, lat_temp, _ = geod.fwd(lon, lat, azimuth_east, noise_east)
        lon_noisy, lat_noisy, _ = geod.fwd(
            lon_temp, lat_temp, azimuth_north, noise_north
        )

        geo_positions_noisy = np.column_stack((lon, lat))

        noise_df = df.with_columns(
            pl.Series(geo_positions_noisy, dtype=pl.List(pl.Float64)).alias(
                "geo_position"
            ),
            pl.Series(lat_noisy, dtype=pl.Float64).alias("lat"),
            pl.Series(lon_noisy, dtype=pl.Float64).alias("lon"),
        )

        noise_df.write_parquet(
            OUTPUT_PATH / "fcd_noisy.parquet", mkdir=True, compression="zstd"
        )

        print("Noisy simulation data saved to", OUTPUT_PATH / "fcd_noisy.parquet")
        print(noise_df)


if __name__ == "__main__":
    main()

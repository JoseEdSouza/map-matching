from pathlib import Path
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


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    vehicle_ids = []
    geo_positions = []
    times = []
    edges = []

    traci.start(cmd)
    while cast(int, traci.simulation.getMinExpectedNumber()) > 0:
        traci.simulation.step()

        current_vehicles = pl.Series(traci.vehicle.getIDList(), dtype=pl.Categorical)
        if len(current_vehicles) == 0:
            continue

        current_pos = pl.Series(
            [traci.vehicle.getPosition(vid) for vid in current_vehicles],
            dtype=pl.Array(pl.Float64, shape=2),
        )
        current_geo = pl.Series(
            [traci.simulation.convertGeo(x, y) for x, y in current_pos],
            dtype=pl.Array(pl.Float64, shape=2),
        )
        current_edges = pl.Series(
            [str(traci.vehicle.getRoadID(vid)) for vid in current_vehicles],
            dtype=pl.Categorical,
        )

        current_time = pl.Series(
            [traci.simulation.getTime()] * len(current_vehicles), dtype=pl.Float64
        )

        vehicle_ids.append(current_vehicles)
        geo_positions.append(current_geo)
        times.append(current_time)
        edges.append(current_edges)

    traci.close()

    lf = pl.LazyFrame(
        {
            "vehicle_id": pl.Series(pl.concat(vehicle_ids), dtype=pl.Categorical),
            "geo_position": pl.Series(
                pl.concat(geo_positions), dtype=pl.Array(pl.Float64, shape=2)
            ),
            "time": pl.concat(times),
            "raw_edge_id": pl.concat(edges),
        }
    )

    lf = lf.with_columns(
        pl.col("raw_edge_id")
        .cast(pl.String)
        .str.extract(r"^\D*(\d+).*$", 1)
        .alias("edge_id")
        .cast(pl.Categorical),
    )

    lf = lf.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    df = lf.collect()
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
            pl.Series(
                geo_positions_noisy,
                dtype=pl.Array(pl.Float64, shape=2),
            ).alias("geo_position"),
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

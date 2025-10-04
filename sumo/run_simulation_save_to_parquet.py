from pathlib import Path
from typing import cast
import traci
import numpy as np
import polars as pl

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
            [traci.vehicle.getRoadID(vid) for vid in current_vehicles]
        )

        current_time = np.array([traci.simulation.getTime()] * len(current_vehicles))

        vehicle_ids.append(current_vehicles)
        geo_positions.append(current_geo)
        times.append(current_time)
        edges.append(current_edges)

    traci.close()

    df = pl.DataFrame(
        {
            "vehicle_id": pl.Series(
                np.concatenate(vehicle_ids, dtype=np.str_), dtype=pl.Categorical
            ),
            "geo_position": np.concatenate(geo_positions, dtype=np.float64),
            "time": np.concatenate(times, dtype=np.float64),
            "edge_id": pl.Series(
                np.concatenate(edges, dtype=np.str_), dtype=pl.Categorical
            ),
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
        rng = np.random.default_rng(RANDOM_SEED)

        # Approximate conversion from meters to degrees at the equator
        meters_to_degrees = 1 / 111320
        noise_std_degrees = NOISE_METERS_STD * meters_to_degrees

        noise_lat = rng.normal(0, noise_std_degrees, size=len(df))
        noise_lon = rng.normal(0, noise_std_degrees, size=len(df))

        lat = df["lat"].to_numpy() + noise_lat
        lon = df["lon"].to_numpy() + noise_lon

        geo_positions_noisy = np.column_stack((lon, lat))

        noise_df = df.with_columns(
            pl.Series(geo_positions_noisy, dtype=pl.List(pl.Float64)).alias(
                "geo_position"
            ),
            pl.Series(lat, dtype=pl.Float64).alias("lat"),
            pl.Series(lon, dtype=pl.Float64).alias("lon"),
        ).drop("edge_id")

        noise_df.write_parquet(
            OUTPUT_PATH / "fcd_noisy.parquet", mkdir=True, compression="zstd"
        )

        print("Noisy simulation data saved to", OUTPUT_PATH / "fcd_noisy.parquet")
        print(noise_df)


if __name__ == "__main__":
    main()

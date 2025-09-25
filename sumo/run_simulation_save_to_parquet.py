from pathlib import Path
import traci
import numpy as np
import polars as pl

BASE_PATH = Path(__file__).parent.absolute()
SIMULATION_PATH = BASE_PATH / "simulations/ohare-chicago/simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "simulations/ohare-chicago/output"


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    vehicle_ids, geo_positions, times = [], [], []

    traci.start(cmd)
    while traci.simulation.getMinExpectedNumber() > 0:
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
        current_time = np.array([traci.simulation.getTime()] * len(current_vehicles))

        vehicle_ids.append(current_vehicles)
        geo_positions.append(current_geo)
        times.append(current_time)

    traci.close()

    df = pl.DataFrame(
        {
            "vehicle_id": pl.Series(
                np.concatenate(vehicle_ids, dtype=np.str_), dtype=pl.Categorical
            ),
            "geo_position": np.concatenate(geo_positions, dtype=np.float64),
            "time": np.concatenate(times, dtype=np.float64),
        }
    )

    df = df.with_columns(
        pl.col("geo_position").arr.get(0).alias("lon"),
        pl.col("geo_position").arr.get(1).alias("lat"),
    )

    df.write_parquet(OUTPUT_PATH / "fcd.parquet", mkdir=True, compression="zstd")

    print("Simulation data saved to", OUTPUT_PATH / "fcd.parquet")
    print(df)


if __name__ == "__main__":
    main()

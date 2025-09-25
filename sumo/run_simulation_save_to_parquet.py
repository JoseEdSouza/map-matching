from pathlib import Path
import traci
import numpy as np
import polars as pl

BASE_PATH = Path(__file__).parent.absolute()
SIMULATION_PATH = BASE_PATH / "simulations/ohare-chicago/simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "simulations/ohare-chicago/output"


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    vehicle_ids, positions, geo_positions, times = [], [], [], []

    traci.start(cmd)
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulation.step()

        current_vehicles = traci.vehicle.getIDList()
        if not current_vehicles:
            continue

        current_pos = [traci.vehicle.getPosition(vid) for vid in current_vehicles]
        current_geo = [traci.simulation.convertGeo(x, y) for x, y in current_pos]
        current_time = traci.simulation.getTime()

        vehicle_ids.extend(current_vehicles)
        positions.extend(current_pos)
        geo_positions.extend(current_geo)
        times.extend([current_time] * len(current_vehicles))
    

    traci.close()


    df = pl.DataFrame(
        {
            "vehicle_id": np.array(vehicle_ids, dtype=str),
            "position": np.array(positions, dtype=np.float64),
            "geo_position": np.array(geo_positions, dtype=np.float64),
            "time": np.array(times, dtype=np.float64),
        }
    )

    df.write_parquet(OUTPUT_PATH / "fcd.parquet", mkdir=True, compression="zstd")

    print("Simulation data saved to", OUTPUT_PATH / "fcd.parquet")
    print(df)

if __name__ == "__main__":
    main()

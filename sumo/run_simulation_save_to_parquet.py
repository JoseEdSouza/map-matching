from functools import partial
from pathlib import Path
from typing import cast

from xml.etree import ElementTree as ET

import traci
import numpy as np
import polars as pl

from pyproj import Geod

ROOT_PATH = Path(".").resolve().absolute()
BASE_PATH = ROOT_PATH / "sumo/simulations/ohare-chicago"
NETWORK_PATH = BASE_PATH / "network.net.xml"
SIMULATION_PATH = BASE_PATH / "simulation.sumocfg"
OUTPUT_PATH = BASE_PATH / "output"
NOISE_METERS_STD: float | None = 5
RANDOM_SEED = 42


def map_junctions_to_osm_ids(network_path: Path) -> dict[str, list[str]]:
    tree = ET.parse(network_path)
    root = tree.getroot()

    jid_to_osmid: dict[str, list[str]] = {}
    for junction in root.iterfind("junction"):
        jid = junction.get("id")
        if not jid:
            continue

        for param in junction.iterfind("param"):
            if param.get("key") != "origEdgeIds":
                continue

            edge_ids = param.get("value")
            if not edge_ids:
                continue

            edge_ids = edge_ids.split()
            jid_to_osmid.setdefault(jid, []).extend(edge_ids)

    return jid_to_osmid


def sumo_eid_to_osmid(jid_to_osmid: dict[str, list[str]], sumo_eid: str) -> str:
    # :cluster_1234_0987_5678_3 -> cluster_1234_0987_5678 3
    if "cluster" not in sumo_eid:
        return sumo_eid
    sumo_eid = sumo_eid.strip().strip(":")
    parts = sumo_eid.rsplit("_", 1)
    if len(parts) != 2:
        return sumo_eid  # Retorna o ID original se o formato for inesperado
    base_id, lane_index = parts
    lane_index = int(lane_index) - 1  # Converter para índice baseado em 0
    osmid_list = jid_to_osmid.get(base_id)
    if not osmid_list:
        return sumo_eid
    if lane_index < 0 or lane_index >= len(osmid_list):
        return sumo_eid
    return osmid_list[lane_index]


def main():
    cmd = ["sumo", "-c", str(SIMULATION_PATH)]

    jid_to_osmid = map_junctions_to_osm_ids(NETWORK_PATH)
    eid_to_osmid = partial(sumo_eid_to_osmid, jid_to_osmid)

    vehicle_ids = pl.Series(dtype=pl.Categorical)
    geo_positions = pl.Series(dtype=pl.Array(pl.Float64, shape=2))
    times = pl.Series(dtype=pl.Float64)
    edges = pl.Series(dtype=pl.Categorical)

    count = 0
    traci.start(cmd)
    while cast(int, traci.simulation.getMinExpectedNumber()) > 0 and count < 1000:
        count += 1

        traci.simulation.step()

        current_vehicles = pl.Series(traci.vehicle.getIDList(), dtype=pl.Categorical)
        if len(current_vehicles) == 0:
            continue

        current_pos = current_vehicles.map_elements(
            traci.vehicle.getPosition,
            return_dtype=pl.Array(pl.Float64, shape=2),
        )

        current_geo = current_pos.map_elements(
            lambda pos: traci.simulation.convertGeo(pos[0], pos[1]),
            return_dtype=pl.List(pl.Float64),
        ).cast(pl.Array(pl.Float64, shape=2))

        current_edges = current_vehicles.map_elements(
            traci.vehicle.getRoadID, return_dtype=pl.String
        )

        current_edges = current_edges.map_elements(
            eid_to_osmid, return_dtype=pl.String
        ).cast(pl.Categorical)

        current_time = pl.Series(
            np.full(len(current_vehicles), traci.simulation.getTime()), dtype=pl.Float64
        )

        vehicle_ids.append(current_vehicles)
        geo_positions.append(current_geo)
        times.append(current_time)
        edges.append(current_edges)

    traci.close()

    lf = pl.LazyFrame(
        (
            vehicle_ids.alias("vehicle_id"),
            geo_positions.alias("geo_position"),
            times.alias("time"),
            edges.alias("raw_edge_id"),
        )
    )

    lf = lf.with_columns(
        pl.col("raw_edge_id")
        .cast(pl.String)
        .str.extract(r"^\D*(\d+).*$", 1)
        .alias("edge_id")
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

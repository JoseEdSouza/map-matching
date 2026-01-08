import asyncio
import json
import logging
from pathlib import Path
import time

import duckdb
import osmnx as ox
import pandas as pd

from bench import launch_service, track_metrics
from mmlib import graphium_online_matcher
from mmlib.matcher.base import BaseOnlineMatcher
from mmlib.result import OnlineMatchResult
from mmlib.benchmark import OnlineBenchMetrics, PartialOnlineBenchMetrics

from mmlib.types import GPSPoint

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

ROOT_PATH = Path.cwd()
SAMPLE_RATE: float | None = 1
VEHICLE_ID = 296
TIME_SPEED_FACTOR = 20

GROUND_TRUTH_PATH = (
    ROOT_PATH
    / "sumo/simulations/ohare-chicago-junctionless/output/teste/fcd_resolved_2.parquet"
)
NOISE_PARQUET = (
    ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless/output/fcd_noisy_2.parquet"
)
NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"


def load_road_dataset(path: Path, sample_rate: float | None = None) -> pd.DataFrame:
    logger.info("Loading road dataset from %s", path)
    df = duckdb.query(
        f"""                
        SELECT lon, lat, TO_TIMESTAMP(time) AS timestamp, edge_id, reversed, raw_lane_id, mapped_lane_id
        FROM '{path}'
        WHERE vehicle_id = {VEHICLE_ID}
        ORDER BY time ASC
        """
    ).to_df()

    if sample_rate is not None:
        logger.info("Resampling dataset with sample rate: %f", sample_rate)
        df = df.resample(f"{sample_rate:.2f}s", on="timestamp").first().reset_index()

    logger.info("Loaded dataset with %d points", len(df))
    return df


def df_to_gps_coordinates(df: pd.DataFrame):
    logger.info("Converting DataFrame to GPS coordinates")
    if SAMPLE_RATE is not None:
        logger.info("Resampling GPS coordinates with sample rate: %f", SAMPLE_RATE)
        df = df.resample(f"{SAMPLE_RATE:.2f}s", on="timestamp").first().reset_index()
    return df[["lat", "lon", "timestamp"]].to_records(index=False).tolist()


def df_to_coordinates(df: pd.DataFrame):
    logger.info("Converting DataFrame to coordinates")
    return df[["lat", "lon"]].to_records(index=False).tolist()


def df_to_edge_ids(df: pd.DataFrame):
    logger.info("Extracting edge IDs from DataFrame")
    return df["edge_id"].tolist()


gt_df = load_road_dataset(GROUND_TRUTH_PATH)

gt_gps_measurements = df_to_gps_coordinates(gt_df)
gt_coordinates = df_to_coordinates(gt_df)
gt_edge_ids = df_to_edge_ids(gt_df)

logger.info("GROUND TRUTH: %d points", len(gt_coordinates))
logger.info("First 3 points: %s", gt_coordinates[:3])
logger.info("First 3 edge ids: %s", gt_edge_ids[:3])
logger.info("First 3 GPS measurements: %s", gt_gps_measurements[:3])

noisy_df = load_road_dataset(NOISE_PARQUET, sample_rate=SAMPLE_RATE)

noisy_gps_measurements = df_to_gps_coordinates(noisy_df)
noisy_coordinates = df_to_coordinates(noisy_df)
noisy_edge_ids = df_to_edge_ids(noisy_df)

logger.info("NOISY: %d points", len(noisy_coordinates))
logger.info("First 3 points: %s", noisy_coordinates[:3])
logger.info("First 3 edge ids: %s", noisy_edge_ids[:3])
logger.info("First 3 GPS measurements: %s", noisy_gps_measurements[:3])

logger.info("Loading graph from %s", NETWORK_PATH)
G = ox.load_graphml(NETWORK_PATH)


async def emit_gps(gps_points: list[GPSPoint], *, K: int = 1):
    if K <= 0:
        raise ValueError("K must be a positive integer.")

    if len(gps_points) == 0:
        logger.warning("No GPS points to emit.")
        return

    last_gps_ts = gps_points[0].time
    for point in gps_points:
        sleep_time, last_gps_ts = point.time - last_gps_ts, point.time
        logger.info("Emitting GPS point: %s", point.as_tuple)
        await asyncio.sleep(sleep_time.seconds / K)
        yield point


async def run_experiment(
    matcher: BaseOnlineMatcher, gps_points: list[GPSPoint]
) -> tuple[OnlineMatchResult, list[PartialOnlineBenchMetrics]]:
    logger.info("Starting experiment with Graphium matcher")

    stream = emit_gps(gps_points, K=TIME_SPEED_FACTOR)

    final_result: OnlineMatchResult | None = None
    metrics: list[PartialOnlineBenchMetrics] = []

    async with matcher:
        async for result, partial_bench in matcher.bench_match_stream(stream):
            final_result = result
            metrics.append(partial_bench)

            logger.info(
                "Received partial result with %d matched points and %d edges",
                len(result.matched_points),
                len(result.edge_ids),
            )
            logger.info("Cummulated metrics so far: %d partials", len(metrics))

        if final_result is None:
            raise RuntimeError("No results were obtained from the matcher.")

    return final_result, metrics


async def main():
    project_name = ROOT_PATH.name
    service_name = "graphium-neo4j"

    matcher = graphium_online_matcher(
        base_url="http://localhost:7474/graphium/api",
        graph_name="network",
        batch_size=20,
    )
    mode = "online_native"
    dataset_id = "ohare_filtered_296"
    matcher_name = "graphium_online_matcher"

    gps_points = [
        GPSPoint(lat=lat, lon=lon, time=timestamp)
        for lat, lon, timestamp in noisy_gps_measurements
    ]

    with track_metrics(project_name) as prom_conn:
        with launch_service(
            service_name,
            project_name,
            dataset_id=dataset_id,
            mode=mode,
            matcher_name=matcher_name,
            startup_sleep_s=10,
        ) as experiment_id:
            matcher.run_id = experiment_id
            logger.info("Running experiment %s with metrics tracking...", experiment_id)
            t0 = time.perf_counter()
            (result, partial_metrics) = await run_experiment(matcher, gps_points)
            t1 = time.perf_counter()
            logger.info(
                "Experiment %s completed. in %.2f seconds", experiment_id, t1 - t0
            )

        prom_conn.custom_query(
            'container_cpu_usage_seconds_total'
        )

    logger.info("Experiment %s finished. Processing metrics...", experiment_id)

    f_name = f"{matcher_name}_{mode}_{dataset_id}_{experiment_id}"

    time_metrics = OnlineBenchMetrics.from_partials(
        partial_metrics,
        (t1 - t0) * 1000,
        custom_metadata={
            "matcher_name": matcher_name,
            "mode": mode,
            "dataset_id": dataset_id,
            "experiment_id": experiment_id,
        },
    )
    metrics_path = ROOT_PATH / "metrics"
    metrics_path.mkdir(parents=True, exist_ok=True)

    result_path = ROOT_PATH / "results"
    result_path.mkdir(parents=True, exist_ok=True)

    time_metrics_df = time_metrics.to_df(expand_summary=True)
    logger.info("Metrics DataFrame:\n%s", time_metrics_df.head())

    time_metrics_df.to_csv(
        metrics_path / f"{f_name}_metrics.csv",
        index=False,
    )
    logger.info("Saved time metrics to %s", metrics_path)

    result.to_df().to_csv(
        result_path / f"{f_name}_result.csv",
        index=False,
    )
    logger.info("Saved result to %s", result_path)

    mm_metrics = result.calculate_metrics(
        graph=G,
        ground_truth_edge_ids=gt_edge_ids,
    )
    logger.info("Match Metrics: %s", mm_metrics)

    with open(metrics_path / f"{f_name}_match_metrics.json", "w") as f:
        f.write(json.dumps(mm_metrics.to_dict(), indent=2))

    logger.info("Match metrics saved to %s", metrics_path)


if __name__ == "__main__":
    asyncio.run(main())

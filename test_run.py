import asyncio
import json
import logging
import time
from pathlib import Path

import duckdb
import osmnx as ox
import pandas as pd
from tqdm.asyncio import tqdm

from bench import launch_service, track_metrics, export_prometheus_timeseries
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


def load_road_dataset(
    path: Path, vehicle_id: int, sample_rate: float | None = None
) -> pd.DataFrame:
    logger.info("Loading dataset for vehicle %d from %s", vehicle_id, path)
    df = duckdb.query(
        f"""                
        SELECT lon, lat, TO_TIMESTAMP(time) AS timestamp, edge_id, reversed, raw_lane_id, mapped_lane_id
        FROM '{path}'
        WHERE vehicle_id = {vehicle_id}
        ORDER BY time ASC
        """
    ).to_df()

    if sample_rate is not None:
        logger.info("Resampling dataset with sample rate: %.2fs", sample_rate)
        df = df.resample(f"{sample_rate:.2f}s", on="timestamp").first().reset_index()

    logger.info("Loaded dataset with %d points", len(df))
    return df


def prepare_data(df: pd.DataFrame) -> tuple[list[GPSPoint], list[tuple[float, float]], list[str]]:
    gps_measurements = [
        GPSPoint(lat=lat, lon=lon, time=timestamp)
        for lat, lon, timestamp in df[["lat", "lon", "timestamp"]].itertuples(index=False)
    ]
    coordinates = df[["lat", "lon"]].to_records(index=False).tolist()
    edge_ids = df["edge_id"].tolist()
    return gps_measurements, coordinates, edge_ids


async def emit_gps(gps_points: list[GPSPoint], *, K: int = 1):
    if K <= 0:
        raise ValueError("K must be a positive integer.")

    if len(gps_points) == 0:
        logger.warning("No GPS points to emit.")
        return

    last_gps_ts = gps_points[0].time
    async for point in tqdm(gps_points, desc="Emitting GPS points"):
        sleep_time, last_gps_ts = point.time - last_gps_ts, point.time
        await asyncio.sleep(sleep_time.total_seconds() / K)
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

    # Load and prepare Ground Truth data
    gt_df = load_road_dataset(GROUND_TRUTH_PATH, VEHICLE_ID)
    _, gt_coords, gt_edge_ids = prepare_data(gt_df)

    logger.info("GROUND TRUTH: %d points", len(gt_coords))
    logger.info("First 3 points: %s", gt_coords[:3])
    logger.info("First 3 edge ids: %s", gt_edge_ids[:3])

    # Load and prepare Noisy data
    noisy_df = load_road_dataset(NOISE_PARQUET, VEHICLE_ID, sample_rate=SAMPLE_RATE)
    noisy_gps, noisy_coords, _ = prepare_data(noisy_df)

    logger.info("NOISY: %d points", len(noisy_coords))
    logger.info("First 3 points: %s", noisy_coords[:3])

    logger.info("Loading graph from %s", NETWORK_PATH)
    G = ox.load_graphml(NETWORK_PATH)

    matcher = graphium_online_matcher(
        base_url="http://localhost:7474/graphium/api",
        graph_name="network",
        batch_size=20,
    )
    mode = "online_native"
    dataset_id = "ohare_filtered_296"
    matcher_name = "graphium_online_matcher"

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
            wall_t0 = time.time()
            t0 = time.perf_counter()
            (result, partial_metrics) = await run_experiment(matcher, noisy_gps)
            t1 = time.perf_counter()
            wall_t1 = time.time()
            logger.info(
                "Experiment %s completed. in %.2f seconds", experiment_id, t1 - t0
            )

        cpu_df, mem_df, net_df = export_prometheus_timeseries(
            prom_conn,
            experiment_id=experiment_id,
            start_ts=wall_t0 - 5,
            end_ts=wall_t1 + 5,
            step_s=1,  # combina com seu scrape_interval=1s
        )

    logger.info("Experiment %s finished. Processing metrics...", experiment_id)

    f_name = f"{matcher_name}_{mode}_{dataset_id}_{experiment_id}"

    metrics_path = ROOT_PATH / "metrics"
    metrics_path.mkdir(parents=True, exist_ok=True)

    result_path = ROOT_PATH / "results"
    result_path.mkdir(parents=True, exist_ok=True)

    cpu_df.to_csv(metrics_path / f"{f_name}_prom_cpu.csv", index=False)
    mem_df.to_csv(metrics_path / f"{f_name}_prom_mem.csv", index=False)
    net_df.to_csv(metrics_path / f"{f_name}_prom_net.csv", index=False)

    logger.info(
        "Saved Prometheus CPU series to %s", metrics_path / f"{f_name}_prom_cpu.csv"
    )
    logger.info(
        "Saved Prometheus MEM series to %s", metrics_path / f"{f_name}_prom_mem.csv"
    )
    logger.info(
        "Saved Prometheus NET series to %s", metrics_path / f"{f_name}_prom_net.csv"
    )

    e2e_time_metrics = OnlineBenchMetrics.from_partials(
        partial_metrics,
        (t1 - t0) * 1000,
        custom_metadata={
            "matcher_name": matcher_name,
            "mode": mode,
            "dataset_id": dataset_id,
            "experiment_id": experiment_id,
        },
    )

    e2e_time_metrics_df = e2e_time_metrics.to_df(expand_summary=True)
    e2e_time_metrics_df.to_csv(
        metrics_path / f"{f_name}_metrics.csv",
        index=False,
    )
    logger.info("Saved E2E time metrics to %s", metrics_path)

    result.to_df().to_csv(
        result_path / f"{f_name}_result.csv",
        index=False,
    )
    logger.info("Saved result to %s", result_path)

    mm_metrics = result.calculate_metrics(
        graph=G,
        ground_truth_edge_ids=gt_edge_ids,
    )
    with open(metrics_path / f"{f_name}_match_metrics.json", "w") as f:
        f.write(json.dumps(mm_metrics.to_dict(), indent=2))

    logger.info("Saved matching metrics to %s", metrics_path)


if __name__ == "__main__":
    asyncio.run(main())

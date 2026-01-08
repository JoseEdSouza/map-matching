import asyncio
import json
import logging
import time
from pathlib import Path

import duckdb
import osmnx as ox
import pandas as pd

from tqdm import tqdm
from mmlib import graphium_online_matcher
from mmlib.matcher.base import BaseOnlineMatcher
from mmlib.result import OnlineMatchResult
from mmlib.benchmark import OnlineBenchMetrics, PartialOnlineBenchMetrics
from mmlib.types import GPSPoint

from bench import launch_service, track_metrics, export_prometheus_timeseries

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

ROOT_PATH = Path.cwd()
SAMPLE_RATE: float | None = 1
VEHICLE_IDS = [5, 9, 13, 17]  # Lista de IDs para processar
TIME_SPEED_FACTOR = 30
SAVE_INDIVIDUAL_REPORTS = False  # individual reports


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


def prepare_data(
    df: pd.DataFrame,
) -> tuple[list[GPSPoint], list[tuple[float, float]], list[str]]:
    gps_measurements = [
        GPSPoint(lat=lat, lon=lon, time=timestamp)
        for lat, lon, timestamp in df[["lat", "lon", "timestamp"]].itertuples(
            index=False
        )
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
    for point in tqdm(gps_points, desc="Emitting GPS points"):
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


def join_metrics(
    *,
    e2e_steps_df: pd.DataFrame,
    prom_df: pd.DataFrame,
    match_df: pd.DataFrame,
    run_key: str = "run_id",
) -> pd.DataFrame:
    """
    Join the three metric sources into a single run-level table.

    Assumptions (based on your schema):
      - E2E is step-level with columns:
        run_id, matcher_name, mode, step_index, timestamp, step_latency_ms,
        inter_arrival_ms, points_per_step, cum_points, memory_mb, cpu_time_ms
      - Prometheus metrics are already run-level (1 row per run).
      - Match metrics are already run-level (1 row per run).
      - dataset_id already encodes vehicle_id, so vehicle_id is not a join key.
      - experiment_id == run_id (may be named differently across dataframes).

    Returns
    -------
    pd.DataFrame
        1 row per run with columns from Prometheus + Match + E2E summary.
    """

    # -----------------------------
    # Normalize keys across dfs
    # -----------------------------
    def _normalize_run_id(df: pd.DataFrame) -> pd.DataFrame:
        if run_key in df.columns:
            return df
        if "experiment_id" in df.columns:
            return df.rename(columns={"experiment_id": run_key})
        raise ValueError(
            f"Expected '{run_key}' or 'experiment_id' in columns: {list(df.columns)}"
        )

    e2e = _normalize_run_id(e2e_steps_df).copy()
    prom = _normalize_run_id(prom_df).copy()
    mm = _normalize_run_id(match_df).copy()

    # -----------------------------
    # Validate E2E minimum columns
    # -----------------------------
    required = {
        run_key,
        "matcher_name",
        "mode",
        "step_index",
        "timestamp",
        "step_latency_ms",
        "inter_arrival_ms",
        "points_per_step",
        "cum_points",
        "memory_mb",
        "cpu_time_ms",
    }
    missing = required - set(e2e.columns)
    if missing:
        raise ValueError(f"E2E dataframe missing columns: {sorted(missing)}")

    # Ensure numeric and ordered
    e2e = e2e.sort_values([run_key, "timestamp", "step_index"])

    # -----------------------------
    # Aggregate E2E step-level -> run-level
    # -----------------------------
    # total points processed: last cum_points (or max)
    # execution time: max(timestamp) - min(timestamp)
    # throughput_pps: total_points / execution_time
    e2e_bounds = e2e.groupby(run_key, as_index=False).agg(
        e2e_t0=("timestamp", "min"),
        e2e_t1=("timestamp", "max"),
        e2e_steps=("step_index", "count"),
        e2e_total_points=("cum_points", "max"),
    )
    e2e_bounds["e2e_execution_time_s"] = e2e_bounds["e2e_t1"] - e2e_bounds["e2e_t0"]
    e2e_bounds["e2e_throughput_pps"] = e2e_bounds["e2e_total_points"] / e2e_bounds[
        "e2e_execution_time_s"
    ].replace(0, pd.NA)

    # distribution stats
    e2e_stats = e2e.groupby(run_key, as_index=False).agg(
        e2e_avg_step_latency_ms=("step_latency_ms", "mean"),
        e2e_p95_step_latency_ms=("step_latency_ms", lambda s: s.quantile(0.95)),
        e2e_max_step_latency_ms=("step_latency_ms", "max"),
        e2e_avg_inter_arrival_ms=("inter_arrival_ms", "mean"),
        e2e_p95_inter_arrival_ms=("inter_arrival_ms", lambda s: s.quantile(0.95)),
        e2e_max_inter_arrival_ms=("inter_arrival_ms", "max"),
        e2e_avg_points_per_step=("points_per_step", "mean"),
        e2e_client_mem_peak_mb=("memory_mb", "max"),
        e2e_client_cpu_time_ms=("cpu_time_ms", "sum"),
    )

    # keep stable identifiers for the run (assumes constant within run)
    e2e_id = e2e.groupby(run_key, as_index=False).agg(
        matcher_name=("matcher_name", "first"),
        mode=("mode", "first"),
    )

    e2e_summary = e2e_id.merge(e2e_bounds, on=run_key, how="inner").merge(
        e2e_stats, on=run_key, how="inner"
    )
    print(e2e_summary.columns, len(e2e_summary))

    # -----------------------------
    # Join: Prometheus + Match + E2E summary
    # -----------------------------
    # Use inner join to ensure completeness; change to "left" if you want partial.
    runs = prom.merge(mm, on=run_key, how="inner", suffixes=("_prom", "_mm"))
    runs = runs.merge(e2e_summary, on=run_key, how="left", suffixes=("", "_e2e"))
    return runs


async def main():
    project_name = ROOT_PATH.name
    service_name = "graphium-neo4j"

    logger.info("Loading graph from %s", NETWORK_PATH)
    G = ox.load_graphml(NETWORK_PATH)

    metrics_path = ROOT_PATH / "metrics"
    metrics_path.mkdir(parents=True, exist_ok=True)

    result_path = ROOT_PATH / "results"
    result_path.mkdir(parents=True, exist_ok=True)

    all_e2e_metrics = []
    all_match_metrics = []
    all_prom_summaries = []

    with track_metrics(project_name, startup_sleep_s=0) as prom_conn:
        for vehicle_id in VEHICLE_IDS:
            logger.info("--- Starting run for VEHICLE_ID: %d ---", vehicle_id)

            # Load and prepare Ground Truth data
            gt_df = load_road_dataset(GROUND_TRUTH_PATH, vehicle_id)
            _, _, gt_edge_ids = prepare_data(gt_df)

            # Load and prepare Noisy data
            noisy_df = load_road_dataset(
                NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE
            )
            noisy_gps, _, _ = prepare_data(noisy_df)

            matcher = graphium_online_matcher(
                base_url="http://localhost:7474/graphium/api",
                graph_name="network",
                batch_size=20,
            )
            mode = "online_native"
            dataset_id = f"ohare_filtered_vid_{vehicle_id}_sr_{SAMPLE_RATE}"
            matcher_name = "graphium_online_matcher"

            with launch_service(
                service_name,
                project_name,
                dataset_id=dataset_id,
                mode=mode,
                matcher_name=matcher_name,
                startup_sleep_s=0,
            ) as experiment_id:
                matcher.run_id = experiment_id
                logger.info(
                    "Running experiment %s for vehicle %d", experiment_id, vehicle_id
                )
                wall_t0 = time.time()
                t0 = time.perf_counter()
                (result, partial_metrics) = await run_experiment(matcher, noisy_gps)
                t1 = time.perf_counter()
                wall_t1 = time.time()
                logger.info(
                    "Experiment %s completed in %.2f seconds", experiment_id, t1 - t0
                )

            cpu_df, mem_df, net_df = export_prometheus_timeseries(
                prom_conn,
                experiment_id=experiment_id,
                start_ts=wall_t0 - 5,
                end_ts=wall_t1 + 5,
                step_s=1,
            )

            f_name = f"{matcher_name}_{mode}_{dataset_id}_{experiment_id}"

            if SAVE_INDIVIDUAL_REPORTS:
                # Salvar métricas individuais de Prometheus
                cpu_df.to_csv(metrics_path / f"{f_name}_prom_cpu.csv", index=False)
                mem_df.to_csv(metrics_path / f"{f_name}_prom_mem.csv", index=False)
                net_df.to_csv(metrics_path / f"{f_name}_prom_net.csv", index=False)

            # Process Prometheus summaries
            duration_s = (
                float(cpu_df["timestamp"].max() - cpu_df["timestamp"].min())
                if not cpu_df.empty
                else 0.0
            )

            cpu_dt = cpu_df["timestamp"].diff().fillna(0.0)
            cpu_total = float((cpu_df["cpu_cores"] * cpu_dt).sum())

            net_dt = net_df["timestamp"].diff().dropna().median()
            if pd.isna(net_dt) or net_dt <= 0:
                net_dt = 1.0

            rx_total_bytes = float((net_df["rx_bps"].fillna(0.0) * net_dt).sum())
            tx_total_bytes = float((net_df["tx_bps"].fillna(0.0) * net_dt).sum())

            all_prom_summaries.append(
                {
                    "matcher_name": matcher_name,
                    "mode": mode,
                    "dataset_id": dataset_id,
                    "experiment_id": experiment_id,
                    "vehicle_id": vehicle_id,
                    "duration_s": duration_s,
                    "cpu_avg": float(cpu_df["cpu_cores"].mean())
                    if not cpu_df.empty
                    else 0.0,
                    "cpu_max": float(cpu_df["cpu_cores"].max())
                    if not cpu_df.empty
                    else 0.0,
                    "cpu_total_core_s": cpu_total,
                    "mem_avg_mb": float(mem_df["mem_mb"].mean())
                    if not mem_df.empty
                    else 0.0,
                    "mem_peak_mb": float(mem_df["mem_mb"].max())
                    if not mem_df.empty
                    else 0.0,
                    "rx_avg_bps": float(net_df["rx_bps"].mean())
                    if not net_df.empty
                    else 0.0,
                    "tx_avg_bps": float(net_df["tx_bps"].mean())
                    if not net_df.empty
                    else 0.0,
                    "rx_peak_bps": float(net_df["rx_bps"].max())
                    if not net_df.empty
                    else 0.0,
                    "tx_peak_bps": float(net_df["tx_bps"].max())
                    if not net_df.empty
                    else 0.0,
                    "rx_total_bytes": rx_total_bytes,
                    "tx_total_bytes": tx_total_bytes,
                }
            )

            # Processar E2E metrics
            e2e_time_metrics = OnlineBenchMetrics.from_partials(
                partial_metrics,
                (t1 - t0) * 1000,
                run_id=experiment_id,
                custom_metadata={
                    "run_id": experiment_id,
                    "matcher_name": matcher_name,
                    "mode": mode,
                    "dataset_id": dataset_id,
                    "experiment_id": experiment_id,
                    "vehicle_id": vehicle_id,
                    "sample_rate": SAMPLE_RATE,
                },
            )
            e2e_df = e2e_time_metrics.to_df(expand_summary=True)
            all_e2e_metrics.append(e2e_df)

            if SAVE_INDIVIDUAL_REPORTS:
                # Salvar resultado individual
                result_df = result.to_df(
                    result.calculate_metrics(gt_edge_ids, graph=G, run_id=experiment_id)
                )
                result_df["vehicle_id"] = vehicle_id
                result_df.to_csv(result_path / f"{f_name}_result.csv", index=False)

            # Matching metrics
            mm_metrics = result.calculate_metrics(
                graph=G,
                run_id=experiment_id,
                ground_truth_edge_ids=gt_edge_ids,
            )
            mm_dict = mm_metrics.to_dict()
            mm_dict.update(
                {
                    "vehicle_id": vehicle_id,
                    "experiment_id": experiment_id,
                    "dataset_id": dataset_id,
                }
            )
            all_match_metrics.append(mm_dict)

            if SAVE_INDIVIDUAL_REPORTS:
                with open(metrics_path / f"{f_name}_match_metrics.json", "w") as f:
                    f.write(json.dumps(mm_dict, indent=2))

    # Agregação Final
    if all_prom_summaries:
        aggregated_prom_df = pd.DataFrame(all_prom_summaries)

        aggregated_prom_df.to_csv(
            metrics_path / "aggregated_prometheus_metrics.csv", index=False
        )
        logger.info(
            "Saved aggregated Prometheus metrics to %s",
            metrics_path / "aggregated_prometheus_metrics.csv",
        )

    if all_e2e_metrics:
        aggregated_e2e_df = pd.concat(all_e2e_metrics, ignore_index=True)
        aggregated_e2e_df.to_csv(
            metrics_path / "aggregated_e2e_metrics.csv", index=False
        )
        logger.info(
            "Saved aggregated E2E metrics to %s",
            metrics_path / "aggregated_e2e_metrics.csv",
        )

    if all_match_metrics:
        aggregated_match_df = pd.DataFrame(all_match_metrics)
        aggregated_match_df.to_csv(
            metrics_path / "aggregated_match_metrics.csv", index=False
        )
        logger.info(
            "Saved aggregated matching metrics to %s",
            metrics_path / "aggregated_match_metrics.csv",
        )

    if all_prom_summaries and all_e2e_metrics and all_match_metrics:
        final_runs_df = join_metrics(
            prom_df=pd.DataFrame(all_prom_summaries),
            match_df=pd.DataFrame(all_match_metrics),
            e2e_steps_df=pd.concat(all_e2e_metrics, ignore_index=True),
        )
        final_runs_df.to_csv(metrics_path / "final_runs_table.csv", index=False)
        logger.info(
            "Saved final runs table to %s",
            metrics_path / "final_runs_table.csv",
        )

    logger.info("All experiments finished.")


if __name__ == "__main__":
    asyncio.run(main())

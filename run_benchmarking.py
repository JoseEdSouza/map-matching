import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import duckdb
import osmnx as ox
import pandas as pd
from tqdm import tqdm

from mmlib.matcher.base import BaseOnlineMatcher
from mmlib.result import OnlineMatchResult
from mmlib.benchmark import OnlineBenchMetrics, PartialOnlineBenchMetrics
from mmlib.types import GPSPoint

from bench import launch_service, track_metrics, export_prometheus_timeseries


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass(frozen=True)
class BenchmarkConfig:
    """Centralized configuration for benchmark experiments."""

    # Paths
    root_path: Path
    ground_truth_path: Path
    noise_parquet_path: Path
    network_path: Path
    vehicle_ids: list[int]

    # Processing parameters
    sample_rates: list[float] = field(default_factory=lambda: [1.0])
    time_speed_factor: int = 1

    # Output configuration
    save_individual_reports: bool = False
    dataset_name: str = "ohare_filtered"


@dataclass
class MatcherConfig:
    """Configuration for a single matcher instance."""

    matcher: BaseOnlineMatcher
    name: str
    services: str | list[str]  # Docker container service name to launch
    mode: str = "online_native"
    metadata: dict = field(default_factory=dict)

    def get_filename_base(self, dataset_id: str, experiment_id: str) -> str:
        """Generate standardized filename base for this matcher's results."""
        return f"{self.name}_{self.mode}_{dataset_id}_{experiment_id}"


# ============================================================================
# DATA MODELS
# ============================================================================


class PreparedData(NamedTuple):
    """Container for prepared GPS data."""

    gps_measurements: list[GPSPoint]
    coordinates: list[tuple[float, float]]


class ExperimentResult(NamedTuple):
    """Container for a single experiment's results."""

    experiment_id: str
    vehicle_id: int
    matcher_name: str
    mode: str
    match_result: OnlineMatchResult
    partial_metrics: list[PartialOnlineBenchMetrics]
    execution_time_s: float
    wall_time_start: float
    wall_time_end: float


class PrometheusMetrics(NamedTuple):
    """Container for Prometheus time series data."""

    cpu_df: pd.DataFrame
    mem_df: pd.DataFrame
    net_df: pd.DataFrame


# ============================================================================
# LOGGING
# ============================================================================


def setup_logging() -> logging.Logger:
    """Configure and return logger."""
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    return logging.getLogger(__name__)


logger = setup_logging()


# ============================================================================
# DATA LOADING
# ============================================================================


class DataLoader:
    """Handles loading and preparing GPS trajectory data."""

    @staticmethod
    def load_trajectory(
        path: Path, vehicle_id: int, sample_rate: float | None = None
    ) -> pd.DataFrame:
        """Load GPS trajectory data for a specific vehicle."""
        logger.info("Loading dataset for vehicle %d from %s", vehicle_id, path)

        df = duckdb.query(
            f"""                
            SELECT lon, lat, TO_TIMESTAMP(time) AS timestamp 
            FROM '{path}'
            WHERE vehicle_id = {vehicle_id}
            ORDER BY time ASC
            """
        ).to_df()

        if sample_rate is not None:
            logger.info("Resampling dataset with sample rate: %.2fs", sample_rate)
            df = (
                df.resample(f"{sample_rate:.2f}s", on="timestamp").first().reset_index()
            )

        logger.info("Loaded dataset with %d points", len(df))
        return df

    @staticmethod
    def load_ground_truth(path: Path, vehicle_id: int) -> list[str]:
        logger.info("Loading ground truth for vehicle %d from %s", vehicle_id, path)

        df = duckdb.query(
            f"""
            SELECT edge_id
            FROM '{path}'
            WHERE vehicle_id = {vehicle_id}
            ORDER BY step ASC
            """
        ).to_df()

        logger.info("Loaded ground truth with %d edges", len(df))

        return df["edge_id"].astype(str).tolist()

    @staticmethod
    def prepare_data(df: pd.DataFrame) -> PreparedData:
        """Convert dataframe to model-ready format."""
        gps_measurements = [
            GPSPoint(lat=lat, lon=lon, time=timestamp)
            for lat, lon, timestamp in df[["lat", "lon", "timestamp"]].itertuples(
                index=False
            )
        ]

        coordinates = df[["lat", "lon"]].to_records(index=False).tolist()

        return PreparedData(gps_measurements, coordinates)


# ============================================================================
# GPS STREAM EMITTER
# ============================================================================


class GPSStreamEmitter:
    """Async generator for emitting GPS points at controlled rate."""

    def __init__(self, gps_points: list[GPSPoint], time_factor: int = 1):
        if time_factor <= 0:
            raise ValueError("time_factor must be positive")
        if not gps_points:
            raise ValueError("gps_points cannot be empty")

        self.gps_points = gps_points
        self.time_factor = time_factor

    async def emit(self):
        """Emit GPS points with timing based on time_factor."""
        last_gps_ts = self.gps_points[0].time

        for point in tqdm(self.gps_points, desc="Emitting GPS points"):
            sleep_time = point.time - last_gps_ts
            last_gps_ts = point.time

            await asyncio.sleep(sleep_time.total_seconds() / self.time_factor)
            yield point


# ============================================================================
# EXPERIMENT RUNNER
# ============================================================================


class ExperimentRunner:
    """Orchestrates map-matching experiments."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config

    async def run_single_experiment(
        self, matcher: BaseOnlineMatcher, gps_points: list[GPSPoint]
    ) -> tuple[OnlineMatchResult, list[PartialOnlineBenchMetrics]]:
        """Execute a single map-matching experiment."""
        logger.info("Starting experiment with matcher")

        emitter = GPSStreamEmitter(gps_points, self.config.time_speed_factor)
        stream = emitter.emit()

        final_result: OnlineMatchResult | None = None
        metrics: list[PartialOnlineBenchMetrics] = []

        async with matcher:
            async for result, partial_bench in matcher.bench_match_stream(stream):
                final_result = result
                metrics.append(partial_bench)

                logger.debug(
                    "Received result: %d matched points, %d edges",
                    len(result.matched_points),
                    len(result.edge_ids),
                )

            if final_result is None:
                raise RuntimeError("No results obtained from matcher")

        return final_result, metrics


# ============================================================================
# METRICS PROCESSING
# ============================================================================


class PrometheusProcessor:
    """Processes Prometheus monitoring data."""

    @staticmethod
    def calculate_summary(metrics: PrometheusMetrics) -> dict:
        """Calculate summary statistics from Prometheus metrics."""
        cpu_df, mem_df, net_df = metrics

        duration_s = (
            float(cpu_df["timestamp"].max() - cpu_df["timestamp"].min())
            if not cpu_df.empty
            else 0.0
        )

        # CPU calculations
        cpu_dt = cpu_df["timestamp"].diff().fillna(0.0)
        cpu_total = float((cpu_df["cpu_cores"] * cpu_dt).sum())

        # Network calculations
        net_dt = net_df["timestamp"].diff().dropna().median()
        if pd.isna(net_dt) or net_dt <= 0:
            net_dt = 1.0

        rx_total_bytes = float((net_df["rx_bps"].fillna(0.0).to_numpy() * net_dt).sum())
        tx_total_bytes = float((net_df["tx_bps"].fillna(0.0).to_numpy() * net_dt).sum())

        return {
            "duration_s": duration_s,
            "cpu_avg": float(cpu_df["cpu_cores"].mean()) if not cpu_df.empty else 0.0,
            "cpu_max": float(cpu_df["cpu_cores"].max()) if not cpu_df.empty else 0.0,
            "cpu_total_core_s": cpu_total,
            "mem_avg_mb": float(mem_df["mem_mb"].mean()) if not mem_df.empty else 0.0,
            "mem_peak_mb": float(mem_df["mem_mb"].max()) if not mem_df.empty else 0.0,
            "rx_avg_bps": float(net_df["rx_bps"].mean()) if not net_df.empty else 0.0,
            "tx_avg_bps": float(net_df["tx_bps"].mean()) if not net_df.empty else 0.0,
            "rx_peak_bps": float(net_df["rx_bps"].max()) if not net_df.empty else 0.0,
            "tx_peak_bps": float(net_df["tx_bps"].max()) if not net_df.empty else 0.0,
            "rx_total_bytes": rx_total_bytes,
            "tx_total_bytes": tx_total_bytes,
        }


class MetricsAggregator:
    """Aggregates metrics from multiple experiments."""

    @staticmethod
    def join_metrics(
        *,
        e2e_steps_df: pd.DataFrame,
        prom_df: pd.DataFrame,
        match_df: pd.DataFrame,
        run_key: str = "run_id",
    ) -> pd.DataFrame:
        """Join E2E, Prometheus, and matching metrics into unified table."""

        # Normalize run_id across dataframes
        def normalize_run_id(df: pd.DataFrame) -> pd.DataFrame:
            if run_key in df.columns:
                return df
            if "experiment_id" in df.columns:
                return df.rename(columns={"experiment_id": run_key})
            raise ValueError(f"Expected '{run_key}' or 'experiment_id'")

        e2e = normalize_run_id(e2e_steps_df).copy()
        prom = normalize_run_id(prom_df).copy()
        mm = normalize_run_id(match_df).copy()

        # Validate E2E columns
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

        e2e = e2e.sort_values([run_key, "timestamp", "step_index"])

        # Aggregate E2E to run-level
        e2e_summary = MetricsAggregator._aggregate_e2e_metrics(e2e, run_key)

        # Join all metrics
        runs = prom.merge(mm, on=run_key, how="inner", suffixes=("_prom", "_mm"))
        runs = runs.merge(e2e_summary, on=run_key, how="left", suffixes=("", "_e2e"))

        return runs

    @staticmethod
    def _aggregate_e2e_metrics(e2e: pd.DataFrame, run_key: str) -> pd.DataFrame:
        """Aggregate step-level E2E metrics to run-level."""

        # Temporal bounds and throughput
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

        # Distribution statistics
        e2e_stats = e2e.groupby(run_key, as_index=False).agg(
            e2e_avg_step_latency_ms=("step_latency_ms", "mean"),
            e2e_p50_step_latency_ms=("step_latency_ms", lambda s: s.quantile(0.50)),
            e2e_p75_step_latency_ms=("step_latency_ms", lambda s: s.quantile(0.75)),
            e2e_p95_step_latency_ms=("step_latency_ms", lambda s: s.quantile(0.95)),
            e2e_p99_step_latency_ms=("step_latency_ms", lambda s: s.quantile(0.99)),
            e2e_max_step_latency_ms=("step_latency_ms", "max"),
            e2e_avg_inter_arrival_ms=("inter_arrival_ms", "mean"),
            e2e_p50_inter_arrival_ms=("inter_arrival_ms", lambda s: s.quantile(0.50)),
            e2e_p75_inter_arrival_ms=("inter_arrival_ms", lambda s: s.quantile(0.75)),
            e2e_p95_inter_arrival_ms=("inter_arrival_ms", lambda s: s.quantile(0.95)),
            e2e_p99_inter_arrival_ms=("inter_arrival_ms", lambda s: s.quantile(0.99)),
            e2e_max_inter_arrival_ms=("inter_arrival_ms", "max"),
            e2e_avg_points_per_step=("points_per_step", "mean"),
            e2e_client_mem_peak_mb=("memory_mb", "max"),
            e2e_client_cpu_time_ms=("cpu_time_ms", "sum"),
        )

        # Run identifiers
        e2e_id = e2e.groupby(run_key, as_index=False).agg(
            matcher_name=("matcher_name", "first"),
            mode=("mode", "first"),
        )

        return e2e_id.merge(e2e_bounds, on=run_key, how="inner").merge(
            e2e_stats, on=run_key, how="inner"
        )


# ============================================================================
# OUTPUT MANAGER
# ============================================================================


class OutputManager:
    """Manages saving experiment results and metrics."""

    def __init__(self, metrics_path: Path, partial_path: Path):
        self.metrics_path = metrics_path
        self.partial_path = partial_path

        metrics_path.mkdir(parents=True, exist_ok=True)
        partial_path.mkdir(parents=True, exist_ok=True)

    def save_individual_report(
        self,
        filename_base: str,
        prom_metrics: PrometheusMetrics,
        result_df: pd.DataFrame,
        match_metrics: dict,
    ):
        """Save individual experiment report."""
        cpu_df, mem_df, net_df = prom_metrics

        cpu_df.to_csv(self.partial_path / f"{filename_base}_prom_cpu.csv", index=False)
        mem_df.to_csv(self.partial_path / f"{filename_base}_prom_mem.csv", index=False)
        net_df.to_csv(self.partial_path / f"{filename_base}_prom_net.csv", index=False)
        result_df.to_csv(self.partial_path / f"{filename_base}_result.csv", index=False)

        with open(self.partial_path / f"{filename_base}_match_metrics.json", "w") as f:
            json.dump(match_metrics, f, indent=2)

    def save_aggregated_metrics(
        self,
        prom_df: pd.DataFrame,
        e2e_df: pd.DataFrame,
        match_df: pd.DataFrame,
        final_runs_df: pd.DataFrame | None = None,
    ):
        """Save aggregated metrics from all experiments."""
        prom_df.to_csv(
            self.metrics_path / "aggregated_prometheus_metrics.csv", index=False
        )
        logger.info("Saved aggregated Prometheus metrics")

        e2e_df.to_csv(self.metrics_path / "aggregated_e2e_metrics.csv", index=False)
        logger.info("Saved aggregated E2E metrics")

        match_df.to_csv(self.metrics_path / "aggregated_match_metrics.csv", index=False)
        logger.info("Saved aggregated matching metrics")

        if final_runs_df is not None:
            final_runs_df.to_csv(
                self.metrics_path / "final_runs_table.csv", index=False
            )
            logger.info("Saved final runs table")


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================


class BenchmarkOrchestrator:
    """Orchestrates the complete benchmark workflow."""

    def __init__(
        self,
        config: BenchmarkConfig,
        matchers: list[MatcherConfig],
    ):
        """
        Initialize benchmark orchestrator.

        Parameters
        ----------
        config : BenchmarkConfig
            Configuration for the benchmark
        matchers : list[MatcherConfig]
            List of matcher configurations to benchmark
        """
        if not matchers:
            raise ValueError("At least one matcher must be provided")

        bench_id = int(time.time())

        self.config = config
        self.matchers = matchers
        self.data_loader = DataLoader()
        self.runner = ExperimentRunner(config)
        self.output_mgr = OutputManager(
            config.root_path / "metrics" / config.dataset_name / str(bench_id),
            config.root_path
            / "metrics"
            / config.dataset_name
            / str(bench_id)
            / "partial",
        )

        self.graph = ox.load_graphml(config.network_path)
        logger.info("Loaded graph from %s", config.network_path)

    async def run_vehicle_matcher_experiment(
        self,
        vehicle_id: int,
        sample_rate: float,
        matcher_config: MatcherConfig,
        ground_truth_edges: list[str],
        noisy_gps: list[GPSPoint],
        prom_conn,
        project_name: str,
    ) -> tuple[dict, pd.DataFrame, dict]:
        """Run experiment for a single vehicle with a specific matcher."""

        dataset_id = f"{self.config.dataset_name}_vid_{vehicle_id}_sr_{sample_rate}"

        logger.info(
            "Running experiment: vehicle=%d, matcher=%s, service=%s, mode=%s",
            vehicle_id,
            matcher_config.name,
            matcher_config.services,
            matcher_config.mode,
        )

        # Setup experiment context with matcher-specific service
        with launch_service(
            matcher_config.services,  # Use service from matcher config
            project_name,
            dataset_id=dataset_id,
            mode=matcher_config.mode,
            matcher_name=matcher_config.name,
            startup_sleep_s=0,
        ) as experiment_id:
            # Set run_id on matcher if it has the attribute
            if hasattr(matcher_config.matcher, "run_id"):
                matcher_config.matcher.run_id = experiment_id

            logger.info("Experiment ID: %s", experiment_id)

            # Time the experiment
            wall_t0 = time.time()
            t0 = time.perf_counter()

            result, partial_metrics = await self.runner.run_single_experiment(
                matcher_config.matcher, noisy_gps
            )

            t1 = time.perf_counter()
            wall_t1 = time.time()

            logger.info("Experiment completed in %.2f seconds", t1 - t0)

        # Collect Prometheus metrics
        cpu_df, mem_df, net_df = export_prometheus_timeseries(
            prom_conn,
            experiment_id=experiment_id,
            start_ts=wall_t0 - 5,
            end_ts=wall_t1 + 5,
            step_s=1,
        )
        prom_metrics = PrometheusMetrics(cpu_df, mem_df, net_df)

        # Process Prometheus summary
        prom_summary = PrometheusProcessor.calculate_summary(prom_metrics)
        prom_summary.update(
            {
                "matcher_name": matcher_config.name,
                "mode": matcher_config.mode,
                "dataset_id": dataset_id,
                "experiment_id": experiment_id,
                "vehicle_id": vehicle_id,
                **matcher_config.metadata,  # Include any custom metadata
            }
        )

        # Process E2E metrics
        e2e_metrics = OnlineBenchMetrics.from_partials(
            partial_metrics,
            (t1 - t0) * 1000,
            run_id=experiment_id,
            custom_metadata={
                "run_id": experiment_id,
                "matcher_name": matcher_config.name,
                "mode": matcher_config.mode,
                "dataset_id": dataset_id,
                "experiment_id": experiment_id,
                "vehicle_id": vehicle_id,
                "sample_rate": sample_rate,
                **matcher_config.metadata,
            },
        )
        e2e_df = e2e_metrics.to_df(expand_summary=True)

        # Process matching metrics
        mm_metrics = result.calculate_metrics(
            graph=self.graph,
            run_id=experiment_id,
            ground_truth_edge_ids=ground_truth_edges,
        )
        mm_dict = mm_metrics.to_dict()
        mm_dict.update(
            {
                "vehicle_id": vehicle_id,
                "experiment_id": experiment_id,
                "dataset_id": dataset_id,
                "matcher_name": matcher_config.name,
                "mode": matcher_config.mode,
                **matcher_config.metadata,
            }
        )

        # Save individual reports if enabled
        if self.config.save_individual_reports:
            filename_base = matcher_config.get_filename_base(dataset_id, experiment_id)
            result_df = result.to_df(mm_metrics)
            result_df["vehicle_id"] = vehicle_id
            result_df["matcher_name"] = matcher_config.name
            result_df["mode"] = matcher_config.mode

            self.output_mgr.save_individual_report(
                filename_base,
                prom_metrics,
                result_df,
                mm_dict,
            )

        return prom_summary, e2e_df, mm_dict

    async def run_vehicle_experiments(
        self,
        vehicle_id: int,
        prom_conn,
        project_name: str,
    ) -> tuple[list[dict], list[pd.DataFrame], list[dict]]:
        """Run experiments for a single vehicle across all matchers and sample rates."""

        logger.info("=" * 80)
        logger.info("Starting experiments for VEHICLE_ID: %d", vehicle_id)
        logger.info("=" * 80)

        gt_edge_ids = self.data_loader.load_ground_truth(
            self.config.ground_truth_path, vehicle_id
        )

        prom_summaries = []
        e2e_dfs = []
        mm_dicts = []

        for sample_rate in self.config.sample_rates:
            logger.info("-" * 40)
            logger.info("Testing SAMPLE_RATE: %.2fs", sample_rate)
            logger.info("-" * 40)

            # Load noisy data for specific sample rate
            noisy_df = self.data_loader.load_trajectory(
                self.config.noise_parquet_path, vehicle_id, sample_rate
            )
            noisy_data = self.data_loader.prepare_data(noisy_df)

            # Run experiments for each matcher
            for i, matcher_config in enumerate(self.matchers, 1):
                logger.info(
                    "Running matcher %d/%d: %s (SR=%.2f)",
                    i,
                    len(self.matchers),
                    matcher_config.name,
                    sample_rate,
                )
                remaining_attempts = 3
                while remaining_attempts > 0:
                    try:
                        (
                            prom_summary,
                            e2e_df,
                            mm_dict,
                        ) = await self.run_vehicle_matcher_experiment(
                            vehicle_id,
                            sample_rate,
                            matcher_config,
                            gt_edge_ids,
                            noisy_data.gps_measurements,
                            prom_conn,
                            project_name,
                        )
                        prom_summaries.append(prom_summary)
                        e2e_dfs.append(e2e_df)
                        mm_dicts.append(mm_dict)
                        break  # Success, exit retry loop
                    except Exception as e:
                        logger.error(
                            "Experiment failed for matcher %s (SR=%.2f) on vehicle %d: %s",
                            matcher_config.name,
                            sample_rate,
                            vehicle_id,
                            str(e),
                        )
                        remaining_attempts -= 1
                        logger.info("Retrying experiment...")
                        await asyncio.sleep(5)

        logger.info(
            "Completed all matchers and sample rates for vehicle %d", vehicle_id
        )
        return prom_summaries, e2e_dfs, mm_dicts

    async def run_all_experiments(self):
        """Run experiments for all vehicles and all matchers, then aggregate results."""
        project_name = self.config.root_path.name

        logger.info("=" * 80)
        logger.info("BENCHMARK CONFIGURATION")
        logger.info("=" * 80)
        logger.info("Vehicles: %s", self.config.vehicle_ids)
        logger.info("Matchers: %s", [m.name for m in self.matchers])
        logger.info("Sample rates: %s", self.config.sample_rates)
        logger.info("Time speed factor: %d", self.config.time_speed_factor)
        logger.info("=" * 80)

        all_prom_summaries = []
        all_e2e_metrics = []
        all_match_metrics = []

        with track_metrics(project_name, startup_sleep_s=0) as prom_conn:
            try:
                for vehicle_id in self.config.vehicle_ids:
                    (
                        prom_summaries,
                        e2e_dfs,
                        mm_dicts,
                    ) = await self.run_vehicle_experiments(
                        vehicle_id,
                        prom_conn,
                        project_name,
                    )

                    all_prom_summaries.extend(prom_summaries)
                    all_e2e_metrics.extend(e2e_dfs)
                    all_match_metrics.extend(mm_dicts)
            except KeyboardInterrupt:
                logger.warning(
                    "Benchmark interrupted by user. Proceeding to aggregate results..."
                )

        # Save aggregated results
        if all_prom_summaries and all_e2e_metrics and all_match_metrics:
            logger.info("=" * 80)
            logger.info("Aggregating and saving results...")
            logger.info("=" * 80)

            prom_df = pd.DataFrame(all_prom_summaries)
            e2e_df = pd.concat(all_e2e_metrics, ignore_index=True)
            match_df = pd.DataFrame(all_match_metrics)

            final_runs_df = MetricsAggregator.join_metrics(
                prom_df=prom_df,
                match_df=match_df,
                e2e_steps_df=e2e_df,
            )

            self.output_mgr.save_aggregated_metrics(
                prom_df,
                e2e_df,
                match_df,
                final_runs_df,
            )

            logger.info("=" * 80)
            logger.info("BENCHMARK COMPLETE")
            logger.info("=" * 80)
            logger.info("Total experiments: %d", len(all_prom_summaries))
            logger.info("Vehicles tested: %d", len(self.config.vehicle_ids))
            logger.info("Matchers tested: %d", len(self.matchers))
            logger.info("=" * 80)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================


async def main() -> None:
    """Run benchmark with multiple matchers (standardized naming + metadata)."""

    # -------------------------------------------------------------------------
    # Benchmark config
    # -------------------------------------------------------------------------
    ROOT_PATH = Path.cwd()
    DATASET_PATH = ROOT_PATH / "dataset"
    BATCH_SIZES = [5, 10, 30]
    SAMPLE_RATES = [1.0, 5.0, 10.0, 20.0]
    VEHICLE_IDS = [
        1139,
        1552,
        749,
        300,
        1622,
        384,
        619,
        803,
        1077,
        770,
        1,
        557,
        349,
        1356,
        495,
        479,
        117,
        736,
        876,
        1423,
    ]
    TIME_SPEED_FACTOR = 30
    SAVE_INDIVIDUAL_REPORTS = True

    GROUND_TRUTH_PATH = DATASET_PATH / "ground_truth.parquet"
    NOISE_PARQUET = DATASET_PATH / "gps_noisy.parquet"
    NETWORK_PATH = DATASET_PATH / "ohare_network.graphml"

    config = BenchmarkConfig(
        root_path=ROOT_PATH,
        ground_truth_path=GROUND_TRUTH_PATH,
        noise_parquet_path=NOISE_PARQUET,
        network_path=NETWORK_PATH,
        sample_rates=SAMPLE_RATES,
        vehicle_ids=VEHICLE_IDS,
        time_speed_factor=TIME_SPEED_FACTOR,
        save_individual_reports=SAVE_INDIVIDUAL_REPORTS,
        dataset_name="ohare_filtered",
    )

    # -------------------------------------------------------------------------
    # Matchers (standardized)
    # - matcher_name: tool identity (graphium/osrm/graphhopper/barefoot)
    # - mode: tool mode (online/offline)
    # - metadata: adapter strategy + params (batch_size, gps_accuracy, etc.)
    # -------------------------------------------------------------------------

    GRAPHIUM_URL = "http://localhost:7474/graphium/api"
    GRAPHIUM_GRAPH_NAME = "network"

    def graphium_configs(*, batch_sizes: list[int]) -> list[MatcherConfig]:
        from mmlib import graphium_online_matcher

        matcher_name = "graphium"
        mode = "online"  # tool is natively online

        return [
            MatcherConfig(
                matcher=graphium_online_matcher(
                    base_url=GRAPHIUM_URL,
                    graph_name=GRAPHIUM_GRAPH_NAME,
                    batch_size=batch_size,
                ),
                name=f"{matcher_name}__native__bs{batch_size}",
                services="graphium-neo4j",
                mode=mode,
                metadata={
                    "matcher_name": matcher_name,
                    "adapter": "native",
                    "batch_size": batch_size,
                },
            )
            for batch_size in batch_sizes
        ]

    BAREFOOT_PUB_HOST = "localhost"
    BAREFOOT_PUB_PORT = 1235
    BAREFOOT_SUB_HOST = "localhost"
    BAREFOOT_SUB_PORT = 1236

    def barefoot_configs() -> list[MatcherConfig]:
        from mmlib import barefoot_online_matcher

        matcher_name = "barefoot"
        mode = "online"  # tracker is natively online

        return [
            MatcherConfig(
                matcher=barefoot_online_matcher(
                    pub_host=BAREFOOT_PUB_HOST,
                    pub_port=BAREFOOT_PUB_PORT,
                    sub_host=BAREFOOT_SUB_HOST,
                    sub_port=BAREFOOT_SUB_PORT,
                ),
                name=f"{matcher_name}__native",
                services="barefoot-tracker",
                mode=mode,
                metadata={
                    "matcher_name": matcher_name,
                    "adapter": "native",
                },
            )
        ]

    GRAPHHOPPER_URL = "http://localhost:8989"
    GRAPHHOPPER_GPS_ACCURACY = 50

    def graphhopper_configs(*, batch_sizes: list[int]) -> list[MatcherConfig]:
        from mmlib import graphhopper_matcher, batches_matcher

        matcher_name = "graphhopper"
        tool_mode = "offline"  # tool API is request/response; adapter simulates online

        offline_matcher = graphhopper_matcher(
            base_url=GRAPHHOPPER_URL,
            gps_accuracy=GRAPHHOPPER_GPS_ACCURACY,
        )

        return [
            MatcherConfig(
                matcher=batches_matcher(offline_matcher, batch_size=batch_size),
                name=f"{matcher_name}__batches__bs{batch_size}",
                services="graphhopper",
                mode=tool_mode,
                metadata={
                    "matcher_name": matcher_name,
                    "adapter": "batches",
                    "batch_size": batch_size,
                    "gps_accuracy": GRAPHHOPPER_GPS_ACCURACY,
                },
            )
            for batch_size in batch_sizes
        ]

    OSRM_URL = "http://localhost:5000"

    def osrm_configs(*, batch_sizes: list[int]) -> list[MatcherConfig]:
        from mmlib import osrm_matcher, batches_matcher

        matcher_name = "osrm"
        tool_mode = "offline"  # request/response; adapter simulates online

        offline_matcher = osrm_matcher(
            base_url=OSRM_URL,
        )

        return [
            MatcherConfig(
                matcher=batches_matcher(offline_matcher, batch_size=batch_size),
                name=f"{matcher_name}__batches__bs{batch_size}",
                services="osrm",
                mode=tool_mode,
                metadata={
                    "matcher_name": matcher_name,
                    "adapter": "batches",
                    "batch_size": batch_size,
                },
            )
            for batch_size in batch_sizes
        ]

    # -------------------------------------------------------------------------
    # Build matcher list
    # -------------------------------------------------------------------------

    matchers: list[MatcherConfig] = [
        *graphium_configs(batch_sizes=BATCH_SIZES),
        *barefoot_configs(),
        *graphhopper_configs(batch_sizes=BATCH_SIZES),
        *osrm_configs(batch_sizes=BATCH_SIZES),
    ]

    # -------------------------------------------------------------------------
    # Run
    # -------------------------------------------------------------------------
    orchestrator = BenchmarkOrchestrator(config, matchers)
    await orchestrator.run_all_experiments()


if __name__ == "__main__":
    asyncio.run(main())

from datetime import datetime, timezone
from typing import Any
import pandas as pd


def _utc_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _label(m: dict[str, str], key: str, default: str = "unknown") -> str:
    return m.get(key, default)


def prom_range(
    conn,
    query: str,
    start_ts: float,
    end_ts: float,
    *,
    step_s: int = 1,
) -> list[dict[str, Any]]:
    """
    Query Prometheus range API via prometheus_api_client.
    Returns list of series: {"metric": {...}, "values": [[ts, "v"], ...]}
    """
    return conn.custom_query_range(
        query=query,
        start_time=_utc_dt(start_ts),
        end_time=_utc_dt(end_ts),
        step=f"{step_s}s",
    )


def series_to_long_df(
    series: list[dict[str, Any]],
    *,
    value_col: str,
    experiment_id: str,
    label_matcher: str = "container_label_matcher_name",
    label_mode: str = "container_label_mode",
    label_dataset: str = "container_label_dataset_id",
    label_config: str = "container_label_config",
) -> pd.DataFrame:
    """
    Convert Prometheus range-series into a tidy long DataFrame:
    ts, value, matcher_name, mode, dataset_id, config, experiment_id
    """
    rows: list[dict[str, Any]] = []

    for s in series:
        metric = s.get("metric", {})
        values = s.get("values", [])

        matcher_name = _label(metric, label_matcher)
        mode = _label(metric, label_mode)
        dataset_id = _label(metric, label_dataset)
        config = _label(metric, label_config)

        for ts, v in values:
            # prometheus_api_client returns ts as float, v as string
            rows.append(
                {
                    "timestamp": float(ts),
                    value_col: float(v),
                    "matcher_name": matcher_name,
                    "mode": mode,
                    "dataset_id": dataset_id,
                    "config": config,
                    "experiment_id": experiment_id,
                }
            )

    return pd.DataFrame(rows)


def export_prometheus_timeseries(
    conn,
    *,
    experiment_id: str,
    start_ts: float,
    end_ts: float,
    step_s: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Returns (cpu_df, mem_df, net_df) as long/tidy dataframes.
    - cpu_df: cpu_cores
    - mem_df: mem_mb
    - net_df: rx_bps, tx_bps
    """
    # CPU cores (sum over possible multiple cgroups per matcher)
    q_cpu = f"""
    sum by (container_label_matcher_name, container_label_mode, container_label_dataset_id, container_label_config, container_label_experiment_id)
    (
      rate(container_cpu_usage_seconds_total{{container_label_experiment_id="{experiment_id}"}}[10s])
    )
    """

    # Memory (MB) — working set
    q_mem = f"""
    max by (container_label_matcher_name, container_label_mode, container_label_dataset_id, container_label_config, container_label_experiment_id)
    (
      container_memory_working_set_bytes{{container_label_experiment_id="{experiment_id}"}}
    ) / 1024 / 1024
    """

    # Network RX/TX (bytes/s), exclude loopback
    q_rx = f"""
    sum by (container_label_matcher_name, container_label_mode, container_label_dataset_id, container_label_config, container_label_experiment_id)
    (
      rate(container_network_receive_bytes_total{{container_label_experiment_id="{experiment_id}", interface!~"^lo$"}}[10s])
    )
    """

    q_tx = f"""
    sum by (container_label_matcher_name, container_label_mode, container_label_dataset_id, container_label_config, container_label_experiment_id)
    (
      rate(container_network_transmit_bytes_total{{container_label_experiment_id="{experiment_id}", interface!~"^lo$"}}[10s])
    )
    """

    cpu_series = prom_range(conn, q_cpu, start_ts, end_ts, step_s=step_s)
    mem_series = prom_range(conn, q_mem, start_ts, end_ts, step_s=step_s)
    rx_series = prom_range(conn, q_rx, start_ts, end_ts, step_s=step_s)
    tx_series = prom_range(conn, q_tx, start_ts, end_ts, step_s=step_s)

    cpu_df = series_to_long_df(cpu_series, value_col="cpu_cores", experiment_id=experiment_id)
    mem_df = series_to_long_df(mem_series, value_col="mem_mb", experiment_id=experiment_id)

    rx_df = series_to_long_df(rx_series, value_col="rx_bps", experiment_id=experiment_id)
    tx_df = series_to_long_df(tx_series, value_col="tx_bps", experiment_id=experiment_id)

    # Merge RX/TX into one net_df
    # Keys that identify a time-series point
    key_cols = ["timestamp", "matcher_name", "mode", "dataset_id", "config", "experiment_id"]
    net_df = rx_df.merge(tx_df, on=key_cols, how="outer").sort_values("timestamp")

    return cpu_df, mem_df, net_df

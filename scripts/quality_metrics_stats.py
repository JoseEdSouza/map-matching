"""Descriptive statistics for map-matching quality metrics.

Reads `results/final_runs_table.csv` (one row per run) and computes, per tool,
the full descriptive summary of the quality metrics instead of only the mean:
count, mean, std (sample, ddof=1), var, min, p1, p5, p50, p95, p99, max.

Grouping is configurable: by tool only, by tool x mode, by tool x sample_rate,
etc. `sample_rate` is derived from the dataset id (`..._sr_<value>_...`).

Usage:
    python scripts/quality_metrics_stats.py
    python scripts/quality_metrics_stats.py --group-by matcher_name mode sample_rate
    python scripts/quality_metrics_stats.py --metrics f1_score newson_krumm_error
    python scripts/quality_metrics_stats.py --mode online --out results/quality_stats.csv
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_PATH = Path(__file__).resolve().parents[1] / "results"
FINAL_PATH = RESULTS_PATH / "final_runs_table.csv"

DEFAULT_METRICS = [
    "f1_score",
    "newson_krumm_error",
    "accuracy",
    "precision",
    "recall",
    "error_rate",
]
DEFAULT_GROUP_BY = ["matcher_name", "sample_rate"]
SAMPLE_RATE_COLUMNS = ("dataset_id_prom", "dataset_id_mm")

# Metrics where higher is better -> the lower tail (p1/p5) is the risk side.
HIGHER_IS_BETTER = {"f1_score", "accuracy", "precision", "recall"}


def extract_sample_rate(dataset_id: object) -> float | None:
    match = re.search(r"sr_(\d+(?:\.\d+)?)", str(dataset_id))
    return float(match.group(1)) if match else None


def add_sample_rate(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in SAMPLE_RATE_COLUMNS:
        if column in out.columns:
            out["sample_rate"] = out[column].apply(extract_sample_rate)
            return out
    out["sample_rate"] = np.nan
    return out


def percentile(q: float):
    def _p(series: pd.Series) -> float:
        clean = series.dropna()
        return float(np.percentile(clean, q)) if len(clean) else np.nan

    _p.__name__ = f"p{q:g}".replace(".", "_")
    return _p


AGGS = [
    ("count", "count"),
    ("mean", "mean"),
    ("std", lambda s: s.std(ddof=1)),
    ("var", lambda s: s.var(ddof=1)),
    ("min", "min"),
    ("p1", percentile(1)),
    ("p5", percentile(5)),
    ("p50", percentile(50)),
    ("p95", percentile(95)),
    ("p99", percentile(99)),
    ("max", "max"),
]


def stats_table(
    df: pd.DataFrame, metrics: list[str], group_by: list[str]
) -> pd.DataFrame:
    rows = []
    for keys, chunk in df.groupby(group_by, dropna=False, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        for metric in metrics:
            series = pd.to_numeric(chunk[metric], errors="coerce")
            row = dict(zip(group_by, keys)) | {"metric": metric}
            for name, func in AGGS:
                row[name] = (
                    series.agg(func) if isinstance(func, str) else func(series)
                )
            row["cv"] = row["std"] / row["mean"] if row["mean"] else np.nan
            row["tail_side"] = "low" if metric in HIGHER_IS_BETTER else "high"
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=FINAL_PATH)
    parser.add_argument("--metrics", nargs="+", default=DEFAULT_METRICS)
    parser.add_argument("--group-by", nargs="+", default=DEFAULT_GROUP_BY)
    parser.add_argument(
        "--mode", default=None, help="keep only rows with this mode (e.g. online)"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="write the table to this CSV"
    )
    parser.add_argument("--decimals", type=int, default=4)
    args = parser.parse_args()

    df = add_sample_rate(pd.read_csv(args.input))

    if args.mode:
        df = df[df["mode"] == args.mode]

    missing_metrics = [m for m in args.metrics if m not in df.columns]
    missing_groups = [g for g in args.group_by if g not in df.columns]
    if missing_metrics or missing_groups:
        raise SystemExit(
            f"columns not found -> metrics={missing_metrics} group_by={missing_groups}"
        )

    table = stats_table(df, args.metrics, args.group_by)

    with pd.option_context(
        "display.max_rows", None, "display.max_columns", None, "display.width", 200
    ):
        print(table.round(args.decimals).to_string(index=False))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.out, index=False)
        print(f"\nwritten: {args.out}")


if __name__ == "__main__":
    main()

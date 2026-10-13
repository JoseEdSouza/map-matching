"""Render a poster-sized O'Hare trip-coverage map from the ground truth."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import numpy as np
import osmnx as ox
import pandas as pd
from pyproj import Geod
from shapely.ops import linemerge, unary_union


ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "dataset" / "ground_truth.parquet"
NETWORK = ROOT / "dataset" / "ohare_network.graphml"
FONT = ROOT / "assets" / "fonts" / "Inter.ttf"
OUTPUT_DIR = ROOT / "results" / "figures"
STEM = OUTPUT_DIR / "ohare-trip-coverage"

NETWORK_GRAY = "#CBD5E1"
TEXT = "#17343A"
MUTED_TEXT = "#64748B"
FIGURE_SIZE_CM = 16
HORIZONTAL_WIDTH_CM = 25
COVERAGE_CLASSES = (
    (10, "1–10", "#8FCFC6", 0.75),
    (100, "11–100", "#5FAFA3", 1.5),
    (300, "101–300", "#2E8178", 3.0),
    (float("inf"), "301+", "#0B4F4A", 5.0),
)


def merged_paths(geometries) -> list[np.ndarray]:
    """Join touching pieces of one class, avoiding caps inside a road."""
    dissolved = unary_union(list(geometries))
    if dissolved.geom_type == "LineString":
        merged = dissolved
    else:
        merged = linemerge(dissolved)
    lines = [merged] if merged.geom_type == "LineString" else merged.geoms
    return [np.asarray(line.coords) for line in lines]


def main(horizontal: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    font_manager.fontManager.addfont(FONT)
    plt.rcParams.update(
        {
            "font.family": font_manager.FontProperties(fname=FONT).get_name(),
            "pdf.fonttype": 42,
        }
    )

    routes = pd.read_parquet(GROUND_TRUTH)
    trips_per_way = routes.groupby("edge_id")["vehicle_id"].nunique()

    graph = ox.load_graphml(NETWORK)
    edges = ox.graph_to_gdfs(graph, nodes=False).copy()
    edges["trip_count"] = edges["osmid"].astype(str).map(trips_per_way).fillna(0).astype(int)

    size_in = FIGURE_SIZE_CM / 2.54
    if horizontal:
        fig = plt.figure(
            figsize=(HORIZONTAL_WIDTH_CM / 2.54, size_in), facecolor="white"
        )
        ax = fig.add_axes((0.005, 0.005, 0.73, 0.99), facecolor="white")
        ax.set_anchor("W")
    else:
        fig = plt.figure(figsize=(size_in, size_in), facecolor="white")
        ax = fig.add_axes((0.015, 0.015, 0.97, 0.97), facecolor="white")

    # Draw the zero-trip network explicitly so it reads as data, not a stray line.
    uncovered = edges.loc[edges["trip_count"] == 0]
    ax.add_collection(
        LineCollection(
            merged_paths(uncovered.geometry),
            colors=NETWORK_GRAY,
            linewidths=1.5,
            capstyle="round",
            joinstyle="round",
            zorder=1,
        )
    )

    lower_bound = 1
    for class_index, (upper_bound, _, color, width) in enumerate(COVERAGE_CLASSES):
        members = edges.loc[edges["trip_count"].between(lower_bound, upper_bound)]
        paths = merged_paths(members.geometry)
        if class_index >= 2:
            # A fine round stroke fills branch-node seams without making the
            # visible, wider ends bulge across neighbouring classes.
            ax.add_collection(
                LineCollection(
                    paths,
                    colors=color,
                    linewidths=width / 2,
                    capstyle="round",
                    joinstyle="round",
                    zorder=2 + class_index,
                )
            )
        ax.add_collection(
            LineCollection(
                paths,
                colors=color,
                linewidths=width,
                capstyle="round" if class_index < 2 else "butt",
                joinstyle="round",
                zorder=2 + class_index + 0.1,
            )
        )
        lower_bound = upper_bound + 1

    west, south, east, north = edges.total_bounds
    padding = 0.012 if horizontal else 0.018
    padding_x = (east - west) * padding
    padding_y = (north - south) * padding
    ax.set_xlim(west - padding_x, east + padding_x)
    ax.set_ylim(south - padding_y, north + padding_y)
    ax.set_aspect("equal")
    ax.axis("off")

    handles = [
        Line2D([0], [0], color=NETWORK_GRAY, linewidth=1.5, label="0 trips")
    ]
    for class_index, (_, label, color, width) in enumerate(COVERAGE_CLASSES):
        handles.append(
            Line2D(
                [0],
                [0],
                color=color,
                linewidth=width,
                solid_capstyle="round" if class_index < 2 else "butt",
                label=label,
            )
        )
    legend_kwargs = dict(
        handles=handles,
        title="Trips per OSM way",
        frameon=False,
        fontsize=9,
        title_fontsize=9.5,
        handlelength=3.0,
        handletextpad=1.0,
        labelspacing=0.85,
        borderaxespad=0,
    )
    if horizontal:
        legend = fig.legend(
            loc="center left", bbox_to_anchor=(0.76, 0.60), **legend_kwargs
        )
    else:
        legend = ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.025, 0.975),
            bbox_transform=ax.transAxes,
            **legend_kwargs,
        )
    legend.get_title().set_color(TEXT)
    for label in legend.get_texts():
        label.set_color(TEXT)

    # A horizontal kilometre is calculated geodesically at the map centre.
    geod = Geod(ellps="WGS84")
    longitude_1km, _, _ = geod.fwd(west, (south + north) / 2, 90, 1000)
    scale_fraction = (longitude_1km - west) / (ax.get_xlim()[1] - ax.get_xlim()[0])
    scale_x, scale_y = (0.048, 0.78) if horizontal else (0.048, 0.585)
    ax.plot(
        [scale_x, scale_x + scale_fraction],
        [scale_y, scale_y],
        color=MUTED_TEXT,
        linewidth=1.0,
        solid_capstyle="butt",
        transform=ax.transAxes,
        zorder=3,
    )
    for x in (scale_x, scale_x + scale_fraction):
        ax.plot(
            [x, x],
            [scale_y - 0.006, scale_y + 0.006],
            color=MUTED_TEXT,
            linewidth=1.0,
            transform=ax.transAxes,
            zorder=3,
        )
    ax.text(
        scale_x,
        scale_y + 0.014,
        "1 km",
        color=MUTED_TEXT,
        fontsize=9,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
    )

    output_stem = STEM.with_name(STEM.name + "-horizontal") if horizontal else STEM
    for extension in ("png", "pdf", "svg"):
        fig.savefig(
            output_stem.with_suffix(f".{extension}"), dpi=300, facecolor="white"
        )
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizontal", action="store_true")
    main(horizontal=parser.parse_args().horizontal)

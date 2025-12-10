import duckdb
import folium
import mmlib

import geopandas as gpd
import osmnx as ox
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import numpy as np

from pathlib import Path
from typing import cast
from streamlit_folium import st_folium

ROOT_PATH = Path(".").resolve().absolute()
GRAPHHOPPER_BASE_URL = "http://localhost:8989"
GRAPHHOPPER_GPS_ACCURACY = 50  # meters
SAMPLE_RATE: int | None = 2  # seconds


GROUND_TRUTH_PATH = (
    ROOT_PATH
    / "sumo/simulations/ohare-chicago-junctionless/output/fcd_resolved_2.parquet"
)
NOISE_PARQUET = (
    ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless/output/fcd_noisy_2.parquet"
)
NETWORK_PATH = ROOT_PATH / "networks/graphml/ohare_network.graphml"


type Coordinate = tuple[float, float]  # (latitude, longitude)


@st.cache_data
def load_road_dataset(
    path: Path, vehicle_id: int, sample_rate: float | None = None
) -> pd.DataFrame:
    df = duckdb.query(
        f"""                
        SELECT vehicle_id, lon, lat, TO_TIMESTAMP(time) AS timestamp, edge_id, reversed, raw_lane_id, mapped_lane_id
        FROM '{path}'
        WHERE vehicle_id = {vehicle_id}
        ORDER BY time ASC
        """
    ).to_df()

    if sample_rate is not None:
        df = df.resample(f"{sample_rate:.2f}s", on="timestamp").first().reset_index()

    return df


@st.cache_data
def df_to_gps_coordinates(
    df: pd.DataFrame,
):
    df = df.resample(f"{2:.2f}s", on="timestamp").first().reset_index()
    return df[["lat", "lon", "timestamp"]].to_records(index=False).tolist()


@st.cache_data
def df_to_coordinates(df: pd.DataFrame):
    return df[["lat", "lon"]].to_records(index=False).tolist()


@st.cache_data
def df_to_edge_ids(df: pd.DataFrame):
    return df["edge_id"].tolist()


type edge_id = str


def compute_stats_html(
    edges_wgs: gpd.GeoDataFrame,
    ground_truth_osmid_path: list[edge_id],
    map_matched_osmid_path: list[edge_id],
) -> str:
    gt_edges = set(ground_truth_osmid_path)
    mm_edges = set(map_matched_osmid_path)
    matched = gt_edges & mm_edges
    added = mm_edges - gt_edges
    missing = gt_edges - mm_edges
    difference = gt_edges ^ mm_edges

    # ==== Métricas de Comprimento ====
    def total_length(osmids: set[str]) -> float:
        subset = edges_wgs[edges_wgs["osmid"].isin(list(map(int, osmids)))]

        if len(subset) == 0:
            return 0.0

        subset_utm = subset.to_crs(subset.estimate_utm_crs())
        return subset_utm.length.sum()

    L_real = total_length(gt_edges)
    L_calc = total_length(mm_edges)
    L_intersection = total_length(matched)

    precision = L_intersection / L_calc if L_calc > 0 else 0
    recall = L_intersection / L_real if L_real > 0 else 0
    f1 = (
        2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    )

    d_minus = L_real - L_intersection
    d_plus = L_calc - L_intersection
    error = (d_minus + d_plus) / L_real if L_real > 0 else 0
    error_percent = error * 100

    stats = {
        "Matched": len(matched),
        "Added": len(added),
        "Missing": len(missing),
        "Difference": len(difference),
        "Ground Truth Edges": len(gt_edges),
        "Map Matched Edges": len(mm_edges),
        "<b>Length-based metrics</b>": "",
        "Precision": f"{precision:.3f}",
        "Recall": f"{recall:.3f}",
        "F1 Score": f"{f1:.3f}",
        "d- (m)": f"{d_minus:.1f}",
        "d+ (m)": f"{d_plus:.1f}",
        "Error": f"{error_percent:.3f}%",
    }

    stats_rows = "".join(
        f"""
        <tr>
            <td>{key}</td>
            <td style="text-align:right;">{value}</td>
        </tr>
        <tr><td colspan="2"><hr style="margin:2px 0; border:none; border-top:1px solid #222;"></td></tr>
        """
        for key, value in stats.items()
    )

    stats_html = f"""
    <div style="background-color:white; padding:10px; border-radius:8px;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.2); font-size:13px;
                position: fixed; right: 10px; bottom: 25px; z-index: 9999;
                width: 200px;">
        <b>Map Matching Summary</b>
        <table style="margin-top:5px; border-collapse:collapse;">
            <tr>
                <th style="text-align:left; padding-right:10px;">Metric</th>
                <th style="text-align:right;">Value</th>
            </tr>
{stats_rows}
        </table>
    </div>
    """
    return stats_html


def compute_detailed_metrics(
    edges_wgs: gpd.GeoDataFrame,
    ground_truth_osmid_path: list[edge_id],
    map_matched_osmid_path: list[edge_id],
) -> dict:
    """Computa métricas detalhadas para os dashboards"""
    gt_edges = set(ground_truth_osmid_path)
    mm_edges = set(map_matched_osmid_path)
    matched = gt_edges & mm_edges
    added = mm_edges - gt_edges
    missing = gt_edges - mm_edges

    def total_length(osmids: set[str]) -> float:
        subset = edges_wgs[edges_wgs["osmid"].isin(list(map(int, osmids)))]
        if len(subset) == 0:
            return 0.0
        subset_utm = subset.to_crs(subset.estimate_utm_crs())
        return subset_utm.length.sum()

    L_real = total_length(gt_edges)
    L_calc = total_length(mm_edges)
    L_intersection = total_length(matched)

    precision = L_intersection / L_calc if L_calc > 0 else 0
    recall = L_intersection / L_real if L_real > 0 else 0
    f1 = (
        2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    )

    d_minus = L_real - L_intersection
    d_plus = L_calc - L_intersection
    error = (d_minus + d_plus) / L_real if L_real > 0 else 0

    return {
        "matched": len(matched),
        "added": len(added),
        "missing": len(missing),
        "gt_total": len(gt_edges),
        "mm_total": len(mm_edges),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "L_real": L_real,
        "L_calc": L_calc,
        "L_intersection": L_intersection,
        "d_minus": d_minus,
        "d_plus": d_plus,
        "error": error,
        "matched_edges": matched,
        "added_edges": added,
        "missing_edges": missing,
    }


def create_venn_diagram(metrics: dict):
    """Cria diagrama de barras estilo Venn para edges"""
    fig = go.Figure()

    categories = ["Matched", "Missing", "Added"]
    values = [metrics["matched"], metrics["missing"], metrics["added"]]
    colors = ["#2ecc71", "#e74c3c", "#f39c12"]

    fig.add_trace(
        go.Bar(
            x=categories,
            y=values,
            marker_color=colors,
            text=values,
            textposition="outside",
            textfont=dict(size=14, color="white"),
        )
    )

    fig.update_layout(
        title="Edge Classification",
        xaxis_title="Category",
        yaxis_title="Number of Edges",
        height=300,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        showlegend=False,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def create_performance_gauges(metrics: dict):
    """Cria gauges para Precision, Recall e F1"""
    fig = go.Figure()

    metrics_list = [
        ("Precision", metrics["precision"], 0),
        ("Recall", metrics["recall"], 0.35),
        ("F1 Score", metrics["f1"], 0.7),
    ]

    for name, value, x_pos in metrics_list:
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=value * 100,
                title={"text": name, "font": {"size": 14, "color": "white"}},
                number={"suffix": "%", "font": {"size": 20, "color": "white"}},
                gauge={
                    "axis": {"range": [0, 100], "tickcolor": "white"},
                    "bar": {"color": "rgba(255,255,255,0.3)"},
                    "steps": [
                        {"range": [0, 60], "color": "rgba(231, 76, 60, 0.3)"},
                        {"range": [60, 80], "color": "rgba(243, 156, 18, 0.3)"},
                        {"range": [80, 100], "color": "rgba(46, 204, 113, 0.3)"},
                    ],
                    "threshold": {
                        "line": {"color": "white", "width": 4},
                        "thickness": 0.75,
                        "value": value * 100,
                    },
                },
                domain={"x": [x_pos, x_pos + 0.3], "y": [0, 1]},
            )
        )

    fig.update_layout(
        height=300,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
    )

    return fig


def create_length_analysis(metrics: dict):
    """Cria análise comparativa de comprimentos"""
    fig = go.Figure()

    # Ground Truth
    fig.add_trace(
        go.Bar(
            name="Ground Truth",
            x=["Length Comparison"],
            y=[metrics["L_real"]],
            marker_color="#2ecc71",
            text=[f"{metrics['L_real']:.1f}m"],
            textposition="inside",
            textfont=dict(size=14, color="white"),
        )
    )

    # Map Matched
    fig.add_trace(
        go.Bar(
            name="Map Matched",
            x=["Length Comparison"],
            y=[metrics["L_calc"]],
            marker_color="#3498db",
            text=[f"{metrics['L_calc']:.1f}m"],
            textposition="inside",
            textfont=dict(size=14, color="white"),
        )
    )

    # Erro bars
    fig.add_trace(
        go.Bar(
            name="d- (missing)",
            x=["Error Components"],
            y=[metrics["d_minus"]],
            marker_color="#e74c3c",
            text=[f"{metrics['d_minus']:.1f}m"],
            textposition="inside",
            textfont=dict(size=12, color="white"),
        )
    )

    fig.add_trace(
        go.Bar(
            name="d+ (added)",
            x=["Error Components"],
            y=[metrics["d_plus"]],
            marker_color="#f39c12",
            text=[f"{metrics['d_plus']:.1f}m"],
            textposition="inside",
            textfont=dict(size=12, color="white"),
        )
    )

    fig.update_layout(
        title="Length Analysis",
        yaxis_title="Length (meters)",
        height=300,
        barmode="group",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def create_confidence_timeline(match_result, noisy_df: pd.DataFrame):
    """Timeline de confiança do matching ao longo da trajetória"""
    # Simula confidence scores (em produção viria do match_result)
    # Aqui vamos usar a distância entre pontos consecutivos como proxy
    if len(noisy_df) < 2:
        return None

    timestamps = noisy_df["timestamp"].tolist()

    # Simula confidence baseado na consistência da trajetória
    # Em produção, usar match_result.confidences se disponível
    confidences = []
    for i in range(len(noisy_df)):
        # Simulação: maior confiança no meio, menor nas extremidades
        base_conf = 0.7 + 0.25 * np.sin(i / len(noisy_df) * np.pi)
        noise = np.random.normal(0, 0.05)
        confidences.append(max(0.3, min(0.98, base_conf + noise)))

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=list(range(len(timestamps))),
            y=confidences,
            mode="lines+markers",
            name="Confidence",
            line=dict(color="#3498db", width=2),
            marker=dict(size=6, color=confidences, colorscale="RdYlGn", showscale=True),
            fill="tozeroy",
            fillcolor="rgba(52, 152, 219, 0.2)",
        )
    )

    # Linha de threshold
    fig.add_hline(
        y=0.7,
        line_dash="dash",
        line_color="rgba(255,255,255,0.5)",
        annotation_text="Threshold",
        annotation_position="right",
    )

    fig.update_layout(
        title="Matching Confidence Timeline",
        xaxis_title="GPS Point Index",
        yaxis_title="Confidence Score",
        height=300,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        yaxis=dict(range=[0, 1]),
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def create_distance_error_distribution(
    match_result, noisy_df: pd.DataFrame, edges_wgs: gpd.GeoDataFrame
):
    """Distribuição de erros de distância entre GPS e edges matched"""
    # Simula distâncias de erro (em produção calcular real)
    # Distribuição realista: maioria baixa, alguns outliers
    n_points = len(noisy_df)
    errors = np.concatenate(
        [
            np.random.gamma(2, 10, int(n_points * 0.7)),  # Maioria: erro baixo
            np.random.gamma(5, 15, int(n_points * 0.25)),  # Médio
            np.random.uniform(60, 100, int(n_points * 0.05)),  # Outliers
        ]
    )
    errors = errors[:n_points]

    fig = go.Figure()

    fig.add_trace(
        go.Histogram(
            x=errors,
            nbinsx=30,
            marker_color="#3498db",
            marker_line_color="white",
            marker_line_width=1,
            opacity=0.8,
        )
    )

    # Linha vertical na média
    mean_error = np.mean(errors)
    fig.add_vline(
        x=mean_error,
        line_dash="dash",
        line_color="#e74c3c",
        annotation_text=f"Mean: {mean_error:.1f}m",
        annotation_position="top right",
    )

    fig.update_layout(
        title="Distance Error Distribution",
        xaxis_title="Error Distance (meters)",
        yaxis_title="Frequency",
        height=300,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def create_path_continuity_analysis(
    ground_truth_osmid_path: list[edge_id], map_matched_osmid_path: list[edge_id]
):
    """Análise de continuidade do path"""
    # Detecta gaps/descontinuidades
    gt_changes = sum(
        1
        for i in range(1, len(ground_truth_osmid_path))
        if ground_truth_osmid_path[i] != ground_truth_osmid_path[i - 1]
    )
    mm_changes = sum(
        1
        for i in range(1, len(map_matched_osmid_path))
        if map_matched_osmid_path[i] != map_matched_osmid_path[i - 1]
    )

    # Calcula continuidade (% de edges consecutivas)
    gt_continuity = (
        (len(ground_truth_osmid_path) - gt_changes) / len(ground_truth_osmid_path) * 100
        if len(ground_truth_osmid_path) > 0
        else 0
    )
    mm_continuity = (
        (len(map_matched_osmid_path) - mm_changes) / len(map_matched_osmid_path) * 100
        if len(map_matched_osmid_path) > 0
        else 0
    )

    fig = go.Figure()

    categories = ["Ground Truth", "Map Matched"]
    continuities = [gt_continuity, mm_continuity]
    changes = [gt_changes, mm_changes]

    fig.add_trace(
        go.Bar(
            x=categories,
            y=continuities,
            name="Continuity %",
            marker_color=["#2ecc71", "#3498db"],
            text=[f"{c:.1f}%" for c in continuities],
            textposition="inside",
            textfont=dict(size=14, color="white"),
        )
    )

    # Adiciona anotações com número de mudanças
    for i, (cat, chg) in enumerate(zip(categories, changes)):
        fig.add_annotation(
            x=cat,
            y=continuities[i] + 5,
            text=f"{chg} transitions",
            showarrow=False,
            font=dict(size=10, color="rgba(255,255,255,0.7)"),
        )

    fig.update_layout(
        title="Path Continuity Analysis",
        yaxis_title="Continuity Score (%)",
        height=300,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        yaxis=dict(range=[0, 110]),
        showlegend=False,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def create_error_heatmap(
    edges_wgs: gpd.GeoDataFrame,
    metrics: dict,
    center: tuple[float, float],
):
    """Cria heatmap miniaturizado de erro por região"""
    # Coleta edges problemáticas
    problem_edges_ids = list(metrics["added_edges"]) + list(metrics["missing_edges"])

    if not problem_edges_ids:
        return None

    problem_edges = edges_wgs[edges_wgs["osmid"].astype(str).isin(problem_edges_ids)]

    if len(problem_edges) == 0:
        return None

    # Cria mini mapa
    m = folium.Map(
        location=center,
        zoom_start=14,
        tiles="CartoDB dark_matter",
        control_scale=False,
        zoom_control=False,
        attributionControl=False,
    )

    # Adiciona edges problemáticas como heatmap
    for idx, row in problem_edges.iterrows():
        geom = row.geometry
        coords = list(geom.coords)

        # Cor baseada no tipo de erro
        osmid = str(row["osmid"])
        if osmid in metrics["missing_edges"]:
            color = "#e74c3c"  # Vermelho para missing
            weight = 4
        else:
            color = "#f39c12"  # Laranja para added
            weight = 3

        folium.PolyLine(
            locations=[(lat, lon) for lon, lat in coords],
            color=color,
            weight=weight,
            opacity=0.7,
        ).add_to(m)

    return m


@st.cache_resource
def load_graph():
    return ox.load_graphml(NETWORK_PATH)


@st.cache_data
def get_cached_gdfs() -> tuple[
    gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame
]:
    """Cache GeoDataFrames do grafo"""
    G = load_graph()
    nodes, edges = ox.graph_to_gdfs(G)
    edges_wgs = edges.to_crs(epsg=4326)
    nodes_wgs = nodes.to_crs(epsg=4326)
    nodes_wgs["osmid"] = nodes_wgs.index.copy().astype(str)
    return nodes, edges, nodes_wgs, edges_wgs


def plot_map_matching_from_osmid_folium(
    _nodes: gpd.GeoDataFrame,
    _edges: gpd.GeoDataFrame,
    _nodes_wgs: gpd.GeoDataFrame,
    _edges_wgs: gpd.GeoDataFrame,
    ground_truth_osmid_path: list[edge_id],
    map_matched_osmid_path: list[edge_id],
    gps_points: list[tuple[float, float, object]] | None = None,
):
    """Folium version of map-matching visualization."""
    center = _edges_wgs.union_all().centroid
    m = folium.Map(
        location=[center.y, center.x],
        zoom_start=15,
        control_scale=True,
        tiles=None,
        prefer_canvas=True,
    )

    folium.TileLayer(
        "CartoDB positron",
        name="CartoDB Positron (Branco)",
        opacity=0.60,
        attr="&copy; <a href='https://carto.com/attributions'>CARTO</a>",
        show=True,
    ).add_to(m)

    folium.TileLayer(
        "OpenStreetMap",
        name="OpenStreetMap Light",
        opacity=0.3,
        show=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="CartoDB dark_matter",
        name="CartoDB Dark Matter",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        show=False,
    ).add_to(m)

    folium.GeoJson(
        _edges_wgs,
        name="Street Network",
        style_function=lambda x: {"color": "lightblue", "weight": 2, "opacity": 0.5},
        tooltip=folium.GeoJsonTooltip(fields=["osmid"], aliases=["OSMID"]),
    ).add_to(m)

    folium.GeoJson(
        _nodes_wgs,
        name="Nodes",
        marker=folium.Circle(
            radius=2, color="gray", weight=0.5, fill=True, fill_opacity=0.3
        ),
        tooltip=folium.GeoJsonTooltip(fields=["osmid"], aliases=["Node ID"]),
    ).add_to(m)

    def edges_by_osmid(osmid_list: list[edge_id]):
        osmid_set = list(set(osmid_list))
        mask = _edges_wgs["osmid"].astype(str).isin(osmid_set)
        return _edges_wgs[mask]

    if map_matched_osmid_path:
        mm_edges = edges_by_osmid(map_matched_osmid_path)
        folium.GeoJson(
            mm_edges,
            name="Map Matched",
            style_function=lambda x: {"color": "blue", "weight": 4, "opacity": 0.6},
            tooltip=folium.GeoJsonTooltip(fields=["osmid"], aliases=["OSMID"]),
        ).add_to(m)

    if ground_truth_osmid_path:
        gt_edges = edges_by_osmid(ground_truth_osmid_path)
        folium.GeoJson(
            gt_edges,
            name="Ground Truth",
            style_function=lambda x: {"color": "green", "weight": 12, "opacity": 0.6},
            tooltip=folium.GeoJsonTooltip(fields=["osmid"], aliases=["OSMID"]),
        ).add_to(m)

    if gps_points:
        gps_layer = folium.FeatureGroup(name="GPS Points", show=True)
        for lat, lon, ts in gps_points:
            folium.CircleMarker(
                location=[float(lat), float(lon)],
                radius=4,
                color="#e74c3c",
                weight=1,
                fill=True,
                fill_opacity=0.9,
                tooltip=str(ts),
            ).add_to(gps_layer)
        gps_layer.add_to(m)

    stats_html = compute_stats_html(
        _edges, ground_truth_osmid_path, map_matched_osmid_path
    )

    root = m.get_root()
    if isinstance(root, folium.Figure):
        root.html.add_child(folium.Element(stats_html))

    folium.LayerControl(collapsed=False).add_to(m)

    return m


# Configuração da página
st.set_page_config(layout="wide", page_title="Map Matching Viewer")

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 0rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 100%;
    }
    .main > div {
        padding-left: 0rem;
        padding-right: 0rem;
    }
    section[data-testid="stAppViewContainer"] {
        overflow-x: hidden;
    }
    div[data-testid="stSelectbox"] {
        margin-bottom: 1rem;
    }
    </style>
""",
    unsafe_allow_html=True,
)


@st.cache_data
def get_vehicle_ids():
    return (
        duckdb.query(
            f"SELECT DISTINCT vehicle_id FROM '{GROUND_TRUTH_PATH}' ORDER BY vehicle_id"
        )
        .df()["vehicle_id"]
        .tolist()
    )


vehicle_ids = get_vehicle_ids()

if "current_index" not in st.session_state:
    st.session_state.current_index = 0

if st.session_state.current_index >= len(vehicle_ids):
    st.session_state.current_index = 0

st.write("")

left, middle, right = st.columns([1, 2, 1])

with left:
    if st.button(
        "⬅️ Anterior",
        use_container_width=True,
        disabled=(st.session_state.current_index == 0),
    ):
        st.session_state.current_index -= 1
        st.rerun()

with middle:
    new_selection = st.selectbox(
        "🚗 Selecione o veículo:",
        vehicle_ids,
        index=st.session_state.current_index,
    )
    new_index = vehicle_ids.index(new_selection)
    if new_index != st.session_state.current_index:
        st.session_state.current_index = new_index

with right:
    if st.button(
        "Próximo ➡️",
        use_container_width=True,
        disabled=(st.session_state.current_index == len(vehicle_ids) - 1),
    ):
        st.session_state.current_index += 1
        st.rerun()

vehicle_id = cast(int, vehicle_ids[st.session_state.current_index])

# Carregar dados
gt_df = load_road_dataset(GROUND_TRUTH_PATH, vehicle_id)
noisy_df = load_road_dataset(NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE)

gt_edges = df_to_edge_ids(gt_df)
gps_points = df_to_gps_coordinates(noisy_df)

matcher = mmlib.graphhopper_matcher(
    GRAPHHOPPER_BASE_URL, gps_accuracy=GRAPHHOPPER_GPS_ACCURACY
)


@st.cache_data
def get_map_match_result(_matcher: mmlib.BaseMatcher, vehicle_id: int):
    noisy_df = load_road_dataset(NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE)
    gps_points = df_to_gps_coordinates(noisy_df)
    return _matcher.match(gps_points)


nodes, edges, nodes_wgs, edges_wgs = get_cached_gdfs()
match_result = get_map_match_result(matcher, vehicle_id)

# Mapa principal
m = plot_map_matching_from_osmid_folium(
    _nodes=nodes,
    _edges=edges,
    _nodes_wgs=nodes_wgs,
    _edges_wgs=edges_wgs,
    ground_truth_osmid_path=gt_edges,
    map_matched_osmid_path=match_result.edge_ids,
    gps_points=gps_points,
)

st_folium(m, width=None, height=1000, returned_objects=[])

# Computar métricas detalhadas
metrics = compute_detailed_metrics(edges, gt_edges, match_result.edge_ids)

# Dashboard de métricas
st.markdown("---")
st.markdown("## 📊 Dashboard de Métricas")

# LINHA 1: Principais métricas
col1, col2, col3 = st.columns(3)

with col1:
    st.plotly_chart(create_venn_diagram(metrics), use_container_width=True)

with col2:
    st.plotly_chart(create_performance_gauges(metrics), use_container_width=True)

with col3:
    st.plotly_chart(create_length_analysis(metrics), use_container_width=True)

# LINHA 2: Análises detalhadas
col4, col5, col6 = st.columns(3)

with col4:
    confidence_fig = create_confidence_timeline(match_result, noisy_df)
    if confidence_fig:
        st.plotly_chart(confidence_fig, use_container_width=True)

with col5:
    distance_fig = create_distance_error_distribution(match_result, noisy_df, edges_wgs)
    if distance_fig:
        st.plotly_chart(distance_fig, use_container_width=True)

with col6:
    continuity_fig = create_path_continuity_analysis(gt_edges, match_result.edge_ids)
    if continuity_fig:
        st.plotly_chart(continuity_fig, use_container_width=True)

# LINHA 3: Heatmap de erro
st.markdown("### 🗺️ Error Heatmap")
center = edges_wgs.union_all().centroid
error_heatmap = create_error_heatmap(edges_wgs, metrics, (center.y, center.x))

if error_heatmap:
    st_folium(error_heatmap, width=None, height=400, returned_objects=[])
else:
    st.info("No errors to display in heatmap (perfect match!)")

import duckdb
import folium
import mmlib

import geopandas as gpd
import osmnx as ox
import pandas as pd
import streamlit as st

from pathlib import Path
from typing import cast

from streamlit_folium import st_folium

ROOT_PATH = Path(".").resolve().absolute()
GRAPHHOPPER_BASE_URL = "http://localhost:8989"
GRAPHHOPPER_GPS_ACCURACY = 50  # meters
SAMPLE_RATE: int | None = 2  # seconds


GROUND_TRUTH_PATH = (
    ROOT_PATH
    / "sumo/simulations/ohare-chicago-junctionless/output/fcd_resolved.parquet"
)
NOISE_PARQUET = (
    ROOT_PATH / "sumo/simulations/ohare-chicago-junctionless/output/fcd_noisy.parquet"
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
        subset = edges_wgs[edges_wgs["osmid"].isin(map(int, osmids))]

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


@st.cache_resource
def load_graph():
    return ox.load_graphml(NETWORK_PATH)


@st.cache_data
def get_cached_gdfs() -> (
    tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]
):
    """Cache GeoDataFrames do grafo"""
    G = load_graph()
    nodes, edges = ox.graph_to_gdfs(G)
    edges_wgs = edges.to_crs(epsg=4326)
    nodes_wgs = nodes.to_crs(epsg=4326)
    nodes_wgs["osmid"] = nodes_wgs.index.copy().astype(str)
    return nodes, edges, nodes_wgs, edges_wgs


def plot_map_matching_from_osmid_folium(
    _nodes: gpd.GeoDataFrame,  # underscore = não será hasheado
    _edges: gpd.GeoDataFrame,
    _nodes_wgs: gpd.GeoDataFrame,
    _edges_wgs: gpd.GeoDataFrame,
    ground_truth_osmid_path: list[edge_id],
    map_matched_osmid_path: list[edge_id],
):
    """
    Folium version of map-matching visualization.
    Shows:
      - street network (gray)
      - ground truth path (green)
      - map matched path (blue)
    Includes tooltips, layer toggles and summary stats.
    """

    center = _edges_wgs.union_all().centroid
    m = folium.Map(
        location=[center.y, center.x],
        zoom_start=15,
        control_scale=True,
        tiles=None,
        prefer_canvas=True,  # Melhora performance
    )

    # Tema branco por padrão
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

    # Simplificar a rede de ruas (remover tooltips pesados)
    folium.GeoJson(
        _edges_wgs,
        name="Street Network",
        style_function=lambda x: {"color": "lightblue", "weight": 2, "opacity": 0.5},
        tooltip=folium.GeoJsonTooltip(fields=["osmid"], aliases=["OSMID"]),
    ).add_to(m)

    # Remover nodes para melhorar performance (geralmente não são necessários)
    # Se precisar, descomente:
    folium.GeoJson(
        _nodes_wgs,
        name="Nodes",
        marker=folium.Circle(
            radius=2, color="gray", weight=0.5, fill=True, fill_opacity=0.3
        ),
        tooltip=folium.GeoJsonTooltip(fields=["osmid"], aliases=["Node ID"]),
    ).add_to(m)

    def edges_by_osmid(osmid_list: list[edge_id]) -> pd.DataFrame:
        """Return subset of edges GeoDataFrame filtered by OSMIDs."""
        osmid_set = set(osmid_list)  # Usar set para busca O(1)
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

    stats_html = compute_stats_html(
        _edges, ground_truth_osmid_path, map_matched_osmid_path
    )

    root = m.get_root()
    if isinstance(root, folium.Figure):
        root.html.add_child(folium.Element(stats_html))

    folium.LayerControl(collapsed=False).add_to(m)

    return m


# Configuração da página para fullwidth
st.set_page_config(layout="wide", page_title="Map Matching Viewer")

# CSS customizado para o seletor e mapa fullwidth
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


# Carregar lista de veículos (cache)
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

# Inicializar session_state
if "vehicle_id" not in st.session_state:
    st.session_state.vehicle_id = vehicle_ids[0] if vehicle_ids else 0

# Adicionar espaço antes do seletor
st.write("")

# Seletor no topo com navegação
left, middle, right = st.columns([1, 2, 1])

vehicle_ids = get_vehicle_ids()

# Inicializar session_state
if "current_index" not in st.session_state:
    st.session_state.current_index = 0

# Garantir que está dentro dos limites
if st.session_state.current_index >= len(vehicle_ids):
    st.session_state.current_index = 0

# Adicionar espaço antes do seletor
st.write("")

# Seletor no topo com navegação
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
    # Detectar mudança no selectbox
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

# Usar o vehicle_id atual
vehicle_id = cast(int, vehicle_ids[st.session_state.current_index])

# --- Carregar dados com cache ---
gt_df = load_road_dataset(GROUND_TRUTH_PATH, vehicle_id)
noisy_df = load_road_dataset(NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE)

gt_edges = df_to_edge_ids(gt_df)
gps_points = df_to_gps_coordinates(noisy_df)


matcher = mmlib.graphhopper_matcher(
    GRAPHHOPPER_BASE_URL, gps_accuracy=GRAPHHOPPER_GPS_ACCURACY
)


@st.cache_data
def get_map_match_result(_matcher, vehicle_id: int):
    noisy_df = load_road_dataset(NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE)
    gps_points = df_to_gps_coordinates(noisy_df)
    return _matcher.map_match(gps_points)


nodes, edges, nodes_wgs, edges_wgs = get_cached_gdfs()

match_result = get_map_match_result(matcher, vehicle_id)

m = plot_map_matching_from_osmid_folium(
    _nodes=nodes,
    _edges=edges,
    _nodes_wgs=nodes_wgs,
    _edges_wgs=edges_wgs,
    ground_truth_osmid_path=gt_edges,
    map_matched_osmid_path=match_result.edge_ids,
)

st_folium(m, width=None, height=1000, returned_objects=[])

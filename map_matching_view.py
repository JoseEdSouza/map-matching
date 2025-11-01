from typing import cast
import duckdb
import mmlib

import folium
import networkx as nx
import osmnx as ox
import pandas as pd
import streamlit as st

from pathlib import Path
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


@st.cache_data
def get_graph_gdfs(_graph: nx.MultiDiGraph):
    """Cache the conversion of graph to GeoDataFrames"""
    nodes, edges = ox.graph_to_gdfs(_graph)
    edges_wgs = edges.to_crs(epsg=4326)
    nodes_wgs = nodes.to_crs(epsg=4326)
    nodes_wgs["osmid"] = nodes_wgs.index.copy().astype(str)
    return nodes_wgs, edges_wgs

def plot_map_matching_from_osmid_folium(
    graph: nx.MultiDiGraph,
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

    nodes_wgs, edges_wgs = get_graph_gdfs(graph)

    center = edges_wgs.union_all().centroid
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
        edges_wgs,
        name="Street Network",
        style_function=lambda x: {"color": "lightblue", "weight": 2, "opacity": 0.5},
    ).add_to(m)

    # Remover nodes para melhorar performance (geralmente não são necessários)
    # Se precisar, descomente:
    folium.GeoJson(
        nodes_wgs,
        name="Nodes",
        marker=folium.Circle(
            radius=2, color="gray", weight=0.5, fill=True, fill_opacity=0.3
        ),
    ).add_to(m)

    def edges_by_osmid(osmid_list: list[edge_id]) -> pd.DataFrame:
        """Return subset of edges GeoDataFrame filtered by OSMIDs."""
        osmid_set = set(osmid_list)  # Usar set para busca O(1)
        mask = edges_wgs["osmid"].astype(str).isin(osmid_set)
        return edges_wgs[mask]

    if map_matched_osmid_path:
        mm_edges = edges_by_osmid(map_matched_osmid_path)
        folium.GeoJson(
            mm_edges,
            name="Map Matched",
            style_function=lambda x: {"color": "blue", "weight": 4, "opacity": 0.6},
        ).add_to(m)

    if ground_truth_osmid_path:
        gt_edges = edges_by_osmid(ground_truth_osmid_path)
        folium.GeoJson(
            gt_edges,
            name="Ground Truth",
            style_function=lambda x: {"color": "green", "weight": 10, "opacity": 0.6},
        ).add_to(m)

    # --- Compute stats ---
    gt_edges = set(ground_truth_osmid_path)
    mm_edges = set(map_matched_osmid_path)
    matched = gt_edges & mm_edges
    added = mm_edges - gt_edges
    missing = gt_edges - mm_edges
    difference = gt_edges ^ mm_edges

    stats = {
        "Matched": len(matched),
        "Added": len(added),
        "Missing": len(missing),
        "Difference": len(difference),
        "Ground Truth Edges": len(gt_edges),
        "Map Matched Edges": len(mm_edges),
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
                width: 160px;">
        <b>Map Matching Summary</b>
        <table style="margin-top:5px; border-collapse:collapse;">
            <tr>
                <th style="text-align:left; padding-right:10px;">Metric</th>
                <th style="text-align:right;">Count</th>
            </tr>
            {stats_rows}
        </table>
    </div>
    """

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

# Adicionar espaço antes do seletor
st.write("")

# Seletor no topo centralizado
col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    vehicle_id = cast(
        int,
        st.selectbox("🚗 Selecione o veículo:", vehicle_ids),
    )

# --- Carregar dados com cache ---
gt_df = load_road_dataset(GROUND_TRUTH_PATH, vehicle_id)
noisy_df = load_road_dataset(NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE)

gt_edges = df_to_edge_ids(gt_df)
gps_points = df_to_gps_coordinates(noisy_df)


@st.cache_resource
def load_graph():
    return ox.load_graphml(NETWORK_PATH)


G = load_graph()


matcher = mmlib.graphhopper_matcher(
    GRAPHHOPPER_BASE_URL, gps_accuracy=GRAPHHOPPER_GPS_ACCURACY
)


# Cache do map matching por veículo
@st.cache_data
def get_map_match_result(_matcher, vehicle_id: int):
    noisy_df = load_road_dataset(NOISE_PARQUET, vehicle_id, sample_rate=SAMPLE_RATE)
    gps_points = df_to_gps_coordinates(noisy_df)
    return _matcher.map_match(gps_points)


match_result = get_map_match_result(matcher, vehicle_id)

# --- plotar ---
m = plot_map_matching_from_osmid_folium(
    graph=G,
    ground_truth_osmid_path=gt_edges,
    map_matched_osmid_path=match_result.edge_ids,
)

st_folium(m, width=None, height=1000, returned_objects=[])

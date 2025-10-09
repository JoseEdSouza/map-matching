import math
import networkx as nx
import pandas as pd
import plotly.graph_objects as go


type lat = float
type lon = float


def plot_trajectories(
    original: list[tuple[lat, lon]],
    calculated: list[tuple[lat, lon]],
    title: str = "Tracks",
    original_label: str = "Original",
    calculated_label: str = "Calculated",
    show_original_line: bool = True,
    show_buttons: bool = True,
    center_lat: float | None = None,
    center_lon: float | None = None,
    zoom: float = 14,
) -> None:
    flat_original = [
        (lat, lon, original_label, i) for i, (lat, lon) in enumerate(original)
    ]
    flat_calculated = [
        (lat, lon, calculated_label, i) for i, (lat, lon) in enumerate(calculated)
    ]

    df = pd.DataFrame(
        flat_original + flat_calculated,
        columns=["lat", "lon", "type", "row_num"],
    )

    fig = go.Figure()
    visible_flags = []

    for type_ in [original_label, calculated_label]:
        subset = df[df["type"] == type_].sort_values("row_num")

        # Pontos
        fig.add_trace(
            go.Scattermap(
                lat=subset["lat"],
                lon=subset["lon"],
                mode="markers",
                marker=dict(size=10),
                name=f"{type_} - pontos",
                legendgroup=type_,
                visible=True,
            )
        )
        visible_flags.append(True)

        # Linhas
        show_line = True
        if type_ == original_label and not show_original_line:
            show_line = False
        fig.add_trace(
            go.Scattermap(
                lat=subset["lat"],
                lon=subset["lon"],
                mode="lines",
                line=dict(width=2),
                name=f"{type_} - linha",
                legendgroup=type_,
                visible=show_line,
            )
        )
        visible_flags.append(show_line)

    # Definir centro do mapa
    if center_lat is None or center_lon is None:
        # Usar centro calculado a partir dos dados
        map_center = dict(lat=df["lat"].mean(), lon=df["lon"].mean())
    else:
        # Usar coordenadas fornecidas
        map_center = dict(lat=center_lat, lon=center_lon)

    if show_buttons:
        fig.update_layout(
            updatemenus=[
                dict(
                    type="buttons",
                    direction="right",
                    showactive=True,
                    x=0.5,
                    xanchor="center",
                    y=1,
                    yanchor="top",
                    buttons=[
                        dict(
                            label="Mostrar Nenhuma",
                            method="update",
                            args=[
                                {"visible": [False, False, False, False]},
                                {"mapbox": dict(center=map_center, zoom=zoom)},
                            ],
                        ),
                        dict(
                            label="Mostrar Ambas",
                            method="update",
                            args=[
                                {"visible": [True, show_original_line, True, True]},
                                {"mapbox": dict(center=map_center, zoom=zoom)},
                            ],
                        ),
                        dict(
                            label=f"Apenas {original_label}",
                            method="update",
                            args=[
                                {"visible": [True, show_original_line, False, False]},
                                {"mapbox": dict(center=map_center, zoom=zoom)},
                            ],
                        ),
                        dict(
                            label=f"Apenas {calculated_label}",
                            method="update",
                            args=[
                                {"visible": [False, False, True, True]},
                                {"mapbox": dict(center=map_center, zoom=zoom)},
                            ],
                        ),
                    ],
                )
            ]
        )

    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox=dict(center=map_center, zoom=zoom),
        margin=dict(l=0, r=0, t=80, b=0),
        height=700,
        title=title,
    )

    fig.show()


def __distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def __map_osmid_to_edges(graph: nx.Graph) -> dict[str, list[tuple[int, int]]]:
    osmid_to_edge_map: dict[str, list[tuple[int, int]]] = {}
    for u, v, data in graph.edges(data=True):
        osmids = data.get("osmid")
        if osmids is None:
            continue

        if not isinstance(osmids, (list, tuple, set)):
            osmids = [osmids]

        for osm in osmids:
            osmid_str = str(osm)
            osmid_to_edge_map.setdefault(osmid_str, []).append((u, v))

        osmid_to_edge_map.setdefault(str(u), []).append((u, v))
        osmid_to_edge_map.setdefault(str(v), []).append((u, v))

    return osmid_to_edge_map


type edge_id = str



def plot_map_matching_from_osmid(
    graph: nx.Graph,
    ground_truth_osmid_path: list[edge_id],
    map_matched_osmid_path: list[edge_id],
):
    pos = {node: (data["x"], data["y"]) for node, data in graph.nodes(data=True)}
    osmid_to_edge_map = __map_osmid_to_edges(graph)

    # --- Helper: ordered path trace ---
    def create_ordered_path_trace(osmid_list, color, name, width=4):
        lons, lats = [], []
        prev_coords = None
        missing = []

        for osmid in osmid_list:
            candidates = osmid_to_edge_map.get(str(osmid))
            if not candidates:
                missing.append(osmid)
                continue

            for u, v in candidates:
                ux, uy = pos[u]
                vx, vy = pos[v]
                segment = [(ux, uy), (vx, vy)]

                if prev_coords and prev_coords != segment[0]:
                    if prev_coords == segment[1]:
                        segment.reverse()
                    elif not __distance(prev_coords, segment[0]) < 0.00005:
                        lons.append(None)
                        lats.append(None)

                for x, y in segment:
                    lons.append(x)
                    lats.append(y)

                prev_coords = segment[-1]

        if missing:
            print(f"⚠️ Missing {len(missing)} osmids: {missing[:5]}{'...' if len(missing) > 5 else ''}")

        return go.Scattermapbox(
            lon=lons,
            lat=lats,
            mode="lines",
            line=dict(color=color, width=width),
            name=name,
            visible=True,
        )

    # --- Figure ---
    traces = []

    # Ground truth
    if ground_truth_osmid_path:
        traces.append(
            create_ordered_path_trace(ground_truth_osmid_path, "green", "Ground Truth")
        )

    # Map matched
    if map_matched_osmid_path:
        traces.append(
            create_ordered_path_trace(map_matched_osmid_path, "blue", "Map Matched")
        )

    gt_edges = set(ground_truth_osmid_path)
    mm_edges = set(map_matched_osmid_path)
    matched = gt_edges & mm_edges
    added = mm_edges - gt_edges
    missing = gt_edges - mm_edges
    difference = gt_edges ^ mm_edges

    # --- Layout with Mapbox ---
    fig = go.Figure(data=traces)

    # Compute approximate center of map
    lons = [data["x"] for _, data in graph.nodes(data=True)]
    lats = [data["y"] for _, data in graph.nodes(data=True)]
    center_lon, center_lat = (sum(lons) / len(lons), sum(lats) / len(lats))

    fig.update_layout(
        mapbox=dict(
            style="carto-positron",  # or "open-street-map", "stamen-terrain", "satellite-streets"
            center=dict(lat=center_lat, lon=center_lon),
            zoom=13,
        ),
        margin=dict(l=10, r=10, t=40, b=60),
        height=700,
        title="Map Matching Visualization",
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                x=0.5,
                y=1.1,
                xanchor="center",
                yanchor="top",
                buttons=[
                    dict(
                        label="Toggle Ground Truth",
                        method="update",
                        args=[{"visible": [False, True]}],
                        args2=[{"visible": [True, True]}],
                    ),
                    dict(
                        label="Toggle Map Matched",
                        method="update",
                        args=[{"visible": [True, False]}],
                        args2=[{"visible": [True, True]}],
                    ),
                    dict(
                        label="Toggle Both",
                        method="update",
                        args=[{"visible": [False, False]}],
                        args2=[{"visible": [True, True]}],
                    ),
                ],
            )
        ],
        annotations=[
            dict(
                text=(
                    f"Matched: {len(matched)} | "
                    f"Added: {len(added)} | "
                    f"Missing: {len(missing)} | "
                    f"Difference: {len(difference)}"
                ),
                showarrow=False,
                xref="paper",
                yref="paper",
                x=0.5,
                y=-0.1,
                xanchor="center",
                font=dict(size=12),
            )
        ],
    )

    # Enable zoom + drag
    fig.show(config=dict(scrollZoom=True, displayModeBar=True))

"""Map rendering without external map tiles: offline geometry remains usable."""

from __future__ import annotations

import geopandas as gpd
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
from shapely.geometry import LineString


def edge_frame(graph: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    rows = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        geometry = data.get("geometry")
        if geometry is None:
            geometry = LineString([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in (u, v)])
        rows.append(
            {
                "u": u,
                "v": v,
                "key": key,
                "name": str(data.get("name", "Unnamed")),
                "travel_time_s": data["travel_time"],
                "geometry": geometry,
            }
        )
    return gpd.GeoDataFrame(rows, crs=graph.graph["crs"])


def network_map(
    graph: nx.MultiDiGraph,
    ranking: pd.DataFrame | None = None,
    selected: list[tuple[int, int, int]] | None = None,
    highlight_label: str = "Intervention",
    anchors: pd.DataFrame | None = None,
    pick_edges: bool = False,
) -> go.Figure:
    edges = edge_frame(graph)
    critical = (
        set()
        if ranking is None
        else set(ranking.head(5)[["u", "v", "key"]].itertuples(index=False, name=None))
    )
    selected_set = set(selected or [])
    groups = {
        "Network": ([], [], "#91a5b8", 1.4),
        "Top structural links": ([], [], "#f49b50", 4),
        highlight_label: ([], [], "#27cfb1", 5),
    }
    for row in edges.itertuples():
        edge = (row.u, row.v, row.key)
        category = (
            highlight_label
            if (edge in selected_set or graph.edges[edge].get("intervention"))
            else "Top structural links"
            if edge in critical
            else "Network"
        )
        x, y, _, _ = groups[category]
        coords = list(row.geometry.coords)
        x.extend([c[0] for c in coords] + [None])
        y.extend([c[1] for c in coords] + [None])
    fig = go.Figure()
    for label, (x, y, color, width) in groups.items():
        if x:
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    name=label,
                    line={"color": color, "width": width},
                    hoverinfo="skip",
                )
            )
    nodes = list(graph.nodes(data=True))
    fig.add_trace(
        go.Scatter(
            x=[d["x"] for _, d in nodes],
            y=[d["y"] for _, d in nodes],
            mode="markers",
            marker={
                "size": 6 if len(graph) < 300 else 2,
                "color": "#dce6f0",
                "line": {"width": 1, "color": "#17263a"},
            },
            text=[f"Node {n}" for n, _ in nodes],
            hovertemplate="%{text}<extra></extra>",
            name="Road nodes",
        )
    )
    if anchors is not None:
        fig.add_trace(
            go.Scatter(
                x=anchors.node_lon,
                y=anchors.node_lat,
                mode="markers+text",
                text=[
                    str(name)
                    .replace(" western approach", " approach")
                    .replace(" approach area", "")
                    .replace(" area", "")
                    for name in anchors["name"]
                ],
                hovertext=anchors["name"],
                textposition="top center",
                textfont={"size": 11, "color": "#ffffff"},
                marker={"size": 10, "color": "#27cfb1", "symbol": "diamond"},
                name="Trip anchors",
                hovertemplate="%{text}<extra></extra>",
            )
        )
    if pick_edges:
        midpoints = [r.geometry.interpolate(0.5, normalized=True) for r in edges.itertuples()]
        fig.add_trace(
            go.Scattergl(
                x=[p.x for p in midpoints],
                y=[p.y for p in midpoints],
                mode="markers",
                marker={"size": 7, "color": "#81abc8", "opacity": 0.35},
                customdata=edges[["u", "v", "key"]].values.tolist(),
                text=[
                    f"{r.name} · {r.u} → {r.v} · {r.travel_time_s:.1f} s"
                    for r in edges.itertuples()
                ],
                hovertemplate="%{text}<extra></extra>",
                name="Pick a road segment",
            )
        )
    # Direction markers on ranked/selected/new arcs; hover exposes exact (u,v,key).
    markers = (
        set(critical)
        | selected_set
        | {(u, v, k) for u, v, k, d in graph.edges(keys=True, data=True) if d.get("intervention")}
    )
    for u, v, k in sorted(markers):
        a, b = graph.nodes[u], graph.nodes[v]
        fig.add_annotation(
            x=b["x"] * 0.55 + a["x"] * 0.45,
            y=b["y"] * 0.55 + a["y"] * 0.45,
            ax=b["x"] * 0.45 + a["x"] * 0.55,
            ay=b["y"] * 0.45 + a["y"] * 0.55,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            text="",
            showarrow=True,
            arrowhead=3,
            arrowsize=1,
            arrowwidth=1.5,
            arrowcolor="#27cfb1"
            if (u, v, k) in selected_set or graph.edges[u, v, k].get("intervention")
            else "#f49b50",
        )
    fig.update_layout(
        height=500,
        clickmode="event+select",
        dragmode="select" if pick_edges else "pan",
        uirevision=graph.graph.get("study", graph.graph.get("name", "network")),
        margin={"l": 5, "r": 5, "t": 15, "b": 5},
        paper_bgcolor="#111e2d",
        plot_bgcolor="#111e2d",
        font={"color": "#dce6f0"},
        legend={"orientation": "h", "y": 1.05},
        xaxis={"title": "Longitude · WGS84", "showgrid": False, "zeroline": False},
        yaxis={
            "title": "Latitude · WGS84",
            "showgrid": False,
            "zeroline": False,
            "scaleanchor": "x",
            "scaleratio": 1.14,
        },
    )
    return fig

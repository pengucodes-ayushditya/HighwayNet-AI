# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9,<4", "networkx>=3.4,<4", "shapely>=2,<3"]
# ///
"""Render actual real-road case outputs. Run: uv run --script scripts/render_preview.py."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.collections import LineCollection
from shapely import wkt

root = Path(__file__).resolve().parents[1]
graph = nx.read_graphml(root / "data/nh48_airport/network.graphml", force_multigraph=True)
manifest = json.loads((root / "results/nh48_case/manifest.json").read_text())
rows = list(csv.DictReader((root / "results/nh48_case/scenario_summary.csv").open()))
anchors = list(csv.DictReader((root / "results/nh48_case/anchors.csv").open()))
selected = {(str(u), str(v), int(k)) for u, v, k in manifest["upgrade"]["edges"]}
background, panel, ink, muted = "#0b1421", "#132337", "#edf5fc", "#9db3c9"
fig = plt.figure(figsize=(14, 8.3), facecolor=background)
fig.text(
    0.05, 0.935, "HIGHWAYNET AI / REAL OSM CASE STUDY", color="#27cfb1", fontsize=13, weight="bold"
)
fig.text(0.05, 0.875, "Real roads. Explicit assumptions.", color=ink, fontsize=28, weight="bold")
fig.text(
    0.05,
    0.826,
    "NH-48 / Mahipalpur–Shiv Murti–Rajokri · 3,793 nodes · 8,107 directed edges",
    color=muted,
    fontsize=12,
)
ax = fig.add_axes((0.05, 0.22, 0.51, 0.53), facecolor=panel)
lines = []
treated = []
for u, v, k, data in graph.edges(keys=True, data=True):
    if data.get("geometry"):
        coords = list(wkt.loads(data["geometry"]).coords)
    else:
        coords = [(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"])) for n in (u, v)]
    lines.append(coords)
    if (u, v, int(k)) in selected:
        treated.append(coords)
ax.add_collection(LineCollection(lines, colors="#6b859f", linewidths=0.45, alpha=0.72))
ax.add_collection(LineCollection(treated, colors="#f49b50", linewidths=2.8))
u, v = str(manifest["new_connection"]["u"]), str(manifest["new_connection"]["v"])
ax.plot(
    [float(graph.nodes[n]["x"]) for n in (u, v)],
    [float(graph.nodes[n]["y"]) for n in (u, v)],
    "--",
    color="#27cfb1",
    linewidth=2.3,
)
for anchor in anchors:
    x, y = float(anchor["node_lon"]), float(anchor["node_lat"])
    label = (
        anchor["name"]
        .replace(" western approach", " approach")
        .replace(" approach area", "")
        .replace(" area", "")
    )
    ax.scatter(x, y, s=30, color="#27cfb1", zorder=4)
    offset = (5, 7) if "Shiv" not in label else (5, -13)
    ax.annotate(label, (x, y), xytext=offset, textcoords="offset points", color=ink, fontsize=8)
ax.set_xlim(77.085, 77.160)
ax.set_ylim(28.500, 28.562)
ax.set_aspect(1.14)
ax.tick_params(colors=muted, labelsize=8)
ax.ticklabel_format(useOffset=False)
ax.set_xlabel("Longitude · WGS84", color=muted, fontsize=9)
ax.set_ylabel("Latitude · WGS84", color=muted, fontsize=9)
for spine in ax.spines.values():
    spine.set_visible(False)
fig.text(0.63, 0.745, "ONE BASELINE / 20 ASSUMED OD PAIRS", color=ink, fontsize=12, weight="bold")
bars = fig.add_axes((0.66, 0.49, 0.29, 0.19), facecolor=background)
values = [float(r["common_od_weighted_savings_seconds"]) for r in rows]
bars.barh(["B / New link", "A / Corridor"], values[::-1], color=["#27cfb1", "#f49b50"], height=0.48)
for y, value in enumerate(values[::-1]):
    bars.text(value + 2, y, f"{value:.2f} s", color=ink, va="center", fontsize=11)
bars.set_xlim(0, max(values) * 1.4)
bars.set_xlabel("Demand-weighted modeled seconds saved", color=muted, fontsize=9)
bars.tick_params(colors=muted, length=0)
for spine in bars.spines.values():
    spine.set_visible(False)
fig.text(0.63, 0.41, "A: 1.117 km corridor · 6 pairs improve", color=ink, fontsize=12)
fig.text(0.63, 0.365, "B: 0.920 km schematic link · 2 pairs improve", color=ink, fontsize=12)
fig.text(0.63, 0.295, "A has the higher savings / assumed cost ratio", color="#f49b50", fontsize=10)
fig.text(0.63, 0.26, "in all 27 tested assumption combinations.", color=muted, fontsize=10)
fig.text(
    0.05,
    0.115,
    "REAL OSM GEOMETRY · Assumed speeds, demand and costs · No observed traffic",
    color=muted,
    fontsize=11,
)
fig.text(
    0.05,
    0.073,
    "© OpenStreetMap contributors / ODbL 1.0 · "
    "Independent research prototype; no NHAI endorsement.",
    color=muted,
    fontsize=10,
)
fig.savefig(root / "docs/network_preview.png", dpi=160, facecolor=background)
plt.close(fig)

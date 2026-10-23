"""Contraction diagnostic using the same snapshot and fixed named OD endpoints.

This is not proof that the full study boundary captures all outside detours.
Run with uv run python scripts/check_boundaries.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from highwaynet.analysis import od_times
from highwaynet.demand import named_demand, snap_anchors
from highwaynet.snapshot import load_snapshot
from highwaynet.studies import NH48

root = Path(__file__).resolve().parents[1]
graph = load_snapshot(root / "data/nh48_airport")
pairs = named_demand(graph, snap_anchors(graph, NH48))
base = od_times(graph, pairs)
rows = []
for degrees in (0, 0.0025, 0.005):
    w, s, e, n = NH48.bbox
    nodes = [
        u
        for u, d in graph.nodes(data=True)
        if w + degrees <= d["x"] <= e - degrees and s + degrees <= d["y"] <= n - degrees
    ]
    contracted = graph.subgraph(nodes).copy()
    # Never resnap removed endpoints and imply the OD experiment is unchanged.
    if any(p.origin not in contracted or p.destination not in contracted for p in pairs):
        rows.append(
            {
                "contraction_degrees": degrees,
                "status": "fixed OD endpoint outside contracted boundary",
            }
        )
        continue
    times = od_times(contracted, pairs)
    common = np.isfinite(base) & np.isfinite(times)
    for i, pair in enumerate(pairs):
        rows.append(
            {
                "contraction_degrees": degrees,
                "nodes": len(contracted),
                "origin": pair.origin,
                "destination": pair.destination,
                "reachable": bool(np.isfinite(times[i])),
                "baseline_seconds": base[i] if np.isfinite(base[i]) else None,
                "contracted_seconds": times[i] if np.isfinite(times[i]) else None,
                "change_seconds": times[i] - base[i] if common[i] else None,
                "status": "node-induced contraction; geometry was not re-extracted",
            }
        )
out = root / "results/nh48_case/boundary_contraction.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print(pd.DataFrame(rows).groupby("contraction_degrees").reachable.agg(["count", "sum"]))

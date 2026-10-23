"""Show how terminal endpoint selection affects topological redundancy.

Run with uv run python scripts/check_anchor_policy.py. Both policies use the
same manually selected area coordinates; no policy is a validated entrance model.
"""

from pathlib import Path

import pandas as pd

from highwaynet.analysis import redundancy
from highwaynet.demand import named_demand, snap_anchors
from highwaynet.snapshot import load_snapshot
from highwaynet.studies import NH48

root = Path(__file__).resolve().parents[1]
graph = load_snapshot(root / "data/nh48_airport")
rows = []
for minimum in (1, 3):
    anchors = snap_anchors(graph, NH48, minimum_neighbors=minimum)
    result = redundancy(graph, named_demand(graph, anchors))
    rows.append(
        {
            "minimum_road_neighbors": minimum,
            "maximum_snap_distance_m": anchors.snap_distance_m.max(),
            "mean_snap_distance_m": anchors.snap_distance_m.mean(),
            **result,
        }
    )
pd.DataFrame(rows).to_csv(root / "results/nh48_case/anchor_policy_sensitivity.csv", index=False)
print(pd.DataFrame(rows).to_string(index=False))

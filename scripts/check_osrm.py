"""Three cached external routing checks, explicitly not observed traffic.

Run with uv run python scripts/check_osrm.py [--refresh]. Coordinates are public
case-study road junctions. No user travel histories are submitted.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from highwaynet.analysis import route_edges
from highwaynet.demand import snap_anchors
from highwaynet.snapshot import load_snapshot
from highwaynet.studies import NH48


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = root / "results/osrm_checks"
    out.mkdir(exist_ok=True)
    graph = load_snapshot(root / "data/nh48_airport")
    anchors = snap_anchors(graph, NH48)
    rows = []
    for i, j in [(0, 2), (3, 4), (1, 0)]:
        a, b = anchors.iloc[i], anchors.iloc[j]
        coordinates = f"{a.node_lon:.7f},{a.node_lat:.7f};{b.node_lon:.7f},{b.node_lat:.7f}"
        url = f"https://router.project-osrm.org/route/v1/driving/{coordinates}"
        path = out / f"{i}_{j}.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        if not args.refresh and previous.get("url") == url and "response" in previous:
            record = previous
            data = record["response"]
        else:
            record = {
                "origin_name": a["name"],
                "destination_name": b["name"],
                "origin": int(a.node),
                "destination": int(b.node),
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "url": url,
                "evidence_type": "independent routing model, not traffic observation",
            }
            try:
                response = requests.get(
                    url,
                    params={"overview": "full", "geometries": "geojson", "steps": "false"},
                    timeout=(10, 30),
                )
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "Ok":
                    raise ValueError(data.get("message", data.get("code")))
                record["response"] = data
            except (requests.RequestException, ValueError) as exc:
                record["error"] = str(exc)
                path.write_text(json.dumps(record, indent=2))
                print("Routing check unavailable:", str(exc))
                continue
            path.write_text(json.dumps(record, indent=2))
        edges = route_edges(graph, int(a.node), int(b.node))
        route = data["routes"][0]
        modeled = sum(graph.edges[e]["travel_time"] for e in edges)
        rows.append(
            {
                **{k: v for k, v in record.items() if k != "response"},
                "highwaynet_seconds": modeled,
                "highwaynet_distance_m": sum(graph.edges[e]["length"] for e in edges),
                "osrm_seconds": route["duration"],
                "osrm_distance_m": route["distance"],
                "duration_difference_seconds": modeled - route["duration"],
                "max_osrm_snap_distance_m": max(w["distance"] for w in data["waypoints"]),
                "status": "obtained",
            }
        )
    pd.DataFrame(rows).to_csv(out / "routing_comparison.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()

"""Reproducible real-road or synthetic study with candidate search and evidence outputs."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import pandas as pd

from highwaynet.analysis import rank_bottlenecks, route_edges
from highwaynet.data import graph_fingerprint, synthetic_graph
from highwaynet.demand import demo_anchors, named_demand, snap_anchors
from highwaynet.experiments import sensitivity_matrix
from highwaynet.maps import edge_frame, network_map
from highwaynet.operating import operating_model
from highwaynet.planning import evaluate_connections, screen_connections
from highwaynet.resilience import (
    closure_impact,
    practical_alternatives,
    reciprocal_edges,
    route_corridor,
)
from highwaynet.scenarios import add_connection, compare, upgrade
from highwaynet.snapshot import load_snapshot
from highwaynet.studies import NH48
from highwaynet.validation import route_boundary_exposure


def run_case_study(source: str, out: Path, candidate_budget: int = 16) -> dict:
    if source not in {"synthetic", "nh48_airport"} or not 1 <= candidate_budget <= 40:
        raise ValueError("Choose a known source and candidate budget 1–40")
    out.mkdir(parents=True, exist_ok=True)
    stages = {}
    started = time.perf_counter()
    original = (
        synthetic_graph() if source == "synthetic" else load_snapshot(Path("data/nh48_airport"))
    )
    anchors = demo_anchors(original) if source == "synthetic" else snap_anchors(original, NH48)
    baseline = operating_model(original, "Uncongested model")
    pairs = named_demand(baseline, anchors)
    stages["load_and_anchors_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    ranking = rank_bottlenecks(baseline, pairs, candidate_limit=40)
    stages["hybrid_ranking_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    screened = screen_connections(
        baseline, limit=candidate_budget, conservative=source != "synthetic"
    )
    candidates = evaluate_connections(baseline, pairs, screened)
    stages["candidate_search_seconds"] = time.perf_counter() - started
    if candidates.empty:
        raise ValueError(
            "No geometrically eligible proposals; expand/review screening rather than invent a link"
        )
    selected = candidates.iloc[0]
    endpoints = (int(selected.u), int(selected.v))
    # Choose the highest-ranked directional link for which the bounded upgrade can improve time.
    top = next(
        (r for r in ranking.itertuples() if baseline.edges[r.u, r.v, r.key]["speed_kph"] < 100),
        None,
    )
    if top is None:
        raise ValueError("No ranked edge supports the stated upgrade speed cap")
    edges = route_corridor(baseline, pairs, (int(top.u), int(top.v), int(top.key)))
    # Cap must permit an improvement for every selected directional segment.
    if any(baseline.edges[e]["speed_kph"] >= 100 for e in edges):
        raise ValueError("Selected corridor includes an edge already at the upgrade cap")
    a = upgrade(baseline, edges, 1.4, 100, 100)
    b = add_connection(baseline, *endpoints, assumed_cost=float(selected.assumed_cost_units))
    started = time.perf_counter()
    summary, detail = compare(baseline, pairs, [a, b])
    alternatives = {item.name: practical_alternatives(item.graph, pairs) for item in (a, b)}
    alternatives["Baseline"] = practical_alternatives(baseline, pairs)
    stages["comparison_and_alternatives_seconds"] = time.perf_counter() - started
    closed_edges = reciprocal_edges(baseline, edges)
    closure_summary, closure_detail = closure_impact(baseline, pairs, closed_edges)
    started = time.perf_counter()
    sensitivity = sensitivity_matrix(
        original, anchors, edges, endpoints, cost_a=a.assumed_cost, cost_b=b.assumed_cost
    )
    stages["sensitivity_seconds"] = time.perf_counter() - started
    routes = []
    route_geo = []
    names = dict(zip(anchors.node, anchors.name, strict=True))
    for pair in pairs:
        try:
            path = route_edges(baseline, pair.origin, pair.destination)
            routes.append(
                {
                    "origin_name": names[pair.origin],
                    "destination_name": names[pair.destination],
                    "origin": pair.origin,
                    "destination": pair.destination,
                    "modeled_seconds": sum(baseline.edges[e]["travel_time"] for e in path),
                    "distance_m": sum(baseline.edges[e]["length"] for e in path),
                    "edge_sequence": json.dumps(path),
                    "reachable": True,
                }
            )
            for sequence, (u, v, k) in enumerate(path):
                route_geo.append(
                    {
                        "origin": pair.origin,
                        "destination": pair.destination,
                        "sequence": sequence,
                        "u": u,
                        "v": v,
                        "key": k,
                    }
                )
        except nx.NetworkXNoPath:
            routes.append(
                {
                    "origin_name": names[pair.origin],
                    "destination_name": names[pair.destination],
                    "origin": pair.origin,
                    "destination": pair.destination,
                    "reachable": False,
                }
            )
    anchors.to_csv(out / "anchors.csv", index=False)
    ranking.to_csv(out / "ranking.csv", index=False)
    screened.to_csv(out / "screened_connections.csv", index=False)
    candidates.to_csv(out / "candidate_evaluation.csv", index=False)
    summary.to_csv(out / "scenario_summary.csv", index=False)
    detail.to_csv(out / "scenario_od_results.csv", index=False)
    pd.DataFrame([asdict(p) for p in pairs]).to_csv(out / "od_demand.csv", index=False)
    pd.DataFrame(routes).to_csv(out / "named_routes.csv", index=False)
    pd.DataFrame(route_geo).to_csv(out / "route_edge_sequences.csv", index=False)
    sensitivity.to_csv(out / "sensitivity_27_cases.csv", index=False)
    closure_detail.to_csv(out / "corridor_closure_od.csv", index=False)
    pd.DataFrame(alternatives).T.to_csv(out / "practical_alternatives.csv")
    if source != "synthetic":
        route_boundary_exposure(baseline, pairs, NH48.bbox).to_csv(
            out / "boundary_exposure.csv", index=False
        )
    network_map(baseline, ranking).write_html(out / "network.html", include_plotlyjs=True)
    network_map(b.graph).write_html(out / "selected_connection.html", include_plotlyjs=True)
    edge_frame(baseline).to_file(out / "network.geojson", driver="GeoJSON")
    audit = {
        "weak_components": nx.number_weakly_connected_components(baseline),
        "strong_components": nx.number_strongly_connected_components(baseline),
        "named_edges": sum(bool(d.get("name")) for _, _, d in baseline.edges(data=True)),
        "tagged_speed_edges": sum(
            "OSM maxspeed" in d.get("speed_source", "") for _, _, d in baseline.edges(data=True)
        ),
        "mapped_signal_nodes": sum(
            d.get("highway") == "traffic_signals" for _, d in baseline.nodes(data=True)
        ),
    }
    manifest = {
        "version": "0.2.0",
        "source": source,
        "real_roads": source != "synthetic",
        "traffic_observations": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "nodes": len(baseline),
        "directed_edges": baseline.number_of_edges(),
        "od_pairs": len(pairs),
        "baseline_graph_sha256": graph_fingerprint(baseline),
        "original_graph_sha256": graph_fingerprint(original),
        "candidate_budget": candidate_budget,
        "evaluated_candidates": len(candidates),
        "candidate_objective": "new reachable demand first; then seconds per assumed cost unit",
        "candidate_cost": "500 assumed arbitrary units per km of modeled new alignment",
        "upgrade": {**a.details, "assumed_cost_units": a.assumed_cost},
        "new_connection": {**b.details, "assumed_cost_units": b.assumed_cost},
        "corridor_closure": closure_summary,
        "closed_edges": closed_edges,
        "stages": stages,
        "audit": audit,
        "python": sys.version,
        "platform": platform.platform(),
        "versions": {
            p: importlib.metadata.version(p) for p in ("networkx", "osmnx", "numpy", "pandas")
        },
        "sources": list(NH48.sources) if source != "synthetic" else [],
        "demand_status": "assumed relative OD weights between approximate area anchors",
        "capacity_assignment": False,
        "construction_feasibility_validated": False,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(summary.to_string(index=False))
    print(json.dumps(manifest, indent=2))
    return manifest

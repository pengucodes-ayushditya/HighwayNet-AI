"""Reproducible command-line benchmark and data fetch."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from highwaynet.analysis import rank_bottlenecks, ranking_sensitivity, sample_od
from highwaynet.data import graph_fingerprint, load_osm, synthetic_graph
from highwaynet.maps import network_map
from highwaynet.scenarios import add_connection, compare, eligible_connections, upgrade


def benchmark(source: str, out: Path, count: int, candidates: int, repeats: int = 3) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    graph = (
        load_osm() if source == "osm" else synthetic_graph(8 if source == "synthetic-region" else 3)
    )
    load_seconds = time.perf_counter() - started
    pairs = sample_od(graph, count, 42)
    timing = []
    for _ in range(repeats):
        start = time.perf_counter()
        ranking = rank_bottlenecks(graph, pairs, candidate_limit=candidates)
        rank_seconds = time.perf_counter() - start
        top = ranking.iloc[0]
        edge = (int(top.u), int(top.v), int(top.key))
        a = upgrade(graph, [edge], 1.4, max_speed_kph=100, assumed_cost=100)
        # Fixed documented synthetic example; live mode uses first geometric candidate.
        candidate = (2, 9) if source == "synthetic" else eligible_connections(graph)[0][:2]
        b = add_connection(graph, *candidate, speed_kph=40, assumed_cost=300)
        start = time.perf_counter()
        summary, detail = compare(graph, pairs, [a, b])
        timing.append(
            {"ranking_seconds": rank_seconds, "comparison_seconds": time.perf_counter() - start}
        )
    ranking.to_csv(out / "ranking.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    detail.to_csv(out / "od_results.csv", index=False)
    import pandas as pd

    pd.DataFrame([asdict(p) for p in pairs]).to_csv(out / "od_demand.csv", index=False)
    ranking_sensitivity(graph, pairs, candidates).to_csv(
        out / "ranking_sensitivity.csv", index=False
    )
    network_map(graph, ranking).write_html(out / "network.html", include_plotlyjs=True)
    manifest = {
        "source": source,
        "synthetic": source != "osm",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "graph_sha256": graph_fingerprint(graph),
        "nodes": len(graph),
        "directed_edges": graph.number_of_edges(),
        "od_pairs": len(pairs),
        "seed": 42,
        "candidate_limit": candidates,
        "load_seconds": load_seconds,
        "runtime_runs": timing,
        "python": sys.version,
        "platform": platform.platform(),
        "versions": {
            p: importlib.metadata.version(p)
            for p in ["networkx", "osmnx", "numpy", "pandas", "geopandas", "streamlit"]
        },
        "scenario_a": {**a.details, "assumed_cost": a.assumed_cost},
        "scenario_b": {**b.details, "assumed_cost": b.assumed_cost},
        "demand": "Uniform synthetic weights, 1 assumed trip per pair per unspecified period",
        "cost_units": "arbitrary assumed total units; not rupees or engineering estimates",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(summary.to_string(index=False))
    print(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="Fetch/cache a bounded named OSM study")
    fetch.add_argument("--refresh", action="store_true")
    fetch.add_argument("--study", choices=["nh48_airport", "rohini"], default="nh48_airport")
    fetch.add_argument("--provider", choices=["overpass", "osm-api"], default="overpass")
    imported = sub.add_parser("import-osm", help="Import a local OSM XML road extract")
    imported.add_argument("path", type=Path)
    imported.add_argument("--study", choices=["nh48_airport", "rohini"], default="nh48_airport")
    study = sub.add_parser(
        "case-study", help="Named OD, candidate search and sensitivity experiment"
    )
    study.add_argument("--source", choices=["synthetic", "nh48_airport"], default="nh48_airport")
    study.add_argument("--out", type=Path, default=Path("results/local/case-study"))
    study.add_argument("--candidate-budget", type=int, default=16)
    observed = sub.add_parser(
        "validate-routes", help="Compare explicitly supplied timestamped observations"
    )
    observed.add_argument("csv", type=Path)
    observed.add_argument("--out", type=Path, default=Path("results/local/validation"))
    bench = sub.add_parser("benchmark", help="Run reproducible fixed-seed comparison")
    bench.add_argument(
        "--source", choices=["synthetic", "synthetic-region", "osm"], default="synthetic"
    )
    bench.add_argument("--out", type=Path, default=Path("results/local"))
    bench.add_argument("--od-count", type=int, default=60)
    bench.add_argument("--candidates", type=int, default=40)
    bench.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.command in {"fetch", "import-osm"}:
        from highwaynet.snapshot import fetch_osm_api_tiles, fetch_snapshot, import_osm
        from highwaynet.studies import STUDIES

        study = STUDIES[args.study]
        target = Path("data") / study.slug
        if args.command == "import-osm":
            graph = import_osm(args.path, study, target)
        else:
            fetcher = fetch_osm_api_tiles if args.provider == "osm-api" else fetch_snapshot
            graph = fetcher(study, target, args.refresh)
        print(f"OSM snapshot: {len(graph)} nodes, {graph.number_of_edges()} directed edges")
    elif args.command == "case-study":
        from highwaynet.case_study import run_case_study

        run_case_study(args.source, args.out, args.candidate_budget)
    elif args.command == "validate-routes":
        import pandas as pd

        from highwaynet.snapshot import load_snapshot
        from highwaynet.validation import validate_observations

        summary, detail = validate_observations(
            load_snapshot(Path("data/nh48_airport")), pd.read_csv(args.csv)
        )
        args.out.mkdir(parents=True, exist_ok=True)
        detail.to_csv(args.out / "route_validation.csv", index=False)
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
    else:
        if not 1 <= args.od_count <= 120 or not 1 <= args.candidates <= 80 or args.repeats < 1:
            parser.error("Require OD 1–120, candidates 1–80, repeats >=1")
        benchmark(args.source, args.out, args.od_count, args.candidates, args.repeats)


if __name__ == "__main__":
    main()

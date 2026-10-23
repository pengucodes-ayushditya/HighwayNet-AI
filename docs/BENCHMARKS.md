# v0.2 benchmark and verification evidence

## Real study and provenance

Genuine OSM snapshot: 3,793 nodes / 8,107 directed arcs, downloaded 22 October 2026 through four sequential main OSM API requests. The balanced experiment uses five approximate area-junction anchors, 20 ordered OD pairs, relative weight 1 per pair and uncongested modeled times. No observed traffic counts or measured trip durations were used.

Exact data/request provenance: `data/nh48_airport/provenance.json` and `request.json`. Exact experiment inputs: `results/nh48_case/manifest.json`, `anchors.csv` and `od_demand.csv`. Graph fingerprints use schema v2, which includes geometry and screening/delay inputs.

## Measured runtime

This table records one completed in-process run using `time.perf_counter`, on Linux-6.18.55-x86_64-with-glibc2.39 with Python 3.12.14. These are actual stage times, not a latency guarantee or a repeated-run median. File exports, GeoJSON and HTML generation are outside the listed analysis-stage timers. Dependency versions are retained in the manifest.

| Stage | Elapsed seconds |
|---|---:|
| load and anchors | 0.6845 |
| hybrid ranking | 7.3234 |
| candidate search | 2.2375 |
| comparison and alternatives | 6.5320 |
| sensitivity | 2.1090 |

The ranking uses 96 seeded centrality sources and a 40-arc hybrid closure shortlist. The new-link search had a budget of 16 and evaluated all 14 proposals passing the conservative geometry gates.

## Fixed scenario results

| Scenario | Weighted seconds saved | Savings % | Improved OD pairs | Seconds / assumed cost unit |
|---|---:|---:|---:|---:|
| A · Upgrade | 101.310220 | 0.987845 | 6 | 1.013102 |
| B · New connection | 49.386461 | 0.481552 | 2 | 0.107403 |

A treats 17 directed segments / 1,116.67 m, ×1.4 modeled speed, cap 100 km/h, assumed total cost 100. B adds a two-way 919.65 m modeled connection at 40 km/h, circuity 1.2, and cost 500 arbitrary units/km (459.824185 total). Baseline aggregate: 10,255.676325 weighted seconds. These are relative-demand aggregate model outputs, not seconds saved per actual vehicle, daily travel savings or rupee benefits.

Baseline and A topological redundancy are 30%; B is 60%. All primary-route-disjoint alternatives fail the 1.5× time bound for these ODs. The nearest-any-road endpoint policy instead gives 0% baseline redundancy; see `anchor_policy_sensitivity.csv`. The choice of endpoints materially affects this measure.

A has the higher assumed benefit/cost ratio in all 27 recorded demand/operating/cost combinations. All 20 OD pairs remain connected in the boundary contractions, but the stronger contraction increases some trip estimates by up to 57.97 s. Neither diagnostic proves real planning validity.

## Routing plausibility and empirical validation

`results/osrm_checks/routing_comparison.csv` compares three cached public OSRM routing estimates with HighwayNet at the same final node coordinates. Differences are about +1.51, −19.06 and −5.43 seconds. This is an external routing-model comparison, not observed travel time, congestion measurement or prediction accuracy. Independent real observations are still absent; the supplied observation CSV is deliberately header-only.

## Software and browser verification

73 tests passed under both Python 3.12.14 and Python 3.11.17. Package statement coverage is 90%; `app.py` is exercised separately through Streamlit AppTest. Tests forbid unmocked external HTTP. Logs are `results/test_run_v2.txt` and `results/test_run_v2_python311.txt`.

Browser evidence: `results/browser_review.json` records real-study loading, successful map box selection, a 390 px viewport with page width 390 px, and no JavaScript page errors. Actual screenshots live in `docs/screenshots/`. This validates these tested flows, not every possible setting/device combination.

## Reproduce

```bash
uv run highwaynet case-study --source nh48_airport --out results/local/nh48
uv run highwaynet case-study --source synthetic --out results/local/demo
uv run python scripts/check_boundaries.py
uv run python scripts/check_anchor_policy.py
uv run python scripts/check_osrm.py
```

Current fictional results are in `results/synthetic_case/`. The old `results/synthetic/`, `results/synthetic-region/` and `results/legacy_v01/` retain historical v0.1 results/logs. Do not use them as v0.2 validation; the ranking and demand definitions changed.

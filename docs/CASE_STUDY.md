# Real-road pilot: NH-48 airport approaches

## Research question

Within a bounded network around Mahipalpur, Shiv Murti and Rajokri, how do an
existing-road corridor treatment and a screened hypothetical local connection
change modeled OD travel time, disruption exposure and route alternatives?

This is a network research experiment, not a proposal for construction. The
study includes local feeder roads; ownership and NHAI jurisdiction of individual
links have not been established.

## Why this area

MoRTH/NHAI's 28 May 2025 release describes airport/Dwarka underpass works intended
to relieve the Delhi–Gurugram NH-48 corridor. The 1 July 2026 Cabinet release
records approval of the Dwarka Expressway–Nelson Mandela Marg connection. These
provide official context for regional connectivity concerns; neither validates
this model's demand, speeds or proposed link.

- https://www.pib.gov.in/PressReleasePage.aspx?PRID=2132154
- https://www.pib.gov.in/PressReleasePage.aspx?PRID=2279818

The approved 8.1 km government project is **not** presented as our invention and
is not the 0.920 km hypothetical local link evaluated here. Existing/proposed
project status must be reviewed separately from this software's candidates.

## Evidence hierarchy

| Input or output | Status |
|---|---|
| Road geometry, way/node IDs, mapped direction, tags | Genuine OSM extract, downloaded 22 October 2026 |
| Five area coordinate choices | Manually selected approximate anchors; not authoritative entrances |
| Anchor-to-junction offsets | Computed and exported; maximum 183.83 m under default policy |
| Tagged maxspeed | Mapped limits on 153 directed edges; not observed operating speed |
| Remaining speeds, operating factors, signal delay | Explicit assumptions |
| OD weights and roles | Explicit synthetic relative-demand hypotheses |
| Costs | Arbitrary assumed units; no engineering estimate |
| OSRM routes | External routing-model estimates, not observed traffic |
| Construction feasibility, traffic calibration | Unverified |

Graph: 3,793 nodes, 8,107 directed edges, 25 mapped signals, 69 weak components
and 198 strong components. Preserve disconnected components and report them;
all 20 ordered pairs between the five default anchors are reachable.

## Baseline and interventions

The balanced baseline assigns relative weight 1 to each of the 20 ordered OD
pairs. Use uncongested modeled travel times; no measured peak-hour condition is
assumed. Baseline aggregate is 10,255.676325 weighted seconds.

**A: existing corridor.** A 1,116.67 m connected route window of 17 directed
segments around a ranked seed, primarily on Abdul Gaffar Khan Marg. Modeled
speeds ×1.4, capped at 100 km/h; total assumed cost 100 units. Export exact edges
rather than implying a surveyed design or a verified management jurisdiction.

**B: hypothetical link.** Nodes 9865312635 and 9832138338, about 766.37 m apart
geodesically; modeled length 919.65 m with circuity 1.2, two directions, assumed
uncongested speed 40 km/h. Cost is 500 arbitrary units/km, totaling 459.824185.
It passes the software's endpoint and road-crossing gates. Buildings, forest,
land rights, airport boundaries, gradients and intersection design remain unchecked.

The spatial screen uses up to 80 nodes and a 16-candidate evaluation budget. Only
14 candidates pass the chosen conservative gates, so all 14 are evaluated. One
has positive time benefit for this OD matrix; zero-benefit results are retained.

## Verified comparison

| Outcome | A | B |
|---|---:|---:|
| Weighted seconds saved | 101.310220 | 49.386461 |
| Common-reachable time reduction | 0.987845% | 0.481552% |
| Improved OD pairs | 6 | 2 |
| Seconds / assumed cost unit | 1.013102 | 0.107403 |
| Reachable demand share | 100% | 100% |
| Demand share with ≥2 directed edge-disjoint routes | 30% | 60% |
| Primary-route-disjoint alternative within 1.5× primary time | 0% | 0% |

Baseline topological redundancy is 30%. B improves that topological measure, but
its alternates are not time-competitive under the 1.5× test. Do not translate the
30→60% change into a physical resilience or congestion-reduction claim.
A has a higher assumed cost-efficiency ratio in all 27 tested combinations of
operating, relative demand and B-cost hypotheses. This is a result within the
stated parameter set, not evidence of the better real engineering project.

## What the diagnostics taught us

**Endpoint policy matters.** Snapping to any nearest road node gives 0% baseline
edge-disjoint demand for these area coordinates, while the default junction policy
gives 30%. Dead-end terminal access can dominate the metric. Both policies are
exported in `anchor_policy_sensitivity.csv`; neither is a verified entrance model.
The junction policy defines an area-access experiment, not door-to-door resilience.

**Boundary dependence remains.** All 20 pairs stay connected when trimming
0.0025° or 0.005° from each bbox edge. The stronger contraction adds up to
57.97 seconds to some routes. No primary route is within the 200 m boundary flag
in the full graph, which illustrates why that flag alone cannot prove stability.
A fresh, properly expanded extract remains a necessary planning-validation step.

**External routing checks are plausible, not empirical validation.** At identical
final node coordinates, HighwayNet and OSRM produced approximately:

| Route | HighwayNet modeled s | OSRM modeled s |
|---|---:|---:|
| Mahipalpur → Rajokri | 530.21 | 528.70 |
| Rangpuri → western Vasant Kunj approach | 706.94 | 726.00 |
| Shiv Murti approach → Mahipalpur | 207.17 | 212.60 |

Different speed profiles, turn handling, snapshot dates or outside routes can
explain differences. Raw responses, node IDs, acquisition times and distances are
retained in `results/osrm_checks/`. No prediction accuracy or observed congestion
metric is inferred from these three routing estimates.

## Reproduction

```bash
uv run highwaynet case-study --source nh48_airport --out results/local/nh48
uv run python scripts/check_boundaries.py
uv run python scripts/check_anchor_policy.py
uv run python scripts/check_osrm.py
```

The case-study command writes every main input/output and stage timing.
Diagnostic scripts write their documented named result paths; external checks
use matching cached responses unless `--refresh` is explicitly requested.
Keep the raw road extract and provenance with the graph. Refreshing OSM or changing
anchor/demand assumptions changes the experiment.

## What remains before real planning use

Obtain independent traffic observations and suitably sourced demand; inspect legal
turn/access restrictions and anchor entrances; expand the boundary; calibrate a
capacity/delay model if needed; investigate physical corridor failure zones; and
obtain engineering, land, environmental, safety and cost review. Positive graph
benefit alone is insufficient evidence to recommend construction.

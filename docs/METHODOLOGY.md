# v0.2 model contract

## Directed graph and modeled time

Use a WGS84 NetworkX MultiDiGraph with distinct `(u,v,key)` arcs. Do not invent
reverse travel or collapse parallel links. Time is positive and finite:
`length_m × 3.6 / speed_kph + nonnegative modeled_delay_s`. Validate units and
coordinates before analysis. Dijkstra chooses minimum modeled time; parallel-arc
ties use stable keys. OSM mapped one-way restrictions survive import; relation
turn restrictions and conditional/legal access rules are not enforced.

Apply an operating hypothesis to the baseline before interventions. Reapplying
the same hypothesis to a baseline is idempotent; applying it after an intervention
is rejected to avoid accidentally erasing that intervention. Busy/severe models
use explicit uniform speed factors and delays at mapped signals only. A new
connection receives the same operating-speed factor and modeled signal-arrival
delay as existing edges. None of these inputs are observed traffic conditions.

## OD matrix

Pairs are unique, ordered, non-self, valid-node pairs with positive finite relative
weights. Defaults in v0.2 use all 20 pairs between five approximate real area
anchors. The synthetic case uses six fictional anchors (30 pairs). Optional seeded
node-pair sampling remains available. Unreachable pairs are retained and reported.

Area anchors snap to the nearest road junction with ≥3 unique neighbors and
incoming/outgoing arcs, within 500 m; duplicates and excessive offsets are rejected.
This is not entrance/access verification. Balanced weights are 1. For the declared
residential-outbound hypothesis, origin residential role multiplies weight by 2
and destination gateway role by 1.5. Inbound reverses those roles. These are
sensitivity hypotheses, not measured morning/evening flows.

## Bottleneck ranking and shortlist

Compute time-weighted directed edge betweenness `b_e` using all nodes up to
300 nodes; otherwise use 96 seed-42 sampled source nodes. Compute an all-or-nothing
OD route-usage share `q_e`: sum of assumed weights whose deterministic shortest
route uses the arc divided by total assumed weight. This is not equilibrium
assignment or observed traffic volume.

Shortlisting interleaves descending betweenness and descending OD usage, retaining
unique arcs up to the budget (default 40). This reduces the risk that a pure
centrality screen misses a link used by the chosen demand, but is not exhaustive.

For baseline-reachable OD set `R`, let `D = sum(w_i for i in R)`. Remove a
candidate directed arc and recalculate times. Components:

- `I_e = 0.5 × (b_e / max_graph_b) + 0.5 × q_e`.
- `T_e = sum[w_i × min(max((t_closed_i − t_base_i)/t_base_i,0),2)] / (2D)`
  over pairs still reachable after closure.
- `L_e = sum(w_i for baseline-reachable pairs now lost) / D`.

Default score: `0.40 I_e + 0.35 T_e + 0.25 L_e`. User weights must be finite,
nonnegative and have positive sum, then are normalized. Zero-reachable-demand
cases assign zero detour/loss components. Components and scores remain 0–1.
Weights and the detour cap are uncalibrated design assumptions; show them alongside
results. A closure removes one directed arc; a physical two-way corridor failure
is a separate experiment.

## Existing-road treatments

Speed treatment: select a connected distinct directed edge set. Update speed to
`min(old_modeled_speed × factor, cap)`; require `1 < factor ≤2`, cap 5–100 km/h,
and a strict improvement on every selected arc. Retain existing modeled signal
delay. Reverse arcs require explicit inclusion. This is a travel-time hypothesis,
not a road-capacity, lane-addition or queue-discharge model.

Delay treatment: reduce explicitly modeled junction delays by a fraction `(0,1]`
on a connected edge set, leaving running speeds fixed. Reject a set with no
modeled delay. It does not demonstrate the feasibility of signal redesign.

The default treatment corridor is a contiguous window of up to 30 arcs on one
assumed-demand shortest route containing a ranked seed, targeting 1,000 m. Select
the highest-weight eligible route with stable endpoint tie breaks; expand by the
shorter adjacent next arc until the target/budget/route boundary is reached. Road
names may differ; this is an explicit route treatment set, not an inferred named
engineering corridor. Export every selected arc and its actual directed length.

## Hypothetical new-link search

1. Select up to 80 nodes using deterministic farthest-point spatial sampling in
   approximate local metric coordinates. Spatial coverage does not depend on
   arbitrary node-ID ordering (IDs only break coincident-coordinate ties).
2. Candidate endpoints must differ, have no direct link in either direction,
   and lie 100–1,500 geodesic metres apart.
3. In conservative real mode, exclude endpoints incident to motorway/trunk/ramp
   classes, bridges and tunnels. Reject schematic straight lines crossing
   existing road geometries without a modeled junction. This conservatively
   excludes some potential grade-separated designs.
4. Sort potential proposals by disconnected-direction status, then existing-network
   distance / straight-line distance, then stable distance/endpoint tie breaks.
   Keep the explicit evaluation budget. This is a screen, not a feasibility model.
5. Evaluate every shortlisted link against the same baseline/OD matrix. New length
   is geodesic distance × circuity (1–2); uncongested assumed speed 5–80 km/h,
   multiplied by the baseline operating-speed factor. One or two arcs are added.
6. Sort evaluated outcomes lexicographically by newly reachable **demand weight**,
   then finite weighted seconds saved per arbitrary cost unit, then time benefit.
   Do not turn newly reachable trips into invented infinite savings.

Default candidate cost is 500 arbitrary units per modeled alignment km. The
upgrade has a separate stated assumed total cost. These assumptions are not
engineering estimates, rupees, monetized benefits or financial BCRs. Land rights,
forest/building/airport boundaries, barriers, gradients, junction design and
construction feasibility remain unchecked. “Eligible” means passing these
software gates only. The displayed straight line is not a proposed alignment.

## Comparison and resilience

For the same OD matrix and common-reachable set in each scenario:
`savings = sum[w_i × (baseline_seconds − scenario_seconds)]`.
Savings percentage uses weighted baseline time on that same common set. Affected
pair threshold is 1e-7 s. Newly reachable and lost pairs are reported separately;
undefined per-pair savings are empty in CSV. Relative weights produce weighted
seconds; no daily/annual extrapolation is justified.

Topological redundancy is demand share with ≥2 directed edge-disjoint routes,
using unit capacity per arc and cutoff-2 max flow. Parallel arcs count separately.
Shared physical infrastructure and junction failures are not identified.

The practical alternative diagnostic removes the arcs of one selected primary
shortest route, reroutes, and reports demand with an alternate within 1.5×
primary time. This is a primary-route-specific conservative diagnostic, not an
exhaustive disjoint-pair optimization. Long alternate routes can improve topology
without improving this time-bounded measure.

Corridor failure removes the selected arcs plus matching reverse arcs with the
same endpoints and OSM way identity (or fictional name). Separate carriageway
node sequences are not inferred to share a physical failure zone. Report finite
detours and lost demand separately.

## Sensitivity and validation

The standardized matrix holds intervention endpoints/edges fixed across 3 operating
models × 3 named demand hypotheses × 3 B-cost multipliers (0.5,1,2): 27 cases.
It uses a two-way new link, 40 km/h uncongested speed, circuity 1.2, and a speed
upgrade. The UI rejects incompatible custom settings instead of silently running
a different experiment. This is a structured scenario set, not statistical
confidence intervals or a robustness guarantee outside its ranges.

Boundary exposure flags primary routes within 200 approximate metric metres of
the bbox. A separate node-induced contraction check preserves OD IDs and compares
routing after trimming 0.0025° and 0.005° from each side. It does not prove the
outer bbox captures all possible detours; a properly expanded re-extract is still
needed before real planning use.

Route-observation validation requires positive durations, valid endpoints,
timezone-aware timestamps and explicit sources. It reports MAE/MAPE on reachable
route comparisons, flags unreachable observations, and does not infer edge speeds
from aggregate route times. Independence/provenance of user-supplied data require
review. No such measured observations are bundled.

Three separately cached OSRM queries compare routing estimates at the same final
road-node coordinates. They offer an external routing implementation check but
share OSM ancestry, can use a different snapshot/profile, may traverse outside the
study boundary, and are not measured traffic or empirical accuracy validation.

## Runtime, integrity and claim boundary

Dijkstra is repeated per distinct origin and closure candidate. Centrality is
source-sampled for the real graph; candidate search and OD count have explicit
budgets. Redundancy uses separate cutoff-2 flow computations per OD. Cache by
fingerprinted model inputs and explicit parameters; keep graph copies for
interventions. Fingerprint schema v2 includes geometry and screening/delay inputs.

An internally consistent result is not an infrastructure recommendation. Missing
traffic counts/speeds, conditional access, legal turns, network boundaries,
incomplete tags, demand assumptions and cost/feasibility gaps can change conclusions.
No learned ML predictor, calibrated traffic assignment, capacity analysis or
endorsed recommendation is claimed.

Primary references: OSMnx user reference (https://osmnx.readthedocs.io/en/stable/user-reference.html),
NetworkX edge betweenness documentation
(https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.edge_betweenness_centrality.html),
OSRM API (https://project-osrm.org/docs/v5.24.0/api/), and OSM data license
(https://www.openstreetmap.org/copyright).

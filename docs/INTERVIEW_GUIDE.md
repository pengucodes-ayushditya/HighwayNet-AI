# Interview guide: HighwayNet AI v0.2

## A concise introduction

“I built an independent Python/Streamlit prototype for road-network decision
support. It uses a genuine OSM snapshot around the NH-48 airport approaches,
with directed and parallel roads, explicit speed/demand assumptions, and a
hybrid bottleneck ranking. I compare a connected existing-road treatment with
systematically screened hypothetical links using the same OD matrix. I also
check corridor failure, useful alternatives, assumption sensitivity and external
routing plausibility. The project does not claim measured congestion or
construction feasibility.”

## What is the engineering contribution?

An auditable end-to-end workflow: bounded source acquisition/import, direction and
units, integrity checks, demand-aware screening, non-mutating scenarios, fair
comparison, reachability handling, runtime budgets, reproducible artifacts,
tested UI and clear evidence boundaries. It integrates established algorithms;
it does not invent a new centrality method or trained traffic model.

## Explain the real case precisely

The real snapshot has 3,793 nodes and 8,107 directed edges. Five manually chosen
area anchors snap to nearby multi-neighbor junctions; 20 ordered OD pairs use
assumed relative weights. A treats 17 directional segments spanning 1.117 km;
B adds a schematic 0.920 km connection from the evaluated shortlist.

Under the fixed balanced/uncongested assumptions, A saves 101.31 weighted seconds
and B 49.39. These are aggregate weighted seconds across assumed demand, not
per-vehicle or daily savings. A's assumed cost efficiency is higher, while B
raises topological redundancy from 30% to 60%. No usable primary-route-disjoint
alternate within 1.5× primary time is found. Discuss the tradeoff and limitations.

## Why direction and parallel edge keys?

One-way roads must not permit invented reverse routes. Multiple links between
the same nodes may differ. Every treatment addresses `(u,v,key)`. Explicitly
select reverse arcs when needed; do not assume a road name identifies a fully
validated physical corridor.

## How is the score calculated?

Connectivity importance averages normalized time-weighted edge betweenness and
assumed OD shortest-route usage. Default score is 40% importance, 35% capped
closure detour and 25% lost reachable-demand fraction. Shortlisting interleaves
centrality and OD usage. Weights/caps are design assumptions. Changing OD weights
or the screen can change the shortlist; it is not a global congestion ranking.

## Why not call this congestion detection?

Congestion requires operating conditions such as observed delay, volume or
capacity. This project has real geometry and mapped limits but no measured
traffic sample. Only 153 directed edges have speed tags. Most use documented
class defaults. Busy/severe modes are explicitly assumed stress cases.

## How does the candidate search improve the first MVP?

The first MVP displayed long geometric gaps and used node-ID sampling. v0.2 uses
farthest-point spatial sampling, distance/access/crossing gates, an explicit budget,
and evaluation of every shortlisted proposal against the same OD matrix. It
keeps zero-benefit proposals. A useful-looking gap does not establish a useful
connection; passing geometry gates does not establish constructability.

## Is upgrading speed equivalent to adding a lane?

No. The speed treatment changes a static time weight. A separate junction-delay
treatment changes an explicitly assumed delay. Neither models capacity,
queue discharge, signal optimization, induced demand or equilibrium assignment.
Add those only when the required inputs and validation exist.

## What happens to disconnected trips?

Never sum infinite times into savings. Report common-reachable time changes and
new/lost reachability separately. Closure loss is its own ranking component.
Blank per-OD savings mean undefined, not zero. Newly connected demand is not
monetized or assigned an arbitrary infinite benefit.

## What did external validation establish?

Three OSRM estimates were obtained for final road-node coordinates and compared
with our route estimates. The differences are retained; they are not empirical
prediction errors. Both systems rely on OSM ancestry, and profiles/snapshots can
differ. Independent observed journey durations are still needed for traffic
calibration and route-level error assessment.

## Why report anchor-policy sensitivity?

Nearest-any-road endpoints gave zero topological redundancy, while nearby junction
endpoints gave 30%. Terminal stubs matter. This is why I explicitly define the
experiment as area-junction access and disclose snapping distances instead of
claiming door-to-door resilience. It also shows that a metric can be internally
correct but sensitive to the question and endpoint definition.

## What do 27 sensitivity cases establish?

Three operating models × three relative-demand hypotheses × three B-cost
multipliers, holding intervention edges/endpoints fixed. A's cost-efficiency
ratio is higher in all those cases. This is robustness within the tested ranges,
not a confidence interval or a real-world project ranking.

## Five-minute walkthrough

1. Start the default real snapshot and show provenance/traffic-assumption labels.
2. Inspect a named route and source speed assumptions.
3. Inspect the shortlisted seed and the default connected treatment corridor.
4. Drag a small box over a map road marker; select a segment and send it to A.
   Restore the default study for the recorded example if demonstrating another link.
5. Compare A and B: savings, arbitrary costs and zero-benefit candidates.
6. Show corridor failure and practical alternatives. Explain why extra topological
   routes need not be competitive or physically independent.
7. Run standardized sensitivity, then inspect boundary and anchor-policy diagnostics.
8. Download exact OD results/assumptions and show the test and browser-review evidence.

## Conservative resume wording

“Built a geospatial road-network analysis prototype using OSMnx, NetworkX and
Streamlit; implemented demand-aware bottleneck ranking, corridor-disruption
analysis and upgrade/new-link comparisons on a real Delhi NCR road snapshot,
with reproducible scenario and sensitivity tests.”

Avoid measured congestion reduction, NHAI endorsement, real construction savings,
validated costs, ML accuracy or real deployment claims without corresponding evidence.

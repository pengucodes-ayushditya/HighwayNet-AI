# Dataset provenance and evidence status

## Real OSM study

`nh48_airport/network.graphml` and `nh48_airport/roads.osm` are genuine
OpenStreetMap road data for bbox W/S/E/N **77.085, 28.500, 77.160, 28.562**.
The graph has 3,793 nodes and 8,107 directed edges. Source: © OpenStreetMap
contributors, ODbL 1.0, https://www.openstreetmap.org/copyright.

On 22 October 2026, four sequential bounded requests to
`https://api.openstreetmap.org/api/0.6/map` succeeded. `request.json` retains tile
bounds, URLs, timestamps and original-byte hashes. A road-only XML merge preserves
way/node IDs and chooses the highest version when tiles overlap. The four requests
are nearby snapshots, not one atomic historical database state. Raw tile caches
are reproducible intermediate inputs and are not part of the release archive;
the merged road extract and final graph are included.

`provenance.json` records the merged XML hash, graph fingerprint, OSMnx version,
import timestamp, bounds, access-filter limitations and evidence status. Loading
verifies graph and raw XML fingerprints. Fingerprint schema v2 includes geometry
(rounded to 9 geographic decimals to ignore WKT noise), signal tags, road identity,
access/screening attributes, lengths, speeds, time/delay weights and operating factors.
A fingerprint is an integrity/reproducibility aid, not an authenticity signature.

Network processing conservatively keeps public passenger-car road classes,
excludes footways and explicitly private/no-access roads plus parking aisles and
driveways, retains mapped one-way directions, then truncates and simplifies.
Traffic-signal nodes are retained during simplification. Specific permissions
that override generic access, conditional restrictions, turn relations and legal
vehicle restrictions require further review.

Data completeness audit: **751 named edges, 153 tagged-speed edges, 25 signal
nodes, 69 weak components and 198 strong components**. Components are preserved,
not silently connected or dropped. A large component supports all named OD routes.
Only about 1.9% of directed edges use tagged speeds; most use explicit class
assumptions. Mapped signal counts do not establish completeness of actual signals.

Earlier Overpass requests timed out. The bundled real dataset comes from the
identified main OSM API, not from those failed attempts. The older v0.1 Google
DNS failure does not describe the successful v0.2 data acquisition.

## Area anchors and demand

Five manually selected approximate area coordinates are defined in `studies.py`.
They are not authoritative geocoded entrances. The closest mapped road junction
with at least three distinct neighbors and an incoming/outgoing arc is selected,
within 500 m, with distinct node IDs. Snap offsets are exported. The selected
anchors are Mahipalpur, Shiv Murti approach, Rajokri, Rangpuri and western Vasant
Kunj approach areas. This avoids letting arbitrary dead-end terminal stubs
completely determine the redundancy diagnostic.

Balanced demand assigns relative weight 1 to every ordered non-self pair.
Residential outbound/inbound hypotheses reweight these same pairs using declared
roles. Neither is a measured AM/PM OD matrix. All 20 balanced pairs are reachable.
`results/nh48_case/anchors.csv` and `od_demand.csv` give exact current inputs.

## Speeds, delay and units

- Length: metres; raw OSMnx segment sums through simplification.
- Speed: km/h. Recognized numeric OSM `maxspeed` limits, including mph, use the
  minimum parseable value. Ambiguous/conditional tags use class defaults.
- Modeled time: `length_m × 3.6 / speed_kph + modeled_delay_s`, in seconds.
- Default/uncongested model: tagged/assumed speeds, zero signal delay.
- Assumed busy: speed ×0.75, 20 s per arrival at a mapped signal.
- Assumed severe delay: speed ×0.50, 40 s per arrival at a mapped signal.

These are hypotheses, not observed traffic or legally applicable speed advice.
Class fallback table:

| Class | Assumed km/h |
|---|---:|
| motorway / link | 70 / 40 |
| trunk / link | 60 / 35 |
| primary / link | 50 / 30 |
| secondary / link | 40 / 30 |
| tertiary / link | 35 / 25 |
| residential / unclassified / unknown | 25 |
| service / living_street | 20 / 15 |

## Other bundled files

- `synthetic_demo.graphml`, `synthetic_od.csv`, `synthetic_provenance.json`:
  project-authored fictional 18-node, 53-arc network and 60-pair historical fixture.
  It is not a Delhi extract. Generator: `synthetic_graph()`; size 8 gives a
  separate fictional 128-node network.
- `route_observations_template.csv`: header-only template; no invented observations.
- `results/osrm_checks/`: external routing-model responses and comparisons, with
  public junction coordinates and acquisition timestamps. These are not measured
  vehicle journeys or proof of congestion.

OSM raw and derived data use ODbL; authored synthetic data use MIT. No private
credentials, personal user travel history or API keys are required or bundled.

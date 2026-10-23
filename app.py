"""HighwayNet AI v0.2 — launch with uv run streamlit run app.py."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from highwaynet.analysis import ODPair, RankingWeights, rank_bottlenecks, route_edges, sample_od
from highwaynet.data import graph_fingerprint, synthetic_graph
from highwaynet.demand import demo_anchors, named_demand, snap_anchors
from highwaynet.experiments import sensitivity_matrix
from highwaynet.maps import network_map
from highwaynet.operating import MODELS, operating_model, reduce_junction_delay
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
from highwaynet.validation import route_boundary_exposure, validate_observations

ROOT = Path(__file__).resolve().parent
REAL = "NH-48 · Real OSM snapshot"
DEMO = "Synthetic offline demo"
st.set_page_config(page_title="HighwayNet AI", page_icon="🛣️", layout="wide")
st.markdown(
    """<style>
.stApp {background:#0b1421;} .block-container {padding-top:4.5rem; max-width:1550px;}
h1,h2,h3 {letter-spacing:-.025em;} [data-testid="stMetric"] {
background:#132337;padding:16px;border-radius:12px;border:1px solid #25405a;}
[data-testid="stSidebar"] {background:#101e2d;} .eyebrow {color:#27cfb1;
font-size:12px;letter-spacing:3px;font-weight:700;} .subtitle {color:#a8bbcf;}
</style>""",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="eyebrow">HIGHWAYNET AI / CORRIDOR RESEARCH LAB</div>', unsafe_allow_html=True
)
st.title("Road networks. Better questions.")
st.markdown(
    (
        '<p class="subtitle">Bottleneck analysis, corridor resilience '
        "and transparent intervention experiments.</p>"
    ),
    unsafe_allow_html=True,
)
st.caption(
    "Independent DTU student research prototype · Real road geometry where selected · "
    "Assumed speeds, demand and costs · No observed congestion or NHAI endorsement"
)


@st.cache_resource(show_spinner=False)
def dataset(source: str) -> nx.MultiDiGraph:
    return load_snapshot(ROOT / "data/nh48_airport") if source == REAL else synthetic_graph()


@st.cache_data(show_spinner=False)
def rank_cached(_graph, fingerprint, pairs, weights, limit):
    return rank_bottlenecks(_graph, pairs, weights, candidate_limit=limit)


@st.cache_data(show_spinner=False)
def search_cached(
    _graph, fingerprint, pairs, conservative, budget, speed, circuity, cost_rate, two_way
):
    proposals = screen_connections(_graph, limit=budget, conservative=conservative)
    return evaluate_connections(_graph, pairs, proposals, speed, circuity, cost_rate, two_way)


@st.cache_data(show_spinner=False)
def compare_cached(_graph, fingerprint, pairs, _a, _b, signature):
    return compare(_graph, pairs, [_a, _b])


with st.sidebar:
    st.markdown("### Study & assumptions")
    source = st.selectbox("Dataset", [REAL, DEMO])
    operating = st.selectbox("Travel-time hypothesis", list(MODELS))
    st.caption(
        "Busy/severe modes reduce assumed operating speeds and add delay only at mapped signals."
    )
    od_mode = st.selectbox("OD locations", ["Named area anchors", "Seeded node-pair sample"])
    demand_profile = st.selectbox(
        "Demand hypothesis", ["balanced", "residential_outbound", "residential_inbound"]
    )
    seed = st.number_input("Sampling seed", 0, 100000, 42)
    od_count = st.slider("Sampled OD count (sample mode)", 10, 120, 60, 10)
    uploaded_od = st.file_uploader("Replace OD matrix · origin,destination,weight", type="csv")
    st.markdown("### Ranking sensitivity")
    bw = st.slider("Connectivity importance", 0.0, 1.0, 0.40, 0.05)
    dw = st.slider("Closure detour", 0.0, 1.0, 0.35, 0.05)
    lw = st.slider("Disconnection loss", 0.0, 1.0, 0.25, 0.05)
    rank_limit = st.slider("Detailed closure candidate budget", 10, 80, 40, 10)
    st.caption(
        "Screen combines structural centrality and assumed OD usage. Score weights are normalized."
    )

try:
    original = dataset(source)
    graph = operating_model(original, operating)
    anchors = snap_anchors(graph, NH48) if source == REAL else demo_anchors(graph)
    pairs = (
        named_demand(graph, anchors, demand_profile)
        if od_mode == "Named area anchors"
        else sample_od(graph, od_count, seed)
    )
    if uploaded_od is not None:
        matrix = pd.read_csv(uploaded_od)
        if not {"origin", "destination", "weight"}.issubset(matrix) or not 1 <= len(matrix) <= 120:
            raise ValueError("OD CSV needs origin,destination,weight and 1–120 rows")
        if not all(float(v).is_integer() for c in ("origin", "destination") for v in matrix[c]):
            raise ValueError("OD node IDs must be integers")
        pairs = [
            ODPair(int(r.origin), int(r.destination), float(r.weight)) for r in matrix.itertuples()
        ]
    weights = RankingWeights(bw, dw, lw)
    fingerprint = graph_fingerprint(graph)
    with st.spinner("Evaluating structural importance and directed closures…"):
        ranking = rank_cached(graph, fingerprint, pairs, weights, rank_limit)
except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
    st.error(f"Study input unavailable or invalid: {exc}")
    st.info(
        "For a missing real snapshot, import local OSM XML or use the documented fetch command. "
        "The synthetic demo is separately selectable."
    )
    st.stop()

if source == REAL:
    st.info(
        "REAL ROAD SNAPSHOT · NH-48 / Mahipalpur–Shiv Murti–Rajokri · "
        "OSM geometry with modeled times. Approximate area anchors use road junctions; "
        "access needs review."
    )
else:
    st.info("SYNTHETIC OFFLINE DEMO · Fictional roads and assumed trips. No traffic measurements.")
metrics = st.columns(4)
metrics[0].metric("Road nodes", f"{len(graph):,}")
metrics[1].metric("Directed road edges", f"{graph.number_of_edges():,}")
metrics[2].metric("OD pairs / weight units", f"{len(pairs)} / {sum(p.weight for p in pairs):g}")
metrics[3].metric(
    "Mapped signal nodes",
    sum(d.get("highway") == "traffic_signals" for _, d in graph.nodes(data=True)),
)
network_tab, lab_tab, resilience_tab, evidence_tab = st.tabs(
    ["Network & routes", "Intervention lab", "Resilience & uncertainty", "Evidence & method"]
)

with network_tab:
    left, right = st.columns([1.65, 1])
    with left:
        st.subheader("Structural bottleneck map")
        picker = st.toggle("Select a road on the map", value=False)
        if picker:
            event = st.plotly_chart(
                network_map(graph, ranking, anchors=anchors, pick_edges=True),
                width="stretch",
                key="picker-map",
                on_select="rerun",
                selection_mode=("points", "box"),
            )
            st.caption("Drag a small box around a road marker, then choose a selected segment.")
            points = event.selection.points
            picked_options = []
            for point in points:
                values = point.get("customdata", [])
                if isinstance(values, (list, tuple)) and len(values) == 3:
                    edge = tuple(int(v) for v in values)
                    if graph.has_edge(*edge) and edge not in picked_options:
                        picked_options.append(edge)
            if picked_options:
                picked = st.selectbox(
                    "Selected road segment",
                    picked_options,
                    format_func=lambda e: f"{graph.edges[e].get('name', 'Unnamed road')} · {e}",
                )
                if st.button("Use selected segment in intervention A"):
                    st.session_state["upgrade_edges"] = [picked]
        else:
            st.plotly_chart(
                network_map(graph, ranking, anchors=anchors), width="stretch", key="baseline-map"
            )
        st.caption(
            "Orange: highest ranked screened links. Diamonds: trip anchors. "
            "Road geometry and selection work without external map tiles."
        )
    with right:
        st.subheader("Priority shortlist")
        st.caption(
            "Modeled structural criticality. A high score does not establish observed congestion."
        )
        st.dataframe(
            ranking[["name", "score", "od_usage_share", "affected_od_pairs"]]
            .head(10)
            .rename(
                columns={
                    "name": "Road",
                    "score": "Score",
                    "od_usage_share": "OD share",
                    "affected_od_pairs": "Affected ODs",
                }
            ),
            column_config={
                "Score": st.column_config.NumberColumn(format="%.3f"),
                "OD share": st.column_config.NumberColumn(format="%.2f"),
            },
            hide_index=True,
            width="stretch",
            height=420,
        )
    with st.expander("Explore a named shortest-time route", expanded=False):
        names = anchors["name"].tolist()
        route_cols = st.columns(2)
        origin_name = route_cols[0].selectbox("Route origin", names)
        destination_name = route_cols[1].selectbox("Route destination", names, index=len(names) - 1)
        origin = int(anchors.loc[anchors["name"] == origin_name, "node"].iloc[0])
        destination = int(anchors.loc[anchors["name"] == destination_name, "node"].iloc[0])
        if origin != destination:
            try:
                route = route_edges(graph, origin, destination)
                seconds = sum(graph.edges[e]["travel_time"] for e in route)
                metres = sum(graph.edges[e]["length"] for e in route)
                st.write(
                    f"{origin_name} → {destination_name} · "
                    f"{seconds / 60:.2f} modeled min · {metres / 1000:.2f} km"
                )
                st.plotly_chart(
                    network_map(
                        graph, selected=route, highlight_label="Selected route", anchors=anchors
                    ),
                    width="stretch",
                    key="route-map",
                )
            except nx.NetworkXNoPath:
                st.warning("No directed route in this study snapshot.")
    with st.expander("Audit anchor positions and score components"):
        st.dataframe(anchors, hide_index=True, width="stretch")
        st.dataframe(ranking, hide_index=True, width="stretch")
    st.download_button("Ranking CSV", ranking.to_csv(index=False), "bottleneck_ranking.csv")

# Experiment inputs are rendered before resilience/evidence outputs so all tabs
# describe the same selected interventions in this rerun.
a = b = None
selected = []
with lab_tab:
    st.subheader("Upgrade a corridor or test a new connection")
    st.caption(
        "Both alternatives use one baseline and one demand matrix. Costs are arbitrary "
        "assumed units; no construction feasibility or financial BCR is claimed."
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### A / Existing infrastructure")
        ranked_edges = [(int(r.u), int(r.v), int(r.key)) for r in ranking.itertuples()]
        seed_edge = next(
            (e for e in ranked_edges if graph.edges[e]["speed_kph"] < 100), ranked_edges[0]
        )
        default_edges = route_corridor(graph, pairs, seed_edge)
        all_edges = list(dict.fromkeys(ranked_edges + sorted(graph.edges(keys=True))))
        # Reset selections when a different dataset is chosen, preserving road picks otherwise.
        if st.session_state.get("edge_source") != source:
            st.session_state["upgrade_edges"] = default_edges
            st.session_state["edge_source"] = source

        def edge_label(e):
            d = graph.edges[e]
            return f"{d.get('name', d.get('ref', 'Unnamed road'))} · {e[0]} → {e[1]} [{e[2]}]"

        selected = st.multiselect(
            "Connected directed treatment segments",
            all_edges,
            key="upgrade_edges",
            max_selections=30,
            format_func=edge_label,
        )
        both_directions = st.checkbox("Include matching reverse segments", value=False)
        if both_directions:
            selected = reciprocal_edges(graph, selected)
        st.caption(
            f"{len(selected)} segments · "
            f"{sum(graph.edges[e]['length'] for e in selected) / 1000:.3f} directed km. "
            "Default is a route window around a ranked link, not an inferred engineering design."
        )
        intervention_type = st.selectbox(
            "Treatment model", ["Modeled speed improvement", "Reduce assumed junction delay"]
        )
        factor = st.slider("Speed multiplier", 1.05, 2.0, 1.4, 0.05)
        cap = st.slider("Operating-speed cap (km/h)", 10, 100, 100, 5)
        delay_reduction = st.slider("Junction-delay reduction fraction", 0.1, 1.0, 0.5, 0.1)
        cost_a = st.number_input("A · assumed total cost units", min_value=1.0, value=100.0)
    with col_b:
        st.markdown("#### B / Hypothetical new connection")
        conservative = st.checkbox("Conservative endpoint / crossing screen", value=source == REAL)
        st.caption(
            "Excludes controlled-access/ramp/bridge/tunnel endpoints and schematic lines "
            "crossing roads without modeled junctions. Land rights and barriers remain unchecked."
        )
        budget = st.slider("Candidate evaluation budget", 4, 40, 16, 4)
        speed_b = st.slider("New-link uncongested modeled speed (km/h)", 5, 80, 40, 5)
        circuity = st.slider("Length / straight-line distance", 1.0, 2.0, 1.2, 0.05)
        two_way = st.checkbox("Two-way proposed connection", value=True)
        cost_rate = st.number_input(
            "B · assumed cost units per modeled km", min_value=1.0, value=500.0
        )
        with st.spinner("Evaluating eligible connections against the same OD demand…"):
            candidates = search_cached(
                graph,
                fingerprint,
                pairs,
                conservative,
                budget,
                speed_b,
                circuity,
                cost_rate,
                two_way,
            )
        if candidates.empty:
            st.warning(
                "No eligible candidates under this screen. Review bounds/data; no link is invented."
            )
            chosen = None
        else:
            candidate_index = st.selectbox(
                "Evaluated connection",
                list(range(len(candidates))),
                format_func=lambda i: (
                    f"{int(candidates.iloc[i].u)} ↔ {int(candidates.iloc[i].v)} · "
                    f"{candidates.iloc[i].weighted_savings_seconds:.1f} weighted seconds saved"
                ),
            )
            chosen = candidates.iloc[candidate_index]
            st.caption(
                f"{len(candidates)} proposals evaluated. Selected alignment: "
                f"{chosen.modeled_length_m:.0f} m · "
                f"assumed total {chosen.assumed_cost_units:.1f} units."
            )
    try:
        a = (
            upgrade(graph, selected, factor, cap, cost_a)
            if intervention_type == "Modeled speed improvement"
            else reduce_junction_delay(graph, selected, delay_reduction, cost_a)
        )
        if chosen is not None:
            b = add_connection(
                graph,
                int(chosen.u),
                int(chosen.v),
                speed_b,
                circuity,
                two_way,
                float(chosen.assumed_cost_units),
            )
            signature = json.dumps(
                [a.details, a.assumed_cost, b.details, b.assumed_cost], sort_keys=True
            )
            with st.spinner("Comparing travel time and topological redundancy…"):
                summary, detail = compare_cached(graph, fingerprint, pairs, a, b, signature)
            columns = st.columns(2)
            for column, item, (_, row) in zip(columns, (a, b), summary.iterrows(), strict=True):
                with column:
                    st.metric(
                        item.name + " · weighted min saved",
                        f"{row.common_od_weighted_savings_seconds / 60:.2f}",
                        f"{row.common_od_savings_pct:.2f}% of common reachable OD time",
                    )
                    st.caption(
                        f"Improved pairs: {int(row.improved_od_pairs)} · "
                        f"Seconds per assumed cost unit: {row.benefit_seconds_per_cost_unit:.3f}"
                    )
                    st.plotly_chart(
                        network_map(
                            item.graph, selected=selected if item is a else None, anchors=anchors
                        ),
                        width="stretch",
                        key=item.name,
                    )
            chart = go.Figure(
                go.Bar(
                    x=summary.scenario,
                    y=summary.common_od_weighted_savings_seconds,
                    marker_color=["#f49b50", "#27cfb1"],
                )
            )
            chart.update_layout(
                height=250,
                yaxis_title="Demand-weighted modeled seconds saved",
                margin={"t": 10, "b": 10},
            )
            st.plotly_chart(chart, width="stretch")
            with st.expander("Candidate evaluation and complete scenario metrics"):
                st.dataframe(candidates, hide_index=True, width="stretch")
                st.dataframe(summary, hide_index=True, width="stretch")
            d1, d2, d3 = st.columns(3)
            d1.download_button("Summary CSV", summary.to_csv(index=False), "scenario_summary.csv")
            d2.download_button(
                "OD results CSV", detail.to_csv(index=False), "scenario_od_results.csv"
            )
            manifest = {
                "version": "0.2.0",
                "source": source,
                "graph_sha256": fingerprint,
                "operating_model": operating,
                "demand_hypothesis": (
                    "uploaded matrix; provenance unverified"
                    if uploaded_od is not None
                    else demand_profile
                    if od_mode == "Named area anchors"
                    else f"uniform sampled pairs, seed {seed}"
                ),
                "od": [asdict(p) for p in pairs],
                "ranking_weights": asdict(weights),
                "a": {**a.details, "cost": a.assumed_cost},
                "b": {**b.details, "cost": b.assumed_cost},
            }
            d3.download_button(
                "Assumptions JSON", json.dumps(manifest, indent=2), "assumptions.json"
            )
    except ValueError as exc:
        a = b = None
        st.warning(str(exc))

with resilience_tab:
    st.subheader("What happens when a corridor fails?")
    if selected:
        closure_edges = reciprocal_edges(graph, selected)
        closure, closure_od = closure_impact(graph, pairs, closure_edges)
        r1, r2, r3 = st.columns(3)
        r1.metric("Closed directed segments", closure["closed_directed_edges"])
        r2.metric("OD pairs losing connectivity", closure["lost_od_pairs"])
        r3.metric(
            "Finite weighted detour (min)",
            f"{closure['common_od_weighted_detour_seconds'] / 60:.2f}",
        )
        st.caption(
            "Includes matching reverse arcs with the same endpoints and way identity. "
            "Separate carriageways or shared bridge failure zones are not inferred."
        )
        st.download_button("Closure OD CSV", closure_od.to_csv(index=False), "closure_od.csv")
    if a is not None and b is not None:
        if st.button("Measure usable alternate routes"):
            with st.spinner("Testing primary-route-disjoint alternatives within 1.5× route time…"):
                alternatives = pd.DataFrame(
                    {
                        "Baseline": practical_alternatives(graph, pairs),
                        "A": practical_alternatives(a.graph, pairs),
                        "B": practical_alternatives(b.graph, pairs),
                    }
                ).T
            st.dataframe(alternatives, width="stretch")
        st.caption(
            "This removes the chosen primary route's directed arcs. It is a route-specific "
            "diagnostic, not proof of physically independent corridors."
        )
        if st.button("Run 27 assumption sensitivity cases"):
            if (
                uploaded_od is not None
                or od_mode != "Named area anchors"
                or intervention_type != "Modeled speed improvement"
                or speed_b != 40
                or circuity != 1.2
                or not two_way
            ):
                st.warning(
                    "The 27-case experiment uses named anchors, speed treatment, "
                    "and a two-way link at 40 km/h, circuity 1.2. Restore those inputs first."
                )
            else:
                with st.spinner(
                    "Holding interventions fixed across demand, operating and cost hypotheses…"
                ):
                    uncertainty = sensitivity_matrix(
                        original,
                        anchors,
                        selected,
                        (int(chosen.u), int(chosen.v)),
                        cost_a,
                        b.assumed_cost,
                        factor,
                        cap,
                    )
                st.dataframe(uncertainty, hide_index=True, width="stretch")
                st.download_button(
                    "Sensitivity CSV", uncertainty.to_csv(index=False), "sensitivity.csv"
                )
    if source == REAL:
        with st.expander("Routes near the study boundary"):
            st.dataframe(
                route_boundary_exposure(graph, pairs, NH48.bbox), hide_index=True, width="stretch"
            )
        st.caption(
            "Boundary exposure is a warning flag. Compare expanded/contracted study graphs "
            "before treating a shortlist as stable."
        )

with evidence_tab:
    st.subheader("Evidence, assumptions and validation")
    st.markdown("""
**Road data:** a cached OpenStreetMap extract in real mode. Mapped one-way directions,
parallel edges, road geometry and signal tags are retained. Conditional access and OSM turn
restriction relations are not enforced. Speeds are tagged limits or explicit class defaults.

**Ranking:** connectivity importance is ½ normalized time-weighted betweenness + ½ assumed OD
route-usage share. Directed closure detour and lost reachable demand form the other
components.
Default score weights are 40/35/25. Exact centrality through 300 nodes; otherwise 96 sampled
sources.
Candidates are screened by both centrality and OD usage; the shortlist is not exhaustive.

**Connection search:** farthest-point geographic sampling; explicit distance and geometry
gates;
then evaluate every shortlisted proposal using the same demand. Order prioritizes newly
reachable
demand and then seconds per assumed cost unit. Results describe the evaluated set, not a
global optimum.

**Travel time:** metres × 3.6 / modeled km/h + explicit modeled signal delay. Busy/severe
modes
are hypotheses, not observed peak traffic. Newly added links receive the same operating-speed
factor.
Speed improvement does not model additional capacity, queue discharge or induced demand.

**Comparison:** savings only on pairs reachable in both graphs. Newly reachable and lost trips
are
reported separately. No infinite savings. Cost units are arbitrary assumptions, not financial
estimates.

**Validation status:** route observations and construction feasibility have not been
validated.
An independent routing-engine comparison, where supplied, checks routing plausibility only;
it is not observed traffic. Official releases motivate this case study but do not validate its
outputs.
""")
    if source == REAL:
        metadata = json.loads((ROOT / "data/nh48_airport/provenance.json").read_text())
        st.json(metadata, expanded=False)
        for url in NH48.sources:
            st.markdown(f"[Official case-study context]({url})")
        check_path = ROOT / "results/osrm_checks/routing_comparison.csv"
        if check_path.exists() and check_path.stat().st_size > 1:
            with st.expander("Independent routing-model checks (not traffic observations)"):
                st.dataframe(pd.read_csv(check_path), hide_index=True, width="stretch")
    observed = st.file_uploader(
        "Validate timestamped route observations CSV", type="csv", key="observed"
    )
    st.caption(
        "Required: origin,destination,observed_seconds,observed_at,source. "
        "Include timezone-aware timestamps and independently collected, sourced observations."
    )
    if observed is not None:
        try:
            validation, observations = validate_observations(graph, pd.read_csv(observed))
            st.json(validation)
            st.dataframe(observations, hide_index=True, width="stretch")
        except (ValueError, KeyError, TypeError) as exc:
            st.error(str(exc))
    st.download_button(
        "Current OD CSV",
        pd.DataFrame([asdict(p) for p in pairs]).to_csv(index=False),
        "od_demand.csv",
    )
    st.download_button("Anchor locations CSV", anchors.to_csv(index=False), "anchors.csv")
    st.caption("© OpenStreetMap contributors · ODbL 1.0 · https://www.openstreetmap.org/copyright")
    st.code(f"Computational graph SHA256: {fingerprint}")

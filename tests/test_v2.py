"""Independent invariants and hand-solvable checks for v0.2 methods."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from highwaynet.analysis import ODPair, od_times, rank_bottlenecks
from highwaynet.data import graph_fingerprint, validate_graph
from highwaynet.demand import demo_anchors, named_demand, snap_anchors
from highwaynet.experiments import sensitivity_matrix
from highwaynet.operating import operating_model, reduce_junction_delay
from highwaynet.planning import (
    conservative_node,
    evaluate_connections,
    screen_connections,
    spatial_nodes,
)
from highwaynet.resilience import (
    closure_impact,
    practical_alternatives,
    reciprocal_edges,
    route_corridor,
)
from highwaynet.scenarios import add_connection, compare, upgrade
from highwaynet.snapshot import fetch_snapshot, import_osm, load_snapshot, query_for
from highwaynet.studies import NH48, Anchor, StudyArea
from highwaynet.validation import route_boundary_exposure, validate_observations


def test_spatial_sampling_is_coordinate_driven(demo):
    selected = spatial_nodes(demo, 5)
    mapping = {n: 1000 - 7 * n for n in demo}
    relabeled = nx.relabel_nodes(demo, mapping)
    assert [mapping[n] for n in selected] == spatial_nodes(relabeled, 5)
    assert len(set(selected)) == 5


def test_candidate_totals_match_comparison(demo):
    pairs = named_demand(demo, demo_anchors(demo))
    screen = screen_connections(demo, limit=4)
    table = evaluate_connections(demo, pairs, screen, cost_per_km=500)
    assert len(table) == len(screen)
    for row in table.itertuples():
        item = add_connection(demo, int(row.u), int(row.v), assumed_cost=row.assumed_cost_units)
        summary, _ = compare(demo, pairs, [item])
        assert row.weighted_savings_seconds == pytest.approx(
            summary.iloc[0].common_od_weighted_savings_seconds
        )
        assert row.assumed_cost_units == pytest.approx(row.modeled_length_m / 1000 * 500)
    assert graph_fingerprint(demo) == graph_fingerprint(demo.copy())


def test_conservative_endpoint_gate(demo):
    assert conservative_node(demo, 0)
    for field, value in [
        ("highway", "motorway"),
        ("highway", "primary_link"),
        ("bridge", "yes"),
        ("tunnel", "yes"),
    ]:
        modified = demo.copy()
        modified.edges[0, 1, 0][field] = value
        assert not conservative_node(modified, 0)


def test_conservative_crossing_gate(demo):
    table = screen_connections(demo, limit=50, conservative=True)
    from shapely.geometry import LineString

    from highwaynet.planning import road_geometry

    for r in table.itertuples():
        a, b = demo.nodes[r.u], demo.nodes[r.v]
        line = LineString([(a["x"], a["y"]), (b["x"], b["y"])])
        assert not any(line.crosses(g) for g in road_geometry(demo))


def test_hybrid_screen_includes_demanded_link(directed):
    table = rank_bottlenecks(directed, [ODPair(0, 2, 100)], candidate_limit=2)
    demanded = table.query("u == 0 and v == 2")
    assert len(demanded) == 1
    assert demanded.iloc[0].od_usage_share == 1
    assert demanded.iloc[0].importance_normalized == pytest.approx(
        (demanded.iloc[0].betweenness_normalized + 1) / 2
    )


def test_closure_lost_and_finite_detour_separated(directed):
    summary, detail = closure_impact(directed, [ODPair(0, 3, 2), ODPair(0, 1)], [(0, 1, 0)])
    assert summary["lost_od_pairs"] == 1
    assert summary["lost_baseline_reachable_demand_share"] == pytest.approx(1 / 3)
    assert summary["common_od_weighted_detour_seconds"] == 40
    assert np.isnan(detail.iloc[1].detour_seconds)


def test_practical_alternative_stretch(directed):
    pairs = [ODPair(0, 3)]
    assert (
        practical_alternatives(directed, pairs, 1.5)["bounded_primary_route_disjoint_demand_share"]
        == 0
    )
    assert (
        practical_alternatives(directed, pairs, 2)["bounded_primary_route_disjoint_demand_share"]
        == 1
    )
    with pytest.raises(ValueError):
        practical_alternatives(directed, pairs, 0.9)


def test_route_corridor_is_connected_and_bounded(demo):
    pairs = named_demand(demo, demo_anchors(demo))
    edges = route_corridor(demo, pairs, (5, 12, 0), target_length_m=1000, maximum_edges=4)
    assert (5, 12, 0) in edges
    assert len(edges) <= 4
    corridor = nx.Graph()
    corridor.add_edges_from((u, v) for u, v, _ in edges)
    assert nx.is_connected(corridor)
    assert reciprocal_edges(demo, [(5, 12, 0)]) == [(5, 12, 0), (12, 5, 0)]


def test_operating_models_are_idempotent_and_delay_is_separate(directed):
    directed.nodes[1]["highway"] = "traffic_signals"
    busy = operating_model(directed, "Assumed busy period")
    assert busy.edges[0, 1, 0]["speed_kph"] == 27
    assert busy.edges[0, 1, 0]["modeled_delay_s"] == 20
    assert busy.edges[0, 1, 0]["travel_time"] == pytest.approx(100 * 3.6 / 27 + 20)
    assert graph_fingerprint(busy) == graph_fingerprint(
        operating_model(busy, "Assumed busy period")
    )
    a = upgrade(busy, [(0, 1, 0)], 2)
    assert a.graph.edges[0, 1, 0]["modeled_delay_s"] == 20
    treatment = reduce_junction_delay(busy, [(0, 1, 0)], 0.5)
    assert treatment.graph.edges[0, 1, 0]["speed_kph"] == 27
    assert treatment.graph.edges[0, 1, 0]["modeled_delay_s"] == 10
    assert directed.edges[0, 1, 0]["travel_time"] == 10
    with pytest.raises(ValueError, match="before interventions"):
        operating_model(treatment.graph, "Uncongested model")
    validate_graph(treatment.graph)


def test_new_links_receive_same_operating_assumptions(demo):
    demo.nodes[9]["highway"] = "traffic_signals"
    busy = operating_model(demo, "Assumed busy period")
    b = add_connection(busy, 2, 9, speed_kph=40)
    assert b.graph.edges[2, 9, 0]["speed_kph"] == 30
    assert b.graph.edges[2, 9, 0]["modeled_delay_s"] == 20
    assert b.graph.edges[9, 2, 0]["modeled_delay_s"] == 0
    validate_graph(b.graph)


def test_demand_hypotheses_and_cost_sensitivity(demo):
    anchors = demo_anchors(demo)
    assert len(named_demand(demo, anchors)) == 30
    assert named_demand(demo, anchors) != named_demand(demo, anchors, "residential_outbound")
    table = sensitivity_matrix(demo, anchors, [(5, 12, 0)], (2, 9))
    assert len(table) == 27
    assert set(table.b_cost_multiplier) == {0.5, 1, 2}
    for _, group in table.groupby(["operating_model", "demand_hypothesis"]):
        assert group.b_weighted_savings_seconds.nunique() == 1
        assert group.a_weighted_savings_seconds.nunique() == 1
        ratios = group.set_index("b_cost_multiplier").b_seconds_per_cost_unit
        assert ratios.loc[0.5] == pytest.approx(ratios.loc[1] * 2)


def test_anchor_policy_avoids_dead_end(demo):
    study = StudyArea(
        "fixture",
        "test",
        (77.1, 28.73, 77.14, 28.76),
        (Anchor("one area", demo.nodes[17]["x"], demo.nodes[17]["y"]),),
        (),
    )
    anchors = snap_anchors(demo, study)
    node = int(anchors.iloc[0].node)
    assert len(set(demo.predecessors(node)) | set(demo.successors(node))) >= 3
    assert node != 17
    modified = demo.copy()
    modified.add_edge(17, 17, length=10, speed_kph=36, travel_time=1)
    assert int(snap_anchors(modified, study).iloc[0].node) != 17
    assert anchors.iloc[0].snap_distance_m <= 500
    with pytest.raises(ValueError):
        snap_anchors(demo, study, maximum_m=1)


def test_timestamped_observation_math(directed):
    obs = pd.DataFrame(
        [
            {
                "origin": 0,
                "destination": 3,
                "observed_seconds": 25,
                "observed_at": "2026-10-22T09:00:00+05:30",
                "source": "authored test fixture",
            },
            {
                "origin": 3,
                "destination": 0,
                "observed_seconds": 50,
                "observed_at": "2026-10-22T09:00:00+05:30",
                "source": "authored test fixture",
            },
        ]
    )
    summary, details = validate_observations(directed, obs)
    assert summary["mae_seconds"] == 5
    assert summary["mape_percent"] == 20
    assert summary["unreachable_observations"] == 1
    assert np.isnan(details.iloc[1].modeled_seconds)
    obs.loc[0, "observed_at"] = "2026-10-22 09:00"
    with pytest.raises(ValueError, match="timezone"):
        validate_observations(directed, obs)


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_observation_bad_durations(directed, duration):
    obs = pd.DataFrame(
        [
            {
                "origin": 0,
                "destination": 3,
                "observed_seconds": duration,
                "observed_at": "2026-10-22T00:00:00Z",
                "source": "test",
            }
        ]
    )
    with pytest.raises(ValueError):
        validate_observations(directed, obs)


OSM_FIXTURE = """<osm version="0.6" generator="authored unit-test fixture">
<node id="1" lat="28.530" lon="77.120"/><node id="2" lat="28.530" lon="77.121"/>
<node id="3" lat="28.530" lon="77.122"/><node id="4" lat="28.531" lon="77.121"/>
<node id="5" lat="28.529" lon="77.121"/>
<way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/>
<tag k="oneway" v="yes"/><tag k="maxspeed" v="30"/></way>
<way id="11"><nd ref="2"/><nd ref="4"/><tag k="highway" v="residential"/></way>
<way id="12"><nd ref="2"/><nd ref="5"/><tag k="highway" v="footway"/></way>
</osm>"""


def test_xml_import_direction_access_and_provenance(tmp_path):
    path = tmp_path / "source.osm"
    path.write_text(OSM_FIXTURE)
    graph = import_osm(path, NH48, tmp_path / "snapshot")
    assert graph.has_edge(1, 2) and not graph.has_edge(2, 1)
    assert graph.has_edge(2, 4) and graph.has_edge(4, 2)
    assert 5 not in graph
    assert graph_fingerprint(load_snapshot(tmp_path / "snapshot")) == graph_fingerprint(graph)
    (tmp_path / "snapshot" / "roads.osm").write_text("corrupted")
    with pytest.raises(ValueError, match="raw-data fingerprint"):
        load_snapshot(tmp_path / "snapshot")


@pytest.mark.parametrize(
    "xml",
    [
        "<!DOCTYPE osm><osm/>",
        "<wrong/>",
        "<osm><remark>timeout</remark></osm>",
        '<osm><way id="1"><nd ref="99"/><tag k="highway" v="primary"/></way></osm>',
    ],
)
def test_reject_invalid_xml(tmp_path, xml):
    path = tmp_path / "bad.osm"
    path.write_text(xml)
    with pytest.raises(ValueError):
        import_osm(path, NH48, tmp_path / "target")


def test_fetch_uses_only_identified_osm_endpoint(tmp_path, monkeypatch):
    from highwaynet import snapshot

    calls = []

    class Response:
        content = OSM_FIXTURE.encode()
        status_code = 200

        def raise_for_status(self):
            return None

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(snapshot.requests, "get", get)
    fetch_snapshot(NH48, tmp_path)
    assert len(calls) == 1
    assert calls[0][0] == "https://overpass-api.de/api/interpreter"
    assert calls[0][1]["params"]["data"] == query_for(NH48)
    assert "8.8.8.8" not in calls[0][0]
    metadata = json.loads((tmp_path / "request.json").read_text())
    assert metadata["http_status"] == 200


def test_bundled_real_snapshot_is_valid_and_anchor_routes_are_reachable():
    root = Path(__file__).resolve().parents[1]
    graph = load_snapshot(root / "data/nh48_airport")
    assert graph.graph["source"] == "OpenStreetMap"
    assert len(graph) > 1000 and graph.number_of_edges() > 2000
    anchors = snap_anchors(graph, NH48)
    pairs = named_demand(graph, anchors)
    assert len(pairs) == 20 and np.isfinite(od_times(graph, pairs)).all()
    boundary = route_boundary_exposure(graph, pairs, NH48.bbox)
    assert len(boundary) == 20
    assert (anchors.snap_distance_m <= 500).all()


def test_v2_synthetic_case_export(tmp_path, capsys):
    from highwaynet.case_study import run_case_study

    manifest = run_case_study("synthetic", tmp_path, 4)
    assert manifest["real_roads"] is False
    assert manifest["traffic_observations"] is False
    assert len(pd.read_csv(tmp_path / "sensitivity_27_cases.csv")) == 27
    assert (tmp_path / "network.geojson").exists()
    assert len(pd.read_csv(tmp_path / "scenario_summary.csv")) == 2


def test_osm_tile_merger_versions_and_cache(tmp_path, monkeypatch):
    from highwaynet import snapshot

    calls = []

    class Response:
        def __init__(self, version):
            self.url = "https://api.openstreetmap.org/api/0.6/map?bbox=bounded-test"
            xml = OSM_FIXTURE.replace('<way id="10">', f'<way id="10" version="{version}">')
            self.content = xml.replace('v="30"', f'v="{30 + version}"').encode()

        def raise_for_status(self):
            return None

    def get(url, **kwargs):
        calls.append(url)
        return Response(len(calls))

    monkeypatch.setattr(snapshot.requests, "get", get)
    graph = snapshot.fetch_osm_api_tiles(NH48, tmp_path)
    assert calls == ["https://api.openstreetmap.org/api/0.6/map"] * 4
    assert graph.edges[1, 2, 0]["speed_kph"] == 34
    assert graph_fingerprint(snapshot.fetch_osm_api_tiles(NH48, tmp_path)) == graph_fingerprint(
        graph
    )
    assert len(calls) == 4
    (tmp_path / "provenance.json").unlink()
    graph = snapshot.fetch_osm_api_tiles(NH48, tmp_path)
    assert graph.edges[1, 2, 0]["speed_kph"] == 34 and len(calls) == 4
    (tmp_path / "provenance.json").unlink()
    (tmp_path / "raw_tiles/0_0.osm").write_text("corrupt")
    with pytest.raises(ValueError):
        snapshot.fetch_osm_api_tiles(NH48, tmp_path)


def test_fingerprint_includes_candidate_and_delay_inputs(demo):
    original = graph_fingerprint(demo)
    for field, value in [("highway", "motorway"), ("bridge", "yes"), ("name", "another road")]:
        modified = demo.copy()
        modified.edges[0, 1, 0][field] = value
        assert graph_fingerprint(modified) != original
    modified = demo.copy()
    modified.nodes[1]["highway"] = "traffic_signals"
    assert graph_fingerprint(modified) != original

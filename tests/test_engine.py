import math

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from highwaynet.analysis import (
    ODPair,
    RankingWeights,
    od_times,
    rank_bottlenecks,
    ranking_sensitivity,
    redundancy,
    route_edges,
    sample_od,
)
from highwaynet.data import (
    graph_fingerprint,
    modeled_speed,
    synthetic_graph,
    validate_graph,
    weight_graph,
)
from highwaynet.maps import edge_frame, network_map
from highwaynet.scenarios import (
    Intervention,
    add_connection,
    compare,
    eligible_connections,
    upgrade,
)


def test_demo_connectivity_direction_and_reproducibility(demo):
    assert len(demo) == 18
    assert demo.number_of_edges() == 53
    assert nx.is_strongly_connected(demo)
    assert demo.has_edge(0, 4) and not demo.has_edge(4, 0)
    assert graph_fingerprint(demo) == graph_fingerprint(synthetic_graph())
    assert graph_fingerprint(demo) != graph_fingerprint(synthetic_graph(4))


@pytest.mark.parametrize(
    "tag,kind,speed",
    [
        ("30 mph", "residential", 48.28032),
        ("50;30", "primary", 30),
        (["50", "40"], "primary", 40),
        (None, "residential", 25),
        ("signals", "primary", 50),
        ("30 @ (school)", "service", 20),
        ("nan", "unknown", 25),
        ("0", "unknown", 25),
    ],
)
def test_speed_assumptions(tag, kind, speed):
    assert modeled_speed(tag, kind)[0] == pytest.approx(speed)


def test_units_and_validation(directed):
    graph = directed.copy()
    graph.edges[0, 1, 0]["maxspeed"] = "36"
    graph.edges[0, 1, 0]["highway"] = "primary"
    weighted = weight_graph(graph)
    assert weighted.edges[0, 1, 0]["travel_time"] == 10
    assert directed.edges[0, 1, 0]["travel_time"] == 10
    validate_graph(directed)
    for invalid in [0, -1, float("nan"), float("inf")]:
        broken = directed.copy()
        broken.edges[0, 1, 0]["travel_time"] = invalid
        with pytest.raises(ValueError):
            validate_graph(broken)


def test_shortest_path_oneway_and_parallel(directed):
    assert od_times(directed, [ODPair(0, 3), ODPair(3, 0)]).tolist() == [20, np.inf]
    directed.add_edge(0, 1, key=5, length=50, speed_kph=36, travel_time=5)
    assert od_times(directed, [ODPair(0, 3)])[0] == 15
    assert route_edges(directed, 0, 3) == [(0, 1, 5), (1, 3, 0)]


def test_upgrade_exact_savings_and_nonmutation(directed):
    a = upgrade(directed, [(0, 1, 0)], 2, 80, 10)
    summary, details = compare(directed, [ODPair(0, 3, 3)], [a])
    assert directed.edges[0, 1, 0]["travel_time"] == 10
    assert a.graph.edges[0, 1, 0]["travel_time"] == 5
    assert summary.iloc[0].common_od_weighted_savings_seconds == 15
    assert summary.iloc[0].common_od_savings_pct == 25
    assert summary.iloc[0].benefit_seconds_per_cost_unit == 1.5
    assert details.iloc[0].savings_seconds == 5


def test_corridor_upgrade_scope(demo):
    a = upgrade(demo, [(5, 12, 0), (12, 5, 0)])
    assert a.graph.edges[5, 12, 0]["travel_time"] < demo.edges[5, 12, 0]["travel_time"]
    assert a.graph.edges[12, 5, 0]["travel_time"] < demo.edges[12, 5, 0]["travel_time"]
    b = upgrade(demo, [(5, 12, 0)])
    assert b.graph.edges[12, 5, 0] == demo.edges[12, 5, 0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"speed_factor": 1},
        {"speed_factor": 2.1},
        {"speed_factor": float("nan")},
        {"max_speed_kph": 10},
        {"assumed_cost": 0},
        {"assumed_cost": float("inf")},
    ],
)
def test_upgrade_constraints(directed, kwargs):
    with pytest.raises(ValueError):
        upgrade(directed, [(0, 1, 0)], **kwargs)


def test_new_connection_units_direction_and_nonmutation(demo):
    b = add_connection(demo, 2, 9, 40, 1.2, bidirectional=False)
    assert not demo.has_edge(2, 9)
    assert b.graph.has_edge(2, 9) and not b.graph.has_edge(9, 2)
    assert b.graph.edges[2, 9, 0]["travel_time"] == pytest.approx(
        b.graph.edges[2, 9, 0]["length"] * 3.6 / 40
    )
    two = add_connection(demo, 2, 9)
    assert two.graph.has_edge(9, 2)
    validate_graph(two.graph)


@pytest.mark.parametrize(
    "u,v,kwargs",
    [
        (0, 0, {}),
        (0, 1, {}),
        (0, 999, {}),
        (2, 9, {"speed_kph": 100}),
        (2, 9, {"circuity": 0.9}),
        (2, 9, {"max_length_m": 50}),
        (2, 9, {"assumed_cost": -1}),
        (2, 9, {"speed_kph": float("nan")}),
    ],
)
def test_connection_constraints(demo, u, v, kwargs):
    with pytest.raises(ValueError):
        add_connection(demo, u, v, **kwargs)


def test_fixed_baseline_comparison_and_reachability(directed):
    pair = [ODPair(0, 3), ODPair(3, 0), ODPair(4, 0)]
    graph = directed.copy()
    graph.add_edge(3, 0, length=100, speed_kph=36, travel_time=10)
    added = Intervention(graph, "connect", 100, {})
    summary, detail = compare(directed, pair, [added])
    assert summary.iloc[0].common_od_weighted_savings_seconds == 0
    assert summary.iloc[0].newly_reachable_od_pairs == 1
    assert summary.iloc[0].lost_od_pairs == 0
    assert detail.status.tolist() == ["common", "newly_reachable", "unreachable"]
    assert math.isnan(detail.iloc[1].savings_seconds)
    removed = directed.copy()
    removed.remove_edges_from(list(removed.out_edges(0, keys=True)))
    summary, detail = compare(directed, pair, [Intervention(removed, "loss", 1, {})])
    assert summary.iloc[0].lost_od_pairs == 1
    assert summary.iloc[0].common_od_weighted_savings_seconds == 0
    assert detail.iloc[0].status == "lost"


def test_redundancy_hand_solvable(directed):
    pairs = [ODPair(0, 3, 3), ODPair(3, 0, 1)]
    assert redundancy(directed, pairs) == {
        "reachable_demand_share": 0.75,
        "two_edge_disjoint_demand_share": 0.75,
    }
    directed.remove_edge(0, 2, 0)
    assert redundancy(directed, pairs)["two_edge_disjoint_demand_share"] == 0


def test_ranking_formula_closure_and_determinism(directed):
    pairs = [ODPair(0, 3)]
    weights = RankingWeights(0.4, 0.35, 0.25)
    table = rank_bottlenecks(directed, pairs, weights, candidate_limit=99)
    row = table[(table.u == 0) & (table.v == 1)].iloc[0]
    # Removing 0→1 doubles shortest time 20→40: increase=1, component=.5.
    assert row.detour_component == 0.5
    assert row.disconnect_component == 0
    assert row.score == pytest.approx(0.4 * row.importance_normalized + 0.35 * 0.5)
    pd.testing.assert_frame_equal(table, rank_bottlenecks(directed, pairs, weights, 99))
    disconnect = rank_bottlenecks(directed, [ODPair(0, 1)], candidate_limit=99)
    assert disconnect.query("u == 0 and v == 1").iloc[0].disconnect_component == 1
    assert table.score.between(0, 1).all()
    with pytest.raises(ValueError):
        RankingWeights(0, 0, 0).normalized()


def test_reweight_sensitivity_and_sample_reproducibility(demo):
    pairs = sample_od(demo)
    assert pairs == sample_od(demo)
    assert pairs != sample_od(demo, seed=3)
    assert len(set((p.origin, p.destination) for p in pairs)) == len(pairs)
    assert all(p.origin != p.destination for p in sample_od(demo, 999))
    sensitivity = ranking_sensitivity(demo, pairs, 10)
    assert set(sensitivity.weights) == {"balanced", "detour", "connectivity", "centrality"}
    assert (sensitivity.groupby("weights")["rank"].min() == 1).all()


@pytest.mark.parametrize(
    "pairs",
    [
        [],
        [ODPair(0, 0)],
        [ODPair(0, 999)],
        [ODPair(0, 3, -1)],
        [ODPair(0, 3, float("nan"))],
        [ODPair(0, 3), ODPair(0, 3)],
    ],
)
def test_bad_od(directed, pairs):
    with pytest.raises(ValueError):
        od_times(directed, pairs)


def test_map_and_connection_screen(demo):
    choices = eligible_connections(demo)
    assert choices
    assert all(not demo.has_edge(u, v) and not demo.has_edge(v, u) for u, v, _ in choices)
    assert all(100 <= length <= 1500 for _, _, length in choices)
    assert edge_frame(demo).crs.to_epsg() == 4326
    fig = network_map(demo, rank_bottlenecks(demo, sample_od(demo), candidate_limit=10))
    assert len(fig.data) >= 3


def test_osm_cache_roundtrip(tmp_path, demo, monkeypatch):
    import osmnx as ox

    from highwaynet.data import load_osm

    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return demo

    monkeypatch.setattr(ox, "graph_from_bbox", fake_fetch)
    first = load_osm(tmp_path)
    second = load_osm(tmp_path)
    assert len(calls) == 1
    assert calls[0][1]["network_type"] == "drive"
    assert calls[0][1]["retain_all"]
    assert graph_fingerprint(first) == graph_fingerprint(second)
    # Corrupt provenance is detected rather than silently used.
    path = tmp_path / "delhi_rohini.provenance.json"
    import json

    metadata = json.loads(path.read_text())
    metadata["sha256"] = "corrupt"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="fingerprint"):
        load_osm(tmp_path)


def test_sampled_centrality_large_graph_is_reproducible():
    graph = nx.cycle_graph(310, create_using=nx.MultiDiGraph)
    graph.graph["crs"] = "EPSG:4326"
    for n in graph:
        graph.nodes[n].update(x=77 + n * 0.00001, y=28.74)
    for _, _, d in graph.edges(data=True):
        d.update(length=100.0, speed_kph=36.0, travel_time=10.0)
    pairs = sample_od(graph, count=5)
    first = rank_bottlenecks(graph, pairs, candidate_limit=2)
    second = rank_bottlenecks(graph, pairs, candidate_limit=2)
    assert (first.centrality_sample_nodes == 96).all()
    pd.testing.assert_frame_equal(first, second)


def test_disconnected_upgrade_rejected(demo):
    with pytest.raises(ValueError, match="connected corridor"):
        upgrade(demo, [(0, 1, 0), (16, 17, 0)])


def test_cli_benchmark_exports_verified_outputs(tmp_path, capsys):
    from highwaynet.cli import benchmark

    result = benchmark("synthetic", tmp_path, 10, 10, repeats=1)
    summary = pd.read_csv(tmp_path / "summary.csv")
    details = pd.read_csv(tmp_path / "od_results.csv")
    assert len(summary) == 2 and len(details) == 20
    assert result["graph_sha256"] == graph_fingerprint(synthetic_graph())
    assert result["synthetic"] is True
    assert result["runtime_runs"][0]["ranking_seconds"] > 0
    assert (tmp_path / "manifest.json").exists()
    for scenario, subset in details.groupby("scenario"):
        total = (subset.demand_weight * subset.savings_seconds).sum()
        assert summary.loc[summary.scenario == scenario, "common_od_weighted_savings_seconds"].iloc[
            0
        ] == pytest.approx(total)


def test_bundled_offline_artifacts_match_generator(demo):
    """Verify the files actually shipped, beyond the in-memory generator."""
    from pathlib import Path

    import osmnx as ox

    root = Path(__file__).resolve().parents[1]
    bundled = ox.load_graphml(root / "data/synthetic_demo.graphml")
    validate_graph(bundled)
    assert graph_fingerprint(bundled) == graph_fingerprint(demo)
    pd.testing.assert_frame_equal(
        pd.read_csv(root / "data/synthetic_od.csv"),
        pd.DataFrame(
            [
                {"origin": p.origin, "destination": p.destination, "weight": p.weight}
                for p in sample_od(demo)
            ]
        ),
    )

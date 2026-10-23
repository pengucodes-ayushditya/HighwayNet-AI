"""Demand-aware screening, conservative geometric gates and bounded candidate search."""

from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString

from highwaynet.analysis import ODPair, od_times, route_edges
from highwaynet.data import distance_m
from highwaynet.scenarios import add_connection


def spatial_nodes(graph: nx.MultiDiGraph, count: int = 80) -> list[int]:
    """Farthest-point spatial sampling in local metric coordinates."""
    if count < 2:
        raise ValueError("Spatial sample must contain at least two nodes")
    nodes = sorted(graph, key=lambda n: (graph.nodes[n]["x"], graph.nodes[n]["y"], n))
    if len(nodes) <= count:
        return nodes
    coords = np.array([[graph.nodes[n]["x"], graph.nodes[n]["y"]] for n in nodes], dtype=float)
    coords[:, 0] *= math.cos(math.radians(float(coords[:, 1].mean())))
    coords *= 111_000
    chosen = [0]
    squared = np.sum((coords - coords[0]) ** 2, axis=1)
    for _ in range(min(count, len(nodes)) - 1):
        squared[chosen] = -1
        index = int(np.argmax(squared))
        chosen.append(index)
        squared = np.minimum(squared, np.sum((coords - coords[index]) ** 2, axis=1))
    return [nodes[i] for i in chosen]


def _values(value: object) -> set[str]:
    return {str(v) for v in value} if isinstance(value, list) else {str(value)}


def road_geometry(graph: nx.MultiDiGraph) -> list[LineString]:
    return [
        d.get("geometry")
        or LineString(
            [
                (graph.nodes[u]["x"], graph.nodes[u]["y"]),
                (graph.nodes[v]["x"], graph.nodes[v]["y"]),
            ]
        )
        for u, v, d in graph.edges(data=True)
    ]


def conservative_node(graph: nx.MultiDiGraph, node: int) -> bool:
    """Exclude endpoints involving controlled-access roads, ramps, bridges or tunnels.

    This intentionally conservative gate is not construction-feasibility validation.
    """
    edges = list(graph.in_edges(node, data=True)) + list(graph.out_edges(node, data=True))
    for _, _, d in edges:
        if _values(d.get("highway")) & {"motorway", "motorway_link", "trunk", "trunk_link"}:
            return False
        if any(str(c).endswith("_link") for c in _values(d.get("highway"))):
            return False
        if _values(d.get("bridge", "no")) - {"no", "None", "False"}:
            return False
        if _values(d.get("tunnel", "no")) - {"no", "None", "False"}:
            return False
    return bool(edges)


def screen_connections(
    graph: nx.MultiDiGraph,
    min_length_m: float = 100,
    max_length_m: float = 1500,
    sample_nodes: int = 80,
    limit: int = 40,
    conservative: bool = False,
) -> pd.DataFrame:
    """Rank geometric proposals by existing-network distance / straight-line distance.

    Candidate budget is explicit. Crossings without modeled junctions are rejected
    in conservative mode. Land use, barriers and rights-of-way are still unknown.
    """
    if not 0 < min_length_m <= max_length_m or limit < 1:
        raise ValueError("Invalid candidate bounds or budget")
    selected = spatial_nodes(graph, sample_nodes)
    if conservative:
        selected = [n for n in selected if conservative_node(graph, n)]
    geometries = road_geometry(graph)
    tree = STRtree(geometries) if conservative else None
    rows = []
    distance_cache = {}
    for index, u in enumerate(selected):
        for v in selected[index + 1 :]:
            if graph.has_edge(u, v) or graph.has_edge(v, u):
                continue
            a, b = graph.nodes[u], graph.nodes[v]
            length = distance_m((a["x"], a["y"]), (b["x"], b["y"]))
            if not min_length_m <= length <= max_length_m:
                continue
            line = LineString([(a["x"], a["y"]), (b["x"], b["y"])])
            if tree is not None and len(tree.query(line, predicate="crosses")):
                continue
            # Bidirectional comparison uses the worse current direction, while
            # unreachable pairs are screened as a distinct connectivity category.
            for n in (u, v):
                if n not in distance_cache:
                    distance_cache[n] = nx.single_source_dijkstra_path_length(
                        graph, n, weight="length"
                    )
            forward = distance_cache[u].get(v, np.inf)
            backward = distance_cache[v].get(u, np.inf)
            disconnected = not (np.isfinite(forward) and np.isfinite(backward))
            finite = [x for x in (forward, backward) if np.isfinite(x)]
            detour = max(finite) / length if finite else 0.0
            rows.append(
                {
                    "u": u,
                    "v": v,
                    "straight_length_m": length,
                    "existing_detour_ratio": detour,
                    "connects_disconnected_direction": disconnected,
                    "conservative_geometry_screen": conservative,
                }
            )
    columns = [
        "u",
        "v",
        "straight_length_m",
        "existing_detour_ratio",
        "connects_disconnected_direction",
        "conservative_geometry_screen",
    ]
    table = pd.DataFrame(rows, columns=columns)
    if table.empty:
        return table
    return (
        table.sort_values(
            [
                "connects_disconnected_direction",
                "existing_detour_ratio",
                "straight_length_m",
                "u",
                "v",
            ],
            ascending=[False, False, True, True, True],
        )
        .head(limit)
        .reset_index(drop=True)
    )


def evaluate_connections(
    graph: nx.MultiDiGraph,
    pairs: list[ODPair],
    screened: pd.DataFrame,
    speed_kph: float = 40,
    circuity: float = 1.2,
    cost_per_km: float = 500,
    bidirectional: bool = True,
) -> pd.DataFrame:
    """Evaluate every screened candidate against one fixed baseline and demand matrix.

    Cost is arbitrary total units/km of schematic alignment, not a rupee estimate.
    Redundancy is deliberately deferred to the final selected-scenario comparison.
    """
    if not math.isfinite(cost_per_km) or cost_per_km <= 0:
        raise ValueError("Assumed cost units/km must be finite and positive")
    base = od_times(graph, pairs)
    demand = np.array([p.weight for p in pairs])
    rows = []
    for candidate in screened.itertuples():
        cost = candidate.straight_length_m * circuity / 1000 * cost_per_km
        item = add_connection(
            graph, int(candidate.u), int(candidate.v), speed_kph, circuity, bidirectional, cost
        )
        times = od_times(item.graph, pairs)
        common = np.isfinite(base) & np.isfinite(times)
        savings = float(np.dot(demand[common], base[common] - times[common]))
        rows.append(
            {
                "u": candidate.u,
                "v": candidate.v,
                "straight_length_m": candidate.straight_length_m,
                "modeled_length_m": candidate.straight_length_m * circuity,
                "existing_detour_ratio": candidate.existing_detour_ratio,
                "assumed_cost_units": cost,
                "weighted_savings_seconds": savings,
                "benefit_seconds_per_cost_unit": savings / cost,
                "improved_od_pairs": int(np.count_nonzero(times[common] < base[common] - 1e-7)),
                "newly_reachable_demand_weight": float(
                    demand[~np.isfinite(base) & np.isfinite(times)].sum()
                ),
                "newly_reachable_od_pairs": int(
                    np.count_nonzero(~np.isfinite(base) & np.isfinite(times))
                ),
                "conservative_geometry_screen": candidate.conservative_geometry_screen,
            }
        )
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(
            [
                "newly_reachable_demand_weight",
                "benefit_seconds_per_cost_unit",
                "weighted_savings_seconds",
                "u",
                "v",
            ],
            ascending=[False, False, False, True, True],
        )
        .reset_index(drop=True)
    )


def od_usage(graph: nx.MultiDiGraph, pairs: list[ODPair]) -> dict[tuple[int, int, int], float]:
    """Share of assumed OD demand using one deterministically selected shortest route.

    This is all-or-nothing modeled assignment with no congestion feedback.
    """
    od_times(graph, pairs)  # validate input and retain unreachable pairs in denominator
    total = sum(p.weight for p in pairs)
    usage = dict.fromkeys(graph.edges(keys=True), 0.0)
    for pair in pairs:
        try:
            for edge in route_edges(graph, pair.origin, pair.destination):
                usage[edge] += pair.weight / total
        except nx.NetworkXNoPath:
            continue
    return usage

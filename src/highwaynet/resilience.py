"""Corridor disruption and practically bounded alternate-route measurements."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from highwaynet.analysis import Edge, ODPair, od_times, route_edges


def reciprocal_edges(graph: nx.MultiDiGraph, selected: list[Edge]) -> list[Edge]:
    """Include reverse arcs with the same endpoints and OSM IDs (or fictional road name).

    Separate-carriageway node sequences are not inferred to share a failure zone.
    """
    output = set(selected)
    for u, v, k in selected:
        if not graph.has_edge(u, v, k):
            raise ValueError("Selected edge does not exist")
        original = graph.edges[u, v, k]
        for reverse_key, reverse in graph.get_edge_data(v, u, default={}).items():
            if original.get("osmid", original.get("name")) == reverse.get(
                "osmid", reverse.get("name")
            ):
                output.add((v, u, reverse_key))
    return sorted(output)


def closure_impact(
    graph: nx.MultiDiGraph, pairs: list[ODPair], edges: list[Edge]
) -> tuple[dict, pd.DataFrame]:
    if not edges or any(not graph.has_edge(*e) for e in edges):
        raise ValueError("Select existing directed closure edges")
    changed = graph.copy()
    changed.remove_edges_from(edges)
    base, times = od_times(graph, pairs), od_times(changed, pairs)
    demand = np.array([p.weight for p in pairs])
    common = np.isfinite(base) & np.isfinite(times)
    lost = np.isfinite(base) & ~np.isfinite(times)
    detours = np.full(len(pairs), np.nan)
    detours[common] = times[common] - base[common]
    reachable_demand = demand[np.isfinite(base)].sum()
    summary = {
        "closed_directed_edges": len(set(edges)),
        "lost_od_pairs": int(lost.sum()),
        "lost_baseline_reachable_demand_share": float(demand[lost].sum() / reachable_demand)
        if reachable_demand
        else 0.0,
        "common_od_weighted_detour_seconds": float(np.dot(demand[common], detours[common])),
        "affected_od_pairs": int(np.count_nonzero(lost | (detours > 1e-7))),
    }
    detail = pd.DataFrame(
        {
            "origin": [p.origin for p in pairs],
            "destination": [p.destination for p in pairs],
            "weight": demand,
            "detour_seconds": detours,
            "lost_connectivity": lost,
        }
    )
    return summary, detail


def practical_alternatives(
    graph: nx.MultiDiGraph, pairs: list[ODPair], max_stretch: float = 1.5
) -> dict:
    """Demand with a primary-route arc-disjoint alternative within a time bound.

    Removes the chosen shortest route's directed arcs. This is a conservative
    primary-route-specific diagnostic, not an exhaustive disjoint-pair optimizer.
    """
    if not np.isfinite(max_stretch) or max_stretch < 1:
        raise ValueError("Alternative-route stretch must be finite and >=1")
    base = od_times(graph, pairs)
    total = sum(p.weight for p in pairs)
    has_alternative = within_bound = 0.0
    for pair, seconds in zip(pairs, base, strict=True):
        if not np.isfinite(seconds):
            continue
        modified = graph.copy()
        modified.remove_edges_from(route_edges(graph, pair.origin, pair.destination))
        try:
            alternative = nx.shortest_path_length(
                modified, pair.origin, pair.destination, weight="travel_time"
            )
            has_alternative += pair.weight
            if alternative <= seconds * max_stretch + 1e-7:
                within_bound += pair.weight
        except nx.NetworkXNoPath:
            continue
    return {
        "primary_route_disjoint_demand_share": has_alternative / total,
        "bounded_primary_route_disjoint_demand_share": within_bound / total,
        "max_time_stretch": max_stretch,
    }


def route_corridor(
    graph: nx.MultiDiGraph,
    pairs: list[ODPair],
    seed: Edge,
    target_length_m: float = 1000,
    maximum_edges: int = 30,
) -> list[Edge]:
    """A contiguous window on an assumed-demand shortest route around a seed link.

    This is an explicitly selected treatment corridor, not a claim that every
    segment has the same road name or supports the same engineering treatment.
    """
    if not graph.has_edge(*seed) or target_length_m <= 0 or maximum_edges < 1:
        raise ValueError("Invalid corridor seed or bounds")
    routes = []
    for pair in pairs:
        try:
            route = route_edges(graph, pair.origin, pair.destination)
            if seed in route:
                routes.append((pair.weight, pair.origin, pair.destination, route))
        except nx.NetworkXNoPath:
            continue
    if not routes:
        return [seed]
    routes.sort(key=lambda r: (-r[0], r[1], r[2]))
    route = routes[0][3]
    start = end = route.index(seed)
    length = graph.edges[seed]["length"]
    while length < target_length_m and end - start + 1 < maximum_edges:
        if start == 0 and end == len(route) - 1:
            break
        # Extend the shorter next segment first; ties extend toward origin.
        left = graph.edges[route[start - 1]]["length"] if start else float("inf")
        right = graph.edges[route[end + 1]]["length"] if end < len(route) - 1 else float("inf")
        if left <= right:
            start -= 1
            length += left
        else:
            end += 1
            length += right
    return route[start : end + 1]

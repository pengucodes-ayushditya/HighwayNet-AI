"""Deterministic OD evaluation and transparent directed-link ranking."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import networkx as nx
import numpy as np
import pandas as pd

Edge = tuple[int, int, int]


@dataclass(frozen=True)
class ODPair:
    origin: int
    destination: int
    weight: float = 1.0


def validate_od(graph: nx.MultiDiGraph, pairs: list[ODPair]) -> None:
    if not pairs:
        raise ValueError("At least one OD pair is required")
    seen = set()
    for pair in pairs:
        if pair.origin not in graph or pair.destination not in graph:
            raise ValueError("OD endpoint missing from graph")
        if pair.origin == pair.destination or (pair.origin, pair.destination) in seen:
            raise ValueError("OD pairs must be distinct and non-self")
        if not math.isfinite(pair.weight) or pair.weight <= 0:
            raise ValueError("OD weight must be finite and positive")
        seen.add((pair.origin, pair.destination))


def sample_od(graph: nx.MultiDiGraph, count: int = 60, seed: int = 42) -> list[ODPair]:
    """Uniform synthetic OD weights over deterministic sampled ordered node pairs."""
    nodes = sorted(graph.nodes)
    total = len(nodes) * (len(nodes) - 1)
    if count < 1:
        raise ValueError("OD count must be positive")
    rng = np.random.default_rng(seed)
    indices = rng.choice(total, size=min(count, total), replace=False)
    result = []
    for index in indices:
        oi, di = divmod(int(index), len(nodes) - 1)
        if di >= oi:
            di += 1
        result.append(ODPair(nodes[oi], nodes[di]))
    return result


def od_times(graph: nx.MultiDiGraph, pairs: list[ODPair]) -> np.ndarray:
    validate_od(graph, pairs)
    distances = {
        origin: nx.single_source_dijkstra_path_length(graph, origin, weight="travel_time")
        for origin in sorted({p.origin for p in pairs})
    }
    return np.array([distances[p.origin].get(p.destination, np.inf) for p in pairs])


def route_edges(graph: nx.MultiDiGraph, origin: int, destination: int) -> list[Edge]:
    path = nx.shortest_path(graph, origin, destination, weight="travel_time")
    return [
        (u, v, min(graph[u][v], key=lambda k: (graph[u][v][k]["travel_time"], k)))
        for u, v in zip(path[:-1], path[1:], strict=True)
    ]


def redundancy(graph: nx.MultiDiGraph, pairs: list[ODPair]) -> dict[str, float]:
    """Demand share with >=2 directed edge-disjoint routes (not physical-corridor disjoint).

    Parallel arcs count as separate edges. Opposite arcs are separate infrastructure
    directions. This is a topological upper bound, not independent failure resilience.
    """
    validate_od(graph, pairs)
    capacity = nx.DiGraph()
    capacity.add_nodes_from(graph)
    for u, v in graph.edges():
        if u != v:
            if capacity.has_edge(u, v):
                capacity[u][v]["capacity"] += 1
            else:
                capacity.add_edge(u, v, capacity=1)
    total = sum(p.weight for p in pairs)
    redundant = reachable = 0.0
    for pair in pairs:
        flow = nx.algorithms.flow.edmonds_karp(
            capacity, pair.origin, pair.destination, capacity="capacity", cutoff=2
        ).graph["flow_value"]
        reachable += pair.weight * (flow >= 1)
        redundant += pair.weight * (flow >= 2)
    return {
        "reachable_demand_share": reachable / total,
        "two_edge_disjoint_demand_share": redundant / total,
    }


@dataclass(frozen=True)
class RankingWeights:
    betweenness: float = 0.40
    detour: float = 0.35
    disconnect: float = 0.25

    def normalized(self) -> np.ndarray:
        values = np.array(list(asdict(self).values()), dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values < 0) or values.sum() <= 0:
            raise ValueError("Ranking weights must be nonnegative with positive sum")
        return values / values.sum()


def rank_bottlenecks(
    graph: nx.MultiDiGraph,
    pairs: list[ODPair],
    weights: RankingWeights | None = None,
    candidate_limit: int = 40,
    seed: int = 42,
) -> pd.DataFrame:
    """Screen by time-weighted betweenness, then simulate directed edge closures.

    Detour: weighted increase/base, capped at 2 per reachable OD pair, with
    disconnected OD contributing zero here and counted in a separate loss term.
    Betweenness is divided by its graph-wide maximum. Scores are relative indices.
    """
    validate_od(graph, pairs)
    coefficients = (weights or RankingWeights()).normalized()
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be positive")
    k = None if len(graph) <= 300 else min(96, len(graph))
    centrality = nx.edge_betweenness_centrality(
        graph, k=k, normalized=True, weight="travel_time", seed=seed
    )
    maximum = max(centrality.values(), default=0.0) or 1.0
    from highwaynet.planning import od_usage

    usage = od_usage(graph, pairs)
    by_centrality = sorted(centrality, key=lambda edge: (-centrality[edge], edge))
    by_demand = sorted(usage, key=lambda edge: (-usage[edge], edge))
    # Interleave structural and OD importance so neither screen monopolizes the budget.
    candidates = []
    for first, second in zip(by_centrality, by_demand, strict=True):
        for edge in (first, second):
            if edge not in candidates and len(candidates) < candidate_limit:
                candidates.append(edge)
        if len(candidates) >= min(candidate_limit, len(centrality)):
            break
    base = od_times(graph, pairs)
    demand = np.array([p.weight for p in pairs])
    reachable = np.isfinite(base)
    reachable_weight = demand[reachable].sum()
    rows = []
    for edge in candidates:
        modified = graph.copy()
        modified.remove_edge(*edge)
        times = od_times(modified, pairs)
        lost = reachable & ~np.isfinite(times)
        common = reachable & np.isfinite(times)
        increases = np.zeros(len(pairs))
        increases[common] = np.maximum(0, times[common] - base[common]) / base[common]
        detour = float(
            np.dot(demand, np.minimum(increases, 2)) / reachable_weight if reachable_weight else 0
        )
        loss = float(demand[lost].sum() / reachable_weight if reachable_weight else 0)
        importance = (centrality[edge] / maximum + usage[edge]) / 2
        attrs = graph.edges[edge]
        rows.append(
            {
                "u": edge[0],
                "v": edge[1],
                "key": edge[2],
                "name": str(attrs.get("name", "Unnamed road")),
                "length_m": attrs["length"],
                "travel_time_s": attrs["travel_time"],
                "betweenness": centrality[edge],
                "betweenness_normalized": centrality[edge] / maximum,
                "od_usage_share": usage[edge],
                "importance_normalized": importance,
                "detour_component": detour / 2,
                "disconnect_component": loss,
                "affected_od_pairs": int(np.count_nonzero(lost | (increases > 1e-9))),
                "score": float(np.dot(coefficients, [importance, detour / 2, loss])),
                "screened_candidates": len(candidates),
                "graph_edges": graph.number_of_edges(),
                "centrality_sample_nodes": k or len(graph),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["score", "u", "v", "key"], ascending=[False, True, True, True])
        .reset_index(drop=True)
    )


def ranking_sensitivity(
    graph: nx.MultiDiGraph, pairs: list[ODPair], limit: int = 40
) -> pd.DataFrame:
    """Reweight identical measured components; closures are not recomputed."""
    table = rank_bottlenecks(graph, pairs, candidate_limit=limit)
    output = []
    for name, weights in {
        "balanced": RankingWeights(),
        "connectivity": RankingWeights(0.2, 0.2, 0.6),
        "detour": RankingWeights(0.2, 0.6, 0.2),
        "centrality": RankingWeights(0.7, 0.2, 0.1),
    }.items():
        values = table[["importance_normalized", "detour_component", "disconnect_component"]]
        ranked = table.assign(score=values.to_numpy() @ weights.normalized()).sort_values(
            ["score", "u", "v", "key"], ascending=[False, True, True, True]
        )
        for rank, row in enumerate(ranked.itertuples(), 1):
            output.append(
                {
                    "weights": name,
                    "rank": rank,
                    "u": row.u,
                    "v": row.v,
                    "key": row.key,
                    "score": row.score,
                }
            )
    return pd.DataFrame(output)

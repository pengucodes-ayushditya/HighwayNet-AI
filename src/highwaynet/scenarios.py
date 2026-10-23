"""Non-mutating interventions and comparable fixed-demand evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from highwaynet.analysis import Edge, ODPair, od_times, redundancy
from highwaynet.data import distance_m, validate_graph


def positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass
class Intervention:
    graph: nx.MultiDiGraph
    name: str
    assumed_cost: float
    details: dict


def upgrade(
    graph: nx.MultiDiGraph,
    edges: list[Edge],
    speed_factor: float = 1.4,
    max_speed_kph: float = 80.0,
    assumed_cost: float = 100.0,
) -> Intervention:
    """Upgrade selected directed arcs; reverse arcs require explicit selection."""
    positive(assumed_cost, "Assumed cost")
    if not math.isfinite(speed_factor) or not 1 < speed_factor <= 2:
        raise ValueError("Speed factor must be >1 and <=2")
    if not math.isfinite(max_speed_kph) or not 5 <= max_speed_kph <= 100:
        raise ValueError("Speed cap must be between 5 and 100 km/h")
    if not edges or len(set(edges)) != len(edges):
        raise ValueError("Select distinct directed edges")
    corridor = nx.Graph()
    corridor.add_edges_from((u, v) for u, v, _ in edges)
    if not nx.is_connected(corridor):
        raise ValueError("Selected edges must form one connected corridor")
    changed = graph.copy()
    for edge in edges:
        if not graph.has_edge(*edge):
            raise ValueError(f"Missing edge {edge}")
        attrs = changed.edges[edge]
        speed = min(attrs["speed_kph"] * speed_factor, max_speed_kph)
        if speed <= attrs["speed_kph"]:
            raise ValueError("Speed cap must exceed every selected baseline speed")
        attrs.update(
            speed_kph=speed,
            travel_time=attrs["length"] * 3.6 / speed + attrs.get("modeled_delay_s", 0),
            speed_source="hypothetical upgrade assumption",
            intervention="upgrade",
        )
    validate_graph(changed)
    return Intervention(
        changed,
        "A · Upgrade",
        assumed_cost,
        {"edges": edges, "speed_factor": speed_factor, "max_speed_kph": max_speed_kph},
    )


def eligible_connections(
    graph: nx.MultiDiGraph,
    min_length_m: float = 100,
    max_length_m: float = 1500,
    limit: int = 100,
) -> list[tuple[int, int, float]]:
    """Compatibility wrapper for spatially screened, network-detour-ranked pairs."""
    from highwaynet.planning import screen_connections

    table = screen_connections(graph, min_length_m, max_length_m, limit=limit)
    return [(int(r.u), int(r.v), float(r.straight_length_m)) for r in table.itertuples()]


def add_connection(
    graph: nx.MultiDiGraph,
    u: int,
    v: int,
    speed_kph: float = 40,
    circuity: float = 1.2,
    bidirectional: bool = True,
    assumed_cost: float = 300,
    min_length_m: float = 100,
    max_length_m: float = 1500,
) -> Intervention:
    positive(assumed_cost, "Assumed cost")
    if u not in graph or v not in graph or u == v:
        raise ValueError("Choose two distinct existing nodes")
    if graph.has_edge(u, v) or graph.has_edge(v, u):
        raise ValueError("Nodes already have a direct connection")
    if not math.isfinite(speed_kph) or not 5 <= speed_kph <= 80:
        raise ValueError("New-road speed must be between 5 and 80 km/h")
    if not math.isfinite(circuity) or not 1 <= circuity <= 2:
        raise ValueError("Circuity must be between 1 and 2")
    a = (graph.nodes[u]["x"], graph.nodes[u]["y"])
    b = (graph.nodes[v]["x"], graph.nodes[v]["y"])
    direct = distance_m(a, b)
    if not min_length_m <= direct <= max_length_m:
        raise ValueError("Connection outside allowed geodesic distance bounds")
    changed = graph.copy()
    length = direct * circuity
    factor = float(graph.graph.get("operating_speed_factor", 1.0))
    effective_speed = speed_kph * factor
    for start, end in [(u, v), (v, u)] if bidirectional else [(u, v)]:
        changed.add_edge(
            start,
            end,
            length=length,
            speed_kph=effective_speed,
            free_speed_kph=speed_kph,
            modeled_delay_s=(
                float(graph.graph.get("signal_delay_s", 0))
                if changed.nodes[end].get("highway") == "traffic_signals"
                else 0.0
            ),
            travel_time=(
                length * 3.6 / effective_speed
                + (
                    float(graph.graph.get("signal_delay_s", 0))
                    if changed.nodes[end].get("highway") == "traffic_signals"
                    else 0.0
                )
            ),
            highway="hypothetical",
            name="Hypothetical connection",
            oneway=not bidirectional,
            speed_source="user hypothetical assumption",
            intervention="new",
            geometry=LineString([a, b] if start == u else [b, a]),
        )
    validate_graph(changed)
    return Intervention(
        changed,
        "B · New connection",
        assumed_cost,
        {
            "u": u,
            "v": v,
            "speed_kph": speed_kph,
            "circuity": circuity,
            "bidirectional": bidirectional,
            "modeled_length_m": length,
        },
    )


def compare(
    baseline: nx.MultiDiGraph,
    pairs: list[ODPair],
    interventions: list[Intervention],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Finite common-OD savings; new reachability is reported separately, never monetized."""
    base = od_times(baseline, pairs)
    demand = np.array([p.weight for p in pairs])
    base_reachable = np.isfinite(base)
    base_total = float(np.dot(demand[base_reachable], base[base_reachable]))
    baseline_redundancy = redundancy(baseline, pairs)
    summaries, detail = [], []
    for item in interventions:
        positive(item.assumed_cost, "Assumed cost")
        times = od_times(item.graph, pairs)
        common = base_reachable & np.isfinite(times)
        saved = np.full(len(pairs), np.nan)
        saved[common] = base[common] - times[common]
        aggregate = float(np.dot(demand[common], saved[common]))
        common_base = float(np.dot(demand[common], base[common]))
        red = redundancy(item.graph, pairs)
        summaries.append(
            {
                "scenario": item.name,
                "assumed_cost_units": item.assumed_cost,
                "baseline_weighted_seconds_reachable": base_total,
                "common_od_weighted_savings_seconds": aggregate,
                "common_od_savings_pct": 100 * aggregate / common_base if common_base else 0.0,
                "benefit_seconds_per_cost_unit": aggregate / item.assumed_cost,
                "affected_od_pairs": int(np.count_nonzero(common & (np.abs(saved) > 1e-7))),
                "improved_od_pairs": int(np.count_nonzero(common & (saved > 1e-7))),
                "newly_reachable_od_pairs": int(
                    np.count_nonzero(~base_reachable & np.isfinite(times))
                ),
                "lost_od_pairs": int(np.count_nonzero(base_reachable & ~np.isfinite(times))),
                "baseline_reachable_demand_share": baseline_redundancy["reachable_demand_share"],
                "reachable_demand_share": red["reachable_demand_share"],
                "baseline_two_edge_disjoint_demand_share": baseline_redundancy[
                    "two_edge_disjoint_demand_share"
                ],
                "two_edge_disjoint_demand_share": red["two_edge_disjoint_demand_share"],
            }
        )
        for index, pair in enumerate(pairs):
            detail.append(
                {
                    "scenario": item.name,
                    "origin": pair.origin,
                    "destination": pair.destination,
                    "demand_weight": pair.weight,
                    "baseline_seconds": base[index] if base_reachable[index] else None,
                    "scenario_seconds": times[index] if np.isfinite(times[index]) else None,
                    "savings_seconds": saved[index] if common[index] else None,
                    "status": "common"
                    if common[index]
                    else "newly_reachable"
                    if np.isfinite(times[index])
                    else "lost"
                    if base_reachable[index]
                    else "unreachable",
                }
            )
    return pd.DataFrame(summaries), pd.DataFrame(detail)

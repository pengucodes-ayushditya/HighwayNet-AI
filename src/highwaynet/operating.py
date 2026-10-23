"""Explicit operating-speed and signal-delay hypotheses; no claimed observations."""

from __future__ import annotations

import math

import networkx as nx

from highwaynet.analysis import Edge
from highwaynet.data import validate_graph
from highwaynet.scenarios import Intervention, positive

MODELS = {
    "Uncongested model": (1.0, 0.0),
    "Assumed busy period": (0.75, 20.0),
    "Assumed severe delay": (0.50, 40.0),
}


def operating_model(graph: nx.MultiDiGraph, name: str) -> nx.MultiDiGraph:
    if name not in MODELS:
        raise ValueError("Unknown operating model")
    if any(d.get("intervention") for _, _, d in graph.edges(data=True)):
        raise ValueError("Apply operating assumptions before interventions")
    factor, delay = MODELS[name]
    result = graph.copy()
    for _, v, _, d in result.edges(keys=True, data=True):
        # Reapplying a model is idempotent, rather than compounding speed reductions.
        free_speed = d.get("free_speed_kph", d["speed_kph"])
        d["free_speed_kph"] = free_speed
        d["speed_kph"] = free_speed * factor
        signals = result.nodes[v].get("highway")
        is_signal = signals == "traffic_signals" or (
            isinstance(signals, list) and "traffic_signals" in signals
        )
        d["modeled_delay_s"] = delay if is_signal else 0.0
        d["travel_time"] = d["length"] * 3.6 / d["speed_kph"] + d["modeled_delay_s"]
        d["operating_assumption"] = name
    result.graph.update(operating_model=name, operating_speed_factor=factor, signal_delay_s=delay)
    validate_graph(result)
    return result


def reduce_junction_delay(
    graph: nx.MultiDiGraph,
    edges: list[Edge],
    reduction_fraction: float = 0.5,
    assumed_cost: float = 100,
) -> Intervention:
    positive(assumed_cost, "Assumed cost")
    if not math.isfinite(reduction_fraction) or not 0 < reduction_fraction <= 1:
        raise ValueError("Delay reduction must be >0 and <=1")
    if not edges or len(set(edges)) != len(edges) or any(not graph.has_edge(*e) for e in edges):
        raise ValueError("Select distinct existing edges")
    corridor = nx.Graph()
    corridor.add_edges_from((u, v) for u, v, _ in edges)
    if not nx.is_connected(corridor):
        raise ValueError("Selected delay treatment must form a connected set")
    if not any(graph.edges[e].get("modeled_delay_s", 0) > 0 for e in edges):
        raise ValueError("Selected edges have no modeled junction delay to reduce")
    changed = graph.copy()
    for edge in edges:
        d = changed.edges[edge]
        d["modeled_delay_s"] = d.get("modeled_delay_s", 0) * (1 - reduction_fraction)
        d["travel_time"] = d["length"] * 3.6 / d["speed_kph"] + d["modeled_delay_s"]
        d["intervention"] = "delay_reduction"
    validate_graph(changed)
    return Intervention(
        changed,
        "A · Junction-delay treatment",
        assumed_cost,
        {
            "edges": edges,
            "reduction_fraction": reduction_fraction,
            "model": "assumed delay reduction, not a capacity increase",
        },
    )

"""Fixed-intervention sensitivity over explicit operating, demand and cost hypotheses."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from highwaynet.analysis import Edge, od_times
from highwaynet.demand import named_demand
from highwaynet.operating import MODELS, operating_model
from highwaynet.scenarios import add_connection, upgrade


def sensitivity_matrix(
    graph: nx.MultiDiGraph,
    anchors: pd.DataFrame,
    upgrade_edges: list[Edge],
    new_endpoints: tuple[int, int],
    cost_a: float = 100,
    cost_b: float = 300,
    speed_factor: float = 1.4,
    cap_kph: float = 100,
) -> pd.DataFrame:
    """27 cases: 3 operating models × 3 demand hypotheses × 3 B/A cost ratios.

    Endpoints and treated edges are fixed across cases, avoiding re-optimization
    leakage. Route topology, signal tags and OD locations are held constant.
    """
    rows = []
    for operating in MODELS:
        baseline = operating_model(graph, operating)
        a = upgrade(baseline, upgrade_edges, speed_factor, cap_kph, cost_a)
        b = add_connection(baseline, *new_endpoints, assumed_cost=cost_b)
        for demand_name in ("balanced", "residential_outbound", "residential_inbound"):
            pairs = named_demand(baseline, anchors, demand_name)
            base_times, a_times, b_times = (
                od_times(g, pairs) for g in (baseline, a.graph, b.graph)
            )
            weights = np.array([p.weight for p in pairs])
            common_a = np.isfinite(base_times) & np.isfinite(a_times)
            common_b = np.isfinite(base_times) & np.isfinite(b_times)
            savings_a = float(np.dot(weights[common_a], base_times[common_a] - a_times[common_a]))
            savings_b = float(np.dot(weights[common_b], base_times[common_b] - b_times[common_b]))
            for cost_multiplier_b in (0.5, 1.0, 2.0):
                ratio_a, ratio_b = savings_a / cost_a, savings_b / (cost_b * cost_multiplier_b)
                winner = (
                    "tie" if abs(ratio_a - ratio_b) <= 1e-8 else "A" if ratio_a > ratio_b else "B"
                )
                rows.append(
                    {
                        "operating_model": operating,
                        "demand_hypothesis": demand_name,
                        "b_cost_multiplier": cost_multiplier_b,
                        "a_assumed_cost_units": cost_a,
                        "b_assumed_cost_units": cost_b * cost_multiplier_b,
                        "a_weighted_savings_seconds": savings_a,
                        "b_weighted_savings_seconds": savings_b,
                        "a_seconds_per_cost_unit": ratio_a,
                        "b_seconds_per_cost_unit": ratio_b,
                        "higher_ratio_under_assumptions": winner,
                    }
                )
    return pd.DataFrame(rows)

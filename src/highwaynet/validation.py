"""Route observations and boundary diagnostics with explicit missing-evidence status."""

from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd

from highwaynet.analysis import ODPair, od_times, route_edges


def validate_observations(
    graph: nx.MultiDiGraph, observations: pd.DataFrame
) -> tuple[dict, pd.DataFrame]:
    """Compare route-level observations without manufacturing edge-level speeds.

    Required: origin,destination,observed_seconds,observed_at,source.
    Errors assess assumed shortest-route times, not a known traversed alignment.
    This is external validation only if the supplied observations are independent.
    """
    columns = {"origin", "destination", "observed_seconds", "observed_at", "source"}
    if not columns.issubset(observations) or observations.empty:
        raise ValueError(
            "Observation CSV needs origin,destination,observed_seconds,observed_at,source"
        )
    rows = []
    for r in observations.itertuples():
        if not float(r.origin).is_integer() or not float(r.destination).is_integer():
            raise ValueError("Observed route endpoints must be integer node IDs")
        pair = ODPair(int(r.origin), int(r.destination))
        observed = float(r.observed_seconds)
        if not math.isfinite(observed) or observed <= 0:
            raise ValueError("Observed durations must be positive and finite")
        timestamp = pd.Timestamp(r.observed_at)
        if (
            pd.isna(timestamp)
            or timestamp.tzinfo is None
            or not str(r.source).strip()
            or pd.isna(r.source)
        ):
            raise ValueError("Observation needs a timestamp with timezone and nonempty source")
        modeled = od_times(graph, [pair])[0]
        rows.append(
            {
                "origin": pair.origin,
                "destination": pair.destination,
                "observed_seconds": observed,
                "modeled_seconds": modeled if np.isfinite(modeled) else np.nan,
                "observed_at": timestamp.isoformat(),
                "source": str(r.source),
            }
        )
    details = pd.DataFrame(rows)
    reachable = details.modeled_seconds.notna()
    valid = details.loc[reachable].copy()
    errors = valid.modeled_seconds - valid.observed_seconds
    summary = {
        "observations": len(details),
        "modeled_reachable_observations": int(reachable.sum()),
        "unreachable_observations": int((~reachable).sum()),
        "mae_seconds": float(np.abs(errors).mean()) if len(valid) else None,
        "mape_percent": float((np.abs(errors) / valid.observed_seconds).mean() * 100)
        if len(valid)
        else None,
        "status": "user-supplied route evidence; independence and provenance require review",
    }
    details["error_seconds"] = details.modeled_seconds - details.observed_seconds
    return summary, details


def route_boundary_exposure(
    graph: nx.MultiDiGraph,
    pairs: list[ODPair],
    bbox: tuple[float, float, float, float],
    margin_m: float = 200,
) -> pd.DataFrame:
    """Flag routes approaching a study boundary; not a replacement for buffer comparisons."""
    w, s, e, n = bbox
    lon_scale = 111_000 * math.cos(math.radians((s + n) / 2))
    rows = []
    for pair in pairs:
        try:
            edges = route_edges(graph, pair.origin, pair.destination)
            nodes = {u for u, _, _ in edges} | {v for _, v, _ in edges}
            proximity = min(
                min(
                    (graph.nodes[v]["x"] - w) * lon_scale,
                    (e - graph.nodes[v]["x"]) * lon_scale,
                    (graph.nodes[v]["y"] - s) * 111_000,
                    (n - graph.nodes[v]["y"]) * 111_000,
                )
                for v in nodes
            )
            rows.append(
                {
                    "origin": pair.origin,
                    "destination": pair.destination,
                    "reachable": True,
                    "minimum_boundary_distance_m": proximity,
                    "near_boundary": proximity <= margin_m,
                }
            )
        except nx.NetworkXNoPath:
            rows.append(
                {
                    "origin": pair.origin,
                    "destination": pair.destination,
                    "reachable": False,
                    "minimum_boundary_distance_m": np.nan,
                    "near_boundary": False,
                }
            )
    return pd.DataFrame(rows)

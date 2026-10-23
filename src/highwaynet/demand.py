"""Named OD anchors and explicit non-observed demand hypotheses."""

from __future__ import annotations

import networkx as nx
import pandas as pd

from highwaynet.analysis import ODPair, validate_od
from highwaynet.data import distance_m
from highwaynet.studies import StudyArea


def snap_anchors(
    graph: nx.MultiDiGraph, study: StudyArea, maximum_m: float = 500, minimum_neighbors: int = 3
) -> pd.DataFrame:
    """Snap approximate area anchors to mapped road nodes and expose every offset.

    This does not verify a building entrance, legal access, or terminal gate.
    """
    if minimum_neighbors < 1:
        raise ValueError("Minimum anchor neighbors must be positive")
    rows = []
    used = set()
    for anchor in study.anchors:
        distances = [
            (distance_m((anchor.longitude, anchor.latitude), (d["x"], d["y"])), n)
            for n, d in graph.nodes(data=True)
            if len((set(graph.predecessors(n)) | set(graph.successors(n))) - {n})
            >= minimum_neighbors
            and graph.in_degree(n) > 0
            and graph.out_degree(n) > 0
        ]
        if not distances:
            raise ValueError("No road nodes satisfy the anchor-neighbor policy")
        offset, node = min(distances)
        if offset > maximum_m:
            raise ValueError(
                f"{anchor.name}: nearest road node is {offset:.0f} m away (limit {maximum_m:g})"
            )
        if node in used:
            raise ValueError("Two named anchors snap to the same node; review coordinates")
        used.add(node)
        rows.append(
            {
                "name": anchor.name,
                "node": node,
                "role": anchor.role,
                "anchor_lon": anchor.longitude,
                "anchor_lat": anchor.latitude,
                "node_lon": graph.nodes[node]["x"],
                "node_lat": graph.nodes[node]["y"],
                "snap_distance_m": offset,
                "coordinate_status": (
                    f"approximate area anchor; nearest >={minimum_neighbors}-neighbor road node; "
                    "access unverified"
                ),
            }
        )
    return pd.DataFrame(rows)


def demo_anchors(graph: nx.MultiDiGraph) -> pd.DataFrame:
    nodes = [0, 2, 5, 9, 12, 17]
    return pd.DataFrame(
        [
            {
                "name": f"Fictional area {n}",
                "node": n,
                "role": "residential" if n < 9 else "gateway",
                "node_lon": graph.nodes[n]["x"],
                "node_lat": graph.nodes[n]["y"],
                "snap_distance_m": 0.0,
                "coordinate_status": "fictional demo anchor",
            }
            for n in nodes
        ]
    )


def named_demand(
    graph: nx.MultiDiGraph, anchors: pd.DataFrame, profile: str = "balanced"
) -> list[ODPair]:
    """Assumed relative trip weights; no observed counts or calibrated OD estimation."""
    if profile not in {"balanced", "residential_outbound", "residential_inbound"}:
        raise ValueError("Unknown demand hypothesis")
    pairs = []
    for origin in anchors.itertuples():
        for destination in anchors.itertuples():
            if origin.node == destination.node:
                continue
            weight = 1.0
            if profile == "residential_outbound":
                weight = (2.0 if origin.role == "residential" else 1.0) * (
                    1.5 if destination.role == "gateway" else 1.0
                )
            elif profile == "residential_inbound":
                weight = (2.0 if destination.role == "residential" else 1.0) * (
                    1.5 if origin.role == "gateway" else 1.0
                )
            pairs.append(ODPair(int(origin.node), int(destination.node), weight))
    validate_od(graph, pairs)
    return pairs

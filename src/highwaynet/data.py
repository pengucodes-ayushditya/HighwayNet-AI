"""Directed datasets, auditable speed assumptions and cache provenance."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
from pyproj import Geod
from shapely.geometry import LineString

# West, south, east, north; ~3 km square around Rohini/DTU approach roads.
DELHI_BBOX = (77.100, 28.735, 77.130, 28.762)
SPEEDS_KPH = {
    "motorway": 70.0,
    "motorway_link": 40.0,
    "trunk": 60.0,
    "trunk_link": 35.0,
    "primary": 50.0,
    "primary_link": 30.0,
    "secondary": 40.0,
    "secondary_link": 30.0,
    "tertiary": 35.0,
    "tertiary_link": 25.0,
    "residential": 25.0,
    "living_street": 15.0,
    "service": 20.0,
    "unclassified": 25.0,
}
GEOD = Geod(ellps="WGS84")


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """WGS84 geodesic distance between (longitude, latitude) coordinates."""
    return float(GEOD.inv(*a, *b)[2])


def modeled_speed(maxspeed: object, highway: object) -> tuple[float, str]:
    """Use conservative minimum of parseable OSM limits, else explicit class default.

    A speed limit is a model input, never an observed operating speed.
    Conditional/ambiguous tags are deliberately not parsed.
    """
    tags = maxspeed if isinstance(maxspeed, list) else [maxspeed]
    values = []
    for tag in tags:
        for part in str(tag).split(";"):
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?\s*", part)
            if match:
                value = float(match[1]) * (1.609344 if match[2] == "mph" else 1)
                if 5 <= value <= 130:
                    values.append(value)
    if values:
        return min(values), "OSM maxspeed tag (modeled limit-based speed)"
    classes = highway if isinstance(highway, list) else [highway]
    return min(SPEEDS_KPH.get(str(c), 25.0) for c in classes), "assumed highway-class speed"


def weight_graph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Copy and assign positive travel time in seconds from metres and km/h."""
    result = graph.copy()
    for _, _, _, edge in result.edges(keys=True, data=True):
        speed, source = modeled_speed(edge.get("maxspeed"), edge.get("highway"))
        edge.update(speed_kph=speed, speed_source=source)
        edge["travel_time"] = float(edge["length"]) * 3.6 / speed + float(
            edge.get("modeled_delay_s", 0)
        )
    validate_graph(result)
    return result


def validate_graph(graph: nx.MultiDiGraph) -> None:
    if not isinstance(graph, nx.MultiDiGraph) or not graph.is_directed():
        raise ValueError("Expected a directed MultiDiGraph")
    if len(graph) < 2 or graph.number_of_edges() == 0:
        raise ValueError("Graph must contain at least two nodes and one edge")
    if str(graph.graph.get("crs")).lower() not in {"epsg:4326", "4326"}:
        raise ValueError("Graph coordinates must use EPSG:4326")
    for _, node in graph.nodes(data=True):
        if not (-180 <= float(node["x"]) <= 180 and -90 <= float(node["y"]) <= 90):
            raise ValueError("Invalid geographic coordinates")
    for _, _, _, edge in graph.edges(keys=True, data=True):
        for attr in ("length", "speed_kph", "travel_time"):
            if not math.isfinite(float(edge[attr])) or float(edge[attr]) <= 0:
                raise ValueError(f"Edge {attr} must be finite and positive")
        delay = float(edge.get("modeled_delay_s", 0))
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Modeled junction delay must be finite and nonnegative")
        expected = float(edge["length"]) * 3.6 / float(edge["speed_kph"]) + delay
        if not math.isclose(expected, float(edge["travel_time"]), rel_tol=1e-8):
            raise ValueError("Travel-time weight disagrees with length/speed units")


def synthetic_graph(size: int = 3) -> nx.MultiDiGraph:
    """Two configurable grid districts, two crossings and a one-way local link; no real roads."""
    if not 3 <= size <= 12:
        raise ValueError("Synthetic district size must be 3–12")
    graph = nx.MultiDiGraph(crs="EPSG:4326", source="synthetic", name="Twin District Demo")
    for district in range(2):
        for row in range(size):
            for col in range(size):
                node = district * size * size + row * size + col
                graph.add_node(
                    node, x=77.105 + (col + district * (size + 1)) * 0.0025, y=28.741 + row * 0.0025
                )

    def road(u: int, v: int, speed: float, name: str, both: bool = True) -> None:
        a = (graph.nodes[u]["x"], graph.nodes[u]["y"])
        b = (graph.nodes[v]["x"], graph.nodes[v]["y"])
        length = distance_m(a, b)
        for start, end in [(u, v), (v, u)] if both else [(u, v)]:
            coords = [a, b] if start == u else [b, a]
            graph.add_edge(
                start,
                end,
                length=length,
                maxspeed=str(speed),
                highway="residential",
                name=name,
                oneway=not both,
                geometry=LineString(coords),
            )

    for district in range(2):
        for row in range(size):
            for col in range(size):
                u = district * size * size + row * size + col
                if col < size - 1:
                    road(u, u + 1, 30, f"District {district + 1} avenue {row + 1}")
                if row < size - 1:
                    road(u, u + size, 25, f"District {district + 1} street {col + 1}")
    road((size // 2 + 1) * size - 1, size * size + (size // 2) * size, 20, "Central crossing")
    road(size * size - 1, size * size + (size - 1) * size, 15, "Southern relief crossing")
    road(0, size + 1, 20, "One-way diagonal", both=False)
    return weight_graph(graph)


def graph_fingerprint(graph: nx.MultiDiGraph) -> str:
    def geometry_coordinates(u, v, data):
        geometry = data.get("geometry")
        coords = (
            geometry.coords
            if geometry is not None
            else [
                (graph.nodes[u]["x"], graph.nodes[u]["y"]),
                (graph.nodes[v]["x"], graph.nodes[v]["y"]),
            ]
        )
        # Sub-millimetre geographic rounding prevents WKT serialization noise.
        return [(round(float(x), 9), round(float(y), 9)) for x, y in coords]

    payload = {
        "fingerprint_version": 2,
        "nodes": sorted((n, d["x"], d["y"], d.get("highway")) for n, d in graph.nodes(data=True)),
        "edges": sorted(
            (
                u,
                v,
                k,
                d["length"],
                d["speed_kph"],
                d["travel_time"],
                d.get("modeled_delay_s", 0),
                d.get("free_speed_kph", d["speed_kph"]),
                {
                    field: d.get(field)
                    for field in ("name", "ref", "osmid", "highway", "bridge", "tunnel", "access")
                },
                geometry_coordinates(u, v, d),
            )
            for u, v, k, d in graph.edges(keys=True, data=True)
        ),
        "operating_speed_factor": graph.graph.get("operating_speed_factor", 1.0),
        "signal_delay_s": graph.graph.get("signal_delay_s", 0.0),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def load_osm(cache_dir: Path = Path("data/cache"), refresh: bool = False) -> nx.MultiDiGraph:
    """Fetch fixed bounded drive graph. No silent synthetic fallback or direction conversion."""
    import osmnx as ox

    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "delhi_rohini.graphml"
    metadata_path = cache_dir / "delhi_rohini.provenance.json"
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(cache_dir / "http")
    ox.settings.requests_timeout = 25
    if path.exists() and metadata_path.exists() and not refresh:
        graph = ox.load_graphml(path)
        provenance = json.loads(metadata_path.read_text())
        validate_graph(graph)
        if graph_fingerprint(graph) != provenance["sha256"]:
            raise ValueError("Cached graph fingerprint does not match provenance; refresh cache")
        return graph
    import socket

    from highwaynet.snapshot import OSM_LOCK

    with OSM_LOCK:
        previous_doh = ox.settings.doh_url_template
        previous_dns = socket.getaddrinfo
        try:
            ox.settings.doh_url_template = None
            graph = ox.graph_from_bbox(
                DELHI_BBOX, network_type="drive", simplify=True, retain_all=True
            )
        finally:
            ox.settings.doh_url_template = previous_doh
            socket.getaddrinfo = previous_dns
    graph = weight_graph(graph)
    graph.graph.update(source="OpenStreetMap", bbox=json.dumps(DELHI_BBOX))
    provenance = {
        "source": "OpenStreetMap contributors / Overpass via OSMnx",
        "license": "ODbL 1.0",
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "bbox_wsen": DELHI_BBOX,
        "network_type": "drive",
        "retain_all": True,
        "nodes": len(graph),
        "directed_edges": graph.number_of_edges(),
        "speed_assumptions_kph": SPEEDS_KPH,
        "osmnx_version": ox.__version__,
        "sha256": graph_fingerprint(graph),
    }
    ox.save_graphml(graph, path)
    metadata_path.write_text(json.dumps(provenance, indent=2))
    return graph

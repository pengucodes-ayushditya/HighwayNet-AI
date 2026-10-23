"""Bounded real OSM ingestion with local import and byte-level provenance.

Requests go only to the named Overpass endpoint. No Google DNS fallback, hidden
retry, provider failover or synthetic substitution is used.
"""

from __future__ import annotations

import hashlib
import json
import threading
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import osmnx as ox
import requests

from highwaynet.data import graph_fingerprint, validate_graph, weight_graph
from highwaynet.studies import StudyArea

OSM_LOCK = threading.RLock()
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
ROAD_CLASSES = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}
EXTRA_TAGS = [
    "access",
    "motor_vehicle",
    "motorcar",
    "service",
    "bridge",
    "tunnel",
    "layer",
    "lanes",
    "ref",
]


def query_for(study: StudyArea) -> str:
    w, s, e, n = study.bbox
    classes = "|".join(sorted(ROAD_CLASSES))
    return (
        '[out:xml][timeout:45];way["highway"~"^(' + classes + ')$"]'
        '["area"!="yes"]["access"!~"^(private|no)$"]'
        '["motor_vehicle"!="no"]["motorcar"!="no"]'
        f"({s},{w},{n},{e});(._;>;);out body;"
    )


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def import_osm(path: Path, study: StudyArea, destination: Path) -> nx.MultiDiGraph:
    """Filter a local .osm XML extract and retain mapped passenger-car directionality.

    Approximate access filter: passenger car, public roads. Conditional restrictions,
    relation turn restrictions and legal interpretation still need independent review.
    """
    raw = path.read_bytes()
    if len(raw) > 100 * 1024 * 1024:
        raise ValueError("OSM import exceeds the 100 MiB study limit")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("OSM XML must not contain document types or entities")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Malformed OSM XML") from exc
    if root.tag != "osm":
        raise ValueError("Expected OSM XML root")
    if root.find("remark") is not None:
        raise ValueError("Overpass response contains a remark/error; snapshot rejected")
    kept = set()
    for way in list(root.findall("way")):
        tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
        # Specific motorcar permission can override generic access in OSM, but this
        # deliberately conservative filter excludes restricted roads instead.
        eligible = (
            tags.get("highway") in ROAD_CLASSES
            and tags.get("area") != "yes"
            and tags.get("access") not in {"private", "no"}
            and tags.get("motor_vehicle") not in {"private", "no"}
            and tags.get("motorcar") not in {"private", "no"}
            and tags.get("service") not in {"parking_aisle", "driveway"}
        )
        if eligible:
            kept.update(nd.attrib["ref"] for nd in way.findall("nd"))
        else:
            root.remove(way)
    for element in list(root):
        if element.tag == "relation" or (
            element.tag == "node" and element.attrib["id"] not in kept
        ):
            root.remove(element)
    available = {n.attrib["id"] for n in root.findall("node")}
    if not kept or not kept.issubset(available):
        raise ValueError("No drivable ways or incomplete way-node references in extract")
    destination.mkdir(parents=True, exist_ok=True)
    filtered = destination / ".filtered.osm"
    ET.ElementTree(root).write(filtered, encoding="utf-8", xml_declaration=True)
    with OSM_LOCK:
        previous = list(ox.settings.useful_tags_way)
        try:
            ox.settings.useful_tags_way = list(dict.fromkeys(previous + EXTRA_TAGS))
            graph = ox.graph_from_xml(
                filtered, bidirectional=False, simplify=False, retain_all=True
            )
            graph = ox.truncate.truncate_graph_bbox(graph, study.bbox, truncate_by_edge=False)
            graph = ox.simplification.simplify_graph(graph, node_attrs_include=["highway"])
        finally:
            ox.settings.useful_tags_way = previous
            filtered.unlink(missing_ok=True)
    graph = weight_graph(graph)
    graph.graph.update(
        source="OpenStreetMap",
        study=study.slug,
        name=study.name,
        bbox=json.dumps(study.bbox),
        data_kind="real_roads_modeled_times",
    )
    provenance = {
        "study": study.slug,
        "bbox_wsen": study.bbox,
        "imported_at_utc": datetime.now(UTC).isoformat(),
        "source": "OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "osm_base_timestamp": (
            root.find("meta").attrib.get("osm_base") if root.find("meta") is not None else None
        ),
        "fingerprint_version": 2,
        "graph_sha256": graph_fingerprint(graph),
        "nodes": len(graph),
        "directed_edges": graph.number_of_edges(),
        "osmnx_version": ox.__version__,
        "access_filter": "conservative public passenger-car roads; conditional rules unmodeled",
        "traffic_observations": False,
        "turn_restrictions_enforced": False,
    }
    # Raw bytes and graph are published before metadata; incomplete writes fail on load.
    raw_copy = destination / "roads.osm"
    if raw_copy.resolve() != path.resolve():
        raw_copy.write_bytes(raw)
    graph_path = destination / "network.graphml"
    ox.save_graphml(graph, graph_path.with_suffix(".tmp.graphml"))
    graph_path.with_suffix(".tmp.graphml").replace(graph_path)
    _atomic_text(destination / "provenance.json", json.dumps(provenance, indent=2))
    return graph


def load_snapshot(directory: Path) -> nx.MultiDiGraph:
    metadata = json.loads((directory / "provenance.json").read_text())
    graph = ox.load_graphml(directory / "network.graphml")
    validate_graph(graph)
    if graph_fingerprint(graph) != metadata["graph_sha256"]:
        raise ValueError("Snapshot graph fingerprint mismatch")
    if hashlib.sha256((directory / "roads.osm").read_bytes()).hexdigest() != metadata["raw_sha256"]:
        raise ValueError("Snapshot raw-data fingerprint mismatch")
    return graph


def fetch_snapshot(study: StudyArea, destination: Path, refresh: bool = False) -> nx.MultiDiGraph:
    if not refresh and (destination / "provenance.json").exists():
        return load_snapshot(destination)
    destination.mkdir(parents=True, exist_ok=True)
    query = query_for(study)
    # A single explicitly bounded request; never call OSMnx's network/DNS helpers.
    response = requests.get(
        OVERPASS_ENDPOINT,
        params={"data": query},
        timeout=(10, 60),
        headers={"User-Agent": "HighwayNet-AI/0.2 (bounded academic road-network prototype)"},
    )
    response.raise_for_status()
    raw_path = destination / "download.osm"
    raw_path.write_bytes(response.content)
    try:
        graph = import_osm(raw_path, study, destination)
        _atomic_text(
            destination / "request.json",
            json.dumps(
                {
                    "endpoint": OVERPASS_ENDPOINT,
                    "query": query,
                    "retrieved_at_utc": datetime.now(UTC).isoformat(),
                    "http_status": response.status_code,
                },
                indent=2,
            ),
        )
        return graph
    finally:
        raw_path.unlink(missing_ok=True)


def fetch_osm_api_tiles(
    study: StudyArea, destination: Path, refresh: bool = False
) -> nx.MultiDiGraph:
    """Explicit OSM main API provider for a modest 2×2 tiled study extract.

    Four sequential requests, each <=0.01 square degrees. No automatic provider
    switching or recursive retries. Main API 50,000-node limits may require a
    smaller study; large regions should use regional extracts or Overpass.
    """
    if not refresh and (destination / "provenance.json").exists():
        return load_snapshot(destination)
    w, s, e, n = study.bbox
    if not (0 < e - w <= 0.2 and 0 < n - s <= 0.2):
        raise ValueError("Main API tile provider supports modest study bounds only")
    destination.mkdir(parents=True, exist_ok=True)
    merged = ET.Element(
        "osm",
        version="0.6",
        generator="HighwayNet OSM API tile merger",
        copyright="OpenStreetMap contributors",
        license="ODbL 1.0",
    )
    elements: dict[tuple[str, str], ET.Element] = {}
    requests_log = []
    cache = destination / "raw_tiles"
    cache.mkdir(exist_ok=True)
    for i in range(2):
        for j in range(2):
            bbox = (
                w + (e - w) * i / 2,
                s + (n - s) * j / 2,
                w + (e - w) * (i + 1) / 2,
                s + (n - s) * (j + 1) / 2,
            )
            path = cache / f"{i}_{j}.osm"
            if not path.exists() or refresh:
                response = requests.get(
                    "https://api.openstreetmap.org/api/0.6/map",
                    params={"bbox": ",".join(f"{v:.7f}" for v in bbox)},
                    timeout=(10, 45),
                    headers={"User-Agent": "HighwayNet-AI/0.2 (one-off bounded academic study)"},
                )
                response.raise_for_status()
                path.write_bytes(response.content)
                _atomic_text(
                    path.with_suffix(".json"),
                    json.dumps(
                        {
                            "bbox_wsen": bbox,
                            "retrieved_at_utc": datetime.now(UTC).isoformat(),
                            "url": response.url,
                            "sha256": hashlib.sha256(response.content).hexdigest(),
                        },
                        indent=2,
                    ),
                )
            tile_bytes = path.read_bytes()
            request = json.loads(path.with_suffix(".json").read_text())
            if request["sha256"] != hashlib.sha256(tile_bytes).hexdigest():
                raise ValueError("Raw OSM tile checksum mismatch")
            try:
                tile = ET.fromstring(tile_bytes)
            except ET.ParseError as exc:
                raise ValueError("Malformed OSM API tile") from exc
            if tile.tag != "osm":
                raise ValueError("OSM API returned an unexpected document")
            requests_log.append(request)
            # Keep road ways and their nodes, not unrelated buildings/relations.
            needed = set()
            for way in tile.findall("way"):
                tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
                if tags.get("highway") not in ROAD_CLASSES:
                    continue
                key = ("way", way.attrib["id"])
                previous = elements.get(key)
                if previous is None or int(way.attrib.get("version", 0)) > int(
                    previous.attrib.get("version", 0)
                ):
                    elements[key] = way
                needed.update(nd.attrib["ref"] for nd in way.findall("nd"))
            for node in tile.findall("node"):
                if node.attrib["id"] in needed:
                    key = ("node", node.attrib["id"])
                    previous = elements.get(key)
                    if previous is None or int(node.attrib.get("version", 0)) > int(
                        previous.attrib.get("version", 0)
                    ):
                        elements[key] = node
    for key in sorted(elements, key=lambda x: (x[0], int(x[1]))):
        merged.append(elements[key])
    source = destination / "merged_download.osm"
    ET.ElementTree(merged).write(source, encoding="utf-8", xml_declaration=True)
    try:
        graph = import_osm(source, study, destination)
        _atomic_text(
            destination / "request.json",
            json.dumps(
                {
                    "provider": "OpenStreetMap main API, sequential 2×2 bounded tiles",
                    "tiles": requests_log,
                    "bbox_wsen": study.bbox,
                    "temporal_consistency": "four nearby download times; not an atomic snapshot",
                },
                indent=2,
            ),
        )
        return graph
    finally:
        source.unlink(missing_ok=True)

import networkx as nx
import pytest

from highwaynet.data import synthetic_graph


@pytest.fixture
def demo():
    return synthetic_graph()


@pytest.fixture
def directed():
    """Hand-solvable directed diamond. 0→1→3=20s; 0→2→3=40s."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for n in range(5):
        graph.add_node(n, x=77.1 + n * 0.001, y=28.74)
    for u, v, seconds in [(0, 1, 10), (1, 3, 10), (0, 2, 20), (2, 3, 20)]:
        graph.add_edge(u, v, length=seconds * 10, speed_kph=36, travel_time=float(seconds))
    return graph


@pytest.fixture(autouse=True)
def forbid_external_http(monkeypatch):
    import requests

    def blocked(*args, **kwargs):
        raise AssertionError("Tests must use cached data or explicitly mocked HTTP")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)

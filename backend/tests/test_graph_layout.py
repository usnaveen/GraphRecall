"""The 3D layout works past 500 nodes without SciPy, and linked concepts end up near each other."""

import math

from backend.services.graph_layout import spring_layout_3d


def test_large_graph_without_scipy():
    nodes = [f"n{i}" for i in range(700)]
    edges = [(f"n{i}", f"n{(i * 7 + 3) % 700}", 1.0) for i in range(700)]
    pos = spring_layout_3d(nodes, edges, iterations=20)
    assert len(pos) == 700
    assert all(all(math.isfinite(c) and abs(c) <= 400.0001 for c in p) for p in pos.values())


def test_linked_nodes_are_closer_than_unlinked():
    nodes = [f"a{i}" for i in range(10)] + [f"b{i}" for i in range(10)]
    edges = [(f"a{i}", f"a{j}", 1.0) for i in range(10) for j in range(i + 1, 10)]
    edges += [(f"b{i}", f"b{j}", 1.0) for i in range(10) for j in range(i + 1, 10)]
    pos = spring_layout_3d(nodes, edges)
    d = lambda u, v: math.dist(pos[u], pos[v])
    within = sum(d("a0", f"a{i}") for i in range(1, 10)) / 9
    across = sum(d("a0", f"b{i}") for i in range(10)) / 10
    assert within < across


def test_tiny_graphs():
    assert spring_layout_3d([], []) == {}
    assert spring_layout_3d(["x"], []) == {"x": (0.0, 0.0, 0.0)}
    assert set(spring_layout_3d(["x", "y"], [("x", "y", None)])) == {"x", "y"}

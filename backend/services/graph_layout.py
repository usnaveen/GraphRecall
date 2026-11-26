"""3D force-directed layout for the knowledge graph, with NumPy only.

networkx's spring_layout switches to a SciPy implementation at 500 nodes, and SciPy is not a
dependency, so /api/graph3d failed with a 500 as soon as a user's graph reached 500 concepts.
This is the same Fruchterman-Reingold method (as in networkx's dense version), computed in row
chunks so memory stays bounded up to the endpoint's 5,000-node limit.
"""

from __future__ import annotations

from typing import Hashable, Iterable

import numpy as np

_CHUNK = 256


def spring_layout_3d(
    nodes: list[Hashable],
    edges: Iterable[tuple[Hashable, Hashable, float]],
    *,
    iterations: int = 50,
    scale: float = 400.0,
    seed: int = 42,
) -> dict[Hashable, tuple[float, float, float]]:
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: (0.0, 0.0, 0.0)}

    index = {node: i for i, node in enumerate(nodes)}
    adjacency = np.zeros((n, n), dtype=np.float32)
    for source, target, weight in edges:
        i, j = index.get(source), index.get(target)
        if i is None or j is None or i == j:
            continue
        w = float(weight) if weight else 1.0
        adjacency[i, j] = adjacency[j, i] = w

    rng = np.random.default_rng(seed)
    pos = rng.random((n, 3)).astype(np.float64)
    k = np.sqrt(1.0 / n)  # optimal distance between nodes
    temperature = max(float(np.ptp(pos, axis=0).max()), 1e-3) * 0.1
    cooling = temperature / (iterations + 1)

    for _ in range(iterations):
        displacement = np.zeros_like(pos)
        for start in range(0, n, _CHUNK):
            stop = min(start + _CHUNK, n)
            delta = pos[start:stop, None, :] - pos[None, :, :]          # (c, n, 3)
            distance = np.linalg.norm(delta, axis=-1)
            np.clip(distance, 0.01, None, out=distance)
            # repulsion k^2/d for every pair, attraction d^2/k along edges (scaled by weight)
            force = (k * k / distance**2) - adjacency[start:stop] * distance / k
            displacement[start:stop] = np.einsum("ijk,ij->ik", delta, force)
        length = np.linalg.norm(displacement, axis=-1)
        length = np.where(length < 0.01, 0.1, length)
        pos += displacement * (temperature / length)[:, None]
        temperature -= cooling

    pos -= pos.mean(axis=0)
    extent = float(np.abs(pos).max()) or 1.0
    pos = pos / extent * scale
    return {node: (float(p[0]), float(p[1]), float(p[2])) for node, p in zip(nodes, pos)}

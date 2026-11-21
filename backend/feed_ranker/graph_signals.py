"""Read-only graph signal contract, in-memory test double, and dynamic adapter."""

from __future__ import annotations

import importlib
import inspect
from collections import deque
from typing import Any, Optional, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()


@runtime_checkable
class GraphSignalsProtocol(Protocol):
    """Read-only, user-scoped graph signals contract owned by backend/services/graph_signals.py."""

    async def concept_neighborhood(
        self,
        user_id: str,
        seed_ids: list[str],
        k: int = 20,
    ) -> dict[str, float]:
        """Return normalized neighborhood/PPR scores mapped by concept_id."""

    async def prerequisites(
        self,
        user_id: str,
        concept_id: str,
        depth: int = 2,
    ) -> list[tuple[str, int, float]]:
        """Return prerequisite ancestors as (prereq_concept_id, hop_depth, strength)."""

    async def weakest_prerequisite(
        self,
        user_id: str,
        concept_id: str,
    ) -> Optional[str]:
        """Return the weakest prerequisite concept_id for remediation, if any."""


class NullGraphSignals:
    """Safe no-op implementation when graph_signals service is not yet deployed."""

    async def concept_neighborhood(
        self,
        user_id: str,
        seed_ids: list[str],
        k: int = 20,
    ) -> dict[str, float]:
        return {}

    async def prerequisites(
        self,
        user_id: str,
        concept_id: str,
        depth: int = 2,
    ) -> list[tuple[str, int, float]]:
        return []

    async def weakest_prerequisite(
        self,
        user_id: str,
        concept_id: str,
    ) -> Optional[str]:
        return None


class InMemoryGraphSignals:
    """Deterministic in-memory implementation of GraphSignalsProtocol for offline unit tests."""

    def __init__(
        self,
        prereq_edges: Optional[dict[str, list[tuple[str, float]]]] = None,
        related_edges: Optional[dict[str, list[tuple[str, float]]]] = None,
        stabilities: Optional[dict[str, float]] = None,
    ) -> None:
        self.prereq_edges: dict[str, list[tuple[str, float]]] = prereq_edges or {}
        self.related_edges: dict[str, list[tuple[str, float]]] = related_edges or {}
        self.stabilities: dict[str, float] = stabilities or {}

    async def concept_neighborhood(
        self,
        user_id: str,
        seed_ids: list[str],
        k: int = 20,
    ) -> dict[str, float]:
        seeds = [s for s in seed_ids if s]
        if not seeds or k <= 0:
            return {}

        # Build undirected weighted adjacency combining related and prerequisite links
        adj: dict[str, dict[str, float]] = {}
        for src, nbrs in self.related_edges.items():
            for dst, w in nbrs:
                weight = max(0.0, float(w))
                adj.setdefault(src, {})[dst] = max(adj.get(src, {}).get(dst, 0.0), weight)
                adj.setdefault(dst, {})[src] = max(adj.get(dst, {}).get(src, 0.0), weight)
        for src, nbrs in self.prereq_edges.items():
            for dst, w in nbrs:
                weight = max(0.0, float(w)) * 0.85
                adj.setdefault(src, {})[dst] = max(adj.get(src, {}).get(dst, 0.0), weight)
                adj.setdefault(dst, {})[src] = max(adj.get(dst, {}).get(src, 0.0), weight)

        nodes = set(adj.keys()) | set(seeds)
        if not nodes:
            return {}

        seed_weight = 1.0 / len(seeds)
        restart = {n: (seed_weight if n in seeds else 0.0) for n in nodes}
        scores = dict(restart)
        damping = 0.85

        for _ in range(15):
            next_scores = {n: (1.0 - damping) * restart[n] for n in nodes}
            for node, mass in scores.items():
                if mass <= 0.0:
                    continue
                nbrs = adj.get(node, {})
                total_w = sum(nbrs.values())
                if total_w <= 0.0:
                    for seed in seeds:
                        next_scores[seed] += damping * mass * seed_weight
                else:
                    for nbr, w in nbrs.items():
                        next_scores[nbr] += damping * mass * (w / total_w)
            scores = next_scores

        # Exclude seed nodes themselves from drift neighborhood output
        seed_set = set(seeds)
        filtered = {nid: val for nid, val in scores.items() if nid not in seed_set and val > 0.0}
        if not filtered:
            return {}

        max_val = max(filtered.values())
        if max_val <= 0.0:
            return {}

        ranked = sorted(filtered.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return {nid: round(val / max_val, 6) for nid, val in ranked}

    async def prerequisites(
        self,
        user_id: str,
        concept_id: str,
        depth: int = 2,
    ) -> list[tuple[str, int, float]]:
        if not concept_id or depth <= 0:
            return []

        best: dict[str, tuple[int, float]] = {}
        queue: deque[tuple[str, int, float]] = deque([(concept_id, 0, 1.0)])

        while queue:
            curr, curr_depth, curr_strength = queue.popleft()
            if curr_depth >= depth:
                continue
            for prereq_id, edge_w in self.prereq_edges.get(curr, []):
                if prereq_id == concept_id:
                    continue
                next_depth = curr_depth + 1
                next_strength = min(1.0, max(0.0, curr_strength * float(edge_w)))
                prev = best.get(prereq_id)
                if prev is None or next_depth < prev[0] or (
                    next_depth == prev[0] and next_strength > prev[1]
                ):
                    best[prereq_id] = (next_depth, next_strength)
                    queue.append((prereq_id, next_depth, next_strength))

        return sorted(
            [(pid, d, round(s, 4)) for pid, (d, s) in best.items()],
            key=lambda item: (item[1], -item[2], item[0]),
        )

    async def weakest_prerequisite(
        self,
        user_id: str,
        concept_id: str,
    ) -> Optional[str]:
        ancestors = await self.prerequisites(user_id, concept_id, depth=2)
        if not ancestors:
            return None
        weak_id, _, _ = min(
            ancestors,
            key=lambda item: (
                float(self.stabilities.get(item[0], 0.0)),
                item[1],
                -item[2],
                item[0],
            ),
        )
        return weak_id


class _ModuleGraphSignalsAdapter:
    """Wraps module-level async functions from backend.services.graph_signals if exported that way."""

    def __init__(self, mod: Any, neo4j_client: Any = None, pg_client: Any = None) -> None:
        self._mod = mod
        self._neo4j = neo4j_client
        self._pg = pg_client

    async def _call(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._mod, fn_name, None)
        if fn is None:
            return None
        sig = inspect.signature(fn)
        call_kwargs = dict(kwargs)
        if "neo4j_client" in sig.parameters and self._neo4j is not None:
            call_kwargs["neo4j_client"] = self._neo4j
        if "pg_client" in sig.parameters and self._pg is not None:
            call_kwargs["pg_client"] = self._pg
        res = fn(*args, **call_kwargs)
        if inspect.isawaitable(res):
            return await res
        return res

    async def concept_neighborhood(
        self,
        user_id: str,
        seed_ids: list[str],
        k: int = 20,
    ) -> dict[str, float]:
        res = await self._call("concept_neighborhood", user_id, seed_ids, k=k)
        return res or {}

    async def prerequisites(
        self,
        user_id: str,
        concept_id: str,
        depth: int = 2,
    ) -> list[tuple[str, int, float]]:
        res = await self._call("prerequisites", user_id, concept_id, depth=depth)
        return res or []

    async def weakest_prerequisite(
        self,
        user_id: str,
        concept_id: str,
    ) -> Optional[str]:
        return await self._call("weakest_prerequisite", user_id, concept_id)


def load_graph_signals(
    neo4j_client: Any = None,
    pg_client: Any = None,
) -> GraphSignalsProtocol:
    """Dynamically bind backend.services.graph_signals when available; degrade to NullGraphSignals."""
    try:
        mod = importlib.import_module("backend.services.graph_signals")
    except ImportError:
        return NullGraphSignals()
    except Exception as exc:
        logger.warning("FeedRanker: Failed loading backend.services.graph_signals", error=str(exc))
        return NullGraphSignals()

    factory = getattr(mod, "get_graph_signals", None)
    if callable(factory):
        try:
            sig = inspect.signature(factory)
            kwargs = {}
            if "neo4j_client" in sig.parameters:
                kwargs["neo4j_client"] = neo4j_client
            if "pg_client" in sig.parameters:
                kwargs["pg_client"] = pg_client
            instance = factory(**kwargs)
            if isinstance(instance, GraphSignalsProtocol):
                return instance
        except Exception as exc:
            logger.warning("FeedRanker: get_graph_signals failed", error=str(exc))

    cls = getattr(mod, "GraphSignals", None)
    if inspect.isclass(cls):
        try:
            sig = inspect.signature(cls.__init__)
            kwargs = {}
            if "neo4j_client" in sig.parameters:
                kwargs["neo4j_client"] = neo4j_client
            if "pg_client" in sig.parameters:
                kwargs["pg_client"] = pg_client
            instance = cls(**kwargs)
            if isinstance(instance, GraphSignalsProtocol):
                return instance
        except Exception as exc:
            logger.warning("FeedRanker: GraphSignals instantiation failed", error=str(exc))

    if all(
        hasattr(mod, attr)
        for attr in ("concept_neighborhood", "prerequisites", "weakest_prerequisite")
    ):
        return _ModuleGraphSignalsAdapter(mod, neo4j_client=neo4j_client, pg_client=pg_client)

    return NullGraphSignals()

"""Lightweight latency telemetry for GraphRecall.

Every measurement is written to the structured log and kept in a small rolling window per
stage, so ``GET /api/debug/latency`` can report p50/p95 without any external service.
Stage names are chosen so they map one-to-one onto OpenTelemetry spans once the API is
deployed and a real tracing backend is worth running.

    with stage("chat.vector_search"):
        rows = await pg.execute_query(...)
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional
from uuid import UUID

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = structlog.get_logger()

WINDOW = 200  # samples kept per stage

_samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW))
_llm_totals: dict[str, dict[str, int]] = defaultdict(
    lambda: {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0}
)
# Stages recorded while handling the current request; feeds the Server-Timing header.
_request_stages: ContextVar[Optional[list[tuple[str, float]]]] = ContextVar("request_stages", default=None)


def now() -> float:
    return time.perf_counter()


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def record(name: str, duration_ms: float, *, log: bool = True, **fields: Any) -> None:
    """Store one duration for ``name`` (and attach it to the current request, if any)."""
    _samples[name].append(duration_ms)
    stages = _request_stages.get()
    if stages is not None:
        stages.append((name, duration_ms))
    if log:
        logger.info("timing", stage=name, duration_ms=round(duration_ms, 1), **fields)


@contextmanager
def stage(name: str, **fields: Any) -> Iterator[None]:
    """Time the enclosed block, including awaits inside it."""
    start = time.perf_counter()
    try:
        yield
    finally:
        record(name, elapsed_ms(start), **fields)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = round(pct / 100 * (len(sorted_values) - 1))
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def snapshot() -> dict:
    """Rolling percentiles per stage plus cumulative LLM call and token counts per model."""
    stages = {}
    for name in sorted(_samples):
        values = sorted(_samples[name])
        if not values:
            continue
        stages[name] = {
            "count": len(values),
            "p50_ms": round(_percentile(values, 50), 1),
            "p95_ms": round(_percentile(values, 95), 1),
            "max_ms": round(values[-1], 1),
        }
    return {
        "window": WINDOW,
        "stages": stages,
        "llm": {model: dict(totals) for model, totals in sorted(_llm_totals.items())},
    }


def reset() -> None:
    _samples.clear()
    _llm_totals.clear()


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


def _usage(response: LLMResult) -> tuple[int, int]:
    for generations in response.generations or []:
        for generation in generations:
            usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
            if usage:
                return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    usage = (response.llm_output or {}).get("usage_metadata") or {}
    return (
        int(usage.get("input_tokens") or usage.get("prompt_token_count") or 0),
        int(usage.get("output_tokens") or usage.get("candidates_token_count") or 0),
    )


class LLMTimingCallback(BaseCallbackHandler):
    """Times every model call: total latency, time to first streamed token, token usage."""

    run_inline = True  # record on the event loop instead of a thread pool

    def __init__(self) -> None:
        self._runs: dict[UUID, tuple[float, str, bool]] = {}

    @staticmethod
    def _model_name(serialized: Optional[dict], kwargs: dict) -> str:
        metadata = kwargs.get("metadata") or {}
        params = kwargs.get("invocation_params") or {}
        name = (
            metadata.get("ls_model_name")
            or params.get("model")
            or params.get("model_name")
            or (serialized or {}).get("name")
            or "unknown"
        )
        return str(name).removeprefix("models/")

    def on_chat_model_start(self, serialized, messages, *, run_id: UUID, **kwargs: Any) -> None:
        self._runs[run_id] = (time.perf_counter(), self._model_name(serialized, kwargs), False)

    def on_llm_start(self, serialized, prompts, *, run_id: UUID, **kwargs: Any) -> None:
        self._runs[run_id] = (time.perf_counter(), self._model_name(serialized, kwargs), False)

    def on_llm_new_token(self, token: str, *, run_id: UUID, **kwargs: Any) -> None:
        run = self._runs.get(run_id)
        if run and not run[2]:
            start, model, _ = run
            self._runs[run_id] = (start, model, True)
            record(f"llm.first_token {model}", elapsed_ms(start), log=False)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        run = self._runs.pop(run_id, None)
        if not run:
            return
        start, model, _ = run
        input_tokens, output_tokens = _usage(response)
        totals = _llm_totals[model]
        totals["calls"] += 1
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        record(
            f"llm.call {model}",
            elapsed_ms(start),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        run = self._runs.pop(run_id, None)
        if not run:
            return
        start, model, _ = run
        _llm_totals[model]["errors"] += 1
        record(f"llm.error {model}", elapsed_ms(start), model=model, error=str(error)[:160])


LLM_TIMING_CALLBACK = LLMTimingCallback()


# ---------------------------------------------------------------------------
# HTTP requests
# ---------------------------------------------------------------------------

_HEADER_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_UNTIMED_PATHS = {"/health", "/api/debug/latency"}


class TimingMiddleware:
    """Pure ASGI middleware, so it also measures streaming (SSE) responses.

    Records total time per route template and logs time-to-first-byte. Stages finished before
    the response starts (auth, request setup) are sent back as a ``Server-Timing`` header.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") in _UNTIMED_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        stages: list[tuple[str, float]] = []
        token = _request_stages.set(stages)
        state: dict[str, Any] = {"status": 500, "first_byte": None}

        async def send_with_timing(message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                if stages:
                    header = ", ".join(
                        f"{_HEADER_UNSAFE.sub('_', name)};dur={duration:.1f}" for name, duration in stages
                    )
                    message = {
                        **message,
                        "headers": [*message.get("headers", []), (b"server-timing", header.encode("latin-1"))],
                    }
            elif message["type"] == "http.response.body" and state["first_byte"] is None and message.get("body"):
                state["first_byte"] = time.perf_counter()
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            total = elapsed_ms(start)
            route = getattr(scope.get("route"), "path", None) or scope.get("path", "")
            _samples[f"http {scope.get('method', '')} {route}"].append(total)
            first_byte = state["first_byte"]
            logger.info(
                "request.timing",
                method=scope.get("method"),
                route=route,
                status=state["status"],
                total_ms=round(total, 1),
                ttfb_ms=round((first_byte - start) * 1000, 1) if first_byte else None,
                stages={name: round(duration, 1) for name, duration in stages},
            )
            _request_stages.reset(token)

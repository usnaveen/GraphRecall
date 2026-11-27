"""OpenTelemetry tracing: one trace per request, with every measured stage as a child span.

Off unless configured, so local runs and tests pay nothing:
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   export OTLP/HTTP (Jaeger, Tempo, Honeycomb, ...)
  OTEL_TRACES_EXPORTER=console                         print spans to stdout (debugging)
  OTEL_SERVICE_NAME                                     defaults to graphrecall-api

How spans are made:
- FastAPI instrumentation opens a server span per request (and joins an incoming traceparent).
- `span(name)` / `@traced(name)` wrap work explicitly (the chat graph's three nodes use it).
- Every existing `telemetry.record(stage, duration_ms, **fields)` call also becomes a child span,
  back-dated by its duration, so the ~30 timed stages (retrieval legs, rerank, embedding, each LLM
  call with token counts, guard decisions) appear on the trace with no other code changes.

No request text is put on spans: attributes are the numeric and categorical fields `record` already
logs, and user ids are hashed.
"""

from __future__ import annotations

import functools
import hashlib
import os
import time
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Iterator, Optional

_tracer = None


def enabled() -> bool:
    return _tracer is not None


def init_tracing(app: Any = None) -> bool:
    """Configure the tracer provider and instrument the app. Returns True when tracing is on."""
    global _tracer
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    console = os.getenv("OTEL_TRACES_EXPORTER", "").strip().lower() == "console"
    if not (endpoint or console):
        return False
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "graphrecall-api")}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("graphrecall")
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
    return True


def use_tracer(tracer: Any) -> None:
    """Tests: install a tracer (e.g. backed by an in-memory exporter). None turns tracing off."""
    global _tracer
    _tracer = tracer


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if k in ("user_id", "uid"):
            out["user.hash"] = hashlib.sha256(str(v).encode()).hexdigest()[:12]
        elif isinstance(v, (bool, int, float, str)):
            out[k] = v if not isinstance(v, str) else v[:200]
        elif isinstance(v, (list, tuple)) and all(isinstance(x, (bool, int, float, str)) for x in v):
            out[k] = [x if not isinstance(x, str) else x[:80] for x in v][:20]
        else:
            out[k] = str(v)[:200]
    return out


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    if _tracer is None:
        with nullcontext() as s:
            yield s
        return
    with _tracer.start_as_current_span(name, attributes=_clean(attrs)) as s:
        yield s


def traced(name: Optional[str] = None) -> Callable:
    """Decorator for async functions: run inside a span named `name` (default: the function name)."""
    def wrap(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def inner(*args: Any, **kwargs: Any) -> Any:
            with span(name or fn.__name__):
                return await fn(*args, **kwargs)
        return inner
    return wrap


def record_span(name: str, duration_ms: float, fields: dict[str, Any]) -> None:
    """A finished, back-dated child span for a stage that telemetry.record() just measured."""
    if _tracer is None:
        return
    end = time.time_ns()
    start = end - int(max(0.0, duration_ms) * 1_000_000)
    s = _tracer.start_span(name, start_time=start, attributes=_clean({**fields, "duration_ms": round(duration_ms, 2)}))
    s.end(end_time=end)

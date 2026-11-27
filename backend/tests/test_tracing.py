"""OpenTelemetry: recorded stages become correctly timed child spans; no user text or raw ids."""

import importlib

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend import telemetry, tracing


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.use_tracer(provider.get_tracer("test"))
    yield exporter
    tracing.use_tracer(None)


def test_recorded_stage_becomes_a_backdated_child_span(spans):
    with tracing.span("chat.get_context", intent="explain"):
        telemetry.record("chat.hybrid_retrieval", 42.0, log=False, rows=7, user_id="u-123")
    got = {s.name: s for s in spans.get_finished_spans()}
    child, parent = got["chat.hybrid_retrieval"], got["chat.get_context"]
    assert child.parent.span_id == parent.context.span_id          # nested under the node
    assert abs((child.end_time - child.start_time) / 1e6 - 42.0) < 1  # carries the measured duration
    assert child.attributes["rows"] == 7
    assert "user_id" not in child.attributes and len(child.attributes["user.hash"]) == 12


@pytest.mark.asyncio
async def test_traced_decorator_wraps_async_nodes(spans):
    @tracing.traced("chat.demo")
    async def node(x):
        telemetry.record("inner", 1.0, log=False)
        return x + 1

    assert await node(1) == 2
    names = [s.name for s in spans.get_finished_spans()]
    assert names == ["inner", "chat.demo"]


def test_tracing_is_off_by_default_and_free(monkeypatch):
    tracing.use_tracer(None)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    assert tracing.init_tracing(None) is False
    telemetry.record("noop", 1.0, log=False)  # must not raise
    with tracing.span("x") as s:
        assert s is None


def test_chat_nodes_are_traced():
    cg = importlib.import_module("backend.graphs.chat_graph")
    for node in ("analyze_query_node", "get_context_node", "generate_response_node"):
        assert hasattr(getattr(cg, node), "__wrapped__"), node

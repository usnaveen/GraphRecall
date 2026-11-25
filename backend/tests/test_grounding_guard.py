"""Pure unit tests for backend.services.grounding_guard."""

from __future__ import annotations

import asyncio

import pytest

from backend.services.grounding_guard import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
    CitationAudit,
    GroundingDecision,
    evaluate_retrieval_confidence,
    is_retryable_llm_error,
    verify_citations,
)


class _FakeClock:
    def __init__(self, initial: float = 1000.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _HttpError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


class ValidationError(Exception):
    """Simulated validation error for non-retryable classification tests."""


# ---------------------------------------------------------------------------
# evaluate_retrieval_confidence
# ---------------------------------------------------------------------------


def test_retrieval_confidence_general_intent_bypasses_abstention() -> None:
    decision = evaluate_retrieval_confidence(chunks=[], graph_concepts=[], intent="general")
    assert isinstance(decision, GroundingDecision)
    assert decision.should_abstain is False
    assert decision.confidence_tier == "medium"
    assert decision.valid_chunk_indices == set()
    assert decision.valid_graph_ids == set()


def test_retrieval_confidence_abstains_when_both_chunks_and_graph_empty() -> None:
    decision = evaluate_retrieval_confidence(chunks=[], graph_concepts=[], intent="explain")
    assert decision.should_abstain is True
    assert decision.confidence_tier == "low"
    assert decision.max_score == 0.0
    assert decision.abstention_message != ""


def test_retrieval_confidence_abstains_on_low_vector_or_rrf_without_graph() -> None:
    low_vec = evaluate_retrieval_confidence(
        chunks=[{"content": "weak", "similarity": 0.41, "note_id": "n1", "parent_chunk_id": "p1"}],
        graph_concepts=[],
        intent="find",
    )
    assert low_vec.should_abstain is True
    assert low_vec.confidence_tier == "low"
    assert low_vec.max_score == pytest.approx(0.41)
    assert low_vec.valid_chunk_indices == {1}

    low_rrf = evaluate_retrieval_confidence(
        chunks=[{"content": "weak", "_rrf_score": 0.006}],
        graph_concepts=[],
        intent="compare",
    )
    assert low_rrf.should_abstain is True
    assert low_rrf.confidence_tier == "low"
    assert low_rrf.max_score == pytest.approx(0.006)


def test_retrieval_confidence_graph_confirmation_prevents_abstention_and_sets_ids() -> None:
    decision = evaluate_retrieval_confidence(
        chunks=[{"content": "c1", "score": 0.45}, {"content": "c2", "score": 0.30}],
        graph_concepts=[{"name": "Attention"}, {"name": "Transformer"}],
        intent="explain",
    )
    assert decision.should_abstain is False
    assert decision.confidence_tier == "medium"
    assert decision.valid_chunk_indices == {1, 2}
    assert decision.valid_graph_ids == {"G1", "G2"}


def test_retrieval_confidence_high_tier_on_strong_chunks_and_graph() -> None:
    decision = evaluate_retrieval_confidence(
        chunks=[{"content": "strong", "similarity": 0.84, "rrf_score": 0.032}],
        graph_concepts=[{"name": "LoRA"}],
        intent="explain",
    )
    assert decision.should_abstain is False
    assert decision.confidence_tier == "high"
    assert decision.max_score == pytest.approx(0.84)


# ---------------------------------------------------------------------------
# verify_citations
# ---------------------------------------------------------------------------


def test_verify_citations_preserves_valid_and_strips_invalid_cleanly() -> None:
    text = "LoRA freezes base weights [1] and adds low-rank adapters [99]. Graph confirms [G1] not [G4]."
    audit = verify_citations(text, valid_chunk_indices={1, 2}, valid_graph_ids={"G1"})

    assert isinstance(audit, CitationAudit)
    assert audit.valid_refs == ["1", "G1"]
    assert audit.invalid_refs == ["99", "G4"]
    assert audit.grounded_ratio == pytest.approx(0.5)
    assert audit.cleaned_text == (
        "LoRA freezes base weights [1] and adds low-rank adapters. Graph confirms [G1] not."
    )
    assert "  " not in audit.cleaned_text


def test_verify_citations_never_touches_markdown_links_or_images() -> None:
    text = (
        "Read [the paper](https://example.com/1) or [1](https://example.com/ref) "
        "and ![Figure 1](https://cdn.example.com/fig.png). Also see [1][2] and [3]."
    )
    audit = verify_citations(text, valid_chunk_indices={1, 2}, valid_graph_ids=None)

    assert audit.valid_refs == ["1", "2"]
    assert audit.invalid_refs == ["3"]
    assert audit.grounded_ratio == pytest.approx(2 / 3)
    assert "[the paper](https://example.com/1)" in audit.cleaned_text
    assert "[1](https://example.com/ref)" in audit.cleaned_text
    assert "![Figure 1](https://cdn.example.com/fig.png)" in audit.cleaned_text
    assert "[1][2]" in audit.cleaned_text
    assert "[3]" not in audit.cleaned_text


def test_verify_citations_comma_separated_and_no_citations_default_ratio() -> None:
    audit_comma = verify_citations(
        "Supported by [1, 5, G1] and [8, 9].",
        valid_chunk_indices={1, 2},
        valid_graph_ids={"G1"},
    )
    assert audit_comma.valid_refs == ["1", "G1"]
    assert audit_comma.invalid_refs == ["5", "8", "9"]
    assert audit_comma.cleaned_text == "Supported by [1, G1] and."

    audit_none = verify_citations("Plain answer with [high confidence] note.", valid_chunk_indices={1})
    assert audit_none.valid_refs == []
    assert audit_none.invalid_refs == []
    assert audit_none.grounded_ratio == 1.0
    assert audit_none.cleaned_text == "Plain answer with [high confidence] note."


# ---------------------------------------------------------------------------
# is_retryable_llm_error & AsyncCircuitBreaker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_HttpError(400), False),
        (_HttpError(401), False),
        (_HttpError(403), False),
        (_HttpError(404), False),
        (ValueError("bad prompt"), False),
        (ValidationError("schema mismatch"), False),
        (_HttpError(429), True),
        (_HttpError(500), True),
        (_HttpError(502), True),
        (_HttpError(503), True),
        (_HttpError(504), True),
        (TimeoutError("deadline exceeded"), True),
        (ConnectionError("reset by peer"), True),
        (RuntimeError("upstream rate limit hit (429)"), True),
        (RuntimeError("service 503 unavailable"), True),
    ],
)
def test_is_retryable_llm_error_classification(exc: BaseException, expected: bool) -> None:
    assert is_retryable_llm_error(exc) is expected


def test_circuit_breaker_non_retryable_errors_do_not_trip() -> None:
    clock = _FakeClock()
    breaker = AsyncCircuitBreaker(failure_threshold=2, recovery_timeout_s=30.0, clock=clock)

    async def fail_400() -> None:
        raise _HttpError(400, "invalid request")

    async def fail_val() -> None:
        raise ValueError("bad input")

    async def scenario() -> None:
        for _ in range(5):
            with pytest.raises(_HttpError):
                await breaker.call(fail_400)
            with pytest.raises(ValueError):
                await breaker.call(fail_val)

    asyncio.run(scenario())
    assert breaker.stats() == {
        "state": "closed",
        "consecutive_failures": 0,
        "open_count": 0,
        "rejected_calls": 0,
    }


def test_circuit_breaker_closed_open_half_open_recovery_lifecycle() -> None:
    clock = _FakeClock(50.0)
    breaker = AsyncCircuitBreaker(
        failure_threshold=3,
        recovery_timeout_s=30.0,
        half_open_max_calls=2,
        clock=clock,
    )

    async def retryable_fail() -> str:
        raise _HttpError(503, "unavailable")

    async def succeed() -> str:
        return "ok"

    async def scenario() -> None:
        # 3 retryable failures trip the breaker to OPEN.
        for _ in range(3):
            with pytest.raises(_HttpError):
                await breaker.call(retryable_fail)

        assert breaker.state == "open"
        assert breaker.stats()["open_count"] == 1

        # Calls while OPEN are rejected fast without invoking fn.
        called = False

        async def should_not_run() -> str:
            nonlocal called
            called = True
            return "never"

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(should_not_run)
        assert called is False
        assert breaker.stats()["rejected_calls"] == 1

        # Advance clock past recovery_timeout_s -> HALF_OPEN.
        clock.advance(30.0)
        assert breaker.state == "half_open"

        # Probe 1 fails -> immediately re-opens breaker.
        with pytest.raises(_HttpError):
            await breaker.call(retryable_fail)
        assert breaker.state == "open"
        assert breaker.stats()["open_count"] == 2

        # Advance clock again -> HALF_OPEN; 2 successes close the breaker.
        clock.advance(31.0)
        assert breaker.state == "half_open"
        assert await breaker.call(succeed) == "ok"
        assert breaker.state == "half_open"
        assert await breaker.call(succeed) == "ok"
        assert breaker.state == "closed"
        assert breaker.stats()["consecutive_failures"] == 0

    asyncio.run(scenario())


def test_circuit_breaker_half_open_limits_concurrent_probes() -> None:
    clock = _FakeClock(0.0)
    breaker = AsyncCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_s=10.0,
        half_open_max_calls=2,
        clock=clock,
    )

    async def retryable_fail() -> None:
        raise TimeoutError("timed out")

    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await breaker.call(retryable_fail)
        clock.advance(10.0)
        assert breaker.state == "half_open"

        gate = asyncio.Event()

        async def slow_probe() -> str:
            await gate.wait()
            return "done"

        t1 = asyncio.create_task(breaker.call(slow_probe))
        t2 = asyncio.create_task(breaker.call(slow_probe))
        await asyncio.sleep(0)

        # 3rd concurrent probe while 2 are in flight must be rejected.
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(slow_probe)

        gate.set()
        assert await asyncio.gather(t1, t2) == ["done", "done"]
        assert breaker.state == "closed"

    asyncio.run(scenario())

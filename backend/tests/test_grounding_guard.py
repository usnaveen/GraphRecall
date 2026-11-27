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
    query_terms,
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


def test_retrieval_confidence_abstains_on_low_vector_without_graph() -> None:
    low_vec = evaluate_retrieval_confidence(
        chunks=[{"content": "weak", "similarity": 0.41, "note_id": "n1", "parent_chunk_id": "p1"}],
        graph_concepts=[],
        intent="find",
    )
    assert low_vec.should_abstain is True
    assert low_vec.confidence_tier == "low"
    assert low_vec.max_score == pytest.approx(0.41)
    assert low_vec.valid_chunk_indices == {1}


# Shapes taken from the Nov 2026 calibration run on the real corpus: off-topic questions still
# get five chunks (best cosine ~0.55-0.61, RRF exactly 1/61) and ~15 unrelated graph concepts.
_ML_CHUNKS = [
    {"content": "Multi-query attention shares one key and value head across query heads.",
     "similarity": 0.57, "_rrf_score": 1 / 61},
    {"content": "The KV cache stores keys and values from earlier decoding steps.",
     "similarity": 0.55, "_rrf_score": 1 / 62},
]
_ML_CONCEPTS = [{"name": "Multi-Query Attention"}, {"name": "KV Cache"}, {"name": "Transformer"}]


@pytest.mark.parametrize("question", [
    "How do I tune a guitar to drop D?",
    "What is the income tax rate in Norway?",
    "Who won the 1998 FIFA World Cup?",
])
def test_off_topic_question_abstains_even_with_graph_concepts_and_top_rrf(question: str) -> None:
    decision = evaluate_retrieval_confidence(_ML_CHUNKS, _ML_CONCEPTS, "explain", query=question)
    assert decision.should_abstain is True
    assert decision.reason == "off_topic"
    assert decision.term_coverage == 0.0 and decision.concept_coverage == 0.0
    assert "don't seem to cover" in decision.abstention_message


def test_rrf_alone_never_decides() -> None:
    """Rank 1 always scores 1/(k+1); a big RRF value must not rescue an off-topic question."""
    chunks = [dict(c, _rrf_score=0.9) for c in _ML_CHUNKS]
    decision = evaluate_retrieval_confidence(chunks, [], "explain", query="best time to visit Kyoto")
    assert decision.should_abstain is True


def test_in_domain_question_with_moderate_similarity_answers_on_term_coverage() -> None:
    # The GCD question scored only 0.605 cosine but every term is in the passage.
    chunks = [{"content": "The Euclidean algorithm computes the GCD by repeated remainders.", "similarity": 0.605}]
    decision = evaluate_retrieval_confidence(chunks, [], "explain", query="What is the Euclidean algorithm for GCD?")
    assert decision.should_abstain is False
    assert decision.term_coverage == pytest.approx(1.0)
    assert decision.confidence_tier == "medium"


def test_query_naming_a_concept_answers_from_graph() -> None:
    decision = evaluate_retrieval_confidence([], [{"name": "LoRA"}], "explain", query="what is LoRA?")
    assert decision.should_abstain is False
    assert decision.reason == "graph_only_support"


def test_paraphrase_with_no_shared_terms_answers_on_strong_similarity() -> None:
    chunks = [{"content": "The KV cache stores keys and values.", "similarity": 0.78}]
    decision = evaluate_retrieval_confidence(
        chunks, [], "explain", query="why is generating text slow without remembering earlier work?")
    assert decision.should_abstain is False
    assert decision.term_coverage == 0.0
    assert decision.confidence_tier == "medium"


def test_strong_similarity_and_term_match_is_high_tier() -> None:
    chunks = [{"content": "Multi-query attention shares key and value heads.", "similarity": 0.75}]
    decision = evaluate_retrieval_confidence(chunks, _ML_CONCEPTS, "explain", query="What is multi-query attention?")
    assert decision.should_abstain is False
    assert decision.confidence_tier == "high"
    assert decision.reason == "graph_and_chunk_support"


def test_query_terms_drop_question_framing() -> None:
    assert query_terms("How do I tune a guitar to drop D?") == ["tune", "guitar", "drop"]
    assert query_terms("Explain this") == []
    assert query_terms("C4 plants in 1998") == ["c4", "plants", "1998"]


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


# --- citation audit must never corrupt code (review of 97a5503) ------------------------------

def test_verify_citations_leaves_code_and_indexing_alone():
    from backend.services.grounding_guard import verify_citations

    answer = (
        "Two-sum keeps a map of complements [1] and a bad cite [9].\n\n"
        "```python\n"
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n"
        "            return [seen[target - x], i]\n"
        "        seen[x] = i\n"
        "    return [0, 1]\n"
        "```\n"
        "Inline `dp[10] = dp[9] + dp[8]` stays, and so does nums[0] or grid[2][9] in prose."
    )
    audit = verify_citations(answer, valid_chunk_indices={1, 2})
    assert audit.invalid_refs == ["9"] and audit.valid_refs == ["1"]
    assert "a bad cite." in audit.cleaned_text
    for kept in ("        seen[x] = i\n", "    return [0, 1]\n", "`dp[10] = dp[9] + dp[8]`", "nums[0]",
                 "return [seen[target - x], i]", "grid[2][9]"):
        assert kept in audit.cleaned_text, kept


def test_scoped_and_corpus_wide_questions_are_never_off_topic() -> None:
    weak = [{"content": "unrelated", "similarity": 0.5}]
    assert evaluate_retrieval_confidence(weak, [], "explain", query="What is the key idea here?", scoped=True).reason == "scoped_sources"
    assert evaluate_retrieval_confidence(weak, [], "summarize", query="Summarize everything", global_summary=True).should_abstain is False
    for q in ("What are the main themes across my notes?", "What did I add most recently?", "What have I read about LSTMs?"):
        d = evaluate_retrieval_confidence(weak, [], "explain", query=q)
        assert d.should_abstain is False and d.reason == "corpus_reference", q
    # A how-to that merely contains "I read" / "I add" is still checked.
    assert evaluate_retrieval_confidence(weak, [], "explain", query="How do I read a CSV file in pandas?").should_abstain is True


def test_one_shared_word_with_a_concept_name_is_not_enough() -> None:
    """Near-domain questions from the calibration run: one word matches a concept name."""
    concepts = [{"name": "Transformer"}, {"name": "Attention"}, {"name": "Multi-Head Attention"}]
    chunks = [{"content": "Self-attention lets each token weigh every other token.", "similarity": 0.60}]
    for q in ("How does an electrical transformer step down voltage?", "What is attention deficit disorder?"):
        d = evaluate_retrieval_confidence(chunks, concepts, "explain", query=q)
        assert d.should_abstain is True, q
    assert evaluate_retrieval_confidence(chunks, concepts, "explain", query="What is multi-head attention?").should_abstain is False


def test_keyword_only_passages_count_any_term_match() -> None:
    chunks = [{"content": "pgvector HNSW uses iterative scan for filtered queries.", "_rrf_score": 0.03}]
    assert evaluate_retrieval_confidence(chunks, [], "explain", query="How does filtered ANN work?").should_abstain is False
    assert evaluate_retrieval_confidence(chunks, [], "explain", query="How do volcanoes form?").should_abstain is True


def test_general_intent_no_longer_skips_the_guard_for_real_questions() -> None:
    # Regression (eval/grounding/results-2026-11-26.json): the router labelled this "general",
    # and "general" bypassed every check, so an off-topic question was answered from ML notes.
    decision = evaluate_retrieval_confidence(
        _ML_CHUNKS, _ML_CONCEPTS, "general", query="How do I make a sourdough starter?")
    assert decision.should_abstain is True
    assert decision.reason == "off_topic"


def test_general_small_talk_is_still_answered_without_grounding() -> None:
    for text in ("thanks!", "hi there", "ok cool"):
        decision = evaluate_retrieval_confidence(_ML_CHUNKS, _ML_CONCEPTS, "general", query=text)
        assert decision.should_abstain is False, text
        assert decision.reason == "general_small_talk"

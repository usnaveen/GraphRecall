"""Pure unit tests for creative reels-style concept card engines (no DB, no LLM)."""
import json

from backend.services.creative_cards import (
    SPOT_THE_BUG_CARDS,
    TRADEOFF_DUEL_CARDS,
    DiagramOcclusionCard,
    DigestArticlePlan,
    SpotTheBugCard,
    TradeoffDuelCard,
    extract_diagram_cards_from_markdown,
    grade_spot_the_bug,
    is_safe_http_url,
    plan_article_digest,
    select_spot_the_bug,
    select_tradeoff_duel,
)


def test_is_safe_http_url_strict_validation():
    assert is_safe_http_url("https://example.com/arch.png")
    assert is_safe_http_url("http://cdn.example.org:8080/fig/1.svg?v=2")

    # Unsafe schemes
    assert not is_safe_http_url("javascript:alert(1)")
    assert not is_safe_http_url("JAVASCRIPT:alert(document.cookie)")
    assert not is_safe_http_url("data:image/png;base64,iVBORw0KGgo=")
    assert not is_safe_http_url("file:///etc/passwd")
    assert not is_safe_http_url("ftp://example.com/a.png")

    # Missing host / empty / malformed
    assert not is_safe_http_url("")
    assert not is_safe_http_url(None)
    assert not is_safe_http_url("https:///missing-host.png")
    assert not is_safe_http_url("http://")
    assert not is_safe_http_url("https://[invalid-ipv6")

    # Control characters and embedded whitespace
    assert not is_safe_http_url("https://example.com/a\x00b.png")
    assert not is_safe_http_url("https://example.com/a\nb.png")
    assert not is_safe_http_url("https://example.com/a\rb.png")
    assert not is_safe_http_url("https://example.com/a\tb.png")
    assert not is_safe_http_url("https://example.com/a\x7fb.png")
    assert not is_safe_http_url("https://exa mple.com/a.png")


def test_extract_mermaid_flowchart_occlusion_and_distractors():
    md = """# Hybrid RAG Pipeline

```mermaid
flowchart TD
    S[Start] --> A["Query Rewriter"]
    A --> B[Dense Vector Search]
    B --> C(BM25 Lexical Search)
    C --> D((Reciprocal Rank Fusion))
    D --> E{Cross-Encoder Reranker}
    E --> X[End]
    X --> Y[ok]
```
"""
    cards = extract_diagram_cards_from_markdown(
        md,
        source_title="RAG Architecture",
        source_url="https://example.com/rag",
        concept_id="c-rag",
    )
    assert len(cards) == 1
    card = cards[0]
    assert isinstance(card, DiagramOcclusionCard)
    assert card.kind == "mermaid"
    assert card.title == "Hybrid RAG Pipeline"
    assert card.source_url == "https://example.com/rag"
    assert card.concept_id == "c-rag"

    # Generic Start/End and short labels (<4 chars like "ok") must never be occluded
    assert 1 <= len(card.answer_key) <= 3
    for slot_key, answer in card.answer_key.items():
        assert answer.lower() not in {"start", "end", "ok"}
        assert len(answer) >= 4
        assert f"[{slot_key}]" in (card.occluded_mermaid or "")
        assert answer not in (card.occluded_mermaid or "")

    # Sibling non-occluded nodes become distractors
    assert len(card.distractors) >= 2
    assert set(card.answer_key.values()).isdisjoint(set(card.distractors))
    assert all(d.lower() not in {"start", "end", "ok"} for d in card.distractors)
    assert set(card.options) == set(card.answer_key.values()) | set(card.distractors)


def test_extract_mermaid_sequence_diagram():
    md = """## Request Auth Flow

```mermaid
sequenceDiagram
    participant C as Mobile Client
    participant G as API Gateway
    participant R as Redis Limiter
    C->>G: Send Bearer Token
    G->>R: Check Sliding Window
    R-->>G: Allow Request
```
"""
    cards = extract_diagram_cards_from_markdown(md, source_title="Auth Flow")
    assert len(cards) == 1
    card = cards[0]
    assert card.kind == "mermaid"
    assert 1 <= len(card.answer_key) <= 3
    for slot_key, answer in card.answer_key.items():
        assert f"[{slot_key}]" in (card.occluded_mermaid or "")
        assert len(answer) >= 4


def test_extract_markdown_figures_rejects_unsafe_urls_and_trivial_captions():
    md = """## System Diagrams

![ok](https://example.com/trivial-short-cap.png)
![High-level KV cache layout across transformer layers](https://cdn.example.com/kv-cache.png)
![XSS attempt diagram](javascript:alert(1))
![Data URI payload diagram](data:image/svg+xml,<svg/>)
![Local file leak diagram](file:///etc/passwd)
![Missing host diagram](https:///nohost/diagram.png)
![Control char diagram](https://example.com/bad\x07path.png)

```markdown
![Should ignore inside fenced code](https://example.com/ignored.png)
```
"""
    cards = extract_diagram_cards_from_markdown(md, source_title="Transformer Notes")
    assert len(cards) == 1
    fig = cards[0]
    assert fig.kind == "figure"
    assert fig.image_url == "https://cdn.example.com/kv-cache.png"
    assert fig.caption == "High-level KV cache layout across transformer layers"
    assert "architecture" in fig.prompt.lower() or "takeaway" in fig.prompt.lower()


def test_spot_the_bug_catalog_invariants_and_grading():
    assert len(SPOT_THE_BUG_CARDS) == 8
    ids = [c.id for c in SPOT_THE_BUG_CARDS]
    assert len(set(ids)) == 8

    expected_ids = {
        "bug-post-ann-filter",
        "bug-data-leakage-scaler",
        "bug-prompt-prefix-cache-bust",
        "bug-semantic-cache-guard",
        "bug-fsrs-null-due-flood",
        "bug-retry-storm-429",
        "bug-binary-search-loop",
        "bug-softmax-overflow",
    }
    assert set(ids) == expected_ids

    for card in SPOT_THE_BUG_CARDS:
        assert isinstance(card, SpotTheBugCard)
        assert 6 <= len(card.lines) <= 10, f"{card.id} has {len(card.lines)} lines"
        assert 1 <= card.buggy_line_index <= len(card.lines)
        assert card.fixed_line.strip()
        assert card.explanation.strip()
        assert card.concept_name.strip()
        assert json.dumps(card.as_dict())

    # Selection by concept/tag and exclude_ids
    picked = select_spot_the_bug(["pgvector", "multi-tenant"])
    assert picked is not None and picked.id == "bug-post-ann-filter"

    picked_next = select_spot_the_bug(["pgvector", "multi-tenant"], exclude_ids=["bug-post-ann-filter"])
    assert picked_next is not None and picked_next.id != "bug-post-ann-filter"

    assert select_spot_the_bug(["anything"], exclude_ids=ids) is None

    # Grading contract aligned with knowledge_map
    bs_card = select_spot_the_bug(["Binary Search"])
    assert bs_card is not None and bs_card.id == "bug-binary-search-loop"

    right = grade_spot_the_bug(bs_card, bs_card.buggy_line_index)
    assert right["correct"] is True
    assert right["selected_line"] == bs_card.buggy_line_index
    assert right["buggy_line_index"] == bs_card.buggy_line_index
    assert right["fixed_line"] == bs_card.fixed_line
    assert right["evidence"]["signal_type"] == "quiz_correct"
    assert right["evidence"]["score"] == 0.85
    assert right["evidence"]["concept_name"] == bs_card.concept_name
    assert right["evidence"]["metadata"]["card_id"] == bs_card.id

    wrong_line = 1 if bs_card.buggy_line_index != 1 else 2
    wrong = grade_spot_the_bug(bs_card, wrong_line)
    assert wrong["correct"] is False
    assert wrong["selected_line"] == wrong_line
    assert wrong["evidence"]["signal_type"] == "quiz_wrong"
    assert wrong["evidence"]["score"] == 0.10
    assert wrong["evidence"]["concept_name"] == bs_card.concept_name


def test_tradeoff_duel_catalog_and_selection():
    assert len(TRADEOFF_DUEL_CARDS) == 6
    ids = [c.id for c in TRADEOFF_DUEL_CARDS]
    assert len(set(ids)) == 6

    expected_ids = {
        "duel-pgvector-hnsw-vs-ivfflat",
        "duel-redis-lua-vs-postgres-limiter",
        "duel-cross-encoder-vs-rrf",
        "duel-explicit-vs-implicit-prompt-cache",
        "duel-evidence-ledger-vs-mutable-score",
        "duel-wkwebview-vs-server-exec",
    }
    assert set(ids) == expected_ids

    for card in TRADEOFF_DUEL_CARDS:
        assert isinstance(card, TradeoffDuelCard)
        assert card.recommended in {"a", "b", "depends"}
        assert card.option_a.strip() and card.option_b.strip()
        assert card.winning_rationale.strip()
        assert card.when_other_wins.strip()
        assert card.scenario.strip()
        assert json.dumps(card.as_dict())

    duel = select_tradeoff_duel(["Cross-Encoder", "RRF"])
    assert duel is not None and duel.id == "duel-cross-encoder-vs-rrf"

    sandbox_duel = select_tradeoff_duel(["WKWebView", "Sandbox"])
    assert sandbox_duel is not None and sandbox_duel.id == "duel-wkwebview-vs-server-exec"

    assert select_tradeoff_duel(["RAG"], exclude_ids=ids) is None


def test_plan_article_digest_extracts_diagrams_claims_terms_and_bounds_cards():
    article = """# Production RAG Architecture

**HNSW**: Hierarchical Navigable Small World graph for fast approximate nearest neighbors.
**Cross-Encoder**: Joint query-document transformer scorer used for second-stage reranking.

## Retrieval Pipeline
- Hybrid Search: combining dense embeddings with BM25 keyword scores via RRF
- Semantic Caching: reusing verified answers when tenant and corpus version match
- Always filter by tenant before applying the vector LIMIT clause in Postgres.

```mermaid
flowchart LR
    U[Start] --> Q["Query Encoder"]
    Q --> H[HNSW Vector Index]
    H --> R(Cross-Encoder Rerank)
    R --> L((LLM Generator))
```

![End-to-end multi-tenant RAG serving topology](https://cdn.example.com/rag-topology.png)
![Ignored unsafe figure](javascript:alert(1))
"""
    plan = plan_article_digest(
        title="Production RAG Architecture",
        markdown_text=article,
        source_url="https://substack.example.com/p/production-rag",
        max_cards=4,
    )
    assert isinstance(plan, DigestArticlePlan)
    assert plan.source_url == "https://substack.example.com/p/production-rag"
    assert plan.source_url_valid is True
    assert plan.total_cards <= 4
    assert plan.total_cards == len(plan.cards)
    assert len(plan.diagram_cards) == 2
    assert len(plan.claims) >= 1
    assert any(t in plan.terms for t in ("RAG", "HNSW", "BM25", "RRF", "LLM"))

    # JSON serializable for agent_jobs / feed persistence
    serialized = json.dumps(plan.as_dict())
    assert "Production RAG Architecture" in serialized

    # Unsafe source_url is rejected/sanitized and max_cards=0 bounds output to 0 cards
    unsafe_plan = plan_article_digest(
        title="Bad URL Article",
        markdown_text=article,
        source_url="javascript:alert(1)",
        max_cards=0,
    )
    assert unsafe_plan.source_url is None
    assert unsafe_plan.source_url_valid is False
    assert unsafe_plan.total_cards == 0
    assert unsafe_plan.cards == []

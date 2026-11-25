"""Follow-up anchoring for retrieval (no LLM)."""
from backend.services.query_rewrite import contextualize, is_followup


def test_followups_are_anchored_to_previous_entities_or_question():
    assert contextualize("what are its limitations?", "Explain LoRA", ["LoRA"]) == \
        "what are its limitations? (about: LoRA)"
    assert contextualize("and for transformers?", "How does dropout work", []) == \
        "and for transformers? (about: How does dropout work)"
    assert contextualize("example?", "What is backpropagation", ["Backpropagation"]).endswith("(about: Backpropagation)")


def test_standalone_questions_are_untouched():
    q = "How does HNSW build its graph layers for approximate search"
    assert contextualize(q, "Explain LoRA", ["LoRA"]) != q  # "its" makes this ambiguous: anchored
    assert contextualize("Compare BM25 and dense retrieval for long documents", "Explain LoRA", ["LoRA"]) == \
        "Compare BM25 and dense retrieval for long documents"
    assert contextualize("what are its limitations?", None, None) == "what are its limitations?"
    assert not is_followup("Explain LoRA", has_history=False)


def test_entities_already_in_query_are_not_repeated():
    assert contextualize("why does LoRA work?", "Explain LoRA", ["LoRA"]) == "why does LoRA work?"

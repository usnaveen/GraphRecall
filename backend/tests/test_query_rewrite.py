"""Follow-up anchoring for retrieval (no LLM)."""
from backend.services.query_rewrite import contextualize, is_followup


def test_followups_are_anchored_to_previous_entities_or_question():
    assert contextualize("what are its limitations?", "Explain LoRA", ["LoRA"]) == (
        "what are its limitations? LoRA"
    )
    assert contextualize("and for transformers?", "How does dropout work", []) == (
        "and for transformers? dropout"
    )
    assert contextualize("example?", "What is backpropagation", ["Backpropagation"]) == (
        "example? Backpropagation"
    )
    assert contextualize("compare with QLoRA", "Explain LoRA", ["LoRA"]) == (
        "compare with QLoRA LoRA"
    )
    assert contextualize("why?", "Explain LoRA", ["LoRA"]) == "why? LoRA"
    assert contextualize("give an example", "Explain LoRA", ["LoRA"]) == (
        "give an example LoRA"
    )
    assert contextualize("how does that work?", "Explain LoRA", ["LoRA"]) == (
        "how does that work? LoRA"
    )


def test_no_about_punctuation_wrapper_for_websearch_tsquery():
    out = contextualize("what are its limitations?", "Explain LoRA", ["LoRA", "PEFT"])
    assert "(about:" not in out
    assert out == "what are its limitations? LoRA PEFT"


def test_standalone_questions_and_topic_shifts_are_untouched():
    q = "How does HNSW build its graph layers for approximate search"
    assert contextualize(q, "Explain LoRA", ["LoRA"]) != q  # "its" makes this ambiguous: anchored
    assert contextualize("Compare BM25 and dense retrieval for long documents", "Explain LoRA", ["LoRA"]) == (
        "Compare BM25 and dense retrieval for long documents"
    )
    # Generic question words on >=5-word topic shifts without pronouns must NOT trigger anchoring.
    for topic_shift in [
        "Why do relational databases use B-trees instead of hash indexes?",
        "And how does PostgreSQL MVCC handle vacuuming?",
        "So how do transformers compute attention weights?",
        "Then what is the difference between TCP and UDP?",
        "But how does flash attention reduce HBM reads?",
    ]:
        assert not is_followup(topic_shift, has_history=True)
        assert contextualize(topic_shift, "Explain LoRA", ["LoRA"]) == topic_shift

    assert contextualize("what are its limitations?", None, None) == "what are its limitations?"
    assert contextualize("what are its limitations?", "   ", ["  ", ""]) == "what are its limitations?"
    assert contextualize("what are its limitations?", "hello!", []) == "what are its limitations?"
    assert not is_followup("Explain LoRA", has_history=False)


def test_entities_already_in_query_are_checked_on_word_boundaries():
    assert contextualize("why does LoRA work?", "Explain LoRA", ["LoRA"]) == "why does LoRA work?"
    # "AI" appears inside "explain", and "R" appears inside "transformers" — must NOT falsely suppress!
    assert contextualize("why explain it?", "What is AI", ["AI"]) == "why explain it? AI"
    assert contextualize("and for transformers?", "Explain R", ["R"]) == "and for transformers? R"

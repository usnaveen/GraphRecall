"""What the SSE stream sends after the tokens, and what gets saved (review of 97a5503, item 3)."""
from backend.routers.chat import finalize_stream_text


def test_cache_hit_sends_everything_once():
    assert finalize_stream_text("", "Answer [1].") == ([{"type": "chunk", "content": "Answer [1]."}], "Answer [1].")


def test_appended_figures_send_only_the_tail():
    events, saved = finalize_stream_text("Answer [1].", "Answer [1].\n\n![fig](u)")
    assert events == [{"type": "chunk", "content": "\n\n![fig](u)"}] and saved.endswith("![fig](u)")


def test_cleaned_text_replaces_what_was_streamed_and_is_what_gets_saved():
    events, saved = finalize_stream_text("Answer [1] and [9].", "Answer [1] and.")
    assert events == [{"type": "replace", "content": "Answer [1] and."}] and saved == "Answer [1] and."


def test_identical_text_sends_nothing():
    assert finalize_stream_text("Same.", "Same.") == ([], "Same.")


def test_prompt_control_blocks_echoed_by_the_model_are_removed():
    import importlib

    cg = importlib.import_module("backend.graphs.chat_graph")
    assert cg.strip_prompt_echo("<intent>explain</intent>\n\nSelf-attention [1].") == "Self-attention [1]."
    assert cg.strip_prompt_echo("<intent>x</intent><retrieved_context>\n[1] a\n</retrieved_context>\nAnswer") == "Answer"
    assert cg.strip_prompt_echo("Use <intent> tags like <intent>x</intent> mid-answer") == \
        "Use <intent> tags like <intent>x</intent> mid-answer"

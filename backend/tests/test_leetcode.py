"""LeetCode recall cards: built from the user's own pattern, pseudocode and mistakes."""
from backend.services.leetcode import build_cards, pseudocode_cloze

PSEUDO = """def lengthOfLongestSubstring(s):
    seen = {}
    left = best = 0
    for right, ch in enumerate(s):
        if ch in seen and seen[ch] >= left:
            left = seen[ch] + 1
        seen[ch] = right
        best = max(best, right - left + 1)
    return best"""


def test_pseudocode_cloze_hides_key_lines_keeps_signature_and_indent():
    cloze, hidden = pseudocode_cloze(PSEUDO)
    lines = cloze.split("\n")
    assert hidden == 3 and lines[0].startswith("def ")
    assert sum("[___]" in l for l in lines) == 3
    for orig, new in zip(PSEUDO.split("\n"), lines):
        if "[___]" in new:  # indentation preserved
            assert new.index("[") == len(orig) - len(orig.lstrip())
    assert "best = max(best, right - left + 1)" not in cloze  # the core update is hidden


def test_short_pseudocode_makes_no_cloze():
    assert pseudocode_cloze("x = 1") == ("", 0)


def test_build_cards_all_kinds():
    problem = {"title": "Longest Substring Without Repeating Characters", "pattern": "Sliding Window",
               "key_insight": "Move left past the last repeat", "complexity": "O(n)", "pseudocode": PSEUDO}
    attempts = [{"mistake": "Forgot seen[ch] >= left, so left jumped backwards", "mistake_tag": "edge_case"},
                {"mistake": "", "mistake_tag": None}]
    cards = build_cards(problem, attempts)
    assert [c.kind for c in cards] == ["pattern", "pseudocode", "mistake"]
    assert "Pattern: Sliding Window" in cards[0].back and "O(n)" in cards[0].back
    assert "(missed an edge case)" in cards[2].front
    assert cards[2].back.startswith("Forgot")

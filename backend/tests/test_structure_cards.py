"""Cards from note structure: bullet lists and Term: definition lines, no LLM."""
from backend.services.structure_cards import extract_structure_cards, pick_concept_id

NOTE = """# Supervised learning

Learning a mapping from labelled examples.

Types of supervised learning:
- Classification: predicting a discrete label from features
- Regression: predicting a continuous value from features

## Steps to train a model
1. Split the data
2. Fit on the training set
3. Tune on validation
4. Report on test

Overfitting: the model memorises noise in the training data
Note: revise this before Friday
See: https://example.com/notes

```python
x: int = 3
```
"""


def test_lists_and_definitions():
    cards = extract_structure_cards(NOTE)
    kinds = [(c.kind, c.anchor) for c in cards]
    assert ("list", "Types of supervised learning") in kinds
    assert ("list", "Steps to train a model") in kinds
    assert ("definition", "Classification") in kinds
    assert ("definition", "Regression") in kinds
    assert ("definition", "Overfitting") in kinds
    # "Note: revise..." and "See: url" are not definitions; code blocks are ignored
    assert not any(c.anchor.lower() in {"note", "see", "x"} for c in cards)

    steps = next(c for c in cards if c.anchor == "Steps to train a model")
    assert steps.front.startswith("Steps to train a model: 4 points (in order)")
    assert steps.front.count("[___]") == 4
    assert steps.back.splitlines()[1] == "2. Fit on the training set"

    ov = next(c for c in cards if c.anchor == "Overfitting")
    assert ov.front == "Overfitting: [___]"
    assert ov.back == "the model memorises noise in the training data"


def test_ocr_style_bullets_and_no_lead():
    ocr = "Causes of WW1:\n• Militarism\n• Alliances\n• Imperialism\n• Nationalism\n\n• stray\n• list"
    cards = extract_structure_cards(ocr)
    assert len(cards) == 1 and cards[0].items == ["Militarism", "Alliances", "Imperialism", "Nationalism"]


def test_limits():
    big = "Things:\n" + "\n".join(f"- item {i}" for i in range(12))
    assert extract_structure_cards(big) == []  # too long to recall as one card
    many = "\n".join(f"Term{i}: definition number {i} is here" for i in range(30))
    assert len(extract_structure_cards(many)) == 12


def test_pick_concept_id():
    concepts = [{"id": "c1", "name": "Supervised Learning"}, {"id": "c2", "name": "Overfitting"},
                {"id": "c3", "name": "Learning"}]
    assert pick_concept_id("Types of supervised learning", concepts, "fb") == "c1"
    assert pick_concept_id("Overfitting", concepts, "fb") == "c2"
    assert pick_concept_id("Causes of WW1", concepts, "fb") == "fb"


def test_generic_terms_get_heading_context_or_are_dropped():
    text = "## Breadth-First Search\nBehavior: moves layer by layer like ripples\nTime Complexity: O(V + E) for adjacency lists\n"
    fronts = [c.front for c in extract_structure_cards(text)]
    assert fronts == ["Breadth-First Search · Behavior: [___]", "Breadth-First Search · Time Complexity: [___]"]
    assert extract_structure_cards("Pros: even distribution of the data") == []


def test_transcripts_dates_and_times_are_not_definitions():
    text = ("User: can you explain how attention works in detail\n"
            "Assistant: attention weighs every token against the others\n"
            "John C. Petersen (November 2, 1842: July 10, 1887) was an American butcher\n"
            "10:30 standup with the whole team today\n")
    assert extract_structure_cards(text) == []

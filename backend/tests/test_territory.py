"""Map-the-territory grading: name a concept's subtopics, matched without an LLM."""
from backend.services.territory import card_content, grade, split_answer

KIDS = [{"id": str(i), "name": n} for i, n in enumerate([
    "Classification", "Regression", "Support Vector Machines", "Decision Trees",
    "K-Nearest Neighbors", "Recurrent Neural Network"])]


def test_split_answer_handles_commas_ands_numbers_and_newlines():
    assert split_answer("classification, regression and SVMs\n1. decision trees 2. knn") == [
        "classification", "regression", "SVMs", "decision trees", "knn"]


def test_grade_matches_acronyms_plurals_typos_and_reports_missed():
    g = grade(KIDS, "regresion, classification, SVM, decision tree, RNN, gradient boosting")
    names = {m["name"] for m in g.matched}
    assert names == {"Regression", "Classification", "Support Vector Machines", "Decision Trees",
                     "Recurrent Neural Network"}
    assert [m["name"] for m in g.missed] == ["K-Nearest Neighbors"]
    assert g.extras == ["gradient boosting"]
    assert g.score == round(5 / 6, 3) and g.suggested == "good"


def test_one_item_cannot_match_two_children_and_empty_answer_is_again():
    kids = [{"id": "a", "name": "Phase 1 Trial"}, {"id": "b", "name": "Phase 2 Trial"}]
    g = grade(kids, "phase 1 trial")
    assert len(g.matched) == 1 and g.matched[0]["id"] == "a"
    assert grade(kids, "").suggested == "again"


def test_card_content_ships_children_for_offline_grading():
    c = card_content({"name": "Supervised Learning", "definition": "x" * 400, "children": KIDS})
    assert c["count"] == 6 and c["prompt"] == "Supervised Learning: name its parts"
    assert len(c["parent_definition"]) == 280

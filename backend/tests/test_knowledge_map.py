"""Knowledge map scoring and name resolution (pure functions; no DB)."""
from datetime import datetime, timedelta, timezone

from backend.services.knowledge_map import (
    Evidence, grade_signal, match_concept, score, skill_key,
)

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)


def _concepts(*names):
    return [{"id": str(i), "name": n, "_key": skill_key(n), "_words": set(skill_key(n).split())}
            for i, n in enumerate(names)]


def test_unexposed_when_nothing_known():
    assert score([], in_graph=False, self_rating=None, now=NOW)[0] == "unexposed"


def test_studied_but_untested_is_seen():
    status, m, _, basis = score([Evidence("note", 0.35, 0.3)], in_graph=True, self_rating=None, now=NOW)
    assert status == "seen" and basis == "studied"


def test_tested_well_is_strong_and_tested_badly_is_shaky():
    good = [Evidence("note", 0.35, 0.3), Evidence("review", 0.9, 2.0, NOW), Evidence("quiz", 0.85, 1.0, NOW)]
    assert score(good, in_graph=True, self_rating=None, now=NOW)[0] == "strong"
    bad = [Evidence("note", 0.35, 0.3), Evidence("review", 0.3, 2.0, NOW)]
    assert score(bad, in_graph=True, self_rating=None, now=NOW)[0] == "shaky"


def test_old_reviews_fade_so_self_rating_takes_over():
    old = NOW - timedelta(days=400)
    ev = [Evidence("review", 0.2, 2.0, old), Evidence("self_rating", 0.85, 0.6, NOW)]
    status, m, _, _ = score(ev, in_graph=True, self_rating=4, now=NOW)
    assert m > 0.7 and status == "strong"


def test_self_rating_never_means_unexposed_and_strong_self_rating_counts():
    assert score([Evidence("self_rating", 0.0, 0.6, NOW)], in_graph=False, self_rating=0, now=NOW)[0] == "unexposed"
    s = score([Evidence("self_rating", 0.85, 0.6, NOW)], in_graph=False, self_rating=4, now=NOW)
    assert s[0] == "strong" and s[3] == "self-reported"


def test_course_grade_alone_can_be_strong_coursework():
    s = score([Evidence("course", grade_signal("A"), 0.8, NOW)], in_graph=False, self_rating=None, now=NOW)
    assert s[0] == "strong" and s[3] == "coursework"


def test_children_lend_mastery_when_no_direct_evidence():
    s = score([Evidence("note", 0.35, 0.3)], in_graph=True, self_rating=None, now=NOW, child_mastery=0.9)
    assert s[1] > 0.6


def test_grade_signal_scales():
    assert grade_signal("A") == 0.85 and grade_signal("S") == 0.88
    assert abs(grade_signal("8.5") - 0.8075) < 1e-3 and abs(grade_signal("72%") - 0.684) < 1e-3
    assert grade_signal("") == 0.6


def test_match_concept_is_conservative():
    cs = _concepts("Linear Algebra", "Support Vector Machine (SVM)", "Python Data Science Handbook",
                   "Recurrent Neural Network", "Python")
    assert match_concept("linear algebra", cs)["name"] == "Linear Algebra"
    assert match_concept("SVM", cs)["name"] == "Support Vector Machine (SVM)"
    assert match_concept("RNNs", cs)["name"] == "Recurrent Neural Network"
    assert match_concept("python", cs)["name"] == "Python"           # not the handbook
    assert match_concept("Kubernetes", cs) is None

"""Audit the quality of LLM-extracted PREREQUISITE_OF links.

sample.jsonl holds 120 links drawn (seed 11) from the 598 PREREQUISITE_OF edges in the demo learner's
graph, which ingestion extracted with Gemini. Each labeller writes labels.<who>.jsonl with one of:

  correct     a teacher would teach A before B because B builds on A
  loose       true but distant or umbrella ("Big O -> Counting Sort")
  part_of     order fine, but it is a subtopic / variant / component, not a prerequisite
  not_prereq  unrelated in that direction, or merely related
  inverted    B is actually needed for A
  unclear     genuinely debatable

    python eval/graph_edges/score.py            # per labeller rates + 95% Wilson CIs; Cohen's kappa if 2+ labellers

Why it matters: the MCP teaching plan, feed prerequisite backtracking and follow-up suggestions all walk
these links. A wrong or inverted link sends the learner to the wrong concept first.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = ("correct", "loose", "part_of", "not_prereq", "inverted", "unclear")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d, (c + r) / d


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main() -> None:
    sample = {r["n"]: r for r in map(json.loads, (HERE / "sample.jsonl").open())}
    labellers = {}
    for f in sorted(HERE.glob("labels.*.jsonl")):
        rows = {r["n"]: r["label"] for r in map(json.loads, f.open())}
        assert set(rows) == set(sample), f"{f.name} must label every row"
        assert set(rows.values()) <= set(LABELS), f"{f.name} has unknown labels"
        labellers[f.name.split(".")[1]] = rows
    for who, rows in labellers.items():
        c, n = Counter(rows.values()), len(rows)
        print(f"\n== {who} (n={n})")
        for name, keys in [("strictly correct", ("correct",)),
                           ("order right (correct + loose + part_of)", ("correct", "loose", "part_of")),
                           ("wrong (not_prereq + inverted)", ("not_prereq", "inverted")),
                           ("inverted", ("inverted",))]:
            k = sum(c[x] for x in keys)
            lo, hi = wilson(k, n)
            print(f"  {name:42s} {k / n:.2f}  [{lo:.2f}, {hi:.2f}]")
    if len(labellers) >= 2:
        (wa, a), (wb, b) = list(labellers.items())[:2]
        ids = sorted(sample)
        la, lb = [a[i] for i in ids], [b[i] for i in ids]
        coarse = lambda l: "ok" if l in ("correct", "loose", "part_of") else ("wrong" if l in ("not_prereq", "inverted") else "unclear")  # noqa: E731
        print(f"\nagreement {wa} vs {wb}: exact {sum(x == y for x, y in zip(la, lb)) / len(ids):.2f}, "
              f"Cohen's kappa {kappa(la, lb):.2f} (6 labels), {kappa([coarse(x) for x in la], [coarse(x) for x in lb]):.2f} (ok / wrong / unclear)")
        print("\ndisagreements on ok vs wrong (for a human to settle):")
        for i in ids:
            if coarse(a[i]) != coarse(b[i]):
                print(f"  {i:3d}. {sample[i]['prerequisite']} -> {sample[i]['of']}:  {wa}={a[i]}  {wb}={b[i]}")


if __name__ == "__main__":
    main()

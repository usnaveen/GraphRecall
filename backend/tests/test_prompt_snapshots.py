"""Prompt regression guard: a prompt change must be deliberate and visible in review.

If one of these fails you changed a prompt. Check the answer and extraction behaviour (rerun
eval/graphrag/run_eval.py and eval/retrieval/), then refresh the snapshot:

    python -m backend.tests.test_prompt_snapshots --update

The answer prompt's hash is also its version: it is stored with every answer
(meta_json.generation.prompt_version) and keys the answer cache, so old cached answers never
outlive a prompt change."""

import hashlib
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = Path(__file__).resolve().parent / "snapshots"
cg = importlib.import_module("backend.graphs.chat_graph")


def test_answer_system_prompt_matches_snapshot():
    assert cg.ANSWER_SYSTEM_PROMPT == (SNAP / "answer_system_prompt.txt").read_text(), (
        "ANSWER_SYSTEM_PROMPT changed: rerun the answer evals, then refresh the snapshot (see module doc)")


def test_template_prompts_match_snapshot_hashes():
    for name in ("extraction.txt", "synthesis.txt"):
        got = hashlib.sha256((ROOT / "backend/prompts" / name).read_bytes()).hexdigest()
        assert got == (SNAP / f"{name}.sha256").read_text().strip(), f"backend/prompts/{name} changed"


def test_prompt_version_is_recorded_with_answers():
    assert len(cg._answer_cache_tag()) == 12


if __name__ == "__main__" and "--update" in sys.argv:
    (SNAP / "answer_system_prompt.txt").write_text(cg.ANSWER_SYSTEM_PROMPT)
    for name in ("extraction.txt", "synthesis.txt"):
        digest = hashlib.sha256((ROOT / "backend/prompts" / name).read_bytes()).hexdigest()
        (SNAP / f"{name}.sha256").write_text(digest + "\n")
    print("prompt snapshots updated")

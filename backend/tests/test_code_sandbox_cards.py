"""Pure unit tests for Step #8 on-device code-completion sandbox cards."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import replace

import pytest

from backend.services.code_sandbox_cards import (
    SANDBOX_CHALLENGES,
    CodeSandboxChallenge,
    CodeSandboxSubmission,
    CodeSandboxTestCase,
    build_sandbox_feed_payload,
    compute_sandbox_evidence,
    select_sandbox_challenge,
    validate_challenge_safety,
)


def _find_node() -> str | None:
    if os.path.exists("/opt/homebrew/bin/node"):
        return "/opt/homebrew/bin/node"
    return shutil.which("node")


def _run_js_challenge(code: str, test_cases: list[CodeSandboxTestCase], node_bin: str) -> tuple[int, int, list[dict]]:
    payload = json.dumps(
        {
            "code": code,
            "tests": [
                {"name": tc.name, "expression": tc.expression, "expected": tc.expected_repr}
                for tc in test_cases
            ],
        }
    )
    harness = r"""
const payload = JSON.parse(process.argv[1]);
function normalize(v) {
  if (Object.is(v, -0)) return 0;
  if (Array.isArray(v)) return v.map(normalize);
  if (v && typeof v === "object") {
    const out = {};
    for (const k of Object.keys(v).sort()) out[k] = normalize(v[k]);
    return out;
  }
  return v;
}
let fnFactory;
try {
  fnFactory = new Function(payload.code + "\n;return function(__expr__) { return eval(__expr__); };");
} catch (err) {
  console.log(JSON.stringify({ passed: 0, total: payload.tests.length, results: [], error: String(err) }));
  process.exit(0);
}
const evalExpr = fnFactory();
let passed = 0;
const results = [];
for (const tc of payload.tests) {
  try {
    const actual = evalExpr(tc.expression);
    const expected = JSON.parse(tc.expected);
    const ok = JSON.stringify(normalize(actual)) === JSON.stringify(normalize(expected));
    if (ok) passed += 1;
    results.push({ name: tc.name, passed: ok, actual: JSON.stringify(actual), expected: tc.expected });
  } catch (err) {
    results.push({ name: tc.name, passed: false, error: String(err), expected: tc.expected });
  }
}
console.log(JSON.stringify({ passed, total: payload.tests.length, results }));
"""
    proc = subprocess.run(
        [node_bin, "-e", harness, payload],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    data = json.loads(proc.stdout.strip())
    return data["passed"], data["total"], data["results"]


def test_curated_library_has_ten_unique_safe_challenges():
    assert len(SANDBOX_CHALLENGES) == 10
    assert len({c.id for c in SANDBOX_CHALLENGES}) == 10
    for ch in SANDBOX_CHALLENGES:
        assert ch.language == "javascript"
        assert len(ch.test_cases) >= 3
        assert validate_challenge_safety(ch) == []


@pytest.mark.parametrize(
    "bad_snippet",
    [
        "fetch('https://evil.example')",
        "new XMLHttpRequest()",
        "new WebSocket('wss://evil.example')",
        "localStorage.getItem('token')",
        "sessionStorage.setItem('x', '1')",
        "indexedDB.open('db')",
        "const c = document.cookie;",
        "window.location = 'https://evil.example';",
        "window.open('https://evil.example');",
        "importScripts('x.js');",
        "eval('1+1')",
        "new Function('return 1')()",
    ],
)
def test_validate_challenge_safety_rejects_disallowed_apis(bad_snippet: str):
    base = SANDBOX_CHALLENGES[0]
    unsafe = replace(base, starter_code=base.starter_code + "\n" + bad_snippet)
    violations = validate_challenge_safety(unsafe)
    assert violations, f"Expected violation for {bad_snippet}"


def test_validate_challenge_safety_rejects_unsafe_test_expression():
    base = SANDBOX_CHALLENGES[0]
    bad_test = CodeSandboxTestCase(name="exfil", expression="fetch('https://x')", expected_repr="null")
    unsafe = replace(base, test_cases=[bad_test])
    violations = validate_challenge_safety(unsafe)
    assert any("test_cases[0].expression" in v for v in violations)


def test_select_sandbox_challenge_matches_concepts_patterns_difficulty_and_exclusions():
    ch1 = select_sandbox_challenge(["Reciprocal Rank Fusion", "Vector Search"])
    assert ch1.id == "reciprocal-rank-fusion"

    ch2 = select_sandbox_challenge(["Unknown Topic"], weak_patterns=["Monotonic Stack"])
    assert ch2.id == "monotonic-stack-next-greater"

    ch3 = select_sandbox_challenge(["Sliding Window"], difficulty="hard")
    assert ch3.difficulty == "hard"

    ch4 = select_sandbox_challenge(["Cosine Similarity"], exclude_ids=["cosine-similarity"])
    assert ch4.id != "cosine-similarity"

    all_ids = [c.id for c in SANDBOX_CHALLENGES]
    fallback = select_sandbox_challenge(["Softmax"], exclude_ids=all_ids)
    assert isinstance(fallback, CodeSandboxChallenge)


def test_build_sandbox_feed_payload_schema_and_safety_guard():
    ch = SANDBOX_CHALLENGES[0]
    payload = build_sandbox_feed_payload(ch)
    assert payload["item_type"] == "code_sandbox"
    assert payload["card_type"] == "code_sandbox"
    assert payload["concept_name"] == ch.concept_name
    content = payload["content"]
    assert content["card_type"] == "code_sandbox"
    assert content["challenge_id"] == ch.id
    assert content["language"] == "javascript"
    assert content["starter_code"] == ch.starter_code
    assert content["solution_code"] == ch.solution_code
    assert len(content["test_cases"]) == len(ch.test_cases)

    unsafe = replace(ch, solution_code="eval('2+2')")
    with pytest.raises(ValueError, match="Unsafe challenge"):
        build_sandbox_feed_payload(unsafe)


def test_compute_sandbox_evidence_scoring_and_zero_test_guard():
    full_pass = compute_sandbox_evidence(
        CodeSandboxSubmission("cosine-similarity", "c1", "Cosine Similarity", 5, 5, "ok", 42)
    )
    assert full_pass["signal_type"] == "code_sandbox_pass"
    assert full_pass["score"] == pytest.approx(0.90)
    assert full_pass["metadata"]["pass_rate"] == pytest.approx(1.0)

    partial = compute_sandbox_evidence(
        CodeSandboxSubmission("softmax-stable", "c2", "Softmax", 2, 4, "", 100)
    )
    assert partial["signal_type"] == "code_sandbox_partial"
    assert partial["score"] == pytest.approx(0.45)
    assert partial["metadata"]["pass_rate"] == pytest.approx(0.5)

    fail = compute_sandbox_evidence(
        CodeSandboxSubmission("lru-cache-eviction", "c3", "LRU Cache", 1, 3, "err", 55)
    )
    assert fail["signal_type"] == "code_sandbox_fail"
    assert fail["score"] == pytest.approx(0.15)

    zero_guard = compute_sandbox_evidence(
        CodeSandboxSubmission("empty", None, "Empty", 0, 0, "", 0)
    )
    assert zero_guard["signal_type"] == "code_sandbox_fail"
    assert zero_guard["score"] == pytest.approx(0.15)
    assert zero_guard["metadata"]["pass_rate"] == pytest.approx(0.0)


@pytest.mark.parametrize("challenge", SANDBOX_CHALLENGES, ids=[c.id for c in SANDBOX_CHALLENGES])
def test_reference_solutions_pass_all_tests_and_starters_do_not(challenge: CodeSandboxChallenge):
    node_bin = _find_node()
    if not node_bin:
        pytest.skip("node binary not available")

    passed, total, results = _run_js_challenge(challenge.solution_code, challenge.test_cases, node_bin)
    assert total == len(challenge.test_cases)
    assert passed == total, f"Solution failed for {challenge.id}: {results}"

    starter_passed, starter_total, _ = _run_js_challenge(challenge.starter_code, challenge.test_cases, node_bin)
    assert starter_passed < starter_total, f"Starter code for {challenge.id} unexpectedly passed all tests"

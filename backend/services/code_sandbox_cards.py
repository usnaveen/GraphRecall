"""On-device JavaScript code-completion sandbox cards (Step #8).

Curates 10 deterministic ML, RAG, and LeetCode coding challenges that execute
completely offline inside iOS WKWebView (zero CDN / Pyodide download, zero LLM
cost at selection time) and produce knowledge-map evidence signals.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class CodeSandboxTestCase:
    name: str
    expression: str
    expected_repr: str


@dataclass(frozen=True)
class CodeSandboxChallenge:
    id: str
    concept_name: str
    concept_id: Optional[str]
    language: str
    title: str
    prompt: str
    starter_code: str
    solution_code: str
    test_cases: list[CodeSandboxTestCase]
    hint: str
    difficulty: str  # "easy" | "medium" | "hard"
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CodeSandboxSubmission:
    challenge_id: str
    concept_id: Optional[str]
    concept_name: str
    passed_tests: int
    total_tests: int
    stdout: str = ""
    elapsed_ms: int = 0


_DISALLOWED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fetch(", re.compile(r"\bfetch\s*\(", re.I)),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("WebSocket", re.compile(r"\bWebSocket\b")),
    ("localStorage", re.compile(r"\blocalStorage\b")),
    ("sessionStorage", re.compile(r"\bsessionStorage\b")),
    ("indexedDB", re.compile(r"\bindexedDB\b")),
    ("document.cookie", re.compile(r"\bdocument\s*\.\s*cookie\b")),
    ("window.location", re.compile(r"\bwindow\s*\.\s*location\b")),
    ("window.open", re.compile(r"\bwindow\s*\.\s*open\b")),
    ("importScripts", re.compile(r"\bimportScripts\b")),
    ("eval(", re.compile(r"\beval\s*\(")),
    ("Function(", re.compile(r"\bFunction\s*\(")),
)


SANDBOX_CHALLENGES: list[CodeSandboxChallenge] = [
    CodeSandboxChallenge(
        id="cosine-similarity",
        concept_name="Cosine Similarity",
        concept_id=None,
        language="javascript",
        title="Cosine Similarity for Embeddings",
        prompt=(
            "Implement cosineSimilarity(a, b) for two numeric embedding vectors. "
            "Return 0 if either vector is empty, lengths differ, or either norm is 0."
        ),
        starter_code=(
            "function cosineSimilarity(a, b) {\n"
            "  if (!Array.isArray(a) || !Array.isArray(b) || a.length === 0 || a.length !== b.length) {\n"
            "    return 0;\n"
            "  }\n"
            "  // TODO: compute dot product and L2 norms, then return dot / (||a|| * ||b||)\n"
            "  return 0;\n"
            "}\n"
        ),
        solution_code=(
            "function cosineSimilarity(a, b) {\n"
            "  if (!Array.isArray(a) || !Array.isArray(b) || a.length === 0 || a.length !== b.length) {\n"
            "    return 0;\n"
            "  }\n"
            "  let dot = 0;\n"
            "  let normA = 0;\n"
            "  let normB = 0;\n"
            "  for (let i = 0; i < a.length; i++) {\n"
            "    dot += a[i] * b[i];\n"
            "    normA += a[i] * a[i];\n"
            "    normB += b[i] * b[i];\n"
            "  }\n"
            "  if (normA === 0 || normB === 0) return 0;\n"
            "  return dot / (Math.sqrt(normA) * Math.sqrt(normB));\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Identical vectors",
                expression="Math.round(cosineSimilarity([1, 2, 3], [1, 2, 3]) * 1e4) / 1e4",
                expected_repr="1",
            ),
            CodeSandboxTestCase(
                name="Orthogonal vectors",
                expression="cosineSimilarity([1, 0, 0], [0, 1, 0])",
                expected_repr="0",
            ),
            CodeSandboxTestCase(
                name="Opposite vectors",
                expression="Math.round(cosineSimilarity([3, 4], [-3, -4]) * 1e4) / 1e4",
                expected_repr="-1",
            ),
            CodeSandboxTestCase(
                name="45-degree angle",
                expression="Math.round(cosineSimilarity([1, 0], [1, 1]) * 1e4) / 1e4",
                expected_repr="0.7071",
            ),
            CodeSandboxTestCase(
                name="Zero vector guard",
                expression="cosineSimilarity([0, 0], [1, 2])",
                expected_repr="0",
            ),
        ],
        hint="Accumulate dot += a[i] * b[i], normA += a[i] ** 2, normB += b[i] ** 2; guard against 0 norms before dividing.",
        difficulty="easy",
        tags=["rag", "embeddings", "vector-search", "linear-algebra"],
    ),
    CodeSandboxChallenge(
        id="reciprocal-rank-fusion",
        concept_name="Reciprocal Rank Fusion",
        concept_id=None,
        language="javascript",
        title="Hybrid Search with Reciprocal Rank Fusion",
        prompt=(
            "Implement reciprocalRankFusion(rankings, k = 60) over an array of ranked doc-ID lists. "
            "Add 1 / (k + rank) with 1-based rank for each occurrence and return doc IDs sorted by "
            "descending score (ties broken lexicographically)."
        ),
        starter_code=(
            "function reciprocalRankFusion(rankings, k = 60) {\n"
            "  const scores = new Map();\n"
            "  // TODO: accumulate 1 / (k + index + 1) per ranked list and sort doc IDs\n"
            "  return Array.from(scores.keys());\n"
            "}\n"
        ),
        solution_code=(
            "function reciprocalRankFusion(rankings, k = 60) {\n"
            "  const scores = new Map();\n"
            "  for (const list of rankings) {\n"
            "    for (let i = 0; i < list.length; i++) {\n"
            "      const docId = list[i];\n"
            "      scores.set(docId, (scores.get(docId) || 0) + 1 / (k + i + 1));\n"
            "    }\n"
            "  }\n"
            "  return Array.from(scores.entries())\n"
            "    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))\n"
            "    .map(([docId]) => docId);\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Fuses two ranked lists",
                expression='reciprocalRankFusion([["a", "b", "c"], ["b", "a", "d"]], 60)',
                expected_repr='["a","b","c","d"]',
            ),
            CodeSandboxTestCase(
                name="Consensus beats single top rank",
                expression='reciprocalRankFusion([["x", "shared"], ["y", "shared"]], 1)',
                expected_repr='["shared","x","y"]',
            ),
            CodeSandboxTestCase(
                name="Empty rankings",
                expression="reciprocalRankFusion([], 60)",
                expected_repr="[]",
            ),
        ],
        hint="Ranks are 1-indexed (i + 1). Sort entries by b[1] - a[1], breaking ties alphabetically.",
        difficulty="medium",
        tags=["rag", "hybrid-search", "retrieval", "ranking", "rrf"],
    ),
    CodeSandboxChallenge(
        id="softmax-stable",
        concept_name="Softmax Numerical Stability",
        concept_id=None,
        language="javascript",
        title="Numerically Stable Softmax (Log-Sum-Exp Trick)",
        prompt=(
            "Implement stableSoftmax(logits) so large positive or negative logits never overflow to NaN "
            "or underflow to 0/0. Return an empty array for empty input."
        ),
        starter_code=(
            "function stableSoftmax(logits) {\n"
            "  if (!Array.isArray(logits) || logits.length === 0) return [];\n"
            "  // TODO: subtract max(logits) before Math.exp, then normalize by sum\n"
            "  return logits.map(() => 0);\n"
            "}\n"
        ),
        solution_code=(
            "function stableSoftmax(logits) {\n"
            "  if (!Array.isArray(logits) || logits.length === 0) return [];\n"
            "  const maxLogit = Math.max(...logits);\n"
            "  const exps = logits.map((x) => Math.exp(x - maxLogit));\n"
            "  const sum = exps.reduce((acc, v) => acc + v, 0);\n"
            "  return exps.map((e) => e / sum);\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Large positive logits",
                expression="stableSoftmax([1000, 1000]).map(x => Math.round(x * 1e4) / 1e4)",
                expected_repr="[0.5,0.5]",
            ),
            CodeSandboxTestCase(
                name="Large negative logits",
                expression="stableSoftmax([-1000, -1000, -1000]).map(x => Math.round(x * 1e4) / 1e4)",
                expected_repr="[0.3333,0.3333,0.3333]",
            ),
            CodeSandboxTestCase(
                name="Peaked distribution",
                expression="stableSoftmax([0, 1, 2]).map(x => Math.round(x * 1e4) / 1e4)",
                expected_repr="[0.09,0.2447,0.6652]",
            ),
            CodeSandboxTestCase(
                name="Empty input",
                expression="stableSoftmax([])",
                expected_repr="[]",
            ),
        ],
        hint="Compute maxLogit = Math.max(...logits) and exponentiate (x - maxLogit) so the largest exponent is 0.",
        difficulty="medium",
        tags=["ml", "deep-learning", "softmax", "numerical-stability", "log-sum-exp"],
    ),
    CodeSandboxChallenge(
        id="attention-masking",
        concept_name="Scaled Dot-Product Attention",
        concept_id=None,
        language="javascript",
        title="Scaled Dot-Product Attention with Mask",
        prompt=(
            "Implement maskedAttention(query, keys, mask) for a single query vector, list of key vectors, "
            "and 0/1 mask. Scale dot products by 1 / sqrt(d_k), assign -1e9 where mask[i] === 0, apply "
            "stable softmax, and return all zeros if every key is masked out."
        ),
        starter_code=(
            "function maskedAttention(query, keys, mask) {\n"
            "  if (!keys.length || !query.length) return [];\n"
            "  // TODO: scale (q . k_i) / sqrt(d), mask with -1e9, apply stable softmax\n"
            "  return keys.map(() => 0);\n"
            "}\n"
        ),
        solution_code=(
            "function maskedAttention(query, keys, mask) {\n"
            "  if (!keys.length || !query.length) return [];\n"
            "  if (!mask.some((m) => m !== 0)) return keys.map(() => 0);\n"
            "  const scale = Math.sqrt(query.length);\n"
            "  const scores = keys.map((k, idx) => {\n"
            "    if (!mask[idx]) return -1e9;\n"
            "    let dot = 0;\n"
            "    for (let j = 0; j < query.length; j++) dot += query[j] * k[j];\n"
            "    return dot / scale;\n"
            "  });\n"
            "  const maxScore = Math.max(...scores);\n"
            "  const exps = scores.map((s, idx) => (mask[idx] ? Math.exp(s - maxScore) : 0));\n"
            "  const total = exps.reduce((a, b) => a + b, 0);\n"
            "  return total === 0 ? keys.map(() => 0) : exps.map((e) => e / total);\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Causal mask zeroes future keys",
                expression="maskedAttention([1, 0, 0, 0], [[1, 0, 0, 0], [1, 0, 0, 0], [10, 0, 0, 0]], [1, 1, 0]).map(x => Math.round(x * 1e4) / 1e4)",
                expected_repr="[0.5,0.5,0]",
            ),
            CodeSandboxTestCase(
                name="Scales dot product by sqrt(d_k)",
                expression="maskedAttention([2, 2, 2, 2], [[1, 1, 1, 1], [0, 0, 0, 0]], [1, 1]).map(x => Math.round(x * 1e4) / 1e4)",
                expected_repr="[0.982,0.018]",
            ),
            CodeSandboxTestCase(
                name="All masked returns zeros",
                expression="maskedAttention([1, 1], [[1, 1], [2, 2]], [0, 0])",
                expected_repr="[0,0]",
            ),
        ],
        hint="Divide each dot product by Math.sqrt(query.length). Guard the all-masked case before taking softmax.",
        difficulty="hard",
        tags=["transformers", "attention", "llm", "masking", "deep-learning"],
    ),
    CodeSandboxChallenge(
        id="binary-search-lower-bound",
        concept_name="Binary Search",
        concept_id=None,
        language="javascript",
        title="Binary Search Lower Bound",
        prompt=(
            "Implement lowerBound(nums, target) returning the smallest index i in sorted nums "
            "where nums[i] >= target (or nums.length if every element is smaller)."
        ),
        starter_code=(
            "function lowerBound(nums, target) {\n"
            "  let lo = 0;\n"
            "  let hi = nums.length;\n"
            "  // TODO: binary search half-open interval [lo, hi)\n"
            "  return lo;\n"
            "}\n"
        ),
        solution_code=(
            "function lowerBound(nums, target) {\n"
            "  let lo = 0;\n"
            "  let hi = nums.length;\n"
            "  while (lo < hi) {\n"
            "    const mid = (lo + hi) >> 1;\n"
            "    if (nums[mid] < target) lo = mid + 1;\n"
            "    else hi = mid;\n"
            "  }\n"
            "  return lo;\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Finds first duplicate",
                expression="lowerBound([1, 2, 2, 2, 5], 2)",
                expected_repr="1",
            ),
            CodeSandboxTestCase(
                name="Finds insertion index",
                expression="lowerBound([1, 3, 5, 7], 4)",
                expected_repr="2",
            ),
            CodeSandboxTestCase(
                name="Target past end",
                expression="lowerBound([1, 3, 5], 9)",
                expected_repr="3",
            ),
            CodeSandboxTestCase(
                name="Empty array",
                expression="lowerBound([], 5)",
                expected_repr="0",
            ),
        ],
        hint="Maintain invariant [lo, hi) with hi initialized to nums.length; move lo = mid + 1 only when nums[mid] < target.",
        difficulty="easy",
        tags=["leetcode", "binary-search", "algorithms"],
    ),
    CodeSandboxChallenge(
        id="sliding-window-max-sum",
        concept_name="Sliding Window",
        concept_id=None,
        language="javascript",
        title="Sliding Window Maximum Subarray Sum (Size k)",
        prompt=(
            "Implement maxSubarraySum(nums, k) to return the maximum sum of any contiguous "
            "subarray of length k in O(n) time. Return null if k <= 0 or nums.length < k."
        ),
        starter_code=(
            "function maxSubarraySum(nums, k) {\n"
            "  if (!Array.isArray(nums) || k <= 0 || nums.length < k) return null;\n"
            "  // TODO: compute initial window sum of k items, then slide one step at a time\n"
            "  return 0;\n"
            "}\n"
        ),
        solution_code=(
            "function maxSubarraySum(nums, k) {\n"
            "  if (!Array.isArray(nums) || k <= 0 || nums.length < k) return null;\n"
            "  let windowSum = 0;\n"
            "  for (let i = 0; i < k; i++) windowSum += nums[i];\n"
            "  let best = windowSum;\n"
            "  for (let i = k; i < nums.length; i++) {\n"
            "    windowSum += nums[i] - nums[i - k];\n"
            "    if (windowSum > best) best = windowSum;\n"
            "  }\n"
            "  return best;\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Standard window",
                expression="maxSubarraySum([2, 1, 5, 1, 3, 2], 3)",
                expected_repr="9",
            ),
            CodeSandboxTestCase(
                name="All negative numbers",
                expression="maxSubarraySum([-4, -2, -7, -1, -5], 2)",
                expected_repr="-6",
            ),
            CodeSandboxTestCase(
                name="Window larger than array",
                expression="maxSubarraySum([1, 2], 3)",
                expected_repr="null",
            ),
        ],
        hint="Initialize best = windowSum (not 0!) so negative arrays work, then update windowSum += nums[i] - nums[i - k].",
        difficulty="easy",
        tags=["leetcode", "sliding-window", "arrays", "two-pointers"],
    ),
    CodeSandboxChallenge(
        id="monotonic-stack-next-greater",
        concept_name="Monotonic Stack",
        concept_id=None,
        language="javascript",
        title="Monotonic Stack: Next Greater Element",
        prompt=(
            "Implement nextGreaterElements(nums) returning an array where index i holds the first "
            "strictly greater element to the right of nums[i], or -1 if none exists."
        ),
        starter_code=(
            "function nextGreaterElements(nums) {\n"
            "  const res = new Array(nums.length).fill(-1);\n"
            "  const stack = []; // store indices\n"
            "  // TODO: pop indices whose value < nums[i] and record nums[i]\n"
            "  return res;\n"
            "}\n"
        ),
        solution_code=(
            "function nextGreaterElements(nums) {\n"
            "  const res = new Array(nums.length).fill(-1);\n"
            "  const stack = [];\n"
            "  for (let i = 0; i < nums.length; i++) {\n"
            "    while (stack.length > 0 && nums[i] > nums[stack[stack.length - 1]]) {\n"
            "      res[stack.pop()] = nums[i];\n"
            "    }\n"
            "    stack.push(i);\n"
            "  }\n"
            "  return res;\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Mixed sequence",
                expression="nextGreaterElements([2, 1, 2, 4, 3])",
                expected_repr="[4,2,4,-1,-1]",
            ),
            CodeSandboxTestCase(
                name="Strictly decreasing",
                expression="nextGreaterElements([5, 4, 3, 2, 1])",
                expected_repr="[-1,-1,-1,-1,-1]",
            ),
            CodeSandboxTestCase(
                name="Equal values require strictly greater",
                expression="nextGreaterElements([3, 3, 4])",
                expected_repr="[4,4,-1]",
            ),
        ],
        hint="Keep a monotonically non-increasing stack of unresolved indices; pop while nums[i] > nums[stack.at(-1)].",
        difficulty="medium",
        tags=["leetcode", "monotonic-stack", "stack", "algorithms"],
    ),
    CodeSandboxChallenge(
        id="precision-recall-f1",
        concept_name="Precision, Recall, and F1",
        concept_id=None,
        language="javascript",
        title="Classification Metrics: Precision, Recall, F1",
        prompt=(
            "Implement precisionRecallF1(yTrue, yPred) over binary 0/1 arrays and return "
            "{ precision, recall, f1 }. Safely return 0 for any metric whose denominator is 0."
        ),
        starter_code=(
            "function precisionRecallF1(yTrue, yPred) {\n"
            "  let tp = 0, fp = 0, fn = 0;\n"
            "  // TODO: count tp, fp, fn and compute precision, recall, f1\n"
            "  return { precision: 0, recall: 0, f1: 0 };\n"
            "}\n"
        ),
        solution_code=(
            "function precisionRecallF1(yTrue, yPred) {\n"
            "  let tp = 0, fp = 0, fn = 0;\n"
            "  for (let i = 0; i < yTrue.length; i++) {\n"
            "    if (yTrue[i] === 1 && yPred[i] === 1) tp++;\n"
            "    else if (yTrue[i] === 0 && yPred[i] === 1) fp++;\n"
            "    else if (yTrue[i] === 1 && yPred[i] === 0) fn++;\n"
            "  }\n"
            "  const precision = tp + fp === 0 ? 0 : tp / (tp + fp);\n"
            "  const recall = tp + fn === 0 ? 0 : tp / (tp + fn);\n"
            "  const f1 = precision + recall === 0 ? 0 : (2 * precision * recall) / (precision + recall);\n"
            "  return { precision, recall, f1 };\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Balanced TP/FP/FN",
                expression=(
                    "(() => { const r = precisionRecallF1([1, 1, 0, 0], [1, 0, 1, 0]); "
                    "return [Math.round(r.precision*1e4)/1e4, Math.round(r.recall*1e4)/1e4, Math.round(r.f1*1e4)/1e4]; })()"
                ),
                expected_repr="[0.5,0.5,0.5]",
            ),
            CodeSandboxTestCase(
                name="High precision, low recall",
                expression=(
                    "(() => { const r = precisionRecallF1([1, 1, 1, 0], [1, 0, 0, 0]); "
                    "return [Math.round(r.precision*1e4)/1e4, Math.round(r.recall*1e4)/1e4, Math.round(r.f1*1e4)/1e4]; })()"
                ),
                expected_repr="[1,0.3333,0.5]",
            ),
            CodeSandboxTestCase(
                name="Zero positives guard",
                expression=(
                    "(() => { const r = precisionRecallF1([0, 0], [0, 0]); "
                    "return [r.precision, r.recall, r.f1]; })()"
                ),
                expected_repr="[0,0,0]",
            ),
        ],
        hint="precision = tp / (tp + fp), recall = tp / (tp + fn), f1 = 2 * p * r / (p + r).",
        difficulty="easy",
        tags=["ml", "evaluation", "metrics", "classification"],
    ),
    CodeSandboxChallenge(
        id="zscore-minmax-normalization",
        concept_name="Feature Scaling",
        concept_id=None,
        language="javascript",
        title="Z-Score and Min-Max Normalization",
        prompt=(
            'Implement normalizeFeatures(values, mode) supporting "zscore" ((x - mean) / std) '
            'and "minmax" ((x - min) / (max - min)). Return 0s for constant arrays.'
        ),
        starter_code=(
            "function normalizeFeatures(values, mode) {\n"
            "  if (!Array.isArray(values) || values.length === 0) return [];\n"
            '  // TODO: handle mode === "zscore" and mode === "minmax" with zero-spread guards\n'
            "  return values.slice();\n"
            "}\n"
        ),
        solution_code=(
            "function normalizeFeatures(values, mode) {\n"
            "  if (!Array.isArray(values) || values.length === 0) return [];\n"
            '  if (mode === "zscore") {\n'
            "    const mean = values.reduce((a, b) => a + b, 0) / values.length;\n"
            "    const variance = values.reduce((acc, x) => acc + (x - mean) * (x - mean), 0) / values.length;\n"
            "    const std = Math.sqrt(variance);\n"
            "    return std === 0 ? values.map(() => 0) : values.map((x) => (x - mean) / std);\n"
            "  }\n"
            '  if (mode === "minmax") {\n'
            "    const minVal = Math.min(...values);\n"
            "    const maxVal = Math.max(...values);\n"
            "    const span = maxVal - minVal;\n"
            "    return span === 0 ? values.map(() => 0) : values.map((x) => (x - minVal) / span);\n"
            "  }\n"
            "  return values.slice();\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Z-score scaling",
                expression='normalizeFeatures([10, 20, 30], "zscore").map(x => Math.round(x * 1e4) / 1e4)',
                expected_repr="[-1.2247,0,1.2247]",
            ),
            CodeSandboxTestCase(
                name="Min-max scaling",
                expression='normalizeFeatures([10, 20, 50], "minmax").map(x => Math.round(x * 1e4) / 1e4)',
                expected_repr="[0,0.25,1]",
            ),
            CodeSandboxTestCase(
                name="Constant array guard",
                expression='normalizeFeatures([7, 7, 7], "zscore")',
                expected_repr="[0,0,0]",
            ),
        ],
        hint="Use population std sqrt(mean((x - mean)^2)) for z-score, and return zeros if std === 0 or max === min.",
        difficulty="easy",
        tags=["ml", "preprocessing", "normalization", "feature-scaling", "statistics"],
    ),
    CodeSandboxChallenge(
        id="lru-cache-eviction",
        concept_name="LRU Cache",
        concept_id=None,
        language="javascript",
        title="LRU Cache Eviction Simulator",
        prompt=(
            'Implement simulateLRU(capacity, ops) processing ["get", key] and ["put", key, val] '
            "operations. Return an array of results for every get (-1 if missing or evicted)."
        ),
        starter_code=(
            "function simulateLRU(capacity, ops) {\n"
            "  const cache = new Map();\n"
            "  const out = [];\n"
            "  // TODO: refresh recency on get/put and evict cache.keys().next().value when full\n"
            "  return out;\n"
            "}\n"
        ),
        solution_code=(
            "function simulateLRU(capacity, ops) {\n"
            "  const cache = new Map();\n"
            "  const out = [];\n"
            "  for (const op of ops) {\n"
            '    if (op[0] === "get") {\n'
            "      const key = op[1];\n"
            "      if (!cache.has(key)) {\n"
            "        out.push(-1);\n"
            "      } else {\n"
            "        const val = cache.get(key);\n"
            "        cache.delete(key);\n"
            "        cache.set(key, val);\n"
            "        out.push(val);\n"
            "      }\n"
            '    } else if (op[0] === "put") {\n'
            "      if (capacity <= 0) continue;\n"
            "      const key = op[1], val = op[2];\n"
            "      if (cache.has(key)) {\n"
            "        cache.delete(key);\n"
            "      } else if (cache.size >= capacity) {\n"
            "        cache.delete(cache.keys().next().value);\n"
            "      }\n"
            "      cache.set(key, val);\n"
            "    }\n"
            "  }\n"
            "  return out;\n"
            "}\n"
        ),
        test_cases=[
            CodeSandboxTestCase(
                name="Evicts least recently used key",
                expression='simulateLRU(2, [["put", 1, 10], ["put", 2, 20], ["get", 1], ["put", 3, 30], ["get", 2], ["get", 3]])',
                expected_repr="[10,-1,30]",
            ),
            CodeSandboxTestCase(
                name="Overwrite refreshes recency",
                expression='simulateLRU(2, [["put", 1, 1], ["put", 2, 2], ["put", 1, 10], ["put", 3, 3], ["get", 1], ["get", 2]])',
                expected_repr="[10,-1]",
            ),
            CodeSandboxTestCase(
                name="Missing key returns -1",
                expression='simulateLRU(1, [["get", 99], ["put", 5, 50], ["get", 5]])',
                expected_repr="[-1,50]",
            ),
        ],
        hint="JavaScript Map preserves insertion order: delete and re-insert on access/update so the oldest key is always first.",
        difficulty="hard",
        tags=["leetcode", "lru-cache", "hash-map", "linked-list", "design"],
    ),
]


def _norm_tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    return {tok for tok in cleaned.split() if len(tok) > 1}


def _norm_phrase(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def validate_challenge_safety(challenge: CodeSandboxChallenge) -> list[str]:
    """Return violation reasons if a challenge uses disallowed WebView/network/storage APIs."""
    violations: list[str] = []
    if not challenge.id.strip():
        violations.append("challenge id is empty")
    if challenge.language.lower() != "javascript":
        violations.append(f"unsupported language: {challenge.language}")
    if not challenge.starter_code.strip():
        violations.append("starter_code is empty")
    if not challenge.solution_code.strip():
        violations.append("solution_code is empty")
    if not challenge.test_cases:
        violations.append("test_cases must not be empty")

    fields_to_scan: list[tuple[str, str]] = [
        ("prompt", challenge.prompt),
        ("starter_code", challenge.starter_code),
        ("solution_code", challenge.solution_code),
    ]
    for idx, tc in enumerate(challenge.test_cases):
        fields_to_scan.append((f"test_cases[{idx}].expression", tc.expression))
        fields_to_scan.append((f"test_cases[{idx}].expected_repr", tc.expected_repr))

    for field_name, content in fields_to_scan:
        for label, pattern in _DISALLOWED_PATTERNS:
            if pattern.search(content or ""):
                violations.append(f"disallowed API '{label}' found in {field_name}")

    return violations


def select_sandbox_challenge(
    concept_names: Iterable[str],
    weak_patterns: Optional[Iterable[str]] = None,
    difficulty: Optional[str] = None,
    exclude_ids: Optional[Iterable[str]] = None,
) -> CodeSandboxChallenge:
    """Select the best matching sandbox challenge deterministically with zero LLM cost."""
    excluded = {cid for cid in (exclude_ids or []) if cid}
    pool = [c for c in SANDBOX_CHALLENGES if c.id not in excluded]
    if not pool:
        pool = list(SANDBOX_CHALLENGES)

    if difficulty:
        target_diff = difficulty.strip().lower()
        diff_pool = [c for c in pool if c.difficulty.lower() == target_diff]
        if diff_pool:
            pool = diff_pool

    concepts_list = [c for c in (concept_names or []) if c and c.strip()]
    patterns_list = [p for p in (weak_patterns or []) if p and p.strip()]

    concept_phrases = [_norm_phrase(c) for c in concepts_list if _norm_phrase(c)]
    concept_tokens = {tok for c in concepts_list for tok in _norm_tokens(c)}
    pattern_phrases = [_norm_phrase(p) for p in patterns_list if _norm_phrase(p)]
    pattern_tokens = {tok for p in patterns_list for tok in _norm_tokens(p)}

    def _score(idx: int, ch: CodeSandboxChallenge) -> tuple[int, int]:
        score = 0
        ch_concept = _norm_phrase(ch.concept_name)
        ch_title = _norm_phrase(ch.title)
        ch_tags = {_norm_phrase(t) for t in ch.tags}
        ch_tokens = (
            _norm_tokens(ch.concept_name)
            | _norm_tokens(ch.title)
            | _norm_tokens(ch.id)
            | {tok for t in ch.tags for tok in _norm_tokens(t)}
        )

        for phrase in concept_phrases:
            if phrase == ch_concept or phrase == ch_title:
                score += 20
            elif phrase in ch_concept or ch_concept in phrase or phrase in ch_tags:
                score += 12
        score += 4 * len(concept_tokens & ch_tokens)

        for phrase in pattern_phrases:
            if phrase == ch_concept or phrase in ch_tags:
                score += 16
            elif phrase in ch_title or ch_concept in phrase:
                score += 10
        score += 5 * len(pattern_tokens & ch_tokens)

        return (score, -idx)

    best_idx, best_ch = max(enumerate(pool), key=lambda pair: _score(pair[0], pair[1]))
    _ = best_idx
    return best_ch


def build_sandbox_feed_payload(challenge: CodeSandboxChallenge) -> dict[str, Any]:
    """Build a FeedItem-compatible JSON payload with card_type='code_sandbox'."""
    violations = validate_challenge_safety(challenge)
    if violations:
        raise ValueError(f"Unsafe challenge '{challenge.id}': {'; '.join(violations)}")

    domain = "Coding Interviews" if "leetcode" in {t.lower() for t in challenge.tags} else "AI & ML"
    serialized_tests = [asdict(tc) for tc in challenge.test_cases]

    return {
        "id": f"code_sandbox:{challenge.id}",
        "item_type": "code_sandbox",
        "card_type": "code_sandbox",
        "concept_id": challenge.concept_id,
        "concept_name": challenge.concept_name,
        "domain": domain,
        "priority_score": 0.85,
        "content": {
            "card_type": "code_sandbox",
            "challenge_id": challenge.id,
            "concept_name": challenge.concept_name,
            "concept_id": challenge.concept_id,
            "language": challenge.language,
            "title": challenge.title,
            "prompt": challenge.prompt,
            "starter_code": challenge.starter_code,
            "solution_code": challenge.solution_code,
            "test_cases": serialized_tests,
            "hint": challenge.hint,
            "difficulty": challenge.difficulty,
            "tags": list(challenge.tags),
        },
    }


def compute_sandbox_evidence(submission: CodeSandboxSubmission) -> dict[str, Any]:
    """Map a sandbox test run into a knowledge_map.add_evidence-ready payload."""
    total = max(0, int(submission.total_tests))
    passed = max(0, min(int(submission.passed_tests), total)) if total > 0 else 0

    if total > 0 and passed == total:
        signal_type = "code_sandbox_pass"
        score = 0.90
    elif total > 0 and passed * 2 >= total:
        signal_type = "code_sandbox_partial"
        score = 0.45
    else:
        signal_type = "code_sandbox_fail"
        score = 0.15

    pass_rate = round(passed / total, 4) if total > 0 else 0.0
    return {
        "signal_type": signal_type,
        "score": score,
        "metadata": {
            "challenge_id": submission.challenge_id,
            "concept_id": submission.concept_id,
            "concept_name": submission.concept_name,
            "passed_tests": passed,
            "total_tests": total,
            "pass_rate": pass_rate,
            "elapsed_ms": max(0, int(submission.elapsed_ms)),
            "stdout_preview": (submission.stdout or "")[:500],
        },
    }

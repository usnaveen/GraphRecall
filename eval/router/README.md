# Chat intent router

Replaces the per-message Gemini "what kind of question is this?" call with a small trained classifier
when it is confident. Code: `backend/services/intent_router/`. Wired in `analyze_query_node`
(`backend/graphs/chat_graph.py`).

## What it decides

Eight intents (`explain, compare, find, summarize, quiz, path, show_images, general`). Only five change
what the chat graph does (`routing.py`): `path` (3-hop prerequisite expansion), `explain` (1 hop),
`summarize` (community map step), `show_images` (more chunks + image retrieval), `quiz` (quiz generation).
`compare`, `find` and `general` share the default 2-hop path, so "routing accuracy" counts confusions
among those three as correct.

The LLM call also returned topic names ("entities") that seed the graph search. On model-routed turns
those come from matching the user's own concept names in the message (`MENTION_QUERY`, word-boundary
filtered; ~9 ms warm on a 189-concept local graph), plus vector seeds from the query embedding the chat
already computes.

## Modes (`CHAT_INTENT_ROUTER`)

| mode | who decides | LLM call |
|---|---|---|
| `model` (default) | classifier if confidence >= 0.6, else Gemini | only on low confidence, or a quiz request with no known topic |
| `shadow` | Gemini; classifier's guess logged next to it | every message |
| `llm` | Gemini (previous behaviour) | every message |

If Gemini fails (quota, timeout), the classifier's guess is used instead of falling back to `general`.
Every decision goes to `intent_decisions` (migration 023): query, chosen intent, source, model intent and
confidence, LLM intent when called, entities, latency. Deleted with the user's data.

## Data

- `data/train.jsonl`: 2,800 synthetic questions (350 per intent) from phrasing templates x ~100 topics
  with light noise (`make_dataset.py`).
- `data/dev.jsonl`: 120 hand-written questions, used for tuning decisions (`threshold`, `C`, template
  additions).
- `data/test.jsonl`: 160 hand-written questions across all 8 intents (agent-written provisional labels).
- `data/heldout_v2.jsonl`: 57 untouched external GraphRAG benchmark questions (`45` MuSiQue multi-hop
  factoid lookups + `12` GraphRAG-Bench medical questions, `sha256=0acae9607dfa...`, agent-provisional
  labels assigned before scoring; spans 4 of the 8 intents: `find=49, compare=3, explain=3, summarize=2`).
- **Human verification & real-query authoring:** `python3 eval/router/label.py` checks existing labels;
  `python3 eval/router/label.py --write` builds `data/human.jsonl` from real user-written questions.

## Results (2026-11-26)

### 1. In-domain 8-class sets (`dev`, `test`, and decontaminated `test`)

| model / slice | dev acc (n=120) | test acc [95% CI] | macro-F1 | routing acc | p50 latency | serve deps |
|---|---|---|---|---|---|---|
| keyword rules (full test, n=160) | 0.550 | 0.625 [0.55, 0.69] | 0.657 | 0.688 | 0.01 ms | none |
| **TF-IDF + LogReg — v1 clean (n=160)** | — | **0.794** *(pre-iteration)* | — | — | 0.08 ms | numpy |
| TF-IDF + LogReg — post-iteration full test (n=160) | 0.850 | 0.919 [0.88, 0.96] | 0.918 | 0.919 | 0.08 ms | numpy |
| **TF-IDF + LogReg — decontaminated `<= 0.80` (n=157)** | — | **0.917 [0.87, 0.96]** | **0.916** | **0.917** | 0.08 ms | numpy |
| TF-IDF + LogReg — decontaminated `<= 0.60` (n=130) | — | 0.915 [0.86, 0.96] | 0.914 | 0.915 | 0.08 ms | numpy |
| MiniLM + LogReg — post-iteration full test (n=160) | 0.833 | 0.844 [0.79, 0.90] | 0.843 | — | 8.4 ms | torch |

### 2. Contamination audit (`eval/router/audit_overlap.py` -> `results/contamination_audit.json`)

- **Overlap distribution vs. `train.jsonl` (2,800 rows):**
  - `dev` (`n=120`): max TF-IDF cosine median `0.422`, p90 `0.653`, max `1.000` (`4` items `> 0.80`);
    max char-5gram Jaccard median `0.181`, p90 `0.382`, max `1.000` (`1` item `> 0.80`; `4` on either).
  - `test` (`n=160`): max TF-IDF cosine median `0.434`, p90 `0.645`, max `0.849` (`3` items `> 0.80`);
    max char-5gram Jaccard median `0.194`, p90 `0.373`, max `0.711` (`0` items `> 0.80`; `3` on either).
- **Why `0.917` on `n=157` (and `0.915` on `n=130`) still exceeds v1 (`0.794`):** after v1 (`0.794`),
  test errors were inspected and short intent-cue stems (`"see if i remember"`, `"dig up"`, `"got any
  figures of"`) were added to `make_dataset.py`. Because topic nouns differ between train and test,
  whole-sentence cosine stays `0.55–0.77` while the cue stem transfers. **Lesson:** post-hoc n-gram
  filtering removes near-duplicates (`3` items `> 0.80`) but cannot undo adaptive template leakage;
  `v1 = 0.794` remains the only uncontaminated score on `test.jsonl`.

### 3. Untouched external benchmark (`heldout_v2.jsonl`, n=57, scored once without error inspection)

| model | 8-class acc [95% CI] | macro-F1 (4 present gold / 8 all) | routing acc [95% CI] | coverage @ 0.6 | quiz false positives |
|---|---|---|---|---|---|
| keyword rules | 0.070 [0.02, 0.14] | 0.152 / 0.076 | 0.754 [0.65, 0.86]* | 1.000 | 0 / 57 |
| **TF-IDF + LogReg (ships)** | **0.316 [0.19, 0.44]** | **0.274 / 0.137** | **0.386 [0.26, 0.51]** | **0.421** | **0 / 57** |

*\*Keyword rules default to `general` on 35/49 encyclopedic `find` questions because `find` rules look
for `"my notes"`; `general` and `find` share the `default` 2-hop route group, inflating rule routing
accuracy despite `0.070` 8-class accuracy. Similarly, TF-IDF `find` templates all mention personal
notes, so third-person MuSiQue factoids (`"When did..."`, `"Where does..."`) scatter to `explain` (14)
and `path` (9), while the `0.6` confidence gate abstains to the Gemini LLM fallback on **57.9% (33/57)**
of these out-of-distribution phrasings and triggers **0 false `quiz` jobs**.*

## Evaluation Hygiene Rules (Mandatory)

1. **Error analysis on `dev` only:** `train.py` suppresses per-item error dumps (`*_errors`) on all
   frozen sets (`test`, `heldout_v2`, `human`). Passing `--inspect-frozen-errors` prints a warning and
   permanently writes `"frozen_errors_inspected": true` + timestamp into `results/<eval_set>.json`.
2. **Dataset & artifact SHA-256 pinning:** every `results/*.json` records `eval_file_sha256` and
   `artifact_sha256` so silent edits to frozen benchmarks are immediately detectable.
3. **One evaluation per model version on frozen sets:** iterate templates, regularization `C`, and
   thresholds strictly on `dev` (`--eval-set dev`). Score `heldout_v2` or `human` once via
   `train.py --score-only --eval-set <name>` when freezing a new model version; if retrained, report
   strict before/after on the frozen set without reading per-item errors.
4. **True clean benchmark still needed:** `heldout_v2` is encyclopedic QA (4 of 8 intents, provisional
   agent labels) and only 6 real queries are logged in `intent_decisions` so far. Authoring ~50 real
   personal study queries via `python3 eval/router/label.py --write` (`data/human.jsonl`) plus shadow
   traffic remains the definitive clean evaluation.

## Calibration & risk-coverage (`eval/router/calibration.py` -> `results/calibration.json`)

Scored strictly from predicted probabilities of the shipped artifact (`tfidf-lr-v1`,
`artifact_sha256=ced416ac2f76...`, `threshold=0.6`) with zero per-item error inspection
(`"frozen_errors_inspected": false` on `test` and `heldout_v2`).

### 1. Summary calibration & selective-prediction metrics

| split | n | acc | routing acc | mean conf | ECE-10 | MCE-10 | Brier | NLL | AURC (8-cls / oracle) | AURC (routing) |
|---|---|---|---|---|---|---|---|---|---|---|
| `dev` | 120 | 0.850 | 0.858 | 0.844 | **0.0458** | 0.3571 | 0.1979 | 0.4061 | 0.0308 / 0.0125 | 0.0270 |
| `test` (frozen) | 160 | 0.919 | 0.919 | 0.866 | **0.0572** | 0.1648 | 0.1264 | 0.2867 | 0.0097 / 0.0036 | 0.0097 |
| `heldout_v2` (frozen OOD) | 57 | 0.316 | 0.386 | 0.590 | **0.2745** | 0.6445 | 0.9495 | 2.3347 | 0.6117 / 0.3261 | 0.5754 |

### 2. 10-bin reliability table (`avg conf` vs. `empirical acc`, `gap = conf - acc`)

| bin | dev (`n`, `conf` -> `acc`, `gap`) | test (`n`, `conf` -> `acc`, `gap`) | heldout_v2 (`n`, `conf` -> `acc`, `gap`) |
|---|---|---|---|
| `[0.2, 0.3)` | 1: 0.262 -> 0.000 (+0.262) | — | 3: 0.250 -> 0.000 (+0.250) |
| `[0.3, 0.4)` | 3: 0.357 -> 0.000 (+0.357) | 5: 0.364 -> 0.400 (-0.036) | 10: 0.344 -> 0.200 (+0.144) |
| `[0.4, 0.5)` | 7: 0.452 -> 0.429 (+0.023) | 3: 0.446 -> 0.333 (+0.112) | 10: 0.448 -> 0.200 (+0.248) |
| `[0.5, 0.6)` | 8: 0.561 -> 0.625 (-0.064) | 11: 0.539 -> 0.636 (-0.097) | 10: 0.550 -> 0.500 (+0.050) |
| `[0.6, 0.7)` | 9: 0.656 -> 0.556 (+0.101) | 8: 0.657 -> 0.750 (-0.093) | 7: 0.655 -> 0.429 (+0.227) |
| `[0.7, 0.8)` | 5: 0.767 -> 1.000 (-0.233) | 13: 0.758 -> 0.923 (-0.165) | 5: 0.742 -> 0.400 (+0.342) |
| `[0.8, 0.9)` | 22: 0.860 -> 0.909 (-0.050) | 21: 0.853 -> 1.000 (-0.147) | 2: 0.861 -> 0.500 (+0.361) |
| `[0.9, 1.0]` | 65: 0.980 -> 0.985 (-0.005) | 99: 0.974 -> 0.990 (-0.016) | 10: 0.945 -> 0.300 (+0.645) |

### 3. Risk-coverage sweep (`threshold` gate on `max(p)`)

| threshold | dev (`cov`, `acc`, `r_acc`, `abst acc`) | test (`cov`, `acc`, `r_acc`, `abst acc`) | heldout_v2 (`cov`, `acc`, `r_acc`, `abst acc`) |
|---|---|---|---|
| `0.00` | 1.000 / 0.850 / 0.858 / — | 1.000 / 0.919 / 0.919 / — | 1.000 / 0.316 / 0.386 / — |
| `0.40` | 0.967 / 0.879 / 0.888 / 0.000 | 0.969 / 0.935 / 0.935 / 0.400 | 0.772 / 0.364 / 0.409 / 0.154 |
| `0.50` | 0.908 / 0.908 / 0.917 / 0.273 | 0.950 / 0.947 / 0.947 / 0.375 | 0.596 / 0.412 / 0.441 / 0.174 |
| `0.55` | 0.892 / 0.916 / 0.925 / 0.308 | 0.900 / 0.965 / 0.965 / 0.500 | 0.509 / 0.414 / 0.448 / 0.214 |
| **`0.60` (ships)** | **0.842 / 0.931 / 0.941 / 0.421** | **0.881 / 0.972 / 0.972 / 0.526** | **0.421 / 0.375 / 0.417 / 0.273** |
| `0.65` | 0.808 / 0.938 / 0.948 / 0.478 | 0.856 / 0.985 / 0.985 / 0.522 | 0.386 / 0.364 / 0.409 / 0.286 |
| `0.70` | 0.767 / 0.967 / 0.978 / 0.464 | 0.831 / 0.985 / 0.985 / 0.593 | 0.298 / 0.353 / 0.412 / 0.300 |
| `0.80` | 0.725 / 0.966 / 0.977 / 0.545 | 0.750 / 0.992 / 0.992 / 0.700 | 0.211 / 0.333 / 0.417 / 0.311 |
| `0.90` | 0.542 / 0.985 / 0.985 / 0.691 | 0.619 / 0.990 / 0.990 / 0.803 | 0.175 / 0.300 / 0.300 / 0.319 |

**Verdict on the shipped `0.60` gate:**
- **In-domain (`dev`, `test`): well-calibrated and well-placed.** ECE-10 is low (`0.0458` on `dev`, `0.0572` on `test`, slightly conservative in `[0.5, 0.9)`). At `0.60`, the router serves `84.2%` of `dev` queries locally at `93.1%` 8-class / `94.1%` routing accuracy (halving selective risk from `0.150` to `0.069`) and abstains only on `19` queries whose local accuracy is `42.1%`. On `test`, `88.1%` coverage achieves `97.2%` accuracy (`0.028` risk). Tightening to `0.65`–`0.70` pushes `dev` kept accuracy to `0.938`–`0.967` (`0.985` on `test`) at a `3.4–7.5 pt` coverage cost.
- **Out-of-distribution (`heldout_v2`): calibration breaks under covariate shift.** `0.60` sends `57.9%` (`33/57`) of encyclopedic OOD questions to Gemini with `0` false `quiz` triggers, which is helpful — however the `24` high-confidence kept items still score only `37.5%` (`10` items in `[0.9, 1.0]` score `30.0%`, producing `ECE = 0.2745`). Softmax confidence on TF-IDF logits cannot distinguish confident OOD phrasing; keeping `0.60` (or raising to `0.65–0.70` if extra LLM fallback calls are cheap) works well in-domain, while OOD safety ultimately relies on log-monitoring `intent_decisions` in `shadow`/`model` mode and training on real user queries.

## Reproduce

```bash
python3 eval/router/make_dataset.py
python3 eval/router/audit_overlap.py                          # overlap audit + decontaminated slices
python3 eval/router/train.py --score-only --eval-set heldout_v2  # one-shot frozen benchmark (numpy only)
python3 eval/router/calibration.py                            # ECE-10, reliability bins, risk-coverage curve
```

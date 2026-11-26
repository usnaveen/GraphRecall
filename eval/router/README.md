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

## Reproduce

```bash
python3 eval/router/make_dataset.py
python3 eval/router/audit_overlap.py                          # overlap audit + decontaminated slices
python3 eval/router/train.py --score-only --eval-set heldout_v2  # one-shot frozen benchmark (numpy only)
```

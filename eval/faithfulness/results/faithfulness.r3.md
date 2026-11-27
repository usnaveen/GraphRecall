# Independent Local NLI Faithfulness Report (`questions_slice.r3`)

- **Judge:** `cross-encoder/nli-deberta-v3-xsmall` (`model.int8.onnx`, Apache-2.0, pinned rev `a15087641532`, **zero Gemini/LLM calls**)
- **Slice:** `eval/graphrag/results/questions_slice.r3.json` (`n=11` questions, `232` unique atomic claims, `6960` `(premise, claim)` NLI inferences)
- **Aggregation:** SummaC-ZS sentence-pair max over top-30 (1- and 2-sentence) candidates per claim sorted by content-stem overlap; entailment argmax >= 0.50 -> entailed, else contradiction argmax >= 0.70 (gated on stem overlap >= 2) -> contradicted, else neutral

## Per-Arm Claim Groundedness (vs. Retrieved Notes)

| Arm | Answered Qs | Claims | % Entailed | % Neutral (Ungrounded) | % Contradicted | Mean Answer % Entailed | Strict p>=0.7 % Entailed |
|---|---|---|---|---|---|---|---|
| `closed_book` | 11/11 | 166 | **9.6%** | 53.6% | 36.7% | 13.7% | 7.8% |
| `vector_only` | 11/11 | 59 | **61.0%** | 28.8% | 10.2% | 59.8% | 55.9% |
| `graph_only` | 10/11 | 50 | **58.0%** | 30.0% | 12.0% | 54.5% | 54.0% |
| `global_only` | 6/11 | 30 | **70.0%** | 26.7% | 3.3% | 73.7% | 70.0% |
| `shipped` | 11/11 | 59 | **59.3%** | 30.5% | 10.2% | 57.5% | 55.9% |

> **Slice audit note:** `10/11` questions in `questions_slice.r3.json` produced byte-identical answer text across all non-empty grounded arms (`vector_only`, `graph_only`, `global_only`, `shipped`). Only `global_only` differs substantially by returning empty answers on `5/11` questions when map-reduce summary is absent, while `graph_only` is empty on `1/11` and `closed_book` writes long parametric essays (`15/15+` claims per answer).

## Blind Human Calibration

- **Sample size:** `n=31` claims hand-labeled blindly before running NLI (`blind=True`)
- **3-way (`entailed` / `neutral` / `contradicted`):** exact agreement = **71.0%**, Cohen's $\kappa$ = **0.466** (chance = 45.7%)
- **Binary (`entailed` vs `not_entailed`):** agreement = **77.4%**, Cohen's $\kappa$ = **0.551**

### Confusion Matrix (rows = human, cols = NLI)

| Human \ NLI | entailed | neutral | contradicted |
|---|---|---|---|
| **entailed** | 13 | 4 | 1 |
| **neutral** | 2 | 9 | 2 |
| **contradicted** | 0 | 0 | 0 |

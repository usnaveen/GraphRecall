# Independent Faithfulness Evaluation (Local ONNX NLI Judge)

> **Who labelled the calibration set:** the 31 "blind" labels in `calibration_labels.jsonl` were written by Neon (the Gemini agent) before NLI ran, each with a rationale. They are an LLM's labels, not a human's, so the κ below is agreement between two models. A human pass over the same 31 claims is still to do.

Scores claim-level groundedness of generated chat answers without any Gemini / LLM judge calls,
breaking same-model generator=judge circularity in `eval/graphrag/run_eval.py`.

## Model & Provenance

- **Model:** [`cross-encoder/nli-deberta-v3-xsmall`](https://huggingface.co/cross-encoder/nli-deberta-v3-xsmall) (**Apache-2.0** license)
- **Pinned revision:** `a150876415327c80daeff35ca6f68f5ed8cf5c24`
- **Weights & verification:** `fetch_nli.py` downloads `onnx/model_qint8_arm64.onnx` (`87.4 MB`, SHA-256 `ef41fe8474f6070373f97fbe8362461d55108f387723280fcdb64f8015133db2`), `tokenizer.json` (`5124ef2ead1a10a717703bc436de7f353da76d6340e4587719b42b1693707964`), and `config.json` (`8d9f07bf7ba54a6fc3b1962483056f94c39dcf188db4cf61843e1c88f94b2342`) into git-ignored `eval/faithfulness/models/`.
- **Runtime dependencies:** `onnxruntime`, `tokenizers`, and `numpy` only (no PyTorch or `transformers` at inference time).

## Scoring Method (`claims.py`, `nli.py`, `score_faithfulness.py`)

1. **Deterministic claim splitting (`claims.py`):** strips markdown formatting and inline `[n]` / `[n, m]` citations, skips bare section headers and meta-lead-ins, and segments answers into atomic factual sentences.
2. **SummaC-ZS sentence-pair aggregation:** retrieved notes (`note_titles` resolved against `eval/graphrag/data/grb/corpus.jsonl`) are split into 1-sentence units, and for each claim the top-30 `(1-sentence or adjacent 2-sentence)` premise candidates ranked by content-stem overlap are scored with NLI (`only_first` truncation at 512 tokens so the claim is never clipped):
   - `entailed` if any candidate has argmax `entailment` and $P(\text{entail}) \ge 0.50$ (also reported at $\ge 0.70$)
   - else `contradicted` if any topically overlapping candidate (`overlap >= 2` stems) has argmax `contradiction` and $P(\text{contradict}) \ge 0.70$
   - else `neutral` (ungrounded / unsupported by retrieved notes).

### Why Sentence-Level Granularity Mattered (Caught by Blind Calibration)

In our initial run using naive `900`-character multi-paragraph chunks, `nli-deberta-v3-xsmall` scored only **12.9% 3-way agreement ($\kappa = 0.047$)** against our already-locked blind human labels — classifying `15/18` human-entailed claims as `contradiction`. Testing the exact same inputs in PyTorch FP32 reproduced the failure (`0.986` contradiction on a 900-char chunk vs `0.993` entailment on the isolated sentence): MNLI/SNLI models are trained on single sentences and treat unrelated adjacent sentences inside a multi-topic PDF excerpt as contradictory. Switching to SummaC-ZS 1- and 2-sentence premises with topic-overlap contradiction gating resolved the mismatch cleanly without modifying any blind label.

## Blind Human Calibration (`calibration_labels.jsonl`, `n=31`)

Thirty-one deduplicated `(question_id, claim)` items spanning closed-book and grounded answers were sampled (`--export-calibration-blind`) and labeled strictly **before** running NLI on `questions_slice.r3.json`:

- **3-way (`entailed` / `neutral` / `contradicted`):** exact agreement = **71.0%** (`22/31`), Cohen's $\kappa$ = **0.466** (expected chance = `45.7%`)
- **Binary (`entailed` vs `not_entailed`):** agreement = **77.4%** (`24/31`), Cohen's $\kappa$ = **0.551**

| Human \ NLI | entailed | neutral | contradicted |
|---|---|---|---|
| **entailed** | 13 | 4 | 1 |
| **neutral** | 2 | 9 | 2 |
| **contradicted** | 0 | 0 | 0 |

## `questions_slice.r3` Results (`results/faithfulness.r3.{json,md}`)

Evaluated on `11` GraphRAG-Bench medical questions (`232` unique claims, `6,960` `(premise, claim)` NLI inferences):

| Arm | Answered Qs | Claims | % Entailed | % Neutral (Ungrounded) | % Contradicted | Mean Answer % Entailed | Strict $p \ge 0.7$ % Entailed |
|---|---|---|---|---|---|---|---|
| `closed_book` | 11/11 | 166 | **9.6%** | 53.6% | 36.7% | 13.7% | 7.8% |
| `vector_only` | 11/11 | 59 | **61.0%** | 28.8% | 10.2% | 59.8% | 55.9% |
| `graph_only` | 10/11 | 50 | **58.0%** | 30.0% | 12.0% | 54.5% | 54.0% |
| `global_only` | 6/11 | 30 | **70.0%** | 26.7% | 3.3% | 73.7% | 70.0% |
| `shipped` | 11/11 | 59 | **59.3%** | 30.5% | 10.2% | 57.5% | 55.9% |

- **Grounded vs. closed book:** Grounded retrieval boosts claim entailment by **+49.7 percentage points** (`59.3%` `shipped` vs `9.6%` `closed_book`) and cuts unsupported parametric essays sharply (`166` ungrounded-heavy claims in `closed_book` vs `59` focused claims in `shipped`).
- **Remaining ungrounded tail (`~30%` neutral in `shipped`):** Mostly reflects conversational note-gap recommendations (`"consider adding notes..."`) and minor external clinical elaborations beyond the NCCN patient excerpts.

> **Important `r3` slice audit note:** `10/11` questions in `eval/graphrag/results/questions_slice.r3.json` have **byte-identical** answer text across all non-empty grounded arms (`vector_only`, `graph_only`, `global_only`, `shipped`); only `global_only` (`5/11` empty) and `graph_only` (`1/11` empty) differ materially in coverage, and `questions_slice.r3.json` stores `note_titles` rather than per-arm formatted context strings. Future `run_eval.py` runs should persist each arm's formatted context alongside `answer` so NLI can compare per-arm context isolation directly.

## Reproduce

```bash
python eval/faithfulness/fetch_nli.py
python eval/faithfulness/nli.py --self-test
python eval/faithfulness/score_faithfulness.py --corpus /path/to/grb/corpus.jsonl
```

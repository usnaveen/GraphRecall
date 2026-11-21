# GraphRecall NeuroFeed & Real-Data Scheduler Benchmark

This directory evaluates the spaced-repetition schedulers shipped in [`backend/services/spaced_repetition.py`](../../backend/services/spaced_repetition.py) and documents the NeuroFeed ranking contract implemented in [`backend/feed_ranker/`](../../backend/feed_ranker/).

---

## 1. iOS Slider ↔ `DifficultyLevel` ↔ FSRS Grade Mapping

All review writes route through [`spaced_repetition.py`](../../backend/services/spaced_repetition.py) and persist both `interaction_type` (Migration `001`) and `rating` `1..4` (Migration `016`) on `study_sessions`:

| iOS Slider Band (`FeedDifficultySlider.swift`) | `DifficultyLevel` | FSRS Grade | SM-2 Quality | Persisted `interaction_type` |
| :--- | :--- | :---: | :---: | :--- |
| `Easy` | `DifficultyLevel.EASY` (`"easy"`) | `4` | `5` | `"review:easy"` |
| `Knew it` | `DifficultyLevel.GOOD` (`"good"`) | `3` | `4` | `"review:good"` |
| `Shaky` | `DifficultyLevel.HARD` (`"hard"`) | `2` | `3` | `"review:hard"` |
| `No idea` | `DifficultyLevel.AGAIN` (`"again"`) | `1` | `1` | `"review:again"` |

---

## 2. Reproducing the Real-Data Causal Replay Benchmark

### Option A: Public Duolingo Slice (No Authentication Required)
Fetches a deterministic 15 MB HTTP-range prefix (`14,999,915` bytes, `147,723` rows, `3,859` users, `7,102` items, SHA-256 `a84846bb3fe48dbea148899c368881888ab1f2c05bb7fa1c6975ab9a2527f556`) from `Zai04/Duolingo-Spaced-Repetition-Data` (`learning_traces.13m.csv`) and runs strict causal online replay per `(user_id, item_id)` with 95% user-cluster bootstrap CIs (1,000 resamples, seed `42`):

```bash
python eval/feed_algo/fetch_real_traces.py
python eval/feed_algo/eval_scheduler.py --format duolingo --input eval/feed_algo/data/duolingo_traces_sample.csv
```

To score across the full 1.3 GB 14-day trace instead of the 15 MB prefix:

```bash
python eval/feed_algo/fetch_real_traces.py --bytes 1310000000
python eval/feed_algo/eval_scheduler.py --format duolingo --input eval/feed_algo/data/duolingo_traces_sample.csv
```

### Option B: Multi-Month/Multi-Year Anki Revlogs (`open-spaced-repetition/anki-revlogs-10k`)
Once authenticated on HuggingFace for the gated `open-spaced-repetition/anki-revlogs-10k` dataset, export/download the per-user revlogs directory and run:

```bash
python eval/feed_algo/eval_scheduler.py --format anki --input /path/to/anki-revlogs-dir
```

---

## 3. Observed Real-Data Results (15 MB Duolingo Prefix)

Evaluated across **707 eligible users** (`>= 20` causal transitions, **`39,497` scored transitions**, pass rate **`0.93954`**; **`507`** users with both pass and fail outcomes for per-user AUC):

| Model | Users | Transitions | Per-User LogLoss [95% CI] | Per-User RMSE [95% CI] | Per-User AUC [95% CI] | Micro `RMSE_bins` |
|---|---:|---:|---|---|---|---:|
| `constant_baseline` | 707 | 39,497 | 0.4545 [0.4115, 0.4973] | 0.1910 [0.1794, 0.2019] | 0.5130 [0.4961, 0.5294] | 0.0598 |
| `sm2_shipped` | 707 | 39,497 | 0.4848 [0.4392, 0.5293] | 0.1910 [0.1794, 0.2019] | 0.5309 [0.5150, 0.5471] | 0.0600 |
| `fsrs_shipped` | 707 | 39,497 | 0.4831 [0.4385, 0.5264] | 0.1909 [0.1793, 0.2018] | 0.5176 [0.4997, 0.5341] | 0.0600 |
| `fsrs_unclamped_ablation` | 707 | 39,497 | 0.4831 [0.4385, 0.5264] | 0.1909 [0.1793, 0.2018] | 0.5176 [0.4997, 0.5341] | 0.0600 |

Full JSON output is saved in [`results/real_scheduler_benchmark.json`](results/real_scheduler_benchmark.json).

### Diagnostic Interpretation of This Slice
- `learning_traces.13m.csv` is chronologically ordered across ~2 weeks, so its first 15 MB captures only the opening ~2–3 hours: **`98.55%`** of `seq[1:]` transitions occur with **`dt < 1 hour`** (`median dt = 0.0038 days ≈ 5.4 minutes`).
- Over 5-minute windows, every forgetting curve predicts `R ≈ 0.999`, so raw RMSE is tied (`0.1909–0.1910`), the small overshoot difference (`0.9998` vs `0.9996`) increases log-loss slightly when the `6%` within-session errors happen, and multi-day post-lapse clamping (`fsrs_shipped` vs `fsrs_unclamped_ablation`) is rarely exercised within a 2-hour horizon.
- Distinguishing multi-day spacing policies (`FSRS` vs `SM-2` vs lapse clamping) requires multi-day intervals via `--format anki` (`open-spaced-repetition/anki-revlogs-10k`) or the full 1.3 GB Duolingo trace.

---

## 4. Honest Evaluation Ceiling & Intentionally Deferred Components

- **What this benchmark proves:** Real-world causal recall prediction on public learner traces (`eval_scheduler.py`) and deterministic correctness of FSRS retrievability ranking, prerequisite backtracking, `"Revisit"` gating, pool-centered MMR diversity, and `FEED_DEMO_CARDS` gating (`backend/tests/test_spaced_repetition.py`, `backend/tests/test_feed_ranker.py`).
- **What it does NOT prove:** User engagement lift or retention gain in GraphRecall's live iOS reels feed — measuring that requires longitudinal multi-user telemetry from a real cohort.
- **Deferred until cohort data exists:** Contextual bandits (`HyperBandit+`), neural semantic interference (`LECTOR`), log-det `k`-DPP subset sampling, and quantile dwell-time debiasing are intentionally omitted from Phase 1 because a single-user database lacks the cross-user interaction data needed to fit or ablate them honestly.

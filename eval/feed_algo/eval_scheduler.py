"""Strict causal online replay benchmark for GraphRecall's spaced-repetition schedulers.

Supports:
  --format duolingo : Zai04/Duolingo-Spaced-Repetition-Data CSV slice
  --format anki     : open-spaced-repetition/anki-revlogs-10k CSV/TSV directory or file
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np

try:
    import fsrs as py_fsrs  # type: ignore
except ImportError:
    py_fsrs = None

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.models.feed_schemas import DifficultyLevel  # noqa: E402
from backend.services.spaced_repetition import FSRSAlgorithm, SM2Algorithm  # noqa: E402

DEFAULT_DUOLINGO_PATH = Path(__file__).resolve().parent / "data" / "duolingo_traces_sample.csv"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "real_scheduler_benchmark.json"


@dataclass
class TraceEvent:
    user_id: str
    item_id: str
    timestamp: float
    elapsed_days: float
    y: int
    p_recall: float
    grade: int


@dataclass
class ScoredTransition:
    user_id: str
    y: int
    p_recall: float
    pred: float


def load_duolingo_events(path: Path) -> list[TraceEvent]:
    """Load Duolingo CSV trace slice into ordered per-(user, item) events."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            grouped[(row["user_id"], row["lexeme_id"])].append(row)

    events: list[TraceEvent] = []
    for (uid, item_id), rows in grouped.items():
        rows.sort(key=lambda r: float(r["timestamp"]))
        prev_ts: Optional[float] = None
        for r in rows:
            ts = float(r["timestamp"])
            delta_sec = float(r["delta"])
            if prev_ts is not None and ts > prev_ts:
                elapsed_days = (ts - prev_ts) / 86400.0
            else:
                elapsed_days = max(0.0, delta_sec / 86400.0)
            prev_ts = ts

            p_val = max(0.0, min(1.0, float(r["p_recall"])))
            y = 1 if p_val >= 0.5 else 0
            grade = 3 if y == 1 else 1
            events.append(
                TraceEvent(
                    user_id=uid,
                    item_id=item_id,
                    timestamp=ts,
                    elapsed_days=elapsed_days,
                    y=y,
                    p_recall=p_val,
                    grade=grade,
                )
            )
    return events


def load_anki_events(path: Path) -> list[TraceEvent]:
    """Load Anki revlogs (file or directory of per-user CSV/TSV/Parquet files)."""
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for fp in files:
        if not fp.is_file():
            continue
        suffix = fp.suffix.lower()
        default_uid = fp.stem
        if default_uid.startswith("revlogs_"):
            default_uid = default_uid[len("revlogs_") :]
        elif fp.parent.name.startswith("user_id="):
            default_uid = fp.parent.name.split("=", 1)[1]

        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            with fp.open("r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f, delimiter=delimiter):
                    uid = str(row.get("user_id") or default_uid)
                    cid = str(row["card_id"])
                    grouped[(uid, cid)].append(row)
        elif suffix == ".parquet":
            try:
                import pyarrow.parquet as pq  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Installing pyarrow is required to read .parquet Anki revlogs") from exc
            table = pq.read_table(fp)
            for row in table.to_pylist():
                uid = str(row.get("user_id") or default_uid)
                cid = str(row["card_id"])
                grouped[(uid, cid)].append(row)

    events: list[TraceEvent] = []
    for (uid, cid), rows in grouped.items():
        rows.sort(key=lambda r: float(r.get("review_th") or r.get("day_offset") or 0))
        for idx, r in enumerate(rows):
            rating = int(float(r["rating"]))
            rating = max(1, min(4, rating))
            raw_elapsed = r.get("elapsed_days", r.get("delta_t", -1))
            raw_elapsed_f = -1.0 if raw_elapsed is None else float(raw_elapsed)
            elapsed_days = max(0.0, raw_elapsed_f) if idx > 0 and raw_elapsed_f > 0 else 0.0
            y = 1 if rating > 1 else 0
            ts_val = float(r.get("review_th") if r.get("review_th") is not None else idx)
            events.append(
                TraceEvent(
                    user_id=uid,
                    item_id=cid,
                    timestamp=ts_val,
                    elapsed_days=elapsed_days,
                    y=y,
                    p_recall=float(y),
                    grade=rating,
                )
            )
    return events


def _fsrs_unclamped_next_stability(s: float, d: float, r: float, grade: int) -> float:
    """FSRS fail path before our min(s, fail_s) clamp fix, for direct ablation."""
    if grade != 1:
        return FSRSAlgorithm.next_stability(s, d, r, grade)
    w = FSRSAlgorithm.W
    fail_s = (
        w[11]
        * d ** (-w[12])
        * ((s + 1) ** w[13] - 1)
        * math.exp(w[14] * (1.0 - r))
    )
    return max(0.1, fail_s)


def replay_model(events: Iterable[TraceEvent], model_name: str) -> list[ScoredTransition]:
    """Run strict causal online replay per (user_id, item_id) using shipped schedulers."""
    series: dict[tuple[str, str], list[TraceEvent]] = defaultdict(list)
    for ev in events:
        series[(ev.user_id, ev.item_id)].append(ev)

    outputs: list[ScoredTransition] = []

    for (uid, _), seq in series.items():
        seq.sort(key=lambda e: e.timestamp)
        if len(seq) < 2:
            continue

        # Initialize state from first observed review (step == 0)
        first = seq[0]
        if model_name == "constant_baseline":
            pass
        elif model_name == "sm2_shipped":
            ef = 2.5
            interval = 1
            rep = 0
            q_lvl = DifficultyLevel.GOOD if first.y == 1 else DifficultyLevel.AGAIN
            ef, interval, rep = SM2Algorithm.calculate_new_interval(
                ef, interval, rep, SM2Algorithm.DIFFICULTY_TO_QUALITY[q_lvl]
            )
        elif model_name == "py_fsrs_reference":
            if py_fsrs is None:
                raise RuntimeError("py-fsrs package is not installed")
            py_scheduler = py_fsrs.Scheduler(
                learning_steps=(),
                relearning_steps=(),
                enable_fuzzing=False,
            )
            rating_map = {
                1: py_fsrs.Rating.Again,
                2: py_fsrs.Rating.Hard,
                3: py_fsrs.Rating.Good,
                4: py_fsrs.Rating.Easy,
            }
            t_cur = datetime(2025, 1, 1, tzinfo=timezone.utc)
            py_card, _ = py_scheduler.review_card(
                py_fsrs.Card(), rating_map[first.grade], review_datetime=t_cur
            )
        elif model_name in {"fsrs_shipped", "fsrs_unclamped_ablation"}:
            s = FSRSAlgorithm.initial_stability(first.grade)
            d = FSRSAlgorithm.initial_difficulty(first.grade)
        else:
            raise ValueError(f"Unknown model: {model_name}")

        # Score step >= 1 transitions BEFORE consuming the outcome
        for ev in seq[1:]:
            dt = ev.elapsed_days
            if dt <= 0.0:
                continue

            if model_name == "constant_baseline":
                pred = 0.9 ** (dt / 1.0)
            elif model_name == "sm2_shipped":
                pred = 0.9 ** (dt / max(1.0, float(interval)))
            elif model_name == "py_fsrs_reference":
                t_cur = t_cur + timedelta(days=dt)
                factor = getattr(py_scheduler, "_FACTOR", None)
                decay = getattr(py_scheduler, "_DECAY", None)
                if factor is not None and decay is not None and py_card.stability:
                    pred = (1.0 + float(factor) * dt / float(py_card.stability)) ** float(decay)
                else:
                    pred = float(py_scheduler.get_card_retrievability(py_card, current_datetime=t_cur))
            else:
                pred = FSRSAlgorithm.retrievability(dt, s)

            pred = float(min(1.0 - 1e-6, max(1e-6, pred)))
            outputs.append(
                ScoredTransition(
                    user_id=uid,
                    y=ev.y,
                    p_recall=ev.p_recall,
                    pred=pred,
                )
            )

            # Update causal state after scoring
            if model_name == "sm2_shipped":
                q_lvl = DifficultyLevel.GOOD if ev.y == 1 else DifficultyLevel.AGAIN
                ef, interval, rep = SM2Algorithm.calculate_new_interval(
                    ef, interval, rep, SM2Algorithm.DIFFICULTY_TO_QUALITY[q_lvl]
                )
            elif model_name == "py_fsrs_reference":
                py_card, _ = py_scheduler.review_card(
                    py_card, rating_map[ev.grade], review_datetime=t_cur
                )
            elif model_name == "fsrs_shipped":
                r_state = FSRSAlgorithm.retrievability(dt, s)
                s = FSRSAlgorithm.next_stability(s, d, r_state, ev.grade)
                d = FSRSAlgorithm.next_difficulty(d, ev.grade)
            elif model_name == "fsrs_unclamped_ablation":
                r_state = FSRSAlgorithm.retrievability(dt, s)
                s = _fsrs_unclamped_next_stability(s, d, r_state, ev.grade)
                d = FSRSAlgorithm.next_difficulty(d, ev.grade)

    return outputs


def roc_auc_score_np(y: np.ndarray, scores: np.ndarray) -> Optional[float]:
    """Exact tie-aware Mann-Whitney U ROC-AUC in pure NumPy."""
    pos = int(np.sum(y == 1))
    neg = int(np.sum(y == 0))
    if pos == 0 or neg == 0:
        return None

    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    sorted_y = y[order]

    # Assign average ranks for tied predictions
    n = len(scores)
    ranks = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_scores[j] == sorted_scores[i]:
            j += 1
        avg_rank = 0.5 * ((i + 1) + j)
        ranks[i:j] = avg_rank
        i = j

    pos_rank_sum = float(np.sum(ranks[sorted_y == 1]))
    auc = (pos_rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)
    return float(auc)


def calibration_rmse_np(y: np.ndarray, preds: np.ndarray, bins: int = 20) -> float:
    """20-bin calibration RMSE (RMSE_bins) following open-spaced-repetition protocol."""
    if len(y) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, bins + 1)
    bin_idx = np.clip(np.digitize(preds, edges[1:-1], right=True), 0, bins - 1)
    sq_err = 0.0
    total = float(len(y))
    for b in range(bins):
        mask = bin_idx == b
        cnt = int(np.sum(mask))
        if cnt == 0:
            continue
        diff = float(np.mean(preds[mask]) - np.mean(y[mask]))
        sq_err += (cnt / total) * (diff ** 2)
    return float(math.sqrt(sq_err))


def compute_metrics(
    transitions: list[ScoredTransition],
    min_user_transitions: int = 20,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> dict:
    """Compute micro metrics and per-user mean metrics with 95% user-cluster bootstrap CIs."""
    by_user: dict[str, list[ScoredTransition]] = defaultdict(list)
    for t in transitions:
        by_user[t.user_id].append(t)

    eligible_users = sorted(
        uid for uid, rows in by_user.items() if len(rows) >= min_user_transitions
    )
    eligible_rows = [row for uid in eligible_users for row in by_user[uid]]

    y_all = np.array([r.y for r in eligible_rows], dtype=np.float64)
    p_true_all = np.array([r.p_recall for r in eligible_rows], dtype=np.float64)
    p_all = np.clip(np.array([r.pred for r in eligible_rows], dtype=np.float64), 1e-6, 1.0 - 1e-6)

    micro_log_loss = float(-np.mean(y_all * np.log(p_all) + (1.0 - y_all) * np.log(1.0 - p_all)))
    micro_rmse = float(np.sqrt(np.mean((y_all - p_all) ** 2)))
    micro_rmse_bins = calibration_rmse_np(y_all, p_all, bins=20)
    micro_brier_cont = float(np.mean((p_true_all - p_all) ** 2))
    micro_auc = roc_auc_score_np(y_all, p_all)

    user_metrics: list[dict[str, Optional[float]]] = []
    for uid in eligible_users:
        rows = by_user[uid]
        uy = np.array([r.y for r in rows], dtype=np.float64)
        up_true = np.array([r.p_recall for r in rows], dtype=np.float64)
        up = np.clip(np.array([r.pred for r in rows], dtype=np.float64), 1e-6, 1.0 - 1e-6)
        ll = float(-np.mean(uy * np.log(up) + (1.0 - uy) * np.log(1.0 - up)))
        rmse = float(np.sqrt(np.mean((uy - up) ** 2)))
        brier = float(np.mean((up_true - up) ** 2))
        auc = roc_auc_score_np(uy, up)
        user_metrics.append({"log_loss": ll, "rmse": rmse, "brier": brier, "auc": auc})

    def _mean_and_ci(vals: list[float]) -> dict[str, float]:
        arr = np.array(vals, dtype=np.float64)
        if len(arr) == 0:
            return {"mean": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
        rng = np.random.default_rng(seed)
        boot = np.empty(n_bootstrap, dtype=np.float64)
        for b in range(n_bootstrap):
            sample = arr[rng.integers(0, len(arr), size=len(arr))]
            boot[b] = float(np.mean(sample))
        return {
            "mean": round(float(np.mean(arr)), 5),
            "ci_low": round(float(np.percentile(boot, 2.5)), 5),
            "ci_high": round(float(np.percentile(boot, 97.5)), 5),
        }

    return {
        "eligible_users": len(eligible_users),
        "scored_transitions": len(eligible_rows),
        "positive_rate": round(float(np.mean(y_all)), 5) if len(y_all) else None,
        "micro": {
            "log_loss": round(micro_log_loss, 5),
            "rmse": round(micro_rmse, 5),
            "rmse_bins_20": round(micro_rmse_bins, 5),
            "brier_vs_p_recall": round(micro_brier_cont, 5),
            "auc": round(micro_auc, 5) if micro_auc is not None else None,
        },
        "per_user_95ci": {
            "log_loss": _mean_and_ci([m["log_loss"] for m in user_metrics if m["log_loss"] is not None]),
            "rmse": _mean_and_ci([m["rmse"] for m in user_metrics if m["rmse"] is not None]),
            "brier_vs_p_recall": _mean_and_ci([m["brier"] for m in user_metrics if m["brier"] is not None]),
            "auc": _mean_and_ci([m["auc"] for m in user_metrics if m["auc"] is not None]),
            "auc_valid_users": sum(1 for m in user_metrics if m["auc"] is not None),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("duolingo", "anki"), default="duolingo")
    parser.add_argument("--input", "--data-dir", dest="input_path", type=Path, default=DEFAULT_DUOLINGO_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--min-user-transitions", type=int, default=20)
    args = parser.parse_args()

    if not args.input_path.exists():
        raise FileNotFoundError(
            f"Input traces not found at {args.input_path}. Run fetch_real_traces.py first."
        )

    events = (
        load_duolingo_events(args.input_path)
        if args.format == "duolingo"
        else load_anki_events(args.input_path)
    )

    models = [
        "constant_baseline",
        "sm2_shipped",
        "fsrs_shipped",
        "fsrs_unclamped_ablation",
    ]
    if py_fsrs is not None:
        models.append("py_fsrs_reference")

    results = {
        "dataset_format": args.format,
        "input_path": str(args.input_path),
        "total_raw_events": len(events),
        "min_user_transitions": args.min_user_transitions,
        "models": {},
    }

    for name in models:
        transitions = replay_model(events, name)
        results["models"][name] = compute_metrics(
            transitions, min_user_transitions=args.min_user_transitions
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print(
        f"| Model | Users | Transitions | Per-User LogLoss [95% CI] | "
        f"Per-User RMSE [95% CI] | Per-User AUC [95% CI] | Micro RMSE_bins |\n"
        f"|---|---:|---:|---|---|---|---:|"
    )
    for name in models:
        m = results["models"][name]
        pu = m["per_user_95ci"]
        ll = pu["log_loss"]
        rm = pu["rmse"]
        au = pu["auc"]
        print(
            f"| `{name}` | {m['eligible_users']} | {m['scored_transitions']} | "
            f"{ll['mean']:.4f} [{ll['ci_low']:.4f}, {ll['ci_high']:.4f}] | "
            f"{rm['mean']:.4f} [{rm['ci_low']:.4f}, {rm['ci_high']:.4f}] | "
            f"{au['mean']:.4f} [{au['ci_low']:.4f}, {au['ci_high']:.4f}] | "
            f"{m['micro']['rmse_bins_20']:.4f} |"
        )


if __name__ == "__main__":
    main()

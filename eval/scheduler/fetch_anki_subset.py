"""Download a reproducible random subset of the Anki Revlogs 10K review logs (FSRS project).

Dataset: open-spaced-repetition/anki-revlogs-10k on Hugging Face (licence: research use, no public
redistribution). Only per-user `revlogs` parquet files are fetched, into eval/scheduler/data/
(git-ignored). Users are sampled with a fixed seed so the benchmark is reproducible.

    .venv/bin/python eval/scheduler/fetch_anki_subset.py [--users 300] [--seed 7] [--max-mb 600]
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

REPO = "open-spaced-repetition/anki-revlogs-10k"
DATA = Path(__file__).resolve().parent / "data"
HEADERS = {"User-Agent": "dataset-fetch/1.0"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-mb", type=float, default=600)
    a = ap.parse_args()

    # Listing 30k files' metadata takes too long on slow links, so sample user ids directly
    # (collections are numbered 1..10000) and stop once enough were fetched or max-mb is reached.
    users = [str(u) for u in range(1, 10001)]
    random.Random(a.seed).shuffle(users)
    rev = {}
    picked, total = [], 0.0
    DATA.mkdir(parents=True, exist_ok=True)
    import requests  # ships with huggingface_hub; uses certifi's CA bundle

    for u in users:
        if len(picked) >= a.users or total >= a.max_mb:
            break
        dest = DATA / f"revlogs_{u}.parquet"
        if not dest.exists():
            url = f"https://huggingface.co/datasets/{REPO}/resolve/main/revlogs/user_id={u}/data.parquet"
            for attempt in range(4):
                try:
                    r = requests.get(url, headers=HEADERS, timeout=120)
                    if r.status_code == 404:
                        break
                    r.raise_for_status()
                    dest.write_bytes(r.content)
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"  retry {u}: {e}", flush=True)
                    time.sleep(3)
        if dest.exists():
            picked.append(u)
            total += dest.stat().st_size / 1e6
            if len(picked) % 25 == 0:
                print(f"{len(picked)} users, {total:.0f} MB", flush=True)
    (DATA / "manifest.json").write_text(json.dumps({"repo": REPO, "seed": a.seed, "users": picked,
                                                    "mb": round(total, 1)}, indent=1))
    print(f"{len(picked)} users, {total:.0f} MB in {DATA}")


if __name__ == "__main__":
    main()

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
    from huggingface_hub import HfApi

    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-mb", type=float, default=600)
    a = ap.parse_args()

    info = HfApi().dataset_info(REPO, files_metadata=True)
    rev = {s.rfilename.split("user_id=")[1].split("/")[0]: s.size or 0
           for s in info.siblings if s.rfilename.startswith("revlogs/user_id=")}
    users = sorted(rev, key=int)
    random.Random(a.seed).shuffle(users)
    picked, total = [], 0.0
    for u in users:
        mb = rev[u] / 1e6
        if total + mb > a.max_mb:
            continue
        picked.append(u)
        total += mb
        if len(picked) >= a.users:
            break
    DATA.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(picked, 1):
        dest = DATA / f"revlogs_{u}.parquet"
        if dest.exists() and dest.stat().st_size == rev[u]:
            continue
        url = f"https://huggingface.co/datasets/{REPO}/resolve/main/revlogs/user_id={u}/data.parquet"
        for attempt in range(4):
            try:
                import requests  # ships with huggingface_hub; uses certifi's CA bundle

                r = requests.get(url, headers=HEADERS, timeout=120)
                r.raise_for_status()
                dest.write_bytes(r.content)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  retry {u}: {e}", flush=True)
                time.sleep(3)
        if i % 25 == 0:
            print(f"{i}/{len(picked)} users", flush=True)
    (DATA / "manifest.json").write_text(json.dumps({"repo": REPO, "seed": a.seed, "users": picked,
                                                    "mb": round(total, 1)}, indent=1))
    print(f"{len(picked)} users, {total:.0f} MB in {DATA}")


if __name__ == "__main__":
    main()

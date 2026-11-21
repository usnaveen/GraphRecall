"""Fetch a deterministic public slice of Duolingo spaced-repetition learning traces."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import httpx

DATASET_URL = (
    "https://huggingface.co/datasets/Zai04/Duolingo-Spaced-Repetition-Data/"
    "resolve/main/learning_traces.13m.csv"
)
DEFAULT_OUT = Path(__file__).resolve().parent / "data" / "duolingo_traces_sample.csv"
DEFAULT_BYTES = 15_000_000


def download_range(url: str, out_path: Path, max_bytes: int) -> Path:
    """Download [0, max_bytes - 1] bytes and trim any incomplete trailing line."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "Range": f"bytes=0-{max_bytes - 1}",
        "User-Agent": "GraphRecall-Eval/1.0",
    }
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    raw = resp.content

    # Trim incomplete last CSV line so row parsing stays clean
    last_nl = raw.rfind(b"\n")
    if last_nl != -1:
        raw = raw[: last_nl + 1]

    out_path.write_bytes(raw)
    return out_path


def summarize_csv(path: Path) -> dict[str, str | int]:
    """Compute SHA-256 and basic cardinality stats for the downloaded trace slice."""
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    users: set[str] = set()
    items: set[str] = set()
    rows = 0
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1
            users.add(row["user_id"])
            items.add(row["lexeme_id"])
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256,
        "rows": rows,
        "unique_users": len(users),
        "unique_items": len(items),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DATASET_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bytes", type=int, default=DEFAULT_BYTES)
    args = parser.parse_args()

    out_path = download_range(args.url, args.out, args.bytes)
    stats = summarize_csv(out_path)
    for key, val in stats.items():
        print(f"{key}: {val}")


if __name__ == "__main__":
    main()

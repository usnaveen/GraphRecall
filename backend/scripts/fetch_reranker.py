"""Fetch the cross-encoder reranker (ms-marco-MiniLM-L6-v2, INT8 ONNX) into backend/models/reranker/.

The files come from the model's official Hugging Face repo at a pinned revision, and every file is
checked against a SHA-256 recorded here, so a build either gets exactly these bytes or fails.
The INT8 build is picked for the CPU: qint8 arm64 on Apple silicon / Graviton, quint8 AVX2 on x86.

    python -m backend.scripts.fetch_reranker            # used by the Dockerfile
    python -m backend.scripts.fetch_reranker --check    # verify what is on disk, download nothing

Model: cross-encoder/ms-marco-MiniLM-L6-v2, Apache-2.0. It was trained on MS MARCO, whose terms
restrict the *dataset* to non-commercial research; check that before a commercial launch.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import sys
import shutil
import ssl
import urllib.request
from pathlib import Path

REPO = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
DEST = Path(__file__).resolve().parents[1] / "models" / "reranker"

FILES = {
    "vocab.txt": ("vocab.txt", "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
    "arm64": ("onnx/model_qint8_arm64.onnx", "3573b6b9593cb2f75987a31815d409ca3dd8808629118fd20451bb1a5d90cec7"),
    "x86_64": ("onnx/model_quint8_avx2.onnx", "c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9"),
}


def _ssl_context() -> ssl.SSLContext:
    """System CAs, or certifi's when the interpreter has none (python.org builds on macOS)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def plan() -> list[tuple[str, str, Path]]:
    """(remote path, expected sha256, local path) for vocab + this machine's model."""
    vocab_remote, vocab_sha = FILES["vocab.txt"]
    model_remote, model_sha = FILES[_arch()]
    return [(vocab_remote, vocab_sha, DEST / "vocab.txt"), (model_remote, model_sha, DEST / "model.int8.onnx")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify files on disk; download nothing")
    args = ap.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    ok = True
    for remote, sha, local in plan():
        if local.exists() and _sha256(local) == sha:
            print(f"ok       {local.relative_to(DEST.parents[1])}")
            continue
        if args.check:
            print(f"MISSING  {local.relative_to(DEST.parents[1])} (or wrong hash)", file=sys.stderr)
            ok = False
            continue
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}"
        tmp = local.with_suffix(local.suffix + ".part")
        with urllib.request.urlopen(url, context=_ssl_context(), timeout=120) as resp, tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        got = _sha256(tmp)
        if got != sha:
            tmp.unlink(missing_ok=True)
            print(f"FAIL     {remote}: sha256 {got} != pinned {sha}", file=sys.stderr)
            return 1
        tmp.replace(local)
        print(f"fetched  {remote} -> {local.relative_to(DEST.parents[1])}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

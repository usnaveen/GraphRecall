"""Fetch the local NLI cross-encoder (cross-encoder/nli-deberta-v3-xsmall, INT8 ONNX) into eval/faithfulness/models/.

The files come from the official Hugging Face repo at a pinned revision, and every file is
verified against a SHA-256 recorded here so evaluations are reproducible and self-contained.
Default picks the CPU-appropriate quantized ONNX file (`qint8_arm64` on Apple Silicon / Graviton,
`quint8_avx2` on x86_64); pass `--fp32` for the unquantized FP32 graph (`onnx/model.onnx`).

    python eval/faithfulness/fetch_nli.py
    python eval/faithfulness/fetch_nli.py --check
    python eval/faithfulness/fetch_nli.py --fp32

Model: cross-encoder/nli-deberta-v3-xsmall (Apache-2.0). Trained on MNLI + SNLI.
Weights are gitignored in eval/faithfulness/models/.
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import ssl
import sys
import urllib.request
from pathlib import Path

REPO = "cross-encoder/nli-deberta-v3-xsmall"
REVISION = "a150876415327c80daeff35ca6f68f5ed8cf5c24"
DEST = Path(__file__).resolve().parent / "models" / "nli-deberta-v3-xsmall"

FILES = {
    "config.json": ("config.json", "8d9f07bf7ba54a6fc3b1962483056f94c39dcf188db4cf61843e1c88f94b2342"),
    "tokenizer.json": ("tokenizer.json", "5124ef2ead1a10a717703bc436de7f353da76d6340e4587719b42b1693707964"),
    "arm64": ("onnx/model_qint8_arm64.onnx", "ef41fe8474f6070373f97fbe8362461d55108f387723280fcdb64f8015133db2"),
    "x86_64": ("onnx/model_quint8_avx2.onnx", "21b14751a95520953bfcc607ceeb617de7cbeaeb6d60f4c8966716c743985337"),
    "fp32": ("onnx/model.onnx", "7105da41f625c42eca24e9465ec99150d02a80e644659d7a1daa93a6357155d4"),
}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _arch_key(fp32: bool) -> str:
    if fp32:
        return "fp32"
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def plan(fp32: bool = False) -> list[tuple[str, str, Path]]:
    cfg_remote, cfg_sha = FILES["config.json"]
    tok_remote, tok_sha = FILES["tokenizer.json"]
    mod_remote, mod_sha = FILES[_arch_key(fp32)]
    mod_name = "model.fp32.onnx" if fp32 else "model.int8.onnx"
    return [
        (cfg_remote, cfg_sha, DEST / "config.json"),
        (tok_remote, tok_sha, DEST / "tokenizer.json"),
        (mod_remote, mod_sha, DEST / mod_name),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify files on disk; download nothing")
    ap.add_argument("--fp32", action="store_true", help="fetch FP32 ONNX weights instead of INT8")
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    ok = True
    for remote, sha, local in plan(fp32=args.fp32):
        rel = local.relative_to(DEST.parents[1])
        if local.exists() and _sha256(local) == sha:
            print(f"ok       {rel}")
            continue
        if args.check:
            print(f"MISSING  {rel} (or wrong hash)", file=sys.stderr)
            ok = False
            continue
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}"
        tmp = local.with_suffix(local.suffix + ".part")
        with urllib.request.urlopen(url, context=_ssl_context(), timeout=180) as resp, tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        got = _sha256(tmp)
        if got != sha:
            tmp.unlink(missing_ok=True)
            print(f"FAIL     {remote}: sha256 {got} != pinned {sha}", file=sys.stderr)
            return 1
        tmp.replace(local)
        print(f"fetched  {remote} -> {rel}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

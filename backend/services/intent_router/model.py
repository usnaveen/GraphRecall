"""Numpy-only inference for the trained chat intent classifier.

Training happens offline in ``eval/router/train.py`` with scikit-learn: word 1-2 gram TF-IDF plus
character 2-5 gram (word-boundary) TF-IDF, concatenated, then multinomial logistic regression.
The fitted vocabularies, idf vectors and weights are exported to JSON, and this module re-implements
exactly the sklearn transform so the API needs no sklearn or torch. ``eval/router/train.py``
asserts parity (max probability difference < 1e-6) before it writes the artifact.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

DEFAULT_ARTIFACT = Path(__file__).parent / "artifacts" / "intent_tfidf_lr.json"

_WORD_TOKEN = re.compile(r"(?u)\b\w\w+\b")
_WHITESPACE = re.compile(r"\s\s+")


def _word_ngrams(text: str, n_min: int, n_max: int) -> list[str]:
    tokens = _WORD_TOKEN.findall(text.lower())
    out: list[str] = []
    if n_min == 1:
        out.extend(tokens)
        n_min = 2
    for n in range(n_min, min(n_max, len(tokens)) + 1):
        out.extend(" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
    return out


def _char_wb_ngrams(text: str, n_min: int, n_max: int) -> list[str]:
    text = _WHITESPACE.sub(" ", text.lower())
    out: list[str] = []
    for w in text.split():
        w = f" {w} "
        w_len = len(w)
        for n in range(n_min, n_max + 1):
            offset = 0
            out.append(w[offset : offset + n])
            while offset + n < w_len:
                offset += 1
                out.append(w[offset : offset + n])
            if offset == 0:  # a word shorter than n is counted once
                break
    return out


@dataclass
class _Block:
    analyzer: str  # "word" | "char_wb"
    ngram_range: tuple[int, int]
    vocab: dict[str, int]
    idf: np.ndarray
    sublinear_tf: bool

    def transform(self, text: str) -> np.ndarray:
        lo, hi = self.ngram_range
        grams = _word_ngrams(text, lo, hi) if self.analyzer == "word" else _char_wb_ngrams(text, lo, hi)
        vec = np.zeros(len(self.idf), dtype=np.float64)
        for g in grams:
            j = self.vocab.get(g)
            if j is not None:
                vec[j] += 1.0
        nz = vec > 0
        if self.sublinear_tf:
            vec[nz] = 1.0 + np.log(vec[nz])
        vec *= self.idf
        norm = math.sqrt(float(vec @ vec))
        return vec / norm if norm > 0 else vec


@dataclass
class Prediction:
    intent: str
    confidence: float
    probs: dict[str, float]


class IntentClassifier:
    def __init__(self, spec: dict):
        self.version: str = spec["version"]
        self.classes: list[str] = list(spec["classes"])
        self.blocks = [
            _Block(
                analyzer=b["analyzer"],
                ngram_range=tuple(b["ngram_range"]),
                vocab={k: int(v) for k, v in b["vocab"].items()},
                idf=np.asarray(b["idf"], dtype=np.float64),
                sublinear_tf=bool(b["sublinear_tf"]),
            )
            for b in spec["blocks"]
        ]
        self.coef = np.asarray(spec["coef"], dtype=np.float64)  # (n_classes, n_features)
        self.intercept = np.asarray(spec["intercept"], dtype=np.float64)
        self.threshold: float = float(spec.get("threshold", 0.0))

    @classmethod
    def load(cls, path: Path = DEFAULT_ARTIFACT) -> "IntentClassifier":
        return cls(json.loads(Path(path).read_text()))

    def features(self, text: str) -> np.ndarray:
        return np.concatenate([b.transform(text) for b in self.blocks])

    def predict_proba(self, text: str) -> np.ndarray:
        z = self.coef @ self.features(text) + self.intercept
        z = z - z.max()
        e = np.exp(z)
        return e / e.sum()

    def predict(self, text: str) -> Prediction:
        p = self.predict_proba(text)
        i = int(np.argmax(p))
        return Prediction(
            intent=self.classes[i],
            confidence=float(p[i]),
            probs={c: float(v) for c, v in zip(self.classes, p)},
        )


@lru_cache(maxsize=1)
def get_classifier(path: Optional[str] = None) -> Optional[IntentClassifier]:
    """Load once per process. Returns None if the artifact is missing, so callers fall back to the LLM."""
    p = Path(path) if path else DEFAULT_ARTIFACT
    if not p.exists():
        return None
    return IntentClassifier.load(p)

"""The cross-encoder must either really run or say loudly that it doesn't.

Before packaging, the model lived in a git-ignored eval folder and onnxruntime was not a dependency,
so a deploy would have served the lexical reranker without anyone noticing."""

import pytest

from backend.scripts import fetch_reranker as fr
from backend.services import reranker as rr


def test_auto_mode_falls_back_to_lexical_when_the_model_is_missing(tmp_path):
    out = rr._cached_reranker("auto", str(tmp_path / "missing.onnx"), str(tmp_path / "vocab.txt"))
    assert isinstance(out, rr.LexicalOverlapReranker)


def test_onnx_mode_refuses_to_run_without_the_model(tmp_path):
    with pytest.raises(RuntimeError):
        rr._cached_reranker("onnx", str(tmp_path / "missing.onnx"), str(tmp_path / "vocab.txt"))


def test_default_model_lives_in_the_packaged_folder():
    assert rr.DEFAULT_INT8_ONNX_MODEL.parent == rr.RERANKER_DIR
    assert "eval" not in rr.RERANKER_DIR.parts


@pytest.mark.parametrize("machine,expected", [("arm64", "model_qint8_arm64"), ("aarch64", "model_qint8_arm64"),
                                              ("x86_64", "model_quint8_avx2"), ("AMD64", "model_quint8_avx2")])
def test_fetch_plan_picks_the_int8_build_for_the_cpu(monkeypatch, machine, expected):
    monkeypatch.setattr(fr.platform, "machine", lambda: machine)
    remotes = [remote for remote, _, _ in fr.plan()]
    assert remotes[0] == "vocab.txt" and expected in remotes[1]
    assert all(len(sha) == 64 for _, sha, _ in fr.plan())

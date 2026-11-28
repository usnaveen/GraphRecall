"""Documents read on the server: text PDFs, scanned PDFs (OCR), mixed PDFs, images, limits, and the endpoint.

Fixtures are generated here with PyMuPDF (a text page, the same page rendered to an image with no text
layer). OCR tests skip when the OCRia-nano model isn't installed (python -m backend.scripts.fetch_ocr_model).
"""

from __future__ import annotations

import asyncio
import io

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("liteparse")

from backend.services.ingestion import document_reader as dr  # noqa: E402

LINES = ["Attention Is All You Need", "", "The Transformer replaces recurrence with self-attention.",
         "Scaled dot-product attention divides the scores by the square root of the key dimension.",
         "Multi-head attention runs several attention functions in parallel.",
         "Positional encodings inject token order using sines and cosines."]

needs_ocr = pytest.mark.skipif(not dr.ocr_model_ready(), reason="OCRia-nano model not installed")


def _text_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in LINES:
        page.insert_text((60, y), line, fontsize=12)
        y += 22
    return doc.tobytes()


def _page_png(pdf: bytes) -> bytes:
    return pymupdf.open(stream=pdf, filetype="pdf")[0].get_pixmap(dpi=200).tobytes("png")


def _scanned_pdf(pdf: bytes) -> bytes:
    png = _page_png(pdf)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=png)
    return doc.tobytes(deflate=True)


def _join(*pdfs: bytes) -> bytes:
    out = pymupdf.open()
    for b in pdfs:
        out.insert_pdf(pymupdf.open(stream=b, filetype="pdf"))
    return out.tobytes(deflate=True)


def test_content_type_from_extension_or_header():
    assert dr.content_type_for("notes.PDF", None) == "application/pdf"
    assert dr.content_type_for("x", "image/jpg") == "image/jpeg"
    assert dr.content_type_for("photo.heic", None) is None
    assert dr.content_type_for("report.docx", "application/octet-stream") is None


async def test_text_pdf_reads_natively_without_ocr():
    doc = await dr.read_document(_text_pdf(), "paper.pdf")
    assert doc.method == "native" and doc.ocr_pages == []
    assert "self-attention" in doc.markdown


@needs_ocr
async def test_scanned_pdf_is_read_with_ocr():
    doc = await dr.read_document(_scanned_pdf(_text_pdf()), "scan.pdf")
    assert doc.method == "ocr" and doc.ocr_pages == [1]
    assert "Transformer" in doc.markdown and "recurrence" in doc.markdown


@needs_ocr
async def test_mixed_pdf_ocrs_only_the_scanned_page():
    text = _text_pdf()
    doc = await dr.read_document(_join(text, _scanned_pdf(text), text), "mixed.pdf")
    assert doc.pages == 3 and doc.ocr_pages == [2] and doc.method == "native+ocr"


@needs_ocr
async def test_image_is_read_with_ocr():
    doc = await dr.read_document(_page_png(_text_pdf()), "page.png", "image/png")
    assert doc.method == "ocr" and "attention" in doc.markdown.lower()


async def test_without_the_model_scanned_pages_are_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(dr, "ocr_model_ready", lambda: False)
    text = _text_pdf()
    doc = await dr.read_document(_join(text, _scanned_pdf(text)), "mixed.pdf")
    assert doc.skipped_pages == [2] and doc.ocr_pages == []
    assert any("skipped" in w for w in doc.warnings)
    with pytest.raises(dr.DocumentError, match="OCR model"):
        await dr.read_document(_scanned_pdf(text), "scan.pdf")
    with pytest.raises(dr.DocumentError, match="OCR model"):
        await dr.read_document(_page_png(text), "page.png")


@pytest.mark.parametrize("name,data,msg", [
    ("notes.docx", b"PK\x03\x04", "Unsupported"),
    ("fake.pdf", b"hello", "isn't a valid PDF"),
    ("empty.pdf", b"", "empty"),
])
async def test_bad_files_are_rejected_with_a_reason(name, data, msg):
    with pytest.raises(dr.DocumentError, match=msg):
        await dr.read_document(data, name)


async def test_size_and_page_caps(monkeypatch):
    monkeypatch.setattr(dr, "MAX_BYTES", 100)
    with pytest.raises(dr.DocumentError, match="limit"):
        await dr.read_document(_text_pdf(), "big.pdf")
    monkeypatch.setattr(dr, "MAX_BYTES", 50 * 1024 * 1024)
    monkeypatch.setattr(dr, "MAX_PAGES", 1)
    with pytest.raises(dr.DocumentError, match="pages"):
        await dr.read_document(_join(_text_pdf(), _text_pdf()), "two.pdf")


# --------------------------------------------------------------------------- endpoint


def _upload(data: bytes, name: str, ctype: str):
    from fastapi import UploadFile
    from starlette.datastructures import Headers

    return UploadFile(file=io.BytesIO(data), filename=name, headers=Headers({"content-type": ctype}))


@pytest.fixture
def ingest(monkeypatch):
    from backend.routers import ingest_v2

    calls: dict = {"ingested": [], "existing": None}

    async def fake_existing(user_id, h):
        return calls["existing"]

    async def fake_run_ingestion(**kw):
        calls["ingested"].append(kw)
        return {"status": "completed", "note_id": "note-1", "concept_ids": ["c1"], "concepts": [{"name": "x"}]}

    async def noop(*a, **k):
        return None

    monkeypatch.setattr("backend.graphs.article_graph._existing_note", fake_existing)
    monkeypatch.setattr(ingest_v2, "run_ingestion", fake_run_ingestion)
    for name in ("_schedule_community_recompute", "_enqueue_note_ingested_event", "_schedule_reembed_if_needed",
                 "_schedule_quiz_scan"):
        monkeypatch.setattr(ingest_v2, name, noop)
    tasks: list = []
    real_create_task = asyncio.create_task
    monkeypatch.setattr(ingest_v2.asyncio, "create_task", lambda coro: tasks.append(real_create_task(coro)) or tasks[-1])
    calls["tasks"] = tasks
    return ingest_v2, calls


async def test_endpoint_reads_in_background_then_ingests(ingest):
    ingest_v2, calls = ingest
    res = await ingest_v2.ingest_document(file=_upload(_text_pdf(), "paper.pdf", "application/pdf"), title=None,
                                          skip_review=True, resource_type="notes", current_user={"id": "u1"})
    assert res.status == "processing" and res.thread_id.startswith("ingest:u1:")
    await asyncio.gather(*calls["tasks"])
    [kw] = calls["ingested"]
    assert kw["title"] == "paper" and kw["resource_type"] == "notes" and "self-attention" in kw["content"]
    result = ingest_v2._zip_ingest_results[res.thread_id]
    assert result["status"] == "completed" and result["document"]["method"] == "native"


async def test_endpoint_reports_unreadable_document_as_error_result(ingest):
    ingest_v2, calls = ingest
    res = await ingest_v2.ingest_document(file=_upload(b"%PDF-1.4 garbage", "bad.pdf", "application/pdf"),
                                          title="Bad", skip_review=True, resource_type="notes",
                                          current_user={"id": "u1"})
    await asyncio.gather(*calls["tasks"])
    assert calls["ingested"] == []
    assert ingest_v2._zip_ingest_results[res.thread_id]["status"] == "error"


async def test_endpoint_duplicate_and_bad_type(ingest):
    from fastapi import HTTPException

    ingest_v2, calls = ingest
    calls["existing"] = "note-old"
    res = await ingest_v2.ingest_document(file=_upload(_text_pdf(), "paper.pdf", "application/pdf"), title=None,
                                          skip_review=True, resource_type="notes", current_user={"id": "u1"})
    assert res.status == "completed_duplicate" and res.note_id == "note-old" and calls["tasks"] == []
    with pytest.raises(HTTPException) as e:
        await ingest_v2.ingest_document(file=_upload(b"x", "a.docx", "application/octet-stream"), title=None,
                                        skip_review=True, resource_type="notes", current_user={"id": "u1"})
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await ingest_v2.ingest_document(file=_upload(_text_pdf(), "p.pdf", "application/pdf"), title=None,
                                        skip_review=True, resource_type="document", current_user={"id": "u1"})
    assert e.value.status_code == 400 and "resource_type" in e.value.detail


async def test_extract_endpoint_returns_text_and_stores_nothing(ingest):
    from fastapi import HTTPException

    ingest_v2, calls = ingest
    out = await ingest_v2.extract_document_text(file=_upload(_text_pdf(), "cv.pdf", "application/pdf"),
                                                current_user={"id": "u1"})
    assert "Transformer" in out.markdown and out.pages == 1 and calls["ingested"] == []
    with pytest.raises(HTTPException) as e:
        await ingest_v2.extract_document_text(file=_upload(b"nope", "cv.pdf", "application/pdf"),
                                              current_user={"id": "u1"})
    assert e.value.status_code == 422

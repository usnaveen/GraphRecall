"""Read an uploaded document (PDF or image) into Markdown on the server, with OCR where there is no text.

Before this, documents were read on the phone: PDFKit pulled a PDF's text layer and the server only ever saw
plain text. A scanned PDF failed ("No extractable text"), a PDF with some scanned pages silently lost them, and
the server refused raw PDFs outright.

How a document is read (LiteParse, MIT, with LlamaIndex's OCRia-nano OCR model):
1. **Native pass, no OCR.** PDFium reads every page's text layer and layout into Markdown. Born-digital
   PDFs are done here, in well under a second for a paper.
2. **OCR pass, only where needed.** Pages whose native text is sparse (scans, photos of pages, slides that
   are one big image) are re-read with OCRia-nano (8.1M parameters, ONNX on CPU, ~0.5 s a page here) and
   spliced back in page order. LiteParse OCRs only those pages; born-digital pages keep their native text.
3. Images (PNG, JPEG, WebP, TIFF) go straight to OCR.

Bounds: a size cap, a page cap, one parse at a time (CPU-bound, run off the event loop) and a timeout.
If the OCR model isn't installed, text PDFs still work and scanned pages are reported as skipped, never
silently read with a different engine. Install it with ``python -m backend.scripts.fetch_ocr_model``.

OCRia-nano's licence is a modified Open RAIL-M: free for personal use and organisations under $2M in
revenue and funding, and not for building a competing document-parsing product.
"""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()

PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/tiff"}
EXT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}

MAX_BYTES = int(os.getenv("DOC_MAX_BYTES", str(50 * 1024 * 1024)))
MAX_PAGES = int(os.getenv("DOC_MAX_PAGES", "400"))
PARSE_TIMEOUT_S = float(os.getenv("DOC_PARSE_TIMEOUT_S", "600"))
OCR_WORKERS = int(os.getenv("DOC_OCR_WORKERS", "2"))
SPARSE_CHARS = 60  # a page with less native text than this is treated as scanned

_PARSE_SLOT = asyncio.Semaphore(int(os.getenv("DOC_PARSE_CONCURRENCY", "1")))
_lock = threading.Lock()
_parsers: dict[str, object] = {}


class DocumentError(Exception):
    """The document can't be read (wrong type, too big, encrypted, unreadable). Message is user-facing."""


@dataclass
class ReadDocument:
    markdown: str
    pages: int
    ocr_pages: list[int] = field(default_factory=list)  # 1-based pages read with OCR
    skipped_pages: list[int] = field(default_factory=list)  # sparse pages left unread (no OCR model)
    method: str = "native"  # native | ocr | native+ocr
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.markdown)


def content_type_for(filename: str, declared: Optional[str]) -> Optional[str]:
    declared = (declared or "").split(";")[0].strip().lower()
    if declared in PDF_TYPES | IMAGE_TYPES:
        return "image/jpeg" if declared == "image/jpg" else declared
    ext = os.path.splitext(filename or "")[1].lower()
    return EXT_TYPES.get(ext)


def ocr_model_ready() -> bool:
    try:
        from liteparse import models

        return any(m.name == "ocria-nano" and m.complete for m in models.list())
    except Exception:
        return False


def _parser(kind: str):
    """One shared LiteParse per mode: building one loads PDFium (and the OCR model for 'ocr')."""
    with _lock:
        if kind not in _parsers:
            from liteparse import LiteParse

            common = dict(output_format="markdown", quiet=True, continue_on_page_error=True)
            if kind == "native":
                _parsers[kind] = LiteParse(ocr_enabled=False, **common)
            else:
                _parsers[kind] = LiteParse(ocr_enabled=True, ocr_backend="ocria-nano", num_workers=OCR_WORKERS,
                                           ocr_failure_fatal=False, **common)
        return _parsers[kind]


def _page_md(page) -> str:
    return (page.markdown or page.text or "").strip()


def _read_sync(data: bytes, content_type: str) -> ReadDocument:
    have_ocr = ocr_model_ready()
    if content_type in IMAGE_TYPES:
        if not have_ocr:
            raise DocumentError("Reading images needs the OCR model, which isn't installed on the server.")
        r = _parser("ocr").parse(data)
        md = "\n\n".join(_page_md(p) for p in r.pages).strip()
        return ReadDocument(markdown=md, pages=len(r.pages), ocr_pages=[1], method="ocr")

    native = _parser("native").parse(data)
    if native.total_pages and native.total_pages > MAX_PAGES:
        raise DocumentError(f"That PDF has {native.total_pages} pages; the limit is {MAX_PAGES}. "
                            "Split it, or use the book importer (processed ZIP).")
    pages = {p.page_num: _page_md(p) for p in native.pages}
    sparse = [n for n, md in pages.items() if len(md) < SPARSE_CHARS]
    doc = ReadDocument(markdown="", pages=len(pages))
    if native.page_errors:
        doc.warnings.append(f"{len(native.page_errors)} page(s) couldn't be read")

    if sparse and have_ocr:
        # LiteParse OCRs only text-sparse pages; born-digital pages come back with their native text.
        for p in _parser("ocr").parse(data).pages:
            text = _page_md(p)
            if p.page_num in sparse and len(text) > len(pages.get(p.page_num, "")):
                pages[p.page_num] = text
                doc.ocr_pages.append(p.page_num)
    elif sparse:
        doc.skipped_pages = sparse
        doc.warnings.append(f"{len(sparse)} page(s) look scanned and were skipped: the OCR model isn't installed")

    doc.markdown = "\n\n".join(pages[n] for n in sorted(pages) if pages[n]).strip()
    doc.method = "native+ocr" if doc.ocr_pages and len(doc.ocr_pages) < len(pages) else (
        "ocr" if doc.ocr_pages else "native")
    if doc.ocr_pages:
        doc.warnings.append(f"read {len(doc.ocr_pages)} scanned page(s) with OCR; check names and formulas")
    return doc


async def read_document(data: bytes, filename: str, content_type: Optional[str] = None) -> ReadDocument:
    """Validate, then parse off the event loop, one document at a time. Raises DocumentError."""
    ctype = content_type_for(filename, content_type)
    if ctype is None:
        raise DocumentError("Unsupported file type. Send a PDF or an image (PNG, JPEG, WebP, TIFF).")
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise DocumentError(f"That file is {len(data) // (1024 * 1024)} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB.")
    if ctype in PDF_TYPES and not data.startswith(b"%PDF"):
        raise DocumentError("That file isn't a valid PDF.")
    async with _PARSE_SLOT:
        try:
            doc = await asyncio.wait_for(asyncio.to_thread(_read_sync, data, ctype), PARSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise DocumentError(f"Reading the document took longer than {int(PARSE_TIMEOUT_S)} s.")
        except DocumentError:
            raise
        except Exception as e:  # PDFium / OCR failures: encrypted, corrupt, unsupported
            logger.warning("document_reader: parse failed", error=str(e)[:300])
            msg = "password" if "password" in str(e).lower() or "encrypt" in str(e).lower() else None
            raise DocumentError("That PDF is password-protected." if msg else "Couldn't read that document.")
    logger.info("document_reader: read", type=ctype, pages=doc.pages, chars=doc.chars, method=doc.method,
                ocr_pages=len(doc.ocr_pages), skipped=len(doc.skipped_pages))
    if len(doc.markdown) < 20:
        raise DocumentError("No readable text in that document." + (
            " Its pages look scanned, and the server's OCR model isn't installed." if doc.skipped_pages else ""))
    return doc

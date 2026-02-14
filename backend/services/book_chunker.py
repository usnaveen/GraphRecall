"""Image-aware, rule-based chunker for OCR-parsed textbooks.

Designed for bulk ingestion without LLM calls. It:
- Parses markdown, keeping headings to preserve hierarchy hints.
- Detects image references (e.g., `![](_page_16_Figure_7.jpeg)`).
- Finds nearby figure captions (preceding or following lines).
- Normalizes filename extension mismatches (.jpeg -> .png when files exist).
- Returns chunks with text + image metadata, avoiding splits between figures
  and their captions.
- Supports configurable overlap (default 15%) for better retrieval at boundaries.

Note: We previously generated the parsed book via the notebook in
`notebooks/pdf_ocr_colab.ipynb`; this chunker consumes that markdown export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\((?P<path>[^)]+)\)")
CAPTION_PATTERN = re.compile(r"^(Figure|Fig\.?|FIGURE)\s+[\w\.\-]+[:\.]?\s*(?P<caption>.+)$")


@dataclass
class ImageInfo:
    filename: str
    caption: Optional[str]
    page: Optional[int]
    url: Optional[str] = None


@dataclass
class Chunk:
    index: int
    text: str
    images: List[ImageInfo] = field(default_factory=list)
    headings: List[str] = field(default_factory=list)


class BookChunker:
    """Rule-based chunker tailored for OCR markdown with figures.

    Also used as the unified chunker for all ingestion (notes, books, PDFs).
    Supports both file-based and string-based input.
    """

    def __init__(
        self,
        max_chars: int = 1400,
        overlap_ratio: float = 0.15,
        heading_weight: bool = True,
    ) -> None:
        self.max_chars = max_chars
        self.overlap_ratio = overlap_ratio
        self.heading_weight = heading_weight

    def chunk_text(
        self,
        text: str,
        images_dir: Optional[Path] = None,
    ) -> List[Chunk]:
        """Chunk a raw markdown/text string. Images dir is optional."""
        return self._chunk_lines(
            text.splitlines(),
            images_dir or Path("/dev/null"),
        )

    def chunk_markdown(
        self,
        md_path: Path,
        images_dir: Path,
        book_slug: Optional[str] = None,
    ) -> List[Chunk]:
        """Chunk a markdown file on disk (original book ingestion path)."""
        lines = md_path.read_text(encoding="utf-8").splitlines()
        return self._chunk_lines(lines, images_dir)

    def _chunk_lines(
        self,
        lines: list[str],
        images_dir: Path,
    ) -> List[Chunk]:
        """Core chunking logic shared by chunk_text and chunk_markdown."""

        units: List[dict] = []  # each unit preserves figure/text boundaries
        current_para: list[str] = []
        heading_stack: list[str] = []

        def flush_para():
            if current_para:
                text = "\n".join(current_para).strip()
                if text:
                    units.append({"type": "text", "text": text, "headings": heading_stack.copy()})
                current_para.clear()

        for idx, line in enumerate(lines):
            stripped = line.strip()

            # Handle headings to retain hierarchy context
            if stripped.startswith("#"):
                flush_para()
                level = len(stripped) - len(stripped.lstrip("#"))
                heading_text = stripped.lstrip("#").strip()
                # Maintain heading stack based on level
                if level <= len(heading_stack):
                    heading_stack = heading_stack[: level - 1]
                heading_stack.append(heading_text)
                # Also treat heading as text unit for semantic context
                units.append({"type": "text", "text": heading_text, "headings": heading_stack.copy()})
                continue

            image_match = IMAGE_PATTERN.search(stripped)
            if image_match:
                flush_para()
                raw_path = image_match.group("path").strip()
                normalized_name, page_num = self._normalize_filename(raw_path, images_dir)
                caption = self._find_caption(lines, idx)

                image_info = ImageInfo(
                    filename=normalized_name,
                    caption=caption,
                    page=page_num,
                )

                placeholder = caption or f"Image {normalized_name}"
                units.append(
                    {
                        "type": "figure",
                        "text": f"[Figure] {placeholder}",
                        "images": [image_info],
                        "headings": heading_stack.copy(),
                    }
                )
                continue

            # Regular text line
            if stripped == "":
                flush_para()
            else:
                current_para.append(stripped)

        flush_para()

        # --- Assemble chunks with overlap ---
        chunks: List[Chunk] = []
        buf_units: list[dict] = []  # units in current chunk
        buf_images: list[ImageInfo] = []
        buf_headings: list[str] = []
        current_len = 0

        def flush_chunk():
            nonlocal buf_units, buf_images, buf_headings, current_len
            if not buf_units:
                return
            chunk_index = len(chunks)
            text = "\n\n".join(u["text"] for u in buf_units).strip()
            chunks.append(
                Chunk(
                    index=chunk_index,
                    text=text,
                    images=list(buf_images),
                    headings=list(buf_headings),
                )
            )

            # Compute overlap: keep trailing units that fit within overlap budget
            overlap_chars = int(self.max_chars * self.overlap_ratio)
            carry_units: list[dict] = []
            carry_images: list[ImageInfo] = []
            carry_len = 0
            for u in reversed(buf_units):
                u_len = len(u.get("text", ""))
                if carry_len + u_len > overlap_chars:
                    break
                # Don't carry over figures into overlap (they'd duplicate)
                if u.get("type") == "figure":
                    break
                carry_units.insert(0, u)
                carry_len += u_len + 2

            buf_units = carry_units
            buf_images = list(carry_images)
            buf_headings = list(buf_headings)  # Keep heading context
            current_len = carry_len

        for unit in units:
            unit_text = unit.get("text", "").strip()
            if not unit_text:
                continue
            unit_len = len(unit_text)
            projected = current_len + unit_len

            # Ensure figures are not split; if overflow would occur and we already
            # have text, flush first.
            if projected > self.max_chars and buf_units:
                flush_chunk()

            buf_units.append(unit)
            buf_images.extend(unit.get("images", []))
            # Track the deepest headings seen in this chunk for metadata
            if unit.get("headings"):
                buf_headings = unit["headings"]
            current_len += unit_len + 2  # account for spacing

        flush_chunk()

        return chunks

    def _normalize_filename(self, raw_path: str, images_dir: Path) -> tuple[str, Optional[int]]:
        """Handle extension mismatches and extract page number."""

        raw_name = Path(raw_path).name
        stem = Path(raw_name).stem

        # Try matching actual files, preferring .png then .jpeg/.jpg
        for ext in (".png", ".jpeg", ".jpg"):
            candidate = images_dir / f"{stem}{ext}"
            if candidate.exists():
                page = self._extract_page(stem)
                return candidate.name, page

        # Fallback to raw name
        return raw_name, self._extract_page(stem)

    def _extract_page(self, stem: str) -> Optional[int]:
        match = re.search(r"_page_(\d+)_", stem)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def _find_caption(self, lines: list[str], idx: int) -> Optional[str]:
        """Look around the image line for a caption."""

        # Check the two previous non-empty lines, then the next two
        offsets = [-2, -1, 1, 2]
        for offset in offsets:
            pos = idx + offset
            if pos < 0 or pos >= len(lines):
                continue
            candidate = lines[pos].strip()
            if not candidate:
                continue
            match = CAPTION_PATTERN.match(candidate)
            if match:
                return match.group("caption").strip()
        return None

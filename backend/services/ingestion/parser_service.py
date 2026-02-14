"""Document parser service.

Supports:
- Text/Markdown files: direct UTF-8 parsing
- PDF files: processed externally via Marker (Colab notebook or local script).
  The backend receives pre-converted markdown, NOT raw PDF bytes.

LlamaParse has been removed in favor of Marker for all PDF processing.
"""

from typing import List, Dict, Any
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class ParsedDocument(BaseModel):
    """Normalized output from any parser."""
    markdown_content: str
    metadata: Dict[str, Any]
    images: List[Dict[str, Any]] = []


class DocumentParserService:
    """Simple document parser. PDFs should be pre-processed via Marker."""

    async def parse_document(
        self, file_content: bytes, filename: str, file_type: str
    ) -> ParsedDocument:
        logger.info("Parsing document", filename=filename, type=file_type)

        if file_type in ("txt", "md", "markdown", "text"):
            return self._parse_text(file_content, filename)

        if file_type in ("pdf", "pptx", "docx"):
            # PDFs should arrive as pre-converted markdown from Marker.
            # If raw bytes are sent, attempt UTF-8 decode (user may have
            # pasted the markdown output). For true PDF binary, return error.
            try:
                text = file_content.decode("utf-8")
                if text.startswith("%PDF"):
                    return ParsedDocument(
                        markdown_content="",
                        metadata={
                            "error": "raw_pdf_not_supported",
                            "message": (
                                "Raw PDF uploads are not supported. Please process "
                                "the PDF through Marker first (use the Colab notebook "
                                "or local pdf_ocr.py script) and upload the resulting markdown."
                            ),
                        },
                    )
                return ParsedDocument(
                    markdown_content=text,
                    metadata={"source": "pre_converted", "filename": filename},
                )
            except UnicodeDecodeError:
                return ParsedDocument(
                    markdown_content="",
                    metadata={
                        "error": "binary_pdf",
                        "message": "Binary PDF detected. Process via Marker first.",
                    },
                )

        # Fallback: attempt text decode
        return self._parse_text(file_content, filename)

    def _parse_text(self, file_content: bytes, filename: str) -> ParsedDocument:
        try:
            text = file_content.decode("utf-8")
        except UnicodeDecodeError:
            text = file_content.decode("latin-1")

        return ParsedDocument(
            markdown_content=text,
            metadata={"source": "simple_text_parser", "filename": filename},
        )

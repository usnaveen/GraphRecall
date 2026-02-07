from typing import List, Dict, Any, Optional
import os
from abc import ABC, abstractmethod
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()

class ParsedDocument(BaseModel):
    """Normalized output from any parser."""
    markdown_content: str
    metadata: Dict[str, Any]
    images: List[Dict[str, Any]] = []

class BaseParser(ABC):
    @abstractmethod
    async def parse(self, file_content: bytes, filename: str, file_type: str) -> ParsedDocument:
        pass

class SimpleTextParser(BaseParser):
    """Fallback parser for plain text/markdown."""
    async def parse(self, file_content: bytes, filename: str, file_type: str) -> ParsedDocument:
        try:
            text = file_content.decode("utf-8")
        except UnicodeDecodeError:
            text = file_content.decode("latin-1")
            
        return ParsedDocument(
            markdown_content=text,
            metadata={"source": "simple_text_parser", "filename": filename}
        )

class LlamaParseWrapper(BaseParser):
    """Wrapper for LlamaParse API (optional dependency)."""
    def __init__(self):
        self.api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        
    async def parse(self, file_content: bytes, filename: str, file_type: str) -> ParsedDocument:
        if not self.api_key:
            raise ValueError("LLAMA_CLOUD_API_KEY not set")
            
        # NOTE: LlamaParse is usually sync/blocking or uses async loop.
        # For MVP we might need to write to temp file.
        import nest_asyncio
        nest_asyncio.apply()
        
        from llama_parse import LlamaParse
        
        # Write to temp file
        import tempfile
        suffix = f".{file_type}" if not filename.endswith(file_type) else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name
            
        try:
            parser = LlamaParse(
                api_key=self.api_key,
                result_type="markdown",
                verbose=True
            )
            # This is blocking call
            documents = parser.load_data(tmp_path)
            
            # Combine all pages
            full_text = "\n\n".join([doc.text for doc in documents])
            
            return ParsedDocument(
                markdown_content=full_text,
                metadata={
                    "source": "llama_parse", 
                    "filename": filename,
                    "pages": len(documents)
                }
            )
        finally:
            os.remove(tmp_path)

class DocumentParserService:
    def __init__(self):
        self.simple_parser = SimpleTextParser()
        self.llama_parser = LlamaParseWrapper() if os.getenv("LLAMA_CLOUD_API_KEY") else None
        
    async def parse_document(self, file_content: bytes, filename: str, file_type: str) -> ParsedDocument:
        logger.info("Parsing document", filename=filename, type=file_type)
        
        # Use LlamaParse for complex docs if available
        if file_type in ["pdf", "pptx", "docx"] and self.llama_parser:
            try:
                return await self.llama_parser.parse(file_content, filename, file_type)
            except Exception as e:
                logger.warning("LlamaParse failed, falling back", error=str(e))
                
        # Fallback to simple text parsing (might result in garbage for PDF binary)
        if file_type in ["txt", "md"]:
            return await self.simple_parser.parse(file_content, filename, file_type)
            
        # If we get here with PDF/Binary and no LlamaParse, we fail or return mock
        # For now, return error string
        return ParsedDocument(
            markdown_content=f"Error: Could not parse {file_type}. Configure LlamaParse.",
            metadata={"error": "no_parser_available"}
        )

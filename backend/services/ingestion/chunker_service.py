import re
from typing import List, Optional
from uuid import uuid4, UUID
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from .parser_service import ParsedDocument
from ...models.schemas import ChunkCreate, ChunkLevel

class HierarchicalChunker:
    """
    Splits documents into a Parent-Child hierarchy.
    Parent: Large context (for LLM generation).
    Child: Small context (for vector retrieval).
    """
    
    def __init__(self, parent_size: int = 1000, child_size: int = 250, overlap: int = 50):
        self.parent_size = parent_size
        self.child_size = child_size
        self.overlap = overlap

    def _extract_page_markers(self, text: str) -> list[tuple[int, int]]:
        markers = [(0, 1)]
        for match in re.finditer(r"<!--\s*Page\s+(\d+)\s*-->", text):
            markers.append((match.start(), int(match.group(1))))
        markers.sort(key=lambda x: x[0])
        return markers

    def _find_page_for_offset(self, offset: Optional[int], markers: list[tuple[int, int]]) -> Optional[int]:
        if offset is None or offset < 0:
            return None
        page = markers[0][1] if markers else 1
        for pos, num in markers:
            if pos <= offset:
                page = num
            else:
                break
        return page

    def chunk(self, document: ParsedDocument, note_id: UUID) -> List[ChunkCreate]:
        chunks = []
        
        # 1. Split into Parent Chunks first
        # Ideally use Markdown splitter if content looks structured
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.parent_size,
            chunk_overlap=self.overlap
        )
        
        doc_text = document.markdown_content
        page_markers = self._extract_page_markers(doc_text)
        parent_texts = parent_splitter.split_text(doc_text)

        search_start = 0
        
        for idx, parent_text in enumerate(parent_texts):
            parent_id = uuid4()
            
            # Create Parent Chunk
            parent_chunk = ChunkCreate(
                note_id=note_id,
                content=parent_text,
                chunk_index=idx,
                chunk_level=ChunkLevel.PARENT,
                source_location={"type": "parent_split", "index": idx}
            )
            # Store ID manually if schema allows, or handle in service layer. 
            # Ideally we pass pre-generated ID to storage service.
            # Here we just treat it as a data object. The ID generation often happens at DB insert 
            # OR we generate it here to link children. 
            # We will generate UUIDs here for linkage purposes.
            
            # Note: Pydantic model doesn't have ID field for Create, but we need it for children linkage.
            # We will return a tuple or extended dict, or modify logic to assume the caller creates ID.
            # Let's attach it to a temporary wrapper or just rely on the saving logic to return ID.
            # Actually, to generate child links, we MUST know parent ID.
            # So let's assume we generate UUIDs on the application side.
            
            # Let's add 'id' attribute to the object effectively (even if not in Schema) 
            # or return a dict structure for now.
            
            # Correction: ChunkCreate model doesn't have 'id'. 
            # We will return a structure that includes the intended ID for the parent.
            
            # Re-reading: The caller (Graph Node) will likely save Parent, get ID, then save Children.
            # But that makes batching hard.
            # Better strategy: Generate UUIDs here.
            
            # For this implementation, I will return a complex structure or flattened list 
            # where children have a placeholder parent_ref.
            
            # Actually, looking at schema, `Chunk` has ID. `ChunkCreate` does not. 
            # I will modify schema usage or just return `Chunk` objects (without DB timestamp).
            # Or I will attach `_temp_id` to the dict.
            
            # Let's assume the Caller handles Saving. I will return a Structure:
            # { "parent": ChunkCreate, "children": [ChunkCreate] }
            
            parent_offset = doc_text.find(parent_text, search_start)
            if parent_offset == -1:
                parent_offset = doc_text.find(parent_text)

            if parent_offset != -1:
                search_start = parent_offset + len(parent_text)

            parent_page_start = self._find_page_for_offset(parent_offset, page_markers)
            parent_page_end = self._find_page_for_offset(
                parent_offset + len(parent_text) - 1 if parent_offset != -1 else None,
                page_markers,
            )

            child_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.child_size,
                chunk_overlap=self.overlap
            )
            child_texts = child_splitter.split_text(parent_text)

            child_page_starts: list[Optional[int]] = []
            child_page_ends: list[Optional[int]] = []
            child_search_start = 0

            for child_text in child_texts:
                child_offset = parent_text.find(child_text, child_search_start)
                if child_offset == -1:
                    child_offset = parent_text.find(child_text)
                if child_offset != -1 and parent_offset != -1:
                    child_search_start = child_offset + len(child_text)
                    child_abs_offset = parent_offset + child_offset
                    child_page_starts.append(self._find_page_for_offset(child_abs_offset, page_markers))
                    child_page_ends.append(
                        self._find_page_for_offset(
                            child_abs_offset + len(child_text) - 1, page_markers
                        )
                    )
                else:
                    child_page_starts.append(None)
                    child_page_ends.append(None)
            
            # We need to return an object that holds the hierarchy.
            # Since we can't save to DB yet to get a real ID, we might need to do strict linear saving.
            
            chunks.append({
                "parent_content": parent_text,
                "parent_index": idx,
                "parent_page_start": parent_page_start,
                "parent_page_end": parent_page_end,
                "child_contents": child_texts,
                "child_page_starts": child_page_starts,
                "child_page_ends": child_page_ends,
            })
            
        return chunks

from typing import List
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

    def chunk(self, document: ParsedDocument, note_id: UUID) -> List[ChunkCreate]:
        chunks = []
        
        # 1. Split into Parent Chunks first
        # Ideally use Markdown splitter if content looks structured
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.parent_size,
            chunk_overlap=self.overlap
        )
        
        parent_texts = parent_splitter.split_text(document.markdown_content)
        
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
            
            child_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.child_size,
                chunk_overlap=self.overlap
            )
            child_texts = child_splitter.split_text(parent_text)
            
            # We need to return an object that holds the hierarchy.
            # Since we can't save to DB yet to get a real ID, we might need to do strict linear saving.
            
            chunks.append({
                "parent_content": parent_text,
                "parent_index": idx,
                "child_contents": child_texts
            })
            
        return chunks

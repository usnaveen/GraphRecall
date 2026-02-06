import pytest
from uuid import uuid4
from backend.services.ingestion.chunker_service import HierarchicalChunker
from backend.services.ingestion.parser_service import ParsedDocument

def test_hierarchical_chunking():
    # Setup
    chunker = HierarchicalChunker(parent_size=50, child_size=10, overlap=0)
    
    # Create dummy long text
    # 5 parents, each ~50 chars. Total ~250 chars.
    long_text = ""
    for i in range(5):
        long_text += f"Parent Section {i}. " + ("A" * 35) + "\n\n"
        
    doc = ParsedDocument(
        markdown_content=long_text,
        metadata={"filename": "test.md"}
    )
    
    note_id = uuid4()
    
    # Execute
    chunks = chunker.chunk(doc, note_id)
    
    # Verify Parent splitting
    assert len(chunks) >= 5
    
    first_parent = chunks[0]
    assert "parent_content" in first_parent
    assert len(first_parent["child_contents"]) > 0
    
    # Verify content logic
    assert "Parent Section 0" in first_parent["parent_content"]
    assert len(first_parent["child_contents"][0]) <= 10  # approximate due to splitter
    
    print("Chunking structure verified:")
    print(f"Total Parent Chunks: {len(chunks)}")
    print(f"First Parent Children: {len(first_parent['child_contents'])}")

if __name__ == "__main__":
    test_hierarchical_chunking()

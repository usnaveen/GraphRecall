"""BookChunker must respect max_chars even when the text has no paragraph breaks.

Regression: a 5,000-character note with no newlines (a flattened PDF page, a YouTube transcript)
came out as ONE chunk. Retrieval keeps one child per parent, so such a note could contribute a
single passage to any answer, and the 'parent window' sent to the model was the whole note."""

from backend.services.book_chunker import BookChunker


def test_one_long_paragraph_is_split_at_sentences_within_the_limit():
    text = " ".join(f"Sentence number {i} explains one fact about basal cell carcinoma." for i in range(80))
    chunks = BookChunker(max_chars=1400, overlap_ratio=0.15).chunk_text(text)
    assert len(chunks) >= 4
    assert all(len(c.text) <= 1400 for c in chunks)
    assert all(c.text.rstrip().endswith(".") for c in chunks)   # cut between sentences, not inside
    assert "\n\n" not in chunks[0].text                         # one paragraph rejoins with spaces


def test_overlap_carries_whole_sentences():
    text = " ".join(f"Fact {i} is stated here in a sentence." for i in range(120))
    a, b = BookChunker(max_chars=600, overlap_ratio=0.2).chunk_text(text)[:2]
    last_sentence_of_a = a.text.rsplit(". ", 1)[-1]
    assert last_sentence_of_a in b.text


def test_a_sentence_longer_than_the_limit_is_cut_at_words():
    chunks = BookChunker(max_chars=200).chunk_text("word " * 200)
    assert all(len(c.text) <= 200 for c in chunks)


def test_paragraphed_text_is_unchanged():
    text = "\n\n".join(["Short paragraph about one idea. " * 8] * 20)
    sizes = [len(c.text) for c in BookChunker(max_chars=1400).chunk_text(text)]
    assert sizes == [1283, 1283, 1283, 1283]

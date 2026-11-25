"""Resume privacy (contact stripping), fallback skill extraction and highlight spans."""
from backend.services.resume import dedupe, fallback_skills, highlight_spans, strip_contacts

RESUME = """Jane Doe
jane.doe@example.com | +91 98765 43210 | linkedin.com/in/janedoe | github.com/janedoe
12 Gandhi Road, Chennai
EDUCATION
MTech Data Science, 2026
Technical Skills: Python, PyTorch, SQL, Docker
Tools: LangGraph; Neo4j; FastAPI
Built a RAG system with Neo4j and pgvector (2025)."""


def test_strip_contacts_removes_email_phone_profiles_and_address_lines():
    out = strip_contacts(RESUME)
    for secret in ("jane.doe@", "98765", "linkedin.com", "github.com", "Gandhi Road"):
        assert secret not in out
    assert "Technical Skills: Python" in out and "Jane Doe" in out


def test_fallback_skills_reads_skill_sections():
    names = [s["name"] for s in dedupe(fallback_skills(strip_contacts(RESUME)))]
    assert names[:7] == ["Python", "PyTorch", "SQL", "Docker", "LangGraph", "Neo4j", "FastAPI"]


def test_highlight_spans_word_bounded():
    text = "Python and PyTorch; python again"
    spans = highlight_spans(text, ["Python", "Torch"])
    assert spans == {"Python": [[0, 6], [20, 26]]}

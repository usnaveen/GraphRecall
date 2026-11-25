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
    assert "Technical Skills: Python" in out and "Jane Doe" not in out


def test_fallback_skills_reads_skill_sections():
    names = [s["name"] for s in dedupe(fallback_skills(strip_contacts(RESUME)))]
    assert names[:7] == ["Python", "PyTorch", "SQL", "Docker", "LangGraph", "Neo4j", "FastAPI"]


def test_highlight_spans_word_bounded():
    text = "Python and PyTorch; python again"
    spans = highlight_spans(text, ["Python", "Torch"])
    assert spans == {"Python": [[0, 6], [20, 26]]}


def test_strip_contacts_us_phone_location_urls_and_portfolio():
    text = "Alex Kim\nLocation: San Francisco, CA 94105\n(415) 555-1234 · mailto:alex@x.io · https://alexkim.dev\nSkills: Go, Rust"
    out = strip_contacts(text)
    for secret in ("Alex Kim", "San Francisco", "555-1234", "mailto", "alexkim.dev"):
        assert secret not in out
    assert "Skills: Go, Rust" in out


def test_fallback_ignores_non_skill_colon_lines_and_c_not_in_cpp():
    assert [s["name"] for s in fallback_skills("Location: Chennai\nSkills: C, C++")] == ["C", "C++"]
    assert highlight_spans("C++ and C#, then C", ["C"]) == {"C": [[17, 18]]}

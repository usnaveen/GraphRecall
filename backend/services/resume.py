"""Resume → skills, each coloured by the knowledge map.

Privacy: contact details (email, phone, profile links, street addresses) are stripped before the
text is stored or sent to any model. The stored text is the user's own data, deleted with the
account, and is never returned by the MCP tools (they return statuses only).

Skill extraction: one fast-model structured-output call; if that fails (quota, offline) a
deterministic fallback reads "Skills"-style sections and comma lists.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
_PROFILE = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com|gitlab\.com|twitter\.com|x\.com)/\S*", re.I)
_ADDRESS = re.compile(r"\b\d{1,5}\s+\w+(?:\s\w+)*\s(?:street|st|road|rd|avenue|ave|lane|ln|nagar|colony)\b.*", re.I)
_SECTION = re.compile(r"^\s*(technical\s+skills|skills|tools|technologies|languages|frameworks|"
                      r"relevant\s+coursework|coursework|core\s+competencies)\b\s*[:\-]?\s*(.*)$", re.I)


def strip_contacts(text: str) -> str:
    out = []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        cleaned = _PROFILE.sub("", _PHONE.sub("", _EMAIL.sub("", line)))
        cleaned = _ADDRESS.sub("", cleaned)
        if line.strip() and not cleaned.strip(" |,·•-–:"):
            continue  # a pure contact line
        out.append(cleaned.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


class _Skill(BaseModel):
    name: str = Field(description="Canonical skill or topic name, e.g. 'PyTorch', 'Linear Algebra', 'RAG'")
    section: str = Field(default="", description="Resume section it came from: skills, experience, projects, education")


class _Skills(BaseModel):
    skills: list[_Skill] = Field(default_factory=list)


PROMPT = """List the technical skills, tools and knowledge topics this resume claims or demonstrates.
Include: programming languages, frameworks, libraries, platforms, ML/AI techniques, math and CS topics,
methods used in projects (e.g. "retrieval-augmented generation", "knowledge graphs", "time-series forecasting").
Exclude soft skills, company names, job titles, degrees and dates. Use canonical names, no duplicates,
at most 60 items.

<resume>
{text}
</resume>"""


def fallback_skills(text: str) -> list[dict]:
    found: list[dict] = []
    for line in text.split("\n"):
        m = _SECTION.match(line)
        body = m.group(2) if m else (line.split(":", 1)[1] if ":" in line and len(line.split(":", 1)[0]) < 30 else "")
        if not body:
            continue
        for part in re.split(r"[,;|•·]", body):
            name = part.strip(" .()-–")
            if 1 < len(name) <= 40 and not re.search(r"\d{4}", name):
                found.append({"name": name, "section": "skills"})
    return found


def dedupe(skills: list[dict]) -> list[dict]:
    from backend.services.knowledge_map import skill_key

    seen, out = set(), []
    for s in skills:
        k = skill_key(s.get("name", ""))
        if k and k not in seen:
            seen.add(k)
            out.append({"name": s["name"].strip(), "key": k, "section": s.get("section") or ""})
    return out[:80]


async def extract_skills(text: str) -> tuple[list[dict], str]:
    """(skills, method). Method is 'llm' or 'fallback'."""
    try:
        from backend.config.llm import get_fast_model

        llm = get_fast_model(temperature=0).with_structured_output(_Skills)
        result: _Skills = await llm.ainvoke(PROMPT.format(text=text[:16000]))
        skills = dedupe([s.model_dump() for s in result.skills])
        if skills:
            return skills, "llm"
    except Exception as e:  # noqa: BLE001
        logger.warning("resume: LLM skill extraction failed, using fallback", error=str(e)[:200])
    return dedupe(fallback_skills(text)), "fallback"


def highlight_spans(text: str, names: list[str]) -> dict[str, list[list[int]]]:
    """Character spans of each skill name in the text (case-insensitive, word-bounded)."""
    spans: dict[str, list[list[int]]] = {}
    for n in names:
        pat = re.compile(rf"(?<![\w]){re.escape(n)}(?![\w])", re.I)
        hits = [[m.start(), m.end()] for m in pat.finditer(text)]
        if hits:
            spans[n] = hits[:20]
    return spans

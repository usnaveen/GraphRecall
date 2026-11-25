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
_URL = re.compile(r"(?:https?://|mailto:|www\.)\S*", re.I)
_PHONE_US = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_LOCATION_LINE = re.compile(r"^\s*(location|address|phone|mobile|email|e-mail|linkedin|github|portfolio|website)\s*[:|]", re.I)
_CITY_ZIP = re.compile(r"\b[A-Z][a-zA-Z .]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?\b|\b\d{6}\b")
_NAME_LINE = re.compile(r"^[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){1,3}$")
_ADDRESS = re.compile(r"\b\d{1,5}\s+\w+(?:\s\w+)*\s(?:street|st|road|rd|avenue|ave|lane|ln|nagar|colony)\b.*", re.I)
_SECTION = re.compile(r"^\s*(technical\s+skills|skills|tools|technologies|languages|frameworks|"
                      r"relevant\s+coursework|coursework|core\s+competencies)\b\s*[:\-]?\s*(.*)$", re.I)


def strip_contacts(text: str) -> str:
    out = []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    for i, line in enumerate(lines):
        if i == first and _NAME_LINE.match(line.strip()):
            continue  # the candidate's name heads the resume
        if _LOCATION_LINE.match(line):
            continue
        cleaned = _URL.sub("", _PROFILE.sub("", line))
        cleaned = _EMAIL.sub("", cleaned)
        cleaned = _PHONE.sub("", _PHONE_US.sub("", cleaned))
        cleaned = _CITY_ZIP.sub("", _ADDRESS.sub("", cleaned))
        if line.strip() and not cleaned.strip(" |,·•-–:()"):
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
        body = m.group(2) if m else ""
        if not body:
            continue
        for part in re.split(r"[,;|•·]", body):
            name = part.strip(" .()-–")
            if name and len(name) <= 40 and (len(name) > 1 or name.isalpha()) and not re.search(r"\d{4}", name):
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
        pat = re.compile(rf"(?<![\w+#]){re.escape(n)}(?![\w+#])", re.I)  # "C" is not inside "C++"
        hits = [[m.start(), m.end()] for m in pat.finditer(text)]
        if hits:
            spans[n] = hits[:20]
    return spans

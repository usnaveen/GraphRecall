"""Knowledge map, capability profile and resume (backend/services/knowledge_map.py, resume.py).

/api/knowledge-map
  POST /assess              {names: [...]}        strong / shaky / seen / unexposed per name, with evidence
  GET  /summary                                    every concept and tracked skill, grouped by status and domain
  GET  /questions?limit=                           "what's your exposure to X?" prompts for unknown skills
  POST /self-rating         {name, level 0-4}      the user's answer
/api/profile
  GET/PUT  ""                                       headline, education status, institution, program, year, goals
  GET/POST /courses, DELETE /courses/{id}           course + grade + topics (topics become evidence)
  GET/POST /projects, DELETE /projects/{id}         project + skills (skills become evidence)
  POST /resume              {text, file_name}      text extracted on device; contacts stripped here
  GET  /resume                                      latest resume, its skills coloured by the map
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.services import knowledge_map as km
from backend.services import resume as rs

logger = structlog.get_logger()
router = APIRouter(tags=["Knowledge map"])


def _ser(r: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if k == "id" else v) for k, v in r.items()}


# --------------------------------------------------------------------------- knowledge map

class AssessBody(BaseModel):
    names: list[str] = Field(..., min_length=1, max_length=200)
    track_unknown: bool = Field(default=False, description="Queue unexposed names so the app asks the user about them")


class RatingBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    level: int = Field(..., ge=0, le=4)


@router.post("/api/knowledge-map/assess")
async def assess(body: AssessBody, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    results = await km.assess(user_id, body.names)
    if body.track_unknown:
        pg = await get_postgres_client()
        for a in results:
            if a.status == "unexposed" and a.self_rating is None:
                await km.upsert_skill(pg, user_id, a.name, source="agent")
    return {"results": [a.as_dict() for a in results],
            "legend": {"strong": "tested well, or backed by coursework/projects/self-rating",
                       "shaky": "tested and struggled, or self-rated low",
                       "seen": "studied or claimed but never tested",
                       "unexposed": "no evidence the user has met this"}}


@router.get("/api/knowledge-map/summary")
async def summary(compact: bool = Query(default=False), current_user: dict = Depends(get_current_user)):
    data = await km.summary(str(current_user["id"]))
    if compact:
        data.pop("items", None)
    return data


@router.get("/api/profile/blueprint")
async def blueprint(current_user: dict = Depends(get_current_user)):
    """Everything that describes what this person can do, for agents and (later) JD matching.
    Excludes resume text and note bodies by design."""
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    profile = await pg.execute_query("SELECT headline, education_status, institution, program, graduation_year, goals "
                                     "FROM user_profile WHERE user_id = CAST(:u AS uuid)", {"u": user_id})
    courses = await pg.execute_query("SELECT code, name, term, grade, topics FROM user_courses "
                                     "WHERE user_id = CAST(:u AS uuid) ORDER BY created_at DESC", {"u": user_id})
    projects = await pg.execute_query("SELECT name, summary, url, skills, started, ended FROM user_projects "
                                      "WHERE user_id = CAST(:u AS uuid) ORDER BY created_at DESC", {"u": user_id})
    leet = await pg.execute_query(
        "SELECT coalesce(p.pattern, 'no pattern') AS pattern, count(a.id) AS attempts, "
        "count(a.id) FILTER (WHERE a.outcome = 'solved') AS solved "
        "FROM coding_problems p LEFT JOIN coding_attempts a ON a.problem_id = p.id "
        "WHERE p.user_id = CAST(:u AS uuid) GROUP BY 1 ORDER BY 2 DESC", {"u": user_id})
    knowledge = await km.summary(user_id, pg=pg)
    knowledge.pop("items", None)
    return {"profile": _ser(profile[0]) if profile else {}, "courses": [_ser(c) for c in courses or []],
            "projects": [_ser(p) for p in projects or []], "leetcode_by_pattern": [_ser(r) for r in leet or []],
            "knowledge": knowledge}


@router.get("/api/knowledge-map/questions")
async def questions(limit: int = Query(default=5, ge=1, le=20), current_user: dict = Depends(get_current_user)):
    """Skills you claimed (resume, courses, projects) or an agent asked about that the map can't judge yet."""
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        """
        SELECT skill_name, sources FROM user_skills
        WHERE user_id = CAST(:u AS uuid) AND self_rating IS NULL
          AND (asked_at IS NULL OR asked_at < now() - interval '14 days')
        ORDER BY created_at DESC LIMIT 60
        """,
        {"u": user_id},
    )
    names = [r["skill_name"] for r in rows or []]
    if not names:
        return {"questions": []}
    sources = {r["skill_name"]: list(r.get("sources") or []) for r in rows}
    assessed = await km.assess(user_id, names)
    picks = [a for a in assessed if a.status == "unexposed" or (a.status == "seen" and a.basis in {"claimed", "none"})]
    return {"questions": [{
        "name": a.name, "status": a.status, "sources": sources.get(a.name, []),
        "prompt": f"What's your exposure to {a.name}?",
        "levels": [{"level": i, "label": km.SELF_LEVEL_LABEL[i]} for i in range(5)],
    } for a in picks[:limit]]}


@router.post("/api/knowledge-map/self-rating")
async def self_rating(body: RatingBody, current_user: dict = Depends(get_current_user)):
    a = await km.rate_skill(str(current_user["id"]), body.name, body.level)
    return a.as_dict()


# --------------------------------------------------------------------------- profile

class ProfileBody(BaseModel):
    headline: Optional[str] = Field(default=None, max_length=200)
    education_status: Optional[str] = Field(default=None, max_length=80)
    institution: Optional[str] = Field(default=None, max_length=200)
    program: Optional[str] = Field(default=None, max_length=200)
    graduation_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    goals: Optional[str] = Field(default=None, max_length=2000)


class CourseBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=40)
    term: Optional[str] = Field(default=None, max_length=60)
    grade: Optional[str] = Field(default=None, max_length=20)
    institution: Optional[str] = Field(default=None, max_length=200)
    topics: list[str] = Field(default_factory=list, max_length=40)


class ProjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=2000)
    url: Optional[str] = Field(default=None, max_length=500)
    skills: list[str] = Field(default_factory=list, max_length=40)
    started: Optional[str] = Field(default=None, max_length=40)
    ended: Optional[str] = Field(default=None, max_length=40)


@router.get("/api/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query("SELECT * FROM user_profile WHERE user_id = CAST(:u AS uuid)", {"u": str(current_user["id"])})
    return _ser(rows[0]) if rows else {}


@router.put("/api/profile")
async def put_profile(body: ProfileBody, current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        """
        INSERT INTO user_profile (user_id, headline, education_status, institution, program, graduation_year, goals)
        VALUES (CAST(:u AS uuid), :headline, :education_status, :institution, :program, :graduation_year, :goals)
        ON CONFLICT (user_id) DO UPDATE SET headline = EXCLUDED.headline,
            education_status = EXCLUDED.education_status, institution = EXCLUDED.institution,
            program = EXCLUDED.program, graduation_year = EXCLUDED.graduation_year, goals = EXCLUDED.goals,
            updated_at = now()
        RETURNING *
        """,
        {"u": str(current_user["id"]), **body.model_dump()},
    )
    return _ser(rows[0])


async def _topics_to_evidence(pg, user_id: str, names: list[str], *, kind: str, signal: float, source_id: str) -> None:
    from backend.db.neo4j_client import get_neo4j_client

    neo = await get_neo4j_client()
    concepts = await km._user_concepts(neo, user_id)
    for name in [n.strip() for n in names if n and n.strip()]:
        c = km.match_concept(name, concepts)
        await km.upsert_skill(pg, user_id, name, source=kind, concept_id=c["id"] if c else None)
        await km.add_evidence(pg, user_id, kind=kind, signal=signal, concept_id=c["id"] if c else None,
                              skill_name=None if c else name, source_id=source_id)


async def _drop_source_evidence(pg, user_id: str, source_id: str) -> None:
    await pg.execute_update(
        "DELETE FROM knowledge_evidence WHERE user_id = CAST(:u AS uuid) AND source_id = :s", {"u": user_id, "s": source_id})


@router.get("/api/profile/courses")
async def list_courses(current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "SELECT * FROM user_courses WHERE user_id = CAST(:u AS uuid) ORDER BY created_at DESC", {"u": str(current_user["id"])})
    return {"courses": [_ser(r) for r in rows or []]}


@router.post("/api/profile/courses")
async def add_course(body: CourseBody, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "INSERT INTO user_courses (user_id, code, name, term, grade, institution, topics) VALUES "
        "(CAST(:u AS uuid), :code, :name, :term, :grade, :institution, :topics) RETURNING *",
        {"u": user_id, **body.model_dump()},
    )
    course = rows[0]
    topics = body.topics or [body.name]
    await _topics_to_evidence(pg, user_id, topics, kind="course", signal=km.grade_signal(body.grade),
                              source_id=f"course:{course['id']}")
    return _ser(course)


@router.delete("/api/profile/courses/{course_id}")
async def delete_course(course_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "DELETE FROM user_courses WHERE id::text = :id AND user_id = CAST(:u AS uuid) RETURNING id", {"id": course_id, "u": user_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Course not found")
    await _drop_source_evidence(pg, user_id, f"course:{course_id}")
    return {"deleted": course_id}


@router.get("/api/profile/projects")
async def list_projects(current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "SELECT * FROM user_projects WHERE user_id = CAST(:u AS uuid) ORDER BY created_at DESC", {"u": str(current_user["id"])})
    return {"projects": [_ser(r) for r in rows or []]}


@router.post("/api/profile/projects")
async def add_project(body: ProjectBody, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    if body.url and not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http(s)")
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "INSERT INTO user_projects (user_id, name, summary, url, skills, started, ended) VALUES "
        "(CAST(:u AS uuid), :name, :summary, :url, :skills, :started, :ended) RETURNING *",
        {"u": user_id, **body.model_dump()},
    )
    project = rows[0]
    await _topics_to_evidence(pg, user_id, body.skills, kind="project", signal=0.7, source_id=f"project:{project['id']}")
    return _ser(project)


@router.delete("/api/profile/projects/{project_id}")
async def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "DELETE FROM user_projects WHERE id::text = :id AND user_id = CAST(:u AS uuid) RETURNING id", {"id": project_id, "u": user_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Project not found")
    await _drop_source_evidence(pg, user_id, f"project:{project_id}")
    return {"deleted": project_id}


# --------------------------------------------------------------------------- resume

class ResumeBody(BaseModel):
    text: str = Field(..., min_length=50, max_length=60000)
    file_name: Optional[str] = Field(default=None, max_length=200)


async def _resume_view(user_id: str, resume: dict) -> dict:
    skills = resume.get("skills") or []
    if isinstance(skills, str):
        import json

        skills = json.loads(skills)
    names = [s["name"] for s in skills]
    assessed = {a.name: a for a in await km.assess(user_id, names)} if names else {}
    text = resume["text"]
    spans = rs.highlight_spans(text, names)
    items = []
    for s in skills:
        a = assessed.get(s["name"])
        items.append({**s, **(a.as_dict() if a else {"status": "unexposed"}), "spans": spans.get(s["name"], [])})
    counts = {st: sum(1 for i in items if i.get("status") == st) for st in km.STATUSES}
    return {"id": str(resume["id"]), "file_name": resume.get("file_name"), "text": text, "skills": items,
            "counts": counts, "created_at": resume["created_at"].isoformat() if resume.get("created_at") else None}


@router.post("/api/profile/resume")
async def upload_resume(body: ResumeBody, current_user: dict = Depends(get_current_user)):
    import json

    user_id = str(current_user["id"])
    text = rs.strip_contacts(body.text)
    skills, method = await rs.extract_skills(text)
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "INSERT INTO user_resumes (user_id, file_name, text, skills) VALUES "
        "(CAST(:u AS uuid), :f, :t, CAST(:s AS jsonb)) RETURNING id, file_name, text, skills, created_at",
        {"u": user_id, "f": body.file_name, "t": text, "s": json.dumps(skills)},
    )
    await pg.execute_update(
        "DELETE FROM knowledge_evidence WHERE user_id = CAST(:u AS uuid) AND kind = 'resume'", {"u": user_id})
    await _topics_to_evidence(pg, user_id, [s["name"] for s in skills], kind="resume", signal=0.6,
                              source_id=f"resume:{rows[0]['id']}")
    view = await _resume_view(user_id, rows[0])
    view["extraction"] = method
    return view


@router.get("/api/profile/resume")
async def get_resume(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "SELECT id, file_name, text, skills, created_at FROM user_resumes WHERE user_id = CAST(:u AS uuid) "
        "ORDER BY created_at DESC LIMIT 1", {"u": user_id})
    if not rows:
        return {}
    return await _resume_view(user_id, rows[0])

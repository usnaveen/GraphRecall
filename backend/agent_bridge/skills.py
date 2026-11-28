"""Skills over MCP (extension ``io.modelcontextprotocol/skills``) for the agent bridge.

Each directory under ``backend/agent_bridge/skill_files/`` is an Agent Skill: a ``SKILL.md`` with YAML
frontmatter (``name`` equal to the directory name, ``description``) plus optional supporting files.
They teach an agent the multi-step workflows the bridge's tools only make sense in (claim ->
research -> submit; frontier -> teach -> record exposure), which tool descriptions can't carry.

Wire format (2026-07-28 revision):
- ``server/discover`` advertises ``resources`` and ``extensions["io.modelcontextprotocol/skills"]``.
- ``skills/list`` -> ``{resultType, skills: [{uri, frontmatter, resources: [{uri, digest, size}]}],
  ttlMs, cacheScope}``; ``skills/get {uri}`` -> ``{resultType, skill, ttlMs, cacheScope}``.
- Files are read with ``resources/read`` at ``skill://<name>/<path>``; manifests are computed from
  the exact bytes served. Unknown URIs are JSON-RPC -32602.

A skill declares the key scopes it needs in ``metadata.graphrecall-scopes`` (space separated). A key
only sees, gets and reads skills it can run, so the listing is per key: ``cacheScope`` is "private".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

EXTENSION_ID = "io.modelcontextprotocol/skills"
SKILLS_DIR = Path(__file__).resolve().parent / "skill_files"
SCHEME = "skill://"
TTL_MS = 300_000
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MIME = {".md": "text/markdown", ".txt": "text/plain", ".json": "application/json", ".py": "text/x-python"}


class SkillNotFound(Exception):
    """Unknown skill or file, or one the caller's key may not see (-32602)."""


@dataclass(frozen=True)
class Skill:
    name: str
    frontmatter: dict[str, Any]
    files: dict[str, bytes]  # relative path ("SKILL.md", "references/x.md") -> exact bytes served
    scopes: frozenset[str]

    @property
    def uri(self) -> str:
        return f"{SCHEME}{self.name}/SKILL.md"

    def file_uri(self, rel: str) -> str:
        return f"{SCHEME}{self.name}/{rel}"

    def entry(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "frontmatter": self.frontmatter,
            "resources": [{"uri": self.file_uri(rel), "digest": "sha256:" + hashlib.sha256(b).hexdigest(),
                           "size": len(b)} for rel, b in sorted(self.files.items())],
        }


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter is not closed")
    data = yaml.safe_load(text[4:end]) or {}
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return data


def load_skill(path: Path) -> Skill:
    files = {p.relative_to(path).as_posix(): p.read_bytes()
             for p in sorted(path.rglob("*")) if p.is_file() and not p.name.startswith(".")}
    if "SKILL.md" not in files:
        raise ValueError(f"{path.name}: missing SKILL.md")
    fm = parse_frontmatter(files["SKILL.md"].decode("utf-8"))
    name, desc = fm.get("name"), fm.get("description")
    if not isinstance(name, str) or not _NAME.match(name) or len(name) > 64:
        raise ValueError(f"{path.name}: name must be 1-64 lowercase letters, digits and single hyphens")
    if name != path.name:
        raise ValueError(f"{path.name}: frontmatter name {name!r} must equal the directory name")
    if not isinstance(desc, str) or not (1 <= len(desc) <= 1024):
        raise ValueError(f"{name}: description must be 1-1024 characters")
    meta = fm.get("metadata") or {}
    scopes = frozenset(str(meta.get("graphrecall-scopes", "read:knowledge")).split())
    return Skill(name=name, frontmatter=fm, files=files, scopes=scopes)


@lru_cache(maxsize=1)
def all_skills(root: Optional[str] = None) -> tuple[Skill, ...]:
    base = Path(root) if root else SKILLS_DIR
    return tuple(load_skill(p) for p in sorted(base.iterdir()) if p.is_dir() and not p.name.startswith(("_", ".")))


def visible(scopes: Iterable[str], skills: Optional[Iterable[Skill]] = None) -> list[Skill]:
    have = frozenset(scopes)
    return [s for s in (skills if skills is not None else all_skills()) if s.scopes <= have]


def _split(uri: str) -> tuple[str, str]:
    if not uri.startswith(SCHEME):
        raise SkillNotFound(uri)
    name, _, rel = uri[len(SCHEME):].partition("/")
    if not name or not rel or ".." in rel.split("/"):
        raise SkillNotFound(uri)
    return name, rel


def _find(name: str, scopes: Iterable[str]) -> Skill:
    for s in visible(scopes):
        if s.name == name:
            return s
    raise SkillNotFound(name)


def _envelope(**body: Any) -> dict[str, Any]:
    return {"resultType": "complete", **body, "ttlMs": TTL_MS, "cacheScope": "private"}


def list_result(scopes: Iterable[str]) -> dict[str, Any]:
    return _envelope(skills=[s.entry() for s in visible(scopes)])


def get_result(uri: str, scopes: Iterable[str]) -> dict[str, Any]:
    name, rel = _split(uri)
    if rel != "SKILL.md":
        raise SkillNotFound(uri)
    return _envelope(skill=_find(name, scopes).entry())


def read_file(uri: str, scopes: Iterable[str]) -> tuple[str, str]:
    """(text, mimeType) of one skill file, exactly the bytes the manifest digests."""
    name, rel = _split(uri)
    skill = _find(name, scopes)
    if rel not in skill.files:
        raise SkillNotFound(uri)
    return skill.files[rel].decode("utf-8"), _MIME.get(Path(rel).suffix, "text/plain")


def is_skill_uri(uri: str) -> bool:
    return str(uri).startswith(SCHEME)

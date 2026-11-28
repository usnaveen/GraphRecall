"""Skills over MCP on the agent bridge: loading, manifests, scope filtering, and the wire protocol."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import BaseModel

from backend.agent_bridge import skills
from backend.agent_bridge.keys import AgentPrincipal

READ = {"read:knowledge"}
ALL = {"read:knowledge", "write:feed", "bridge:answer"}


def test_every_skill_loads_and_matches_its_directory():
    loaded = skills.all_skills()
    assert {s.name for s in loaded} == {"teach-at-my-level", "quiz-due-reviews", "answer-app-questions",
                                        "curate-my-feed"}
    for s in loaded:
        assert s.frontmatter["name"] == s.name
        assert 1 <= len(s.frontmatter["description"]) <= 1024
        assert "SKILL.md" in s.files
        assert len(s.files["SKILL.md"]) < 100_000  # Claude Code's per-file limit


def test_manifest_digest_and_size_match_served_bytes():
    for entry in skills.list_result(ALL)["skills"]:
        for f in entry["resources"]:
            text, mime = skills.read_file(f["uri"], ALL)
            body = text.encode("utf-8")
            assert f["size"] == len(body)
            assert f["digest"] == "sha256:" + hashlib.sha256(body).hexdigest()
            assert mime == "text/markdown"


def test_envelope_fields():
    res = skills.list_result(READ)
    assert res["resultType"] == "complete" and res["ttlMs"] > 0 and res["cacheScope"] == "private"
    got = skills.get_result("skill://teach-at-my-level/SKILL.md", READ)
    assert got["skill"]["uri"] == "skill://teach-at-my-level/SKILL.md" and got["resultType"] == "complete"


def test_read_only_key_sees_only_skills_it_can_run():
    names = {e["frontmatter"]["name"] for e in skills.list_result(READ)["skills"]}
    assert names == {"teach-at-my-level", "quiz-due-reviews"}
    with pytest.raises(skills.SkillNotFound):
        skills.get_result("skill://answer-app-questions/SKILL.md", READ)
    with pytest.raises(skills.SkillNotFound):
        skills.read_file("skill://curate-my-feed/SKILL.md", READ)
    assert {e["frontmatter"]["name"] for e in skills.list_result(ALL)["skills"]} == {
        s.name for s in skills.all_skills()}
    assert skills.list_result(set())["skills"] == []


@pytest.mark.parametrize("uri", [
    "skill://nope/SKILL.md",
    "skill://teach-at-my-level/missing.md",
    "skill://teach-at-my-level/../curate-my-feed/SKILL.md",
    "skill://teach-at-my-level",
    "file:///etc/passwd",
    "skill:///SKILL.md",
])
def test_unknown_or_traversal_uris_are_not_found(uri):
    with pytest.raises(skills.SkillNotFound):
        skills.read_file(uri, ALL)


def test_loader_rejects_name_directory_mismatch(tmp_path):
    d = tmp_path / "right-name"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: wrong-name\ndescription: x\n---\nbody\n")
    with pytest.raises(ValueError, match="directory name"):
        skills.load_skill(d)
    (d / "SKILL.md").write_text("no frontmatter\n")
    with pytest.raises(ValueError, match="frontmatter"):
        skills.load_skill(d)


# --- the wire protocol, through the official SDK client in-process ------------------------------

class _Any(BaseModel):
    model_config = {"extra": "allow"}


@pytest.fixture
def server_for():
    pytest.importorskip("mcp.server.lowlevel")
    from backend.agent_bridge import mcp_app

    def make(scopes: set[str]):
        token = mcp_app._current_principal.set(AgentPrincipal(user_id="u1", key_id="k1", scopes=frozenset(scopes)))
        return mcp_app.build_lowlevel_server(lambda: None), token, mcp_app._current_principal
    return make


async def _request(client: Any, method: str, params: dict) -> dict:
    import mcp.types as types

    res = await client.session.send_request(types.Request[Any, Any](method=method, params=params), _Any)
    return res.model_dump(by_alias=True)


async def test_protocol_end_to_end(server_for):
    from mcp import Client
    from mcp.shared.exceptions import MCPError

    server, token, var = server_for(READ)
    try:
        async with Client(server) as c:
            caps = c.server_capabilities.model_dump(by_alias=True, exclude_none=True)
            assert "io.modelcontextprotocol/skills" in caps["extensions"]
            assert "resources" in caps

            listed = await _request(c, "skills/list", {})
            assert listed["resultType"] == "complete" and listed["cacheScope"] == "private"
            assert {s["frontmatter"]["name"] for s in listed["skills"]} == {"teach-at-my-level", "quiz-due-reviews"}

            got = await _request(c, "skills/get", {"uri": "skill://quiz-due-reviews/SKILL.md"})
            assert got["skill"]["frontmatter"]["name"] == "quiz-due-reviews"

            read = await c.read_resource("skill://quiz-due-reviews/SKILL.md")
            text = read.contents[0].text
            entry = next(s for s in listed["skills"] if s["frontmatter"]["name"] == "quiz-due-reviews")
            assert "sha256:" + hashlib.sha256(text.encode()).hexdigest() == entry["resources"][0]["digest"]

            res = await c.list_resources()
            assert {str(r.uri) for r in res.resources} == {s["uri"] for s in listed["skills"]}

            for call in (lambda: _request(c, "skills/get", {"uri": "skill://curate-my-feed/SKILL.md"}),
                         lambda: c.read_resource("skill://answer-app-questions/SKILL.md")):
                with pytest.raises(MCPError) as e:
                    await call()
                assert e.value.code == -32602
    finally:
        var.reset(token)

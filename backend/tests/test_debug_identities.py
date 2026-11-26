"""The fixed debug identities: only on DEBUG, never in production, and the showcase learner is a
different person from the developer's test account (so recording a demo never touches real data)."""

import pytest
from fastapi import HTTPException

from backend.auth import google_oauth


@pytest.fixture
def debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")


async def test_showcase_is_its_own_identity(debug):
    test = await google_oauth.verify_google_token("test-token")
    show = await google_oauth.verify_google_token("showcase-token")
    assert show["google_id"] != test["google_id"]
    assert show["email"] != test["email"]
    assert show["name"] == "Jordan Avery"


async def test_callers_cannot_change_the_table(debug):
    got = await google_oauth.verify_google_token("showcase-token")
    got["google_id"] = "someone-else"
    again = await google_oauth.verify_google_token("showcase-token")
    assert again["google_id"] == "showcase-google-id"


@pytest.mark.parametrize("env", [{"DEBUG": "false"}, {"DEBUG": "true", "ENVIRONMENT": "production"}])
async def test_refused_outside_local_debug(monkeypatch, env):
    monkeypatch.delenv("DEBUG", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for token in ("test-token", "showcase-token"):
        with pytest.raises(HTTPException):
            await google_oauth.verify_google_token(token)

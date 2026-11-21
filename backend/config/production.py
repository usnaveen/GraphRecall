"""Fail-fast checks for `ENVIRONMENT=production`.

Anything that is a convenience in development and a vulnerability in production is refused here, at
start-up, instead of being remembered by whoever deploys.
"""

from __future__ import annotations

import os


class UnsafeProductionConfig(RuntimeError):
    pass


REQUIRED_IN_PRODUCTION = ("DATABASE_URL", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "GOOGLE_API_KEY")


def problems() -> list[str]:
    if os.getenv("ENVIRONMENT", "development") != "production":
        return []
    out = []
    if os.getenv("DEBUG", "").lower() == "true":
        out.append("DEBUG=true enables the 'test-token' login bypass (backend/auth/google_oauth.py)")
    if not (os.getenv("GOOGLE_CLIENT_IDS") or os.getenv("GOOGLE_CLIENT_ID")):
        out.append("GOOGLE_CLIENT_IDS (iOS and web OAuth client IDs) is not set: no sign-in can be verified")
    for name in REQUIRED_IN_PRODUCTION:
        if not os.getenv(name):
            out.append(f"{name} is not set")
    if os.getenv("FEED_DEMO_CARDS") == "1":
        out.append("FEED_DEMO_CARDS=1 shows demo cards to real users")
    origins = os.getenv("CORS_ORIGINS", "")
    if not origins or "*" in origins.split(","):
        out.append("CORS_ORIGINS must list the allowed origins explicitly (no '*')")
    elif "localhost" in origins:
        out.append("CORS_ORIGINS includes localhost")
    if len(os.getenv("SESSION_SECRET", "")) < 32:
        out.append("SESSION_SECRET must be at least 32 characters (signs session access tokens)")
    if os.getenv("APPLE_CLIENT_IDS"):
        missing = [k for k in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY") if not os.getenv(k)]
        if missing:
            out.append(f"Sign in with Apple is on but {', '.join(missing)} unset: account deletion can't "
                       "revoke Apple tokens (App Store guideline 5.1.1(v))")
    if os.getenv("CHECKPOINTER", "postgres") == "memory":
        out.append("CHECKPOINTER=memory loses paused ingests on restart")
    return out


def check_production_settings() -> None:
    found = problems()
    if found:
        raise UnsafeProductionConfig("refusing to start in production:\n  - " + "\n  - ".join(found))

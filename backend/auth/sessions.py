"""GraphRecall-issued sessions: short-lived access JWTs and rotating refresh tokens.

Why not keep using provider tokens as bearers: Apple identity tokens can't be refreshed by the
client, and Google ID tokens expire after an hour, which also breaks background share uploads.

- Access token: HS256 JWT, 1 hour, `iss=graphrecall`, `aud=graphrecall-api`, `typ=access`.
  The algorithm is pinned and every claim is required.
- Refresh token: 256 random bits, 60 days. Only its SHA-256 is stored. Single use: each refresh
  returns a new one. Presenting an already-used token revokes its whole family (theft detection,
  RFC 6819 5.2.2.3), so only one client (the app, not the share extension) may refresh.
- Apple nonces: issued here, single use, 10 minutes.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from typing import Optional

import jwt
import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger()

ISSUER = "graphrecall"
AUDIENCE = "graphrecall-api"
ACCESS_TTL_S = 3600
REFRESH_TTL_DAYS = 60
NONCE_TTL_S = 600
_ALG = "HS256"
_dev_secret: Optional[str] = None


def _secret() -> str:
    s = os.getenv("SESSION_SECRET")
    if s:
        return s
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise RuntimeError("SESSION_SECRET is required in production")  # also refused at start-up
    global _dev_secret
    if _dev_secret is None:
        _dev_secret = secrets.token_urlsafe(48)
        logger.warning("SESSION_SECRET not set: using a per-process dev secret (sessions end on restart)")
    return _dev_secret


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _unauthorized(detail: str = "Invalid or expired session") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


# ---- access tokens -----------------------------------------------------------

def issue_access_token(user_id: str, *, now: Optional[int] = None) -> str:
    now = int(now if now is not None else time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": str(user_id), "iat": now, "exp": now + ACCESS_TTL_S,
              "typ": "access", "jti": uuid.uuid4().hex}
    return jwt.encode(claims, _secret(), algorithm=_ALG)


def looks_like_session_token(token: str) -> bool:
    """Routing only (no trust): does the *unverified* payload claim our issuer?"""
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss") == ISSUER
    except jwt.PyJWTError:
        return False


def verify_access_token(token: str) -> str:
    """Returns the user id. Raises 401 on anything other than a valid, unexpired access token."""
    try:
        claims = jwt.decode(
            token, _secret(), algorithms=[_ALG], audience=AUDIENCE, issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired")
    except jwt.PyJWTError:
        raise _unauthorized()
    if claims.get("typ") != "access":
        raise _unauthorized()
    return claims["sub"]


# ---- refresh tokens ------------------------------------------------------------

async def issue_session(pg, user_id: str, *, family_id: Optional[str] = None) -> dict:
    refresh = secrets.token_urlsafe(32)
    await pg.execute_update(
        "INSERT INTO auth_refresh_tokens (token_hash, user_id, family_id, expires_at) "
        f"VALUES (:h, CAST(:u AS uuid), CAST(:f AS uuid), NOW() + INTERVAL '{REFRESH_TTL_DAYS} days')",
        {"h": sha256_hex(refresh), "u": str(user_id), "f": family_id or str(uuid.uuid4())},
    )
    return {"access_token": issue_access_token(user_id), "refresh_token": refresh,
            "token_type": "Bearer", "expires_in": ACCESS_TTL_S}


async def rotate_refresh_token(pg, refresh_token: str) -> tuple[str, dict]:
    """Consume a refresh token and issue a new session in the same family. Returns (user_id, session)."""
    h = sha256_hex(refresh_token)
    # One atomic UPDATE: of two concurrent refreshes with the same token, exactly one wins.
    rows = await pg.execute_query(
        "UPDATE auth_refresh_tokens SET used_at = NOW() "
        "WHERE token_hash = :h AND used_at IS NULL AND revoked_at IS NULL AND expires_at > NOW() "
        "RETURNING user_id, family_id",
        {"h": h},
    )
    if not rows:
        old = await pg.execute_query(
            "SELECT family_id, used_at FROM auth_refresh_tokens WHERE token_hash = :h", {"h": h})
        if old and old[0]["used_at"] is not None:
            await revoke_family(pg, str(old[0]["family_id"]))
            logger.warning("auth: refresh token reuse, family revoked")
        raise _unauthorized()
    user_id, family = str(rows[0]["user_id"]), str(rows[0]["family_id"])
    return user_id, await issue_session(pg, user_id, family_id=family)


async def revoke_family(pg, family_id: str) -> None:
    await pg.execute_update(
        "UPDATE auth_refresh_tokens SET revoked_at = NOW() WHERE family_id = CAST(:f AS uuid) AND revoked_at IS NULL",
        {"f": family_id})


async def revoke_refresh_token(pg, refresh_token: str) -> None:
    rows = await pg.execute_query(
        "SELECT family_id FROM auth_refresh_tokens WHERE token_hash = :h", {"h": sha256_hex(refresh_token)})
    if rows:
        await revoke_family(pg, str(rows[0]["family_id"]))


# ---- Apple nonces ---------------------------------------------------------------

async def issue_nonce(pg) -> str:
    raw = secrets.token_urlsafe(24)
    await pg.execute_update("DELETE FROM auth_nonces WHERE expires_at < NOW()")
    await pg.execute_update(
        f"INSERT INTO auth_nonces (nonce_hash, expires_at) VALUES (:h, NOW() + INTERVAL '{NONCE_TTL_S} seconds')",
        {"h": sha256_hex(raw)})
    return raw


async def consume_nonce(pg, raw: str) -> bool:
    rows = await pg.execute_query(
        "DELETE FROM auth_nonces WHERE nonce_hash = :h AND expires_at > NOW() RETURNING 1 AS ok",
        {"h": sha256_hex(raw)})
    return bool(rows)

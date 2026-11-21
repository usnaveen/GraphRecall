"""Sign in with Apple: identity-token verification, and token revocation on account deletion.

Verification (https://developer.apple.com/documentation/sign_in_with_apple/sign_in_with_apple_rest_api/verifying_a_user):
- signature: RS256 only (the algorithm is pinned, never read from the token), key from Apple's
  JWKS by `kid`, cached for a day and refetched at most once a minute for an unknown `kid`
- `iss` = https://appleid.apple.com, `aud` in APPLE_CLIENT_IDS (the iOS bundle ID; a web Services
  ID if the web app adds Apple sign-in), `exp`/`iat` required
- `nonce` = SHA-256 hex of the server-issued raw nonce, which is single use (sessions.consume_nonce)

Revocation (App Store guideline 5.1.1(v)): when APPLE_TEAM_ID, APPLE_KEY_ID and APPLE_PRIVATE_KEY
(the .p8 contents) are set, sign-in exchanges the `authorization_code` for an Apple refresh token,
stored encrypted, and account deletion revokes it. Without them, sign-in still works and the
production check flags the gap.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Optional

import httpx
import jwt
import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException, status

logger = structlog.get_logger()

APPLE_ISSUER = "https://appleid.apple.com"
JWKS_URL = "https://appleid.apple.com/auth/keys"
TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"
JWKS_TTL_S = 24 * 3600
JWKS_MIN_REFETCH_S = 60


def client_ids() -> list[str]:
    return [c.strip() for c in os.getenv("APPLE_CLIENT_IDS", "").split(",") if c.strip()]


def revocation_configured() -> bool:
    return all(os.getenv(k) for k in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY"))


def _invalid(detail: str = "Invalid Apple identity token") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


# ---- JWKS cache ---------------------------------------------------------------

class _JWKS:
    def __init__(self) -> None:
        self.keys: dict[str, dict] = {}
        self.fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _fetch(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
        self.keys = {k["kid"]: k for k in resp.json().get("keys", []) if k.get("kid")}
        self.fetched_at = time.monotonic()

    async def get(self, kid: str) -> Optional[dict]:
        async with self._lock:
            age = time.monotonic() - self.fetched_at
            stale = age > JWKS_TTL_S
            unknown_and_may_refetch = kid not in self.keys and age > JWKS_MIN_REFETCH_S
            if not self.keys or stale or unknown_and_may_refetch:
                try:
                    await self._fetch()
                except Exception as e:  # keep serving cached keys if Apple is briefly unreachable
                    logger.warning("apple: JWKS fetch failed", error=str(e))
            return self.keys.get(kid)


jwks = _JWKS()


async def verify_identity_token(token: str, *, expected_nonce_hash: str) -> dict:
    audiences = client_ids()
    if not audiences:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sign in with Apple is not configured")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise _invalid()
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise _invalid()
    jwk = await jwks.get(header["kid"])
    if jwk is None:
        raise _invalid()
    try:
        key = jwt.PyJWK(jwk, algorithm="RS256").key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=audiences, issuer=APPLE_ISSUER, leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise _invalid("Apple identity token expired")
    except jwt.PyJWTError:
        raise _invalid()
    if claims.get("nonce") != expected_nonce_hash:
        raise _invalid("Sign-in nonce mismatch")
    return claims


# ---- client secret, code exchange, revocation ------------------------------------

def _client_secret(client_id: str) -> str:
    now = int(time.time())
    key = os.environ["APPLE_PRIVATE_KEY"].replace("\\n", "\n")
    return jwt.encode(
        {"iss": os.environ["APPLE_TEAM_ID"], "iat": now, "exp": now + 300, "aud": APPLE_ISSUER, "sub": client_id},
        key, algorithm="ES256", headers={"kid": os.environ["APPLE_KEY_ID"]},
    )


def _fernet() -> Fernet:
    from backend.auth.sessions import _secret

    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"graphrecall/apple-refresh-token").derive(
        _secret().encode())
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_refresh(client_id: str, refresh_token: str) -> str:
    return _fernet().encrypt(json.dumps({"c": client_id, "t": refresh_token}).encode()).decode()


def decrypt_refresh(blob: str) -> Optional[tuple[str, str]]:
    try:
        data = json.loads(_fernet().decrypt(blob.encode()))
        return data["c"], data["t"]
    except (InvalidToken, ValueError, KeyError):
        return None


async def exchange_code(code: str, client_id: str) -> Optional[str]:
    """authorization_code -> Apple refresh token (for later revocation). None when not configured or on failure."""
    if not revocation_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(TOKEN_URL, data={
                "client_id": client_id, "client_secret": _client_secret(client_id),
                "code": code, "grant_type": "authorization_code"})
        if resp.status_code != 200:
            logger.warning("apple: code exchange failed", status=resp.status_code)
            return None
        return resp.json().get("refresh_token")
    except Exception as e:  # sign-in must not fail because revocation setup did
        logger.warning("apple: code exchange error", error=str(e))
        return None


async def revoke(blob: Optional[str]) -> bool:
    """Revoke the stored Apple authorization. True when Apple accepted it."""
    if not blob or not revocation_configured():
        return False
    parsed = decrypt_refresh(blob)
    if not parsed:
        return False
    client_id, refresh_token = parsed
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(REVOKE_URL, data={
                "client_id": client_id, "client_secret": _client_secret(client_id),
                "token": refresh_token, "token_type_hint": "refresh_token"})
        ok = resp.status_code == 200
        if not ok:
            logger.warning("apple: revoke failed", status=resp.status_code)
        return ok
    except Exception as e:
        logger.warning("apple: revoke error", error=str(e))
        return False

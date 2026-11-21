"""Sign in with Apple, GraphRecall sessions and identity linking.

Token checks run without databases. Linking, rotation, nonces and deletion use a scratch Postgres
(migrated), and skip when Postgres is unreachable.
"""

import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.auth import apple, sessions
from backend.tests.test_migrate import scratch_db  # noqa: F401  (fixture)

BUNDLE = "com.usnaveen.graphrecall"
KID = "test-kid-1"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUB_PEM = _KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
_JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key())), "kid": KID, "alg": "RS256", "use": "sig"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("APPLE_CLIENT_IDS", BUNDLE)
    monkeypatch.setenv("SESSION_SECRET", "s" * 48)
    for k in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)

    async def get(kid):
        return _JWK if kid == KID else None
    monkeypatch.setattr(apple.jwks, "get", get)


def apple_token(*, nonce_raw="n0nce", aud=BUNDLE, iss=apple.APPLE_ISSUER, exp_in=600, sub="000123.apple",
                email="ada@example.com", email_verified="true", kid=KID, key=None, alg="RS256"):
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "iat": now, "exp": now + exp_in,
              "nonce": sessions.sha256_hex(nonce_raw), "nonce_supported": True}
    if email:
        claims.update(email=email, email_verified=email_verified)
    return jwt.encode(claims, key if key is not None else _KEY, algorithm=alg, headers={"kid": kid})


# ---- Apple identity token --------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_apple_token():
    claims = await apple.verify_identity_token(apple_token(), expected_nonce_hash=sessions.sha256_hex("n0nce"))
    assert claims["sub"] == "000123.apple" and claims["aud"] == BUNDLE


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,detail", [
    ({"aud": "com.evil.app"}, "Invalid"),
    ({"iss": "https://accounts.google.com"}, "Invalid"),
    ({"exp_in": -3600}, "expired"),
    ({"kid": "unknown-kid"}, "Invalid"),
    ({"nonce_raw": "other"}, "nonce"),
])
async def test_apple_token_rejected(kwargs, detail):
    with pytest.raises(HTTPException) as e:
        await apple.verify_identity_token(apple_token(**kwargs), expected_nonce_hash=sessions.sha256_hex("n0nce"))
    assert e.value.status_code == 401 and detail in e.value.detail


@pytest.mark.asyncio
async def test_alg_none_rejected():
    now = int(time.time())
    forged = jwt.encode({"iss": apple.APPLE_ISSUER, "aud": BUNDLE, "sub": "x", "iat": now, "exp": now + 60,
                         "nonce": sessions.sha256_hex("n0nce")}, None, algorithm="none", headers={"kid": KID})
    with pytest.raises(HTTPException):
        await apple.verify_identity_token(forged, expected_nonce_hash=sessions.sha256_hex("n0nce"))


@pytest.mark.asyncio
async def test_hs256_signed_with_public_key_rejected():
    """Algorithm confusion: HMAC "signed" with Apple's public key must not verify."""
    import hmac, hashlib, base64

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "kid": KID, "typ": "JWT"}).encode())
    payload = b64(json.dumps({"iss": apple.APPLE_ISSUER, "aud": BUNDLE, "sub": "x", "iat": now, "exp": now + 60,
                              "nonce": sessions.sha256_hex("n0nce")}).encode())
    sig = b64(hmac.new(_PUB_PEM, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    with pytest.raises(HTTPException):
        await apple.verify_identity_token(f"{header}.{payload}.{sig}", expected_nonce_hash=sessions.sha256_hex("n0nce"))


@pytest.mark.asyncio
async def test_token_signed_by_other_key_rejected():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException):
        await apple.verify_identity_token(apple_token(key=other), expected_nonce_hash=sessions.sha256_hex("n0nce"))


@pytest.mark.asyncio
async def test_apple_not_configured_is_503(monkeypatch):
    monkeypatch.setenv("APPLE_CLIENT_IDS", "")
    with pytest.raises(HTTPException) as e:
        await apple.verify_identity_token(apple_token(), expected_nonce_hash="x")
    assert e.value.status_code == 503


def test_apple_refresh_token_encryption_roundtrip():
    blob = apple.encrypt_refresh(BUNDLE, "r.apple.secret")
    assert "r.apple.secret" not in blob
    assert apple.decrypt_refresh(blob) == (BUNDLE, "r.apple.secret")
    assert apple.decrypt_refresh("garbage") is None


# ---- session access tokens ----------------------------------------------------------

def test_access_token_roundtrip():
    tok = sessions.issue_access_token("u-1")
    assert sessions.looks_like_session_token(tok)
    assert sessions.verify_access_token(tok) == "u-1"


def test_access_token_expired():
    tok = sessions.issue_access_token("u-1", now=int(time.time()) - 2 * sessions.ACCESS_TTL_S)
    with pytest.raises(HTTPException, match="expired"):
        sessions.verify_access_token(tok)


@pytest.mark.parametrize("mutate", [
    lambda c: jwt.encode(c, "wrong-secret-" * 4, algorithm="HS256"),
    lambda c: jwt.encode({**c, "typ": "refresh"}, "s" * 48, algorithm="HS256"),
    lambda c: jwt.encode({**c, "aud": "someone-else"}, "s" * 48, algorithm="HS256"),
    lambda c: jwt.encode(c, None, algorithm="none"),
    lambda c: jwt.encode({k: v for k, v in c.items() if k != "exp"}, "s" * 48, algorithm="HS256"),
])
def test_forged_access_tokens_rejected(mutate):
    now = int(time.time())
    claims = {"iss": "graphrecall", "aud": "graphrecall-api", "sub": "u-1", "iat": now, "exp": now + 60, "typ": "access"}
    with pytest.raises(HTTPException) as e:
        sessions.verify_access_token(mutate(claims))
    assert e.value.status_code == 401


def test_routing_by_issuer():
    assert not sessions.looks_like_session_token(apple_token())   # Apple/Google JWTs go to their own verifier
    assert not sessions.looks_like_session_token("test-token")
    assert not sessions.looks_like_session_token("a.b.c")


# ---- with Postgres ----------------------------------------------------------------------

@pytest.fixture
async def pg(scratch_db, monkeypatch):  # noqa: F811
    from backend.db import migrate as M

    client, _ = scratch_db
    await M.migrate(client)

    async def get_pg():
        return client
    for mod in ("backend.routers.auth", "backend.auth.middleware"):
        monkeypatch.setattr(f"{mod}.get_postgres_client", get_pg)
    return client


async def _apple_login(nonce=None, **token_kwargs):
    from backend.routers import auth as auth_router

    raw = nonce or await sessions.issue_nonce(await auth_router.get_postgres_client())
    AppleAuthRequest, AppleName, apple_login = auth_router.AppleAuthRequest, auth_router.AppleName, auth_router.apple_login
    return await apple_login(AppleAuthRequest(
        identity_token=apple_token(nonce_raw=raw, **token_kwargs), nonce=raw,
        full_name=AppleName(given="Ada", family="Lovelace")))


@pytest.mark.asyncio
async def test_apple_login_creates_user_and_session(pg):
    from backend.auth.middleware import get_current_user

    out = await _apple_login(sub=f"apple-{uuid.uuid4().hex}")
    assert out["user"]["name"] == "Ada Lovelace" and out["user"]["email"] == "ada@example.com"
    user = await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=out["access_token"]))
    assert str(user["id"]) == out["user"]["id"]


@pytest.mark.asyncio
async def test_nonce_is_single_use(pg):
    raw = await sessions.issue_nonce(pg)
    await _apple_login(nonce=raw, sub=f"apple-{uuid.uuid4().hex}", email=None)
    with pytest.raises(HTTPException, match="already used"):
        await _apple_login(nonce=raw, sub=f"apple-{uuid.uuid4().hex}", email=None)


@pytest.mark.asyncio
async def test_unissued_nonce_rejected(pg):
    with pytest.raises(HTTPException, match="nonce"):
        await _apple_login(nonce="never-issued", sub=f"apple-{uuid.uuid4().hex}")


@pytest.mark.asyncio
async def test_apple_then_google_links_by_verified_email(pg):
    from backend.auth.identity import resolve_user

    email = f"link-{uuid.uuid4().hex[:6]}@example.com"
    a = await _apple_login(sub=f"apple-{uuid.uuid4().hex}", email=email)
    g = await resolve_user(pg, provider="google", subject=f"g-{uuid.uuid4().hex}", email=email.upper(),
                           email_verified=True, name="Ada G")
    assert str(g["id"]) == a["user"]["id"] and g["google_id"] and g["apple_id"]


@pytest.mark.asyncio
async def test_unverified_or_missing_email_never_links(pg):
    from backend.auth.identity import resolve_user

    email = f"unv-{uuid.uuid4().hex[:6]}@example.com"
    first = await resolve_user(pg, provider="google", subject=f"g-{uuid.uuid4().hex}", email=email, email_verified=True)
    other = await resolve_user(pg, provider="apple", subject=f"a-{uuid.uuid4().hex}", email=email, email_verified="false")
    assert other["id"] != first["id"] and other["email"] is None
    hidden1 = await resolve_user(pg, provider="apple", subject=f"a-{uuid.uuid4().hex}", email=None, email_verified=None)
    hidden2 = await resolve_user(pg, provider="apple", subject=f"a-{uuid.uuid4().hex}", email=None, email_verified=None)
    assert hidden1["id"] != hidden2["id"]  # several no-email users coexist


@pytest.mark.asyncio
async def test_refresh_rotation_and_reuse_detection(pg):
    from backend.routers.auth import RefreshRequest, refresh

    out = await _apple_login(sub=f"apple-{uuid.uuid4().hex}", email=None)
    r1 = out["refresh_token"]
    second = await refresh(RefreshRequest(refresh_token=r1))
    assert second["refresh_token"] != r1 and second["user"]["id"] == out["user"]["id"]
    with pytest.raises(HTTPException):                      # replaying the used token...
        await refresh(RefreshRequest(refresh_token=r1))
    with pytest.raises(HTTPException):                      # ...revoked the newer one too
        await refresh(RefreshRequest(refresh_token=second["refresh_token"]))


@pytest.mark.asyncio
async def test_logout_revokes(pg):
    from backend.routers.auth import RefreshRequest, logout, refresh

    out = await _apple_login(sub=f"apple-{uuid.uuid4().hex}", email=None)
    await logout(RefreshRequest(refresh_token=out["refresh_token"]))
    with pytest.raises(HTTPException):
        await refresh(RefreshRequest(refresh_token=out["refresh_token"]))


@pytest.mark.asyncio
async def test_deleted_account_session_is_dead(pg):
    from backend.auth.middleware import get_current_user

    out = await _apple_login(sub=f"apple-{uuid.uuid4().hex}", email=None)
    await pg.execute_update("DELETE FROM users WHERE id = CAST(:u AS uuid)", {"u": out["user"]["id"]})
    left = await pg.execute_query("SELECT count(*) AS n FROM auth_refresh_tokens WHERE user_id = CAST(:u AS uuid)",
                                  {"u": out["user"]["id"]})
    assert left[0]["n"] == 0  # cascaded
    with pytest.raises(HTTPException) as e:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=out["access_token"]))
    assert e.value.status_code == 401

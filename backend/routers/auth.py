from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
import structlog

from backend.auth import apple, sessions
from backend.auth.google_oauth import verify_google_token
from backend.auth.identity import public_user, resolve_user
from backend.db.postgres_client import get_postgres_client
from backend.auth.middleware import get_current_user
import json

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleAuthRequest(BaseModel):
    token: str


async def _google_user(token: str) -> dict:
    info = await verify_google_token(token)
    pg = await get_postgres_client()
    return await resolve_user(
        pg, provider="google", subject=info["google_id"], email=info.get("email"),
        email_verified=info.get("email_verified"), name=info.get("name"), picture=info.get("profile_picture"),
    )


@router.post("/google")
async def google_login(request: GoogleAuthRequest):
    """Legacy login: verify a Google ID token, return the user, and echo the token as the bearer.

    New clients should call ``/auth/session/google`` instead, which returns refreshable sessions.
    """
    user = await _google_user(request.token)
    return {"status": "success", "user": {**public_user(user), "drive_folder_id": user.get("drive_folder_id")},
            "token": request.token}


# ---- sessions (Apple and Google) -------------------------------------------------

class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: dict


class GoogleSessionRequest(BaseModel):
    id_token: str


@router.post("/session/google", response_model=SessionResponse)
async def google_session(request: GoogleSessionRequest):
    """Exchange a Google ID token for a GraphRecall session."""
    user = await _google_user(request.id_token)
    pg = await get_postgres_client()
    return {**await sessions.issue_session(pg, str(user["id"])), "user": public_user(user)}


class NonceResponse(BaseModel):
    nonce: str
    expires_in: int


@router.post("/apple/nonce", response_model=NonceResponse)
async def apple_nonce():
    """A single-use nonce. The app sets ASAuthorizationAppleIDRequest.nonce = sha256_hex(nonce)."""
    pg = await get_postgres_client()
    return {"nonce": await sessions.issue_nonce(pg), "expires_in": sessions.NONCE_TTL_S}


class AppleName(BaseModel):
    given: Optional[str] = None
    family: Optional[str] = None


class AppleAuthRequest(BaseModel):
    identity_token: str
    nonce: str                                # the raw nonce from /auth/apple/nonce
    authorization_code: Optional[str] = None  # lets account deletion revoke Apple tokens
    full_name: Optional[AppleName] = None     # Apple only provides it on the first authorization


@router.post("/apple", response_model=SessionResponse)
async def apple_login(request: AppleAuthRequest):
    """Verify a Sign in with Apple identity token and start a GraphRecall session."""
    pg = await get_postgres_client()
    claims = await apple.verify_identity_token(
        request.identity_token, expected_nonce_hash=sessions.sha256_hex(request.nonce))
    # Consume only after the signature checks out, so garbage tokens can't burn real nonces.
    if not await sessions.consume_nonce(pg, request.nonce):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in nonce expired or already used",
                            headers={"WWW-Authenticate": "Bearer"})

    name = None
    if request.full_name:
        name = " ".join(p for p in (request.full_name.given, request.full_name.family) if p) or None
    user = await resolve_user(
        pg, provider="apple", subject=claims["sub"], email=claims.get("email"),
        email_verified=claims.get("email_verified"), name=name,
    )
    if request.authorization_code:
        client_id = claims["aud"] if isinstance(claims["aud"], str) else claims["aud"][0]
        apple_refresh = await apple.exchange_code(request.authorization_code, client_id)
        if apple_refresh:
            await pg.execute_update(
                "UPDATE users SET apple_refresh_token_enc = :t WHERE id = :id",
                {"t": apple.encrypt_refresh(client_id, apple_refresh), "id": user["id"]})
    return {**await sessions.issue_session(pg, str(user["id"])), "user": public_user(user)}


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=SessionResponse)
async def refresh(request: RefreshRequest):
    """Rotate a refresh token. Reusing an old one revokes the whole session family."""
    pg = await get_postgres_client()
    user_id, session = await sessions.rotate_refresh_token(pg, request.refresh_token)
    rows = await pg.execute_query("SELECT * FROM users WHERE id = CAST(:id AS uuid)", {"id": user_id})
    if not rows:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return {**session, "user": public_user(rows[0])}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: RefreshRequest):
    pg = await get_postgres_client()
    await sessions.revoke_refresh_token(pg, request.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class UpdateProfileRequest(BaseModel):
    settings: dict | None = None
    daily_limit: int | None = None

@router.patch("/profile")
async def update_profile(
    request: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update user profile settings."""
    pg_client = await get_postgres_client()
    try:
        if request.settings is not None:
            # Merge existing settings with new ones (simple JSON update)
            # In a real app, might want deep merge, but JSONB || operator works too
            # For now, just replacing/updating keys at top level
            await pg_client.execute_update(
                """
                UPDATE users 
                SET settings_json = COALESCE(settings_json, '{}'::jsonb) || :settings::jsonb,
                    last_login = NOW()
                WHERE id = :id
                """,
                {"settings": json.dumps(request.settings), "id": current_user["id"]}
            )
            
        return {"status": "success"}
    except Exception as e:
        logger.error("Auth: Failed to update profile", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update profile")

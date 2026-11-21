from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog

from backend.auth import sessions
from backend.auth.google_oauth import verify_google_token
from backend.auth.identity import resolve_user
from backend.db.postgres_client import get_postgres_client
from backend.telemetry import stage

logger = structlog.get_logger()
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Authenticate the bearer token and return the user row.

    Two kinds of bearer are accepted:
    - a GraphRecall session access token (``backend/auth/sessions.py``), issued by ``/auth/apple``,
      ``/auth/session/google`` and ``/auth/refresh``. The user must still exist: a deleted
      account's unexpired token gets 401, and no account is ever created on this path.
    - a Google ID token, for older app builds and the web app: verified with Google, then the
      user is found, linked or created (``backend/auth/identity.py``).

    Routing looks at the unverified issuer only; each branch then verifies fully, so a forged
    token can't cross over.
    """
    token = credentials.credentials
    pg_client = await get_postgres_client()

    if sessions.looks_like_session_token(token):
        with stage("auth.verify_session"):
            user_id = sessions.verify_access_token(token)
        rows = await pg_client.execute_query("SELECT * FROM users WHERE id = CAST(:id AS uuid)", {"id": user_id})
        if not rows:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found",
                                headers={"WWW-Authenticate": "Bearer"})
        return rows[0]

    with stage("auth.verify_token"):
        info = await verify_google_token(token)
    try:
        with stage("auth.load_user"):
            return await resolve_user(
                pg_client, provider="google", subject=info["google_id"], email=info.get("email"),
                email_verified=info.get("email_verified"), name=info.get("name"),
                picture=info.get("profile_picture"),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Auth: Database error in get_current_user", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication"
        )

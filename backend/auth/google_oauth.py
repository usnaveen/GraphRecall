import asyncio
import os

from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
import requests as http_requests
import structlog

logger = structlog.get_logger()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
# Tokens from the iOS app carry the iOS OAuth client ID as their audience, the web app's carry the web
# client ID: accept any of the configured ones (comma-separated), falling back to GOOGLE_CLIENT_ID.
GOOGLE_CLIENT_IDS = [c.strip() for c in os.getenv("GOOGLE_CLIENT_IDS", GOOGLE_CLIENT_ID or "").split(",") if c.strip()]

_http_session = http_requests.Session()
_google_request = google_requests.Request(session=_http_session)


_DEBUG_IDENTITIES = {
    "test-token": {
        "google_id": "test-google-id",
        "email": "test@example.com",
        "email_verified": True,
        "name": "Test User",
        "profile_picture": None,
    },
    "showcase-token": {
        "google_id": "showcase-google-id",
        "email": "jordan.avery@example.com",
        "email_verified": True,
        "name": "Jordan Avery",
        "profile_picture": None,
    },
}


async def verify_google_token(token: str) -> dict:
    """
    Verify a Google ID token and return user information.
    
    Args:
        token: The ID token string from the frontend.
        
    Returns:
        Dictionary containing user info (google_id, email, name, profile_picture).
        
    Raises:
        HTTPException: If the token is invalid or expired.
    """
    try:
        # Debug backends only: fixed local identities. 'test-token' is the developer's own test
        # account; 'showcase-token' is a fictional learner for screenshots and demo videos
        # (scripts/showcase_account.py), kept apart so recording never touches real data.
        if (os.getenv("DEBUG") == "true" and token in _DEBUG_IDENTITIES
                and os.getenv("ENVIRONMENT", "development") != "production"):
            return dict(_DEBUG_IDENTITIES[token])

        idinfo = await asyncio.to_thread(
            id_token.verify_oauth2_token,
            token,
            _google_request,
            GOOGLE_CLIENT_IDS or GOOGLE_CLIENT_ID,
        )

        # ID token is valid. Get the user's Google ID from the 'sub' claim.
        return {
            "google_id": idinfo["sub"],
            "email": idinfo.get("email"),
            "email_verified": idinfo.get("email_verified", False),
            "name": idinfo.get("name"),
            "profile_picture": idinfo.get("picture"),
        }
    except ValueError as e:
        logger.error("Auth: Invalid Google token", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error("Auth: Unexpected error during token verification", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error verifying authentication token",
        )

from fastapi import HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests
import os
import structlog

logger = structlog.get_logger()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

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
        # If we're in debug mode and token is 'test-token', return a mock user
        if os.getenv("DEBUG") == "true" and token == "test-token":
            return {
                "google_id": "test-google-id",
                "email": "test@example.com",
                "name": "Test User",
                "profile_picture": None,
            }

        idinfo = id_token.verify_oauth2_token(
            token, 
            requests.Request(), 
            GOOGLE_CLIENT_ID
        )

        # ID token is valid. Get the user's Google ID from the 'sub' claim.
        return {
            "google_id": idinfo["sub"],
            "email": idinfo["email"],
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

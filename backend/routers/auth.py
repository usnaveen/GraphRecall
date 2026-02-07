from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import structlog
from backend.auth.google_oauth import verify_google_token
from backend.db.postgres_client import get_postgres_client
from backend.auth.middleware import get_current_user
import json

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])

class GoogleAuthRequest(BaseModel):
    token: str

@router.post("/google")
async def google_login(request: GoogleAuthRequest):
    """
    Exchange a Google ID token for a user record.
    This endpoint also creates the user if they don't exist.
    """
    try:
        # Verify the token
        user_info = await verify_google_token(request.token)
        
        # Get or Create User in Postgres
        pg_client = await get_postgres_client()
        
        # Try to find existing user
        result = await pg_client.execute_query(
            "SELECT * FROM users WHERE google_id = :google_id",
            {"google_id": user_info["google_id"]}
        )
        
        if result:
            user = result[0]
            # Update last login — use execute_update for non-returning statements
            await pg_client.execute_update(
                "UPDATE users SET last_login = NOW() WHERE id = :id",
                {"id": user["id"]}
            )
        else:
            # Create new user — use execute_query (not execute_insert) to get full row dict
            logger.info("Auth: Creating new user through login endpoint", email=user_info["email"])
            new_users = await pg_client.execute_query(
                """
                INSERT INTO users (google_id, email, name, profile_picture)
                VALUES (:google_id, :email, :name, :profile_picture)
                RETURNING *
                """,
                user_info
            )
            user = new_users[0] if new_users else {}
        
        # Format the response
        return {
            "status": "success",
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "name": user["name"],
                "profile_picture": user["profile_picture"],
                "drive_folder_id": user.get("drive_folder_id")
            },
            "token": request.token  # For simplicity, we use the ID token as the session token
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error("Auth: Unexpected error in google_login", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )

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

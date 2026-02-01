from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import structlog
from backend.auth.google_oauth import verify_google_token
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])

class GoogleAuthRequest(BaseModel):
    id_token: str

@router.post("/google")
async def google_login(request: GoogleAuthRequest):
    """
    Exchange a Google ID token for a user record.
    This endpoint also creates the user if they don't exist.
    """
    try:
        # Verify the token
        user_info = await verify_google_token(request.id_token)
        
        # Get or Create User in Postgres
        pg_client = await get_postgres_client()
        
        # Try to find existing user
        result = await pg_client.execute_query(
            "SELECT * FROM users WHERE google_id = :google_id",
            {"google_id": user_info["google_id"]}
        )
        
        if result:
            user = result[0]
            # Update last login
            await pg_client.execute_query(
                "UPDATE users SET last_login = NOW() WHERE id = :id",
                {"id": user["id"]}
            )
        else:
            # Create new user
            logger.info("Auth: Creating new user through login endpoint", email=user_info["email"])
            user = await pg_client.execute_insert(
                """
                INSERT INTO users (google_id, email, name, profile_picture)
                VALUES (:google_id, :email, :name, :profile_picture)
                RETURNING *
                """,
                user_info
            )
        
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
            "token": request.id_token  # For simplicity, we use the ID token as the session token
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error("Auth: Unexpected error in google_login", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )

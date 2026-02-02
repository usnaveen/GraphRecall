from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog
from backend.auth.google_oauth import verify_google_token
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()
security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    FastAPI dependency to get the current authenticated user.
    
    Validates the Bearer token, fetches/creates the user in Postgres,
    and returns the user record.
    
    Args:
        credentials: The HTTP Bearer credentials from the request.
        
    Returns:
        The user record from the database.
        
    Raises:
        HTTPException: If authentication fails.
    """
    token = credentials.credentials
    
    # 1. Verify Google Token
    user_info = await verify_google_token(token)
    
    # 2. Get or Create User in Postgres
    pg_client = await get_postgres_client()
    try:
        # Try to find existing user
        result = await pg_client.execute_query(
            "SELECT * FROM users WHERE google_id = :google_id",
            {"google_id": user_info["google_id"]}
        )
        
        if result:
            user = result[0]
            # Update last login
            await pg_client.execute_update(
                "UPDATE users SET last_login = NOW() WHERE id = :id",
                {"id": user["id"]}
            )
            return user
        
        # Create new user if doesn't exist
        logger.info("Auth: Creating new user", email=user_info["email"])
        new_users = await pg_client.execute_query(
            """
            INSERT INTO users (google_id, email, name, profile_picture)
            VALUES (:google_id, :email, :name, :profile_picture)
            RETURNING *
            """,
            user_info
        )
        return new_users[0] if new_users else {}
        
    except Exception as e:
        logger.error("Auth: Database error in get_current_user", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication"
        )

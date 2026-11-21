from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from backend.auth.middleware import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])
logger = structlog.get_logger()


@router.delete("/me/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_user_data(current_user: dict = Depends(get_current_user)):
    """DANGER: permanently delete ALL of the current user's data (notes, graph, reviews, files).
    The account itself stays, so the user can start over."""
    from backend.services.account_deletion import delete_user_data

    user_id = str(current_user["id"])
    try:
        await delete_user_data(user_id, delete_account=False)
    except Exception as e:
        logger.error("Purge failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Deleting your data failed. Try again.")


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(current_user: dict = Depends(get_current_user)):
    """Delete the account and everything in it (App Store guideline 5.1.1(v)). Irreversible: the next
    sign-in creates a new, empty account."""
    from backend.services.account_deletion import delete_user_data

    user_id = str(current_user["id"])
    try:
        await delete_user_data(user_id, delete_account=True)
    except Exception as e:
        logger.error("Account deletion failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Deleting your account failed. Try again.")

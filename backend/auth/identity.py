"""One place that turns a verified identity (Google or Apple) into a GraphRecall user row.

Rules:
- A provider's stable subject (`sub`) is the key: `google_id` or `apple_id`. Never the email.
- First sign-in with a new provider links to an existing account only through a *verified* email,
  so an Apple user who later signs in with Google (same address) gets the same account, and the
  reverse, instead of colliding on the UNIQUE email.
- Unverified or missing email: the user gets a new account with no email stored.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger()

PROVIDER_COLUMNS = {"google": "google_id", "apple": "apple_id"}


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


async def resolve_user(
    pg,
    *,
    provider: str,
    subject: str,
    email: Optional[str],
    email_verified,
    name: Optional[str] = None,
    picture: Optional[str] = None,
) -> dict:
    col = PROVIDER_COLUMNS[provider]  # KeyError on an unknown provider is a programming error
    email = email.strip().lower() if email else None
    verified_email = email if (email and _truthy(email_verified)) else None

    rows = await pg.execute_query(f"SELECT * FROM users WHERE {col} = :sub", {"sub": subject})
    if rows:
        user = rows[0]
        last = user.get("last_login")
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or datetime.now(timezone.utc) - last > timedelta(hours=1) or (name and not user.get("name")):
            await pg.execute_update(
                "UPDATE users SET last_login = NOW(), name = COALESCE(name, :name) WHERE id = :id",
                {"id": user["id"], "name": name},
            )
        return user

    if verified_email:
        rows = await pg.execute_query("SELECT * FROM users WHERE lower(email) = :e", {"e": verified_email})
        if rows:
            user = rows[0]
            if user.get(col) and user[col] != subject:
                # Same verified address already tied to a different account at this provider.
                logger.warning("auth: email belongs to another identity", provider=provider)
                raise HTTPException(status.HTTP_409_CONFLICT, "This email is already linked to another account.")
            linked = await pg.execute_query(
                f"UPDATE users SET {col} = :sub, last_login = NOW(), name = COALESCE(name, :name), "
                f"profile_picture = COALESCE(profile_picture, :pic) WHERE id = :id RETURNING *",
                {"sub": subject, "id": user["id"], "name": name, "pic": picture},
            )
            logger.info("auth: linked provider to existing account", provider=provider)
            return linked[0]

    created = await pg.execute_query(
        f"INSERT INTO users ({col}, email, name, profile_picture, last_login) "
        f"VALUES (:sub, :email, :name, :pic, NOW()) ON CONFLICT DO NOTHING RETURNING *",
        {"sub": subject, "email": verified_email, "name": name, "pic": picture},
    )
    if created:
        logger.info("auth: created user", provider=provider)
        return created[0]
    # Lost a race with a concurrent first sign-in: the other request created the row.
    rows = await pg.execute_query(f"SELECT * FROM users WHERE {col} = :sub", {"sub": subject})
    if rows:
        return rows[0]
    raise HTTPException(status.HTTP_409_CONFLICT, "Could not create the account; try again.")


def public_user(user: dict) -> dict:
    return {
        "id": str(user["id"]),
        "email": user.get("email"),
        "name": user.get("name"),
        "profile_picture": user.get("profile_picture"),
    }

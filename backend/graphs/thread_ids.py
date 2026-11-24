"""LangGraph checkpoint thread ids that carry their owner.

The checkpointer is keyed by thread_id alone, so a thread id taken from a request (a chat
conversation id) used to load whoever's thread had that id (GR-SEC-03). Every thread id we create
now starts with its kind and owner, which:

- makes a foreign id useless (it can only ever address the caller's own namespace), and
- lets account deletion find and remove all of a user's checkpoints by prefix (GR-SEC-04).
"""

from __future__ import annotations

import uuid
from typing import Optional


def chat_thread_id(user_id: str, conversation_id: Optional[str] = None) -> str:
    return f"chat:{user_id}:{conversation_id or uuid.uuid4()}"


def ingest_thread_id(user_id: str) -> str:
    return f"ingest:{user_id}:{uuid.uuid4()}"


def user_thread_prefixes(user_id: str) -> tuple[str, ...]:
    return (f"chat:{user_id}:", f"ingest:{user_id}:")


def thread_belongs_to(thread_id: str, user_id: str) -> bool:
    return any(thread_id.startswith(p) for p in user_thread_prefixes(user_id))

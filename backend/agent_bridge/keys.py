"""Scoped agent API keys.

Format: ``grk_<prefix>_<secret>``. ``grk_<prefix>`` is public (shown in the UI and logs);
only ``sha256(pepper + full_key)`` is stored. Keys are bound to exactly one user_id.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

KEY_PREFIX = "grk"

# --- Scopes -----------------------------------------------------------------
SCOPE_READ_KNOWLEDGE = "read:knowledge"
SCOPE_WRITE_FEED = "write:feed"
SCOPE_BRIDGE_ANSWER = "bridge:answer"

ALL_SCOPES: frozenset[str] = frozenset(
    {SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED, SCOPE_BRIDGE_ANSWER}
)
DEFAULT_SCOPES: tuple[str, ...] = (SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED, SCOPE_BRIDGE_ANSWER)


class InvalidScopeError(ValueError):
    pass


def validate_scopes(scopes: Iterable[str]) -> list[str]:
    out = sorted({s.strip() for s in scopes if s and s.strip()})
    unknown = [s for s in out if s not in ALL_SCOPES]
    if unknown:
        raise InvalidScopeError(f"Unknown scopes: {unknown}. Allowed: {sorted(ALL_SCOPES)}")
    if not out:
        raise InvalidScopeError("At least one scope is required")
    return out


def _pepper() -> str:
    # TODO(agent-bridge): require AGENT_KEY_PEPPER in production (fail closed) once deployed.
    return os.environ.get("AGENT_KEY_PEPPER", "")


def hash_key(full_key: str) -> str:
    return hashlib.sha256((_pepper() + full_key).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GeneratedKey:
    full_key: str  # shown to the user exactly once
    key_prefix: str  # "grk_xxxxxxxx" (public)
    key_hash: str


def generate_key() -> GeneratedKey:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full = f"{KEY_PREFIX}_{prefix}_{secret}"
    return GeneratedKey(full_key=full, key_prefix=f"{KEY_PREFIX}_{prefix}", key_hash=hash_key(full))


def parse_key_prefix(full_key: str) -> Optional[str]:
    """Return ``grk_<prefix>`` if the token looks like an agent key, else None."""
    parts = full_key.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    return f"{parts[0]}_{parts[1]}"


def hashes_match(stored_hash: str, full_key: str) -> bool:
    return hmac.compare_digest(stored_hash.strip(), hash_key(full_key))


@dataclass(frozen=True)
class AgentPrincipal:
    """The authenticated caller behind an agent key. Bound to ONE user."""

    user_id: str
    key_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has(self, scope: str) -> bool:
        return scope in self.scopes


class ScopeError(PermissionError):
    def __init__(self, scope: str):
        super().__init__(f"Agent key is missing required scope '{scope}'")
        self.scope = scope


def require_scope(principal: AgentPrincipal, scope: str) -> None:
    if not principal.has(scope):
        raise ScopeError(scope)


def key_row_is_active(row: dict, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if row.get("revoked_at") is not None:
        return False
    exp = row.get("expires_at")
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            return False
    return True

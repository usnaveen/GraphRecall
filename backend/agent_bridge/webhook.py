"""Outbound notifications to the agent (optional).

When a user asks their agent a question, GraphRecall can POST a small signed event so
the agent wakes up immediately instead of waiting for its next poll. The payload never
contains the question text - the agent fetches it over MCP with its own key.

Signature: ``X-GraphRecall-Signature: t=<unix>,v1=<hex hmac_sha256(secret, f"{t}.{body}")>``
(same shape as Stripe's, so receivers can reuse existing verification code).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional, Protocol

import structlog

logger = structlog.get_logger()

SIGNATURE_HEADER = "X-GraphRecall-Signature"
MAX_SKEW_SECONDS = 300


def sign_payload(secret: str, body: bytes, timestamp: Optional[int] = None) -> str:
    ts = int(timestamp if timestamp is not None else time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secret: str, body: bytes, header: str, now: Optional[int] = None) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        sig = parts["v1"]
    except (KeyError, ValueError):
        return False
    now = int(now if now is not None else time.time())
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return False
    expected = sign_payload(secret, body, ts).split("v1=", 1)[1]
    return hmac.compare_digest(expected, sig)


class Notifier(Protocol):
    async def notify(self, user_id: str, event: str, data: dict[str, Any]) -> None: ...


class NullNotifier:
    async def notify(self, user_id: str, event: str, data: dict[str, Any]) -> None:
        return None


class WebhookNotifier:
    """POSTs signed events to AGENT_BRIDGE_WEBHOOK_URL. Fire-and-forget, never raises."""

    def __init__(self, url: str, secret: str, timeout: float = 5.0):
        self.url = url
        self.secret = secret
        self.timeout = timeout

    async def notify(self, user_id: str, event: str, data: dict[str, Any]) -> None:
        import httpx

        body = json.dumps({"event": event, "user_id": user_id, "data": data,
                           "sent_at": int(time.time())}, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json",
                   SIGNATURE_HEADER: sign_payload(self.secret, body)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(self.url, content=body, headers=headers)
        except Exception as e:  # pragma: no cover - network
            # TODO(agent-bridge): retry with backoff / outbox table if delivery matters.
            logger.warning("agent_bridge: webhook failed", event=event, error=str(e))


def notifier_from_env() -> Notifier:
    # TODO(agent-bridge): per-user webhook URL + secret (users.settings_json) instead of
    # one global env pair. The Grok Bot side needs a reachable inbound URL for this; until
    # then the bot polls list_pending_questions on a routine.
    url = os.environ.get("AGENT_BRIDGE_WEBHOOK_URL")
    secret = os.environ.get("AGENT_BRIDGE_WEBHOOK_SECRET")
    if url and secret:
        return WebhookNotifier(url, secret)
    return NullNotifier()

"""Outbound notifications to the agent (optional).

When a user asks their agent a question, GraphRecall can POST a small signed event so
the agent wakes up immediately instead of waiting for its next poll. The payload never
contains the question text - the agent fetches it over MCP with its own key.

Headers on every delivery:

* ``X-GraphRecall-Event-Id``: unique per event (UUID). It stays the same across retries of
  the same event, so receivers can dedupe redeliveries.
* ``X-GraphRecall-Timestamp``: unix seconds when this attempt was signed.
* ``X-GraphRecall-Signature: t=<ts>,id=<event_id>,v1=<hex>`` where
  ``v1 = HMAC_SHA256(secret, f"{ts}.{event_id}." + body)``.

Receiver checklist (see :func:`verify_webhook` / :class:`ReplayGuard`):

1. Recompute the HMAC with the shared secret and compare in constant time.
2. Reject timestamps more than 5 minutes from now.
3. Reject an ``event_id`` already seen within that window (replay or duplicate retry).
   Keep seen ids at least as long as the skew window, in a shared store if there is
   more than one receiver process.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Mapping, Optional, Protocol

import structlog

logger = structlog.get_logger()

SIGNATURE_HEADER = "X-GraphRecall-Signature"
EVENT_ID_HEADER = "X-GraphRecall-Event-Id"
TIMESTAMP_HEADER = "X-GraphRecall-Timestamp"
MAX_SKEW_SECONDS = 300


def _mac(secret: str, ts: int, event_id: str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{ts}.{event_id}.".encode() + body,
                    hashlib.sha256).hexdigest()


def sign_payload(secret: str, body: bytes, timestamp: Optional[int] = None,
                 event_id: str = "") -> str:
    ts = int(timestamp if timestamp is not None else time.time())
    return f"t={ts},id={event_id},v1={_mac(secret, ts, event_id, body)}"


def _parse(header: str) -> Optional[tuple[int, str, str]]:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        return int(parts["t"]), parts.get("id", ""), parts["v1"]
    except (KeyError, ValueError, AttributeError):
        return None


def verify_signature(secret: str, body: bytes, header: str, now: Optional[int] = None,
                     event_id: Optional[str] = None) -> bool:
    """Signature + timestamp window. If ``event_id`` (from X-GraphRecall-Event-Id) is
    given it must match the signed id."""
    parsed = _parse(header)
    if parsed is None:
        return False
    ts, signed_id, sig = parsed
    if event_id is not None and not hmac.compare_digest(event_id, signed_id):
        return False
    now = int(now if now is not None else time.time())
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return False
    return hmac.compare_digest(_mac(secret, ts, signed_id, body), sig)


class ReplayGuard:
    """Remembers event ids for ``window`` seconds (in-process reference implementation)."""

    def __init__(self, window: int = MAX_SKEW_SECONDS):
        self.window = window
        self._seen: dict[str, float] = {}

    def check_and_remember(self, event_id: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        for k, t in list(self._seen.items()):
            if now - t > self.window:
                del self._seen[k]
        if not event_id or event_id in self._seen:
            return False
        self._seen[event_id] = now
        return True


def verify_webhook(secret: str, body: bytes, headers: Mapping[str, str], guard: ReplayGuard,
                   now: Optional[int] = None) -> bool:
    """Full receiver-side check: signature, timestamp window, and replay (reused id)."""
    h = {k.lower(): v for k, v in headers.items()}
    event_id = h.get(EVENT_ID_HEADER.lower(), "")
    if not verify_signature(secret, body, h.get(SIGNATURE_HEADER.lower(), ""), now=now,
                            event_id=event_id):
        return False
    return guard.check_and_remember(event_id, now=now)


class Notifier(Protocol):
    async def notify(self, user_id: str, event: str, data: dict[str, Any]) -> None: ...


class NullNotifier:
    async def notify(self, user_id: str, event: str, data: dict[str, Any]) -> None:
        return None


class WebhookNotifier:
    """POSTs signed events to AGENT_BRIDGE_WEBHOOK_URL with bounded retry. Never raises.

    Retries on connection errors, timeouts, 429 and 5xx (``max_attempts`` total, with
    exponential backoff); gives up immediately on other 4xx.
    """

    def __init__(self, url: str, secret: str, timeout: float = 5.0, max_attempts: int = 3,
                 backoff_seconds: float = 0.5, transport: Any = None):
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.backoff = backoff_seconds
        self.transport = transport  # httpx transport override (tests)
        self.last_attempts = 0

    async def notify(self, user_id: str, event: str, data: dict[str, Any]) -> bool:
        import httpx

        event_id = str(uuid.uuid4())  # same id across retries of this event
        body = json.dumps({"id": event_id, "event": event, "user_id": user_id, "data": data,
                           "sent_at": int(time.time())}, separators=(",", ":")).encode()
        self.last_attempts = 0
        self.last_event_id = event_id
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            for attempt in range(1, self.max_attempts + 1):
                self.last_attempts = attempt
                # Re-sign each attempt so the timestamp stays inside the replay window.
                ts = int(time.time())
                headers = {"Content-Type": "application/json",
                           EVENT_ID_HEADER: event_id,
                           TIMESTAMP_HEADER: str(ts),
                           SIGNATURE_HEADER: sign_payload(self.secret, body, ts, event_id)}
                try:
                    resp = await client.post(self.url, content=body, headers=headers)
                    if resp.status_code < 300:
                        return True
                    if resp.status_code < 500 and resp.status_code != 429:
                        logger.warning("agent_bridge: webhook rejected", webhook_event=event,
                                       status=resp.status_code)
                        return False
                except Exception as e:  # network error / timeout -> retry
                    logger.warning("agent_bridge: webhook error", webhook_event=event, error=str(e),
                                   attempt=attempt)
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
        # TODO(agent-bridge): durable outbox table if delivery must survive restarts.
        logger.warning("agent_bridge: webhook gave up", webhook_event=event, attempts=self.max_attempts)
        return False


_background_tasks: set[asyncio.Task] = set()


def dispatch_in_background(notifier: Notifier, user_id: str, event: str,
                           data: dict[str, Any]) -> Optional[asyncio.Task]:
    """Fire-and-forget: schedule ``notifier.notify`` without awaiting it. Keeps a strong
    reference so the task is not garbage-collected mid-flight."""
    if isinstance(notifier, NullNotifier):
        return None

    async def _run() -> None:
        try:
            await notifier.notify(user_id, event, data)
        except Exception as e:  # pragma: no cover - notifiers should not raise
            logger.warning("agent_bridge: notifier crashed", webhook_event=event, error=str(e))

    task = asyncio.get_running_loop().create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def notifier_from_env() -> Notifier:
    # TODO(agent-bridge): per-user webhook URL + secret (users.settings_json) instead of
    # one global env pair. The Grok Bot side needs a reachable inbound URL for this; until
    # then the bot polls list_pending_questions on a routine.
    url = os.environ.get("AGENT_BRIDGE_WEBHOOK_URL")
    secret = os.environ.get("AGENT_BRIDGE_WEBHOOK_SECRET")
    if url and secret:
        return WebhookNotifier(url, secret)
    return NullNotifier()

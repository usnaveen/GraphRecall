"""MCP OAuth 2.1 Authorization Server + Dynamic Client Registration + Protected Resource Metadata.

Implements the MCP Authorization Specification so remote web connectors (claude.ai Custom
Connectors, ChatGPT MCP Connectors) and OAuth-capable desktop clients can connect directly
without manually pasting ``Bearer grk_...`` headers:

* RFC 9728 Protected Resource Metadata: ``GET /.well-known/oauth-protected-resource``
  (plus path-scoped ``GET /.well-known/oauth-protected-resource/mcp/agent``)
* RFC 8414 Authorization Server Metadata: ``GET /.well-known/oauth-authorization-server``
* RFC 7591 Dynamic Client Registration: ``POST /oauth/register``
* OAuth 2.1 Authorization Code + PKCE (``S256`` required): ``GET /oauth/authorize``,
  ``POST /oauth/authorize/approve``, ``POST /oauth/token``, ``POST /oauth/revoke``.

Every issued access token is a standard ``grk_<prefix>_<secret>`` key created via
``BridgeRepository.create_key`` so it appears immediately in the user's iOS Agent Keys
list, respects per-key rate limits and audit logs, and can be revoked in one tap.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.agent_bridge.keys import (
    ALL_SCOPES,
    DEFAULT_SCOPES,
    InvalidScopeError,
    hash_key,
    parse_key_prefix,
    validate_scopes,
)
from backend.agent_bridge.tools import BridgeServices

CODE_TTL = timedelta(minutes=10)
ACCESS_TOKEN_DAYS = 30
REFRESH_TOKEN_DAYS = 90
ACCESS_TOKEN_EXPIRES_IN = ACCESS_TOKEN_DAYS * 86400

router = APIRouter(tags=["MCP OAuth 2.1"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def base_url_from_request(request: Request) -> str:
    """Public origin behind TLS reverse proxies (Caddy / Cloudflare / Render)."""
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme or "http").split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    host = host.split(",")[0].strip()
    return f"{proto}://{host}"


def base_url_from_asgi_scope(scope: dict) -> str:
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    proto = headers.get("x-forwarded-proto", scope.get("scheme", "http")).split(",")[0].strip()
    host = (headers.get("x-forwarded-host") or headers.get("host") or "127.0.0.1").split(",")[0].strip()
    return f"{proto}://{host}"


def is_allowed_redirect_uri(uri: str) -> bool:
    """OAuth 2.1 redirect URI rules: HTTPS anywhere, or HTTP strictly on loopback."""
    if not uri or len(uri) > 2048:
        return False
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.fragment:  # RFC 6749 §3.1.2: redirect URI MUST NOT include a fragment
        return False
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https" and host:
        return True
    if scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return True
    return False


def verify_pkce_s256(code_verifier: str, expected_challenge: str) -> bool:
    """RFC 7636 S256: BASE64URL-ENCODE(SHA256(ASCII(code_verifier))) == code_challenge."""
    if not code_verifier or not (43 <= len(code_verifier) <= 128):
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii", errors="strict")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed, expected_challenge)


def _csrf_secret() -> bytes:
    secret = (
        os.environ.get("AGENT_KEY_PEPPER")
        or os.environ.get("JWT_SECRET_KEY")
        or "graphrecall-dev-oauth-csrf"
    )
    return secret.encode("utf-8")


def sign_consent_ticket(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
    sig = hmac.new(_csrf_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_consent_ticket(ticket: str, max_age_seconds: int = 900) -> Optional[dict[str, Any]]:
    if not ticket or "." not in ticket:
        return None
    body, sig = ticket.rsplit(".", 1)
    expected = hmac.new(_csrf_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        raw = base64.urlsafe_b64decode(body.encode("ascii") + b"===")
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    issued_at = int(data.get("iat", 0))
    if abs(int(_now().timestamp()) - issued_at) > max_age_seconds:
        return None
    return data


def _append_query(uri: str, params: dict[str, str]) -> str:
    parsed = urlparse(uri)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None and v != ""})
    return urlunparse(parsed._replace(query=urlencode(existing)))


# ---------------------------------------------------------------------------
# Persistence abstraction (Postgres in production, in-memory in unit tests)
# ---------------------------------------------------------------------------


class OAuthStore(ABC):
    @abstractmethod
    async def register_client(
        self,
        client_name: str,
        redirect_uris: list[str],
        grant_types: list[str],
        response_types: list[str],
        token_endpoint_auth_method: str,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_client(self, client_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    async def store_code(
        self,
        code_hash: str,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str,
        resource: Optional[str],
        expires_at: datetime,
    ) -> None: ...

    @abstractmethod
    async def consume_code(self, code_hash: str) -> Optional[dict[str, Any]]:
        """Atomically mark code used and return it if unexpired and unused, else None."""

    @abstractmethod
    async def store_refresh_token(
        self,
        token_hash: str,
        key_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None: ...

    @abstractmethod
    async def consume_refresh_token(self, token_hash: str) -> Optional[dict[str, Any]]:
        """Atomically revoke refresh token for rotation and return row if active."""

    @abstractmethod
    async def revoke_refresh_by_hash(self, token_hash: str) -> Optional[dict[str, Any]]: ...


class InMemoryOAuthStore(OAuthStore):
    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, dict[str, Any]] = {}

    async def register_client(
        self,
        client_name: str,
        redirect_uris: list[str],
        grant_types: list[str],
        response_types: list[str],
        token_endpoint_auth_method: str,
    ) -> dict[str, Any]:
        cid = f"grc_{secrets.token_hex(12)}"
        row = {
            "client_id": cid,
            "client_name": client_name,
            "redirect_uris": list(redirect_uris),
            "grant_types": list(grant_types),
            "response_types": list(response_types),
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "client_id_issued_at": int(_now().timestamp()),
        }
        self.clients[cid] = row
        return dict(row)

    async def get_client(self, client_id: str) -> Optional[dict[str, Any]]:
        row = self.clients.get(client_id)
        return dict(row) if row else None

    async def store_code(
        self,
        code_hash: str,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str,
        resource: Optional[str],
        expires_at: datetime,
    ) -> None:
        self.codes[code_hash] = {
            "code_hash": code_hash,
            "client_id": client_id,
            "user_id": user_id,
            "redirect_uri": redirect_uri,
            "scopes": list(scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "resource": resource,
            "expires_at": expires_at,
            "used_at": None,
        }

    async def consume_code(self, code_hash: str) -> Optional[dict[str, Any]]:
        row = self.codes.get(code_hash)
        if not row or row["used_at"] is not None or row["expires_at"] <= _now():
            return None
        row["used_at"] = _now()
        return dict(row)

    async def store_refresh_token(
        self,
        token_hash: str,
        key_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        self.refresh_tokens[token_hash] = {
            "token_hash": token_hash,
            "key_id": key_id,
            "client_id": client_id,
            "user_id": user_id,
            "scopes": list(scopes),
            "expires_at": expires_at,
            "revoked_at": None,
        }

    async def consume_refresh_token(self, token_hash: str) -> Optional[dict[str, Any]]:
        row = self.refresh_tokens.get(token_hash)
        if not row or row["revoked_at"] is not None or row["expires_at"] <= _now():
            return None
        row["revoked_at"] = _now()
        return dict(row)

    async def revoke_refresh_by_hash(self, token_hash: str) -> Optional[dict[str, Any]]:
        row = self.refresh_tokens.get(token_hash)
        if not row:
            return None
        row["revoked_at"] = row["revoked_at"] or _now()
        return dict(row)


class PostgresOAuthStore(OAuthStore):
    def __init__(self, pg_client: Any) -> None:
        self.pg = pg_client

    async def register_client(
        self,
        client_name: str,
        redirect_uris: list[str],
        grant_types: list[str],
        response_types: list[str],
        token_endpoint_auth_method: str,
    ) -> dict[str, Any]:
        cid = f"grc_{secrets.token_hex(12)}"
        rows = await self.pg.execute_insert(
            """
            INSERT INTO agent_oauth_clients
                (client_id, client_name, redirect_uris, grant_types, response_types, token_endpoint_auth_method)
            VALUES
                (:client_id, :client_name, :redirect_uris, :grant_types, :response_types, :auth_method)
            RETURNING client_id, client_name, redirect_uris, grant_types, response_types,
                      token_endpoint_auth_method, created_at
            """,
            {
                "client_id": cid,
                "client_name": client_name,
                "redirect_uris": list(redirect_uris),
                "grant_types": list(grant_types),
                "response_types": list(response_types),
                "auth_method": token_endpoint_auth_method,
            },
        )
        row = dict(rows[0])
        created = row.pop("created_at", None)
        row["client_id_issued_at"] = int(created.timestamp()) if hasattr(created, "timestamp") else int(_now().timestamp())
        return row

    async def get_client(self, client_id: str) -> Optional[dict[str, Any]]:
        rows = await self.pg.execute_query(
            """
            SELECT client_id, client_name, redirect_uris, grant_types, response_types, token_endpoint_auth_method
            FROM agent_oauth_clients
            WHERE client_id = :client_id
            """,
            {"client_id": client_id},
        )
        return dict(rows[0]) if rows else None

    async def store_code(
        self,
        code_hash: str,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str,
        resource: Optional[str],
        expires_at: datetime,
    ) -> None:
        await self.pg.execute_update(
            """
            INSERT INTO agent_oauth_codes
                (code_hash, client_id, user_id, redirect_uri, scopes, code_challenge,
                 code_challenge_method, resource, expires_at)
            VALUES
                (:code_hash, :client_id, CAST(:user_id AS uuid), :redirect_uri, :scopes,
                 :code_challenge, :code_challenge_method, :resource, :expires_at)
            """,
            {
                "code_hash": code_hash,
                "client_id": client_id,
                "user_id": user_id,
                "redirect_uri": redirect_uri,
                "scopes": list(scopes),
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "resource": resource,
                "expires_at": expires_at,
            },
        )

    async def consume_code(self, code_hash: str) -> Optional[dict[str, Any]]:
        rows = await self.pg.execute_insert(
            """
            UPDATE agent_oauth_codes
            SET used_at = CURRENT_TIMESTAMP
            WHERE code_hash = :code_hash
              AND used_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            RETURNING code_hash, client_id, user_id::text AS user_id, redirect_uri, scopes,
                      code_challenge, code_challenge_method, resource
            """,
            {"code_hash": code_hash},
        )
        return dict(rows[0]) if rows else None

    async def store_refresh_token(
        self,
        token_hash: str,
        key_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        await self.pg.execute_update(
            """
            INSERT INTO agent_oauth_refresh_tokens
                (token_hash, key_id, client_id, user_id, scopes, expires_at)
            VALUES
                (:token_hash, CAST(:key_id AS uuid), :client_id, CAST(:user_id AS uuid), :scopes, :expires_at)
            """,
            {
                "token_hash": token_hash,
                "key_id": key_id,
                "client_id": client_id,
                "user_id": user_id,
                "scopes": list(scopes),
                "expires_at": expires_at,
            },
        )

    async def consume_refresh_token(self, token_hash: str) -> Optional[dict[str, Any]]:
        rows = await self.pg.execute_insert(
            """
            UPDATE agent_oauth_refresh_tokens
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE token_hash = :token_hash
              AND revoked_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            RETURNING token_hash, key_id::text AS key_id, client_id, user_id::text AS user_id, scopes
            """,
            {"token_hash": token_hash},
        )
        return dict(rows[0]) if rows else None

    async def revoke_refresh_by_hash(self, token_hash: str) -> Optional[dict[str, Any]]:
        rows = await self.pg.execute_insert(
            """
            UPDATE agent_oauth_refresh_tokens
            SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
            WHERE token_hash = :token_hash
            RETURNING key_id::text AS key_id, user_id::text AS user_id
            """,
            {"token_hash": token_hash},
        )
        return dict(rows[0]) if rows else None


async def get_oauth_store() -> OAuthStore:
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()
    return PostgresOAuthStore(pg)


async def get_oauth_bridge_services() -> BridgeServices:
    from backend.agent_bridge.mcp_app import default_services

    return await default_services()


async def resolve_authorizing_user(request: Request, bearer_token: str = "") -> Optional[dict[str, Any]]:
    """Authenticate the GraphRecall user approving the OAuth consent form.

    Accepts a GraphRecall session JWT / Google token supplied via Authorization header,
    form field ``session_token`` (pasted or injected by web login), or ``gr_session`` cookie.
    """
    from fastapi.security import HTTPAuthorizationCredentials
    from backend.auth.middleware import get_current_user

    raw = bearer_token.strip()
    if not raw:
        auth_h = request.headers.get("authorization", "")
        if auth_h.lower().startswith("bearer "):
            raw = auth_h[7:].strip()
    if not raw:
        raw = (request.cookies.get("gr_session") or "").strip()
    if not raw:
        return None
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw)
    try:
        return await get_current_user(request=request, credentials=creds)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Metadata Discovery (RFC 9728 + RFC 8414)
# ---------------------------------------------------------------------------


def _protected_resource_doc(base: str) -> dict[str, Any]:
    return {
        "resource": f"{base}/mcp/agent",
        "authorization_servers": [base],
        "scopes_supported": sorted(ALL_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "GraphRecall Personal Knowledge Snapshot",
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp/agent")
async def oauth_protected_resource_metadata(request: Request):
    return _protected_resource_doc(base_url_from_request(request))


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
async def oauth_authorization_server_metadata(request: Request):
    base = base_url_from_request(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "scopes_supported": sorted(ALL_SCOPES),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "service_documentation": f"{base}/docs",
    }


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------


class ClientRegistrationRequest(BaseModel):
    client_name: str = Field("MCP Client", min_length=1, max_length=200)
    redirect_uris: list[str] = Field(..., min_length=1, max_length=10)
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = Field("none", max_length=32)


@router.post("/oauth/register", status_code=201)
async def register_oauth_client(
    body: ClientRegistrationRequest,
    store: OAuthStore = Depends(get_oauth_store),
):
    bad = [u for u in body.redirect_uris if not is_allowed_redirect_uri(u)]
    if bad:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_redirect_uri",
                "error_description": "Redirect URIs must use https:// (or http://localhost for local tools) with no fragment.",
            },
        )
    allowed_grants = {"authorization_code", "refresh_token"}
    grants = [g for g in body.grant_types if g in allowed_grants] or ["authorization_code"]
    auth_method = body.token_endpoint_auth_method if body.token_endpoint_auth_method in {"none", "client_secret_post"} else "none"
    client = await store.register_client(
        client_name=body.client_name.strip(),
        redirect_uris=[u.strip() for u in body.redirect_uris],
        grant_types=grants,
        response_types=["code"],
        token_endpoint_auth_method=auth_method,
    )
    return client


# ---------------------------------------------------------------------------
# Authorization Endpoint + Liquid-Glass Consent UI (OAuth 2.1 + PKCE S256)
# ---------------------------------------------------------------------------


def _parse_requested_scopes(scope_param: str) -> list[str]:
    if not scope_param or not scope_param.strip():
        return list(DEFAULT_SCOPES)
    parts = [p for p in scope_param.replace(",", " ").split() if p in ALL_SCOPES]
    return sorted(set(parts)) if parts else list(DEFAULT_SCOPES)


def _render_consent_html(
    *,
    client_name: str,
    redirect_host: str,
    requested_scopes: list[str],
    ticket: str,
    needs_token_input: bool,
    error_banner: str = "",
) -> str:
    esc_client = html.escape(client_name)
    esc_host = html.escape(redirect_host)
    esc_ticket = html.escape(ticket)
    err_html = (
        f'<div class="err">{html.escape(error_banner)}</div>'
        if error_banner
        else ""
    )
    scope_descriptions = {
        "read:knowledge": ("Read Knowledge Snapshot", "Check which concepts are strong, shaky, seen, or new—never raw note bodies or resume text."),
        "write:feed": ("Propose Feed Items", "Stage reading and review cards into your Agent Inbox for your approval."),
        "bridge:answer": ("Answer Delegated Questions", "Claim and answer questions you explicitly hand off from the Assistant."),
        "write:ingest": ("Add to Your Knowledge Graph", "Import links and learning-session notes straight into your graph, without an approval step."),
    }
    scope_rows = []
    for sc in sorted(ALL_SCOPES):
        title, desc = scope_descriptions[sc]
        checked = "checked" if sc in requested_scopes else ""
        scope_rows.append(
            f"""
            <label class="scope">
              <input type="checkbox" name="scopes" value="{html.escape(sc)}" {checked}>
              <div>
                <div class="scope-title">{html.escape(title)} <code>{html.escape(sc)}</code></div>
                <div class="scope-desc">{html.escape(desc)}</div>
              </div>
            </label>
            """
        )
    token_field = (
        """
        <label class="field">
          <span>GraphRecall Session Token (from iOS Profile → Agent Keys → Web Connect)</span>
          <input type="password" name="session_token" placeholder="Paste your GraphRecall session token" required autocomplete="off">
        </label>
        """
        if needs_token_input
        else '<input type="hidden" name="session_token" value="">'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect {esc_client} · GraphRecall</title>
  <style>
    :root {{ color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 20px;
      background: radial-gradient(circle at 20% 10%, rgba(182,255,46,0.12), transparent 55%), #07070A;
      color: #fff; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
    }}
    .card {{
      width: 100%; max-width: 460px; padding: 28px; border-radius: 26px;
      background: rgba(26, 26, 34, 0.78); backdrop-filter: blur(28px);
      border: 1px solid rgba(255,255,255,0.14);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), 0 24px 64px rgba(0,0,0,0.65);
    }}
    .badge {{
      display: inline-block; padding: 4px 11px; border-radius: 999px; font-size: 12px; font-weight: 700;
      background: rgba(182,255,46,0.15); color: #B6FF2E; border: 1px solid rgba(182,255,46,0.38);
      margin-bottom: 14px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 22px; letter-spacing: -0.02em; }}
    p.sub {{ margin: 0 0 20px; font-size: 14px; color: rgba(255,255,255,0.66); line-height: 1.5; }}
    .scope {{
      display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; margin-bottom: 10px;
      border-radius: 14px; background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.1);
      cursor: pointer;
    }}
    .scope input {{ margin-top: 3px; accent-color: #B6FF2E; }}
    .scope-title {{ font-size: 14px; font-weight: 600; margin-bottom: 3px; }}
    .scope-title code {{ font-size: 11px; color: #2EFFE6; background: rgba(46,255,230,0.12); padding: 2px 6px; border-radius: 6px; }}
    .scope-desc {{ font-size: 12.5px; color: rgba(255,255,255,0.6); line-height: 1.45; }}
    .field {{ display: block; margin: 16px 0; }}
    .field span {{ display: block; font-size: 12px; color: rgba(255,255,255,0.68); margin-bottom: 6px; }}
    .field input {{
      width: 100%; padding: 11px 13px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.18);
      background: #0D0D13; color: #fff; font-size: 14px;
    }}
    .err {{
      padding: 10px 12px; border-radius: 12px; margin-bottom: 14px; font-size: 13px;
      background: rgba(248,113,113,0.16); border: 1px solid rgba(248,113,113,0.4); color: #FCA5A5;
    }}
    .actions {{ display: flex; gap: 10px; margin-top: 20px; }}
    button {{
      flex: 1; padding: 12px 16px; border-radius: 999px; font-size: 14px; font-weight: 700; cursor: pointer; border: 0;
    }}
    .btn-allow {{ background: linear-gradient(135deg, #B6FF2E, #9EF01A); color: #07070A; }}
    .btn-deny {{ background: rgba(255,255,255,0.08); color: #fff; border: 1px solid rgba(255,255,255,0.14); }}
    .fine {{ margin: 14px 0 0; font-size: 11.5px; color: rgba(255,255,255,0.44); text-align: center; }}
  </style>
</head>
<body>
  <form class="card" method="post" action="/oauth/authorize/approve">
    <span class="badge">GraphRecall Super-Context · OAuth 2.1</span>
    <h1>Authorize {esc_client}</h1>
    <p class="sub">Redirects to <strong>{esc_host}</strong> after approval. You can revoke this connection any time in the GraphRecall iOS app.</p>
    {err_html}
    <input type="hidden" name="ticket" value="{esc_ticket}">
    {"".join(scope_rows)}
    {token_field}
    <div class="actions">
      <button class="btn-deny" type="submit" name="decision" value="deny" formnovalidate>Cancel</button>
      <button class="btn-allow" type="submit" name="decision" value="approve">Connect</button>
    </div>
    <p class="fine">Note bodies and resume PDFs are never shared over MCP.</p>
  </form>
</body>
</html>"""


def _csp_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https: http://localhost:* http://127.0.0.1:*; frame-ancestors 'none'",
        "X-Frame-Options": "DENY",
        "Cache-Control": "no-store",
    }


@router.get("/oauth/authorize")
async def oauth_authorize(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "code",
    scope: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    resource: str = "",
    store: OAuthStore = Depends(get_oauth_store),
):
    client = await store.get_client(client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client_id; register via POST /oauth/register first")
    if redirect_uri not in (client.get("redirect_uris") or []):
        raise HTTPException(status_code=400, detail="redirect_uri does not match registered client")
    if response_type != "code":
        return RedirectResponse(_append_query(redirect_uri, {"error": "unsupported_response_type", "state": state}), status_code=302)
    if not code_challenge or code_challenge_method.upper() != "S256":
        return RedirectResponse(
            _append_query(redirect_uri, {"error": "invalid_request", "error_description": "PKCE S256 code_challenge required", "state": state}),
            status_code=302,
        )

    requested_scopes = _parse_requested_scopes(scope)
    existing_user = await resolve_authorizing_user(request)
    ticket = sign_consent_ticket(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": resource,
            "iat": int(_now().timestamp()),
            "nonce": secrets.token_hex(8),
        }
    )
    redirect_host = urlparse(redirect_uri).hostname or redirect_uri
    body = _render_consent_html(
        client_name=client["client_name"],
        redirect_host=redirect_host,
        requested_scopes=requested_scopes,
        ticket=ticket,
        needs_token_input=(existing_user is None),
    )
    return HTMLResponse(content=body, status_code=200, headers=_csp_headers())


@router.post("/oauth/authorize/approve")
async def oauth_authorize_approve(
    request: Request,
    store: OAuthStore = Depends(get_oauth_store),
):
    form = await request.form()
    ticket_str = str(form.get("ticket") or "")
    ticket = verify_consent_ticket(ticket_str)
    if not ticket:
        raise HTTPException(status_code=400, detail="Expired or invalid authorization session")

    client = await store.get_client(ticket["client_id"])
    if not client or ticket["redirect_uri"] not in (client.get("redirect_uris") or []):
        raise HTTPException(status_code=400, detail="Invalid OAuth client state")

    decision = str(form.get("decision") or "deny")
    if decision != "approve":
        return RedirectResponse(
            _append_query(ticket["redirect_uri"], {"error": "access_denied", "state": ticket.get("state", "")}),
            status_code=302,
        )

    session_token = str(form.get("session_token") or "").strip()
    user = await resolve_authorizing_user(request, bearer_token=session_token)
    raw_scopes = form.getlist("scopes") if hasattr(form, "getlist") else []
    try:
        scopes = validate_scopes([str(s) for s in raw_scopes] or list(DEFAULT_SCOPES))
    except InvalidScopeError as exc:
        scopes = list(DEFAULT_SCOPES)
        user = None
        err_msg = str(exc)
    else:
        err_msg = "Sign in with a valid GraphRecall session token to authorize this connector."

    if user is None:
        html_body = _render_consent_html(
            client_name=client["client_name"],
            redirect_host=urlparse(ticket["redirect_uri"]).hostname or ticket["redirect_uri"],
            requested_scopes=scopes,
            ticket=ticket_str,
            needs_token_input=True,
            error_banner=err_msg,
        )
        return HTMLResponse(content=html_body, status_code=401, headers=_csp_headers())

    raw_code = f"grac_{secrets.token_urlsafe(32)}"
    await store.store_code(
        code_hash=hash_key(raw_code),
        client_id=ticket["client_id"],
        user_id=str(user["id"]),
        redirect_uri=ticket["redirect_uri"],
        scopes=scopes,
        code_challenge=ticket["code_challenge"],
        code_challenge_method="S256",
        resource=ticket.get("resource") or None,
        expires_at=_now() + CODE_TTL,
    )
    return RedirectResponse(
        _append_query(ticket["redirect_uri"], {"code": raw_code, "state": ticket.get("state", "")}),
        status_code=302,
    )


# ---------------------------------------------------------------------------
# Token & Revocation Endpoints (RFC 6749 + RFC 7636 + RFC 7009)
# ---------------------------------------------------------------------------


async def _parse_token_params(request: Request) -> dict[str, str]:
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            body = await request.json()
            return {k: str(v) for k, v in body.items() if v is not None}
        except Exception:
            return {}
    form = await request.form()
    return {k: str(v) for k, v in form.items() if v is not None}


def _oauth_error(code: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "error_description": description},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/oauth/token")
async def oauth_token(
    request: Request,
    store: OAuthStore = Depends(get_oauth_store),
    svc: BridgeServices = Depends(get_oauth_bridge_services),
):
    params = await _parse_token_params(request)
    grant_type = params.get("grant_type", "")

    if grant_type == "authorization_code":
        code = params.get("code", "").strip()
        code_verifier = params.get("code_verifier", "").strip()
        client_id = params.get("client_id", "").strip()
        redirect_uri = params.get("redirect_uri", "").strip()
        if not code or not code_verifier:
            return _oauth_error("invalid_request", "code and code_verifier are required")

        consumed = await store.consume_code(hash_key(code))
        if not consumed:
            return _oauth_error("invalid_grant", "Authorization code is invalid, expired, or already used")
        if client_id and client_id != consumed["client_id"]:
            return _oauth_error("invalid_grant", "client_id mismatch")
        if redirect_uri and redirect_uri != consumed["redirect_uri"]:
            return _oauth_error("invalid_grant", "redirect_uri mismatch")
        if not verify_pkce_s256(code_verifier, consumed["code_challenge"]):
            return _oauth_error("invalid_grant", "PKCE code_verifier verification failed")

        client = await store.get_client(consumed["client_id"])
        cname = (client["client_name"] if client else "MCP Connector")[:72]
        scopes = list(consumed["scopes"])
        user_id = str(consumed["user_id"])

        key_row, access_token = await svc.repo.create_key(
            user_id=user_id,
            name=f"OAuth · {cname}",
            scopes=scopes,
            expires_at=_now() + timedelta(days=ACCESS_TOKEN_DAYS),
        )
        refresh_token = f"grr_{secrets.token_urlsafe(36)}"
        await store.store_refresh_token(
            token_hash=hash_key(refresh_token),
            key_id=str(key_row["id"]),
            client_id=consumed["client_id"],
            user_id=user_id,
            scopes=scopes,
            expires_at=_now() + timedelta(days=REFRESH_TOKEN_DAYS),
        )
        try:
            await svc.repo.audit(
                user_id,
                "oauth_token_issued",
                actor="user",
                key_id=str(key_row["id"]),
                target_id=str(key_row["id"]),
                details={"client_id": consumed["client_id"], "scopes": scopes},
            )
        except Exception:
            pass
        return JSONResponse(
            content={
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": ACCESS_TOKEN_EXPIRES_IN,
                "refresh_token": refresh_token,
                "scope": " ".join(scopes),
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    if grant_type == "refresh_token":
        raw_rt = params.get("refresh_token", "").strip()
        client_id = params.get("client_id", "").strip()
        if not raw_rt:
            return _oauth_error("invalid_request", "refresh_token is required")
        old_rt = await store.consume_refresh_token(hash_key(raw_rt))
        if not old_rt:
            return _oauth_error("invalid_grant", "Refresh token is invalid, expired, or revoked")
        if client_id and client_id != old_rt["client_id"]:
            return _oauth_error("invalid_grant", "client_id mismatch")

        user_id = str(old_rt["user_id"])
        # Revoke previous access key on rotation
        await svc.repo.revoke_key(user_id, str(old_rt["key_id"]))

        client = await store.get_client(old_rt["client_id"])
        cname = (client["client_name"] if client else "MCP Connector")[:72]
        scopes = list(old_rt["scopes"])
        key_row, access_token = await svc.repo.create_key(
            user_id=user_id,
            name=f"OAuth · {cname}",
            scopes=scopes,
            expires_at=_now() + timedelta(days=ACCESS_TOKEN_DAYS),
        )
        new_rt = f"grr_{secrets.token_urlsafe(36)}"
        await store.store_refresh_token(
            token_hash=hash_key(new_rt),
            key_id=str(key_row["id"]),
            client_id=old_rt["client_id"],
            user_id=user_id,
            scopes=scopes,
            expires_at=_now() + timedelta(days=REFRESH_TOKEN_DAYS),
        )
        return JSONResponse(
            content={
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": ACCESS_TOKEN_EXPIRES_IN,
                "refresh_token": new_rt,
                "scope": " ".join(scopes),
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    return _oauth_error("unsupported_grant_type", "Supported grant_types: authorization_code, refresh_token")


@router.post("/oauth/revoke")
async def oauth_revoke(
    request: Request,
    store: OAuthStore = Depends(get_oauth_store),
    svc: BridgeServices = Depends(get_oauth_bridge_services),
):
    params = await _parse_token_params(request)
    token = params.get("token", "").strip()
    if not token:
        return Response(status_code=200)

    if token.startswith("grr_"):
        revoked = await store.revoke_refresh_by_hash(hash_key(token))
        if revoked:
            await svc.repo.revoke_key(str(revoked["user_id"]), str(revoked["key_id"]))
        return Response(status_code=200)

    prefix = parse_key_prefix(token)
    if prefix:
        row = await svc.repo.get_key_by_prefix(prefix)
        if row:
            await svc.repo.revoke_key(str(row["user_id"]), str(row["id"]))
    return Response(status_code=200)

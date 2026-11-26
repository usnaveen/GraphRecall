-- Migration 034: MCP OAuth 2.1 + PKCE (S256) + Dynamic Client Registration
-- Enables remote MCP connectors (claude.ai, ChatGPT) to authenticate directly
-- while minting scoped keys backed by agent_api_keys for unified iOS visibility/revocation.

CREATE TABLE IF NOT EXISTS agent_oauth_clients (
    client_id VARCHAR(64) PRIMARY KEY,
    client_name VARCHAR(200) NOT NULL DEFAULT 'MCP Connector',
    redirect_uris TEXT[] NOT NULL,
    grant_types TEXT[] NOT NULL DEFAULT ARRAY['authorization_code', 'refresh_token'],
    response_types TEXT[] NOT NULL DEFAULT ARRAY['code'],
    token_endpoint_auth_method VARCHAR(32) NOT NULL DEFAULT 'none',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_oauth_codes (
    code_hash CHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES agent_oauth_clients(client_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri VARCHAR(2048) NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    code_challenge VARCHAR(128) NOT NULL,
    code_challenge_method VARCHAR(16) NOT NULL DEFAULT 'S256',
    resource VARCHAR(2048),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_oauth_codes_user ON agent_oauth_codes(user_id);

CREATE TABLE IF NOT EXISTS agent_oauth_refresh_tokens (
    token_hash CHAR(64) PRIMARY KEY,
    key_id UUID NOT NULL REFERENCES agent_api_keys(id) ON DELETE CASCADE,
    client_id VARCHAR(64) NOT NULL REFERENCES agent_oauth_clients(client_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_oauth_refresh_user ON agent_oauth_refresh_tokens(user_id);

"""Versioned migrations against a real PostgreSQL (skipped when none is reachable).

Each test creates its own throwaway database (graphrecall_migtest_<random>) and drops it after.
Set MIGTEST_PG_ADMIN_URL to point at a server; the default is the local Homebrew Postgres.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio

ADMIN = os.getenv("MIGTEST_PG_ADMIN_URL", f"postgresql+asyncpg://{os.getenv('USER', 'postgres')}@localhost:5432/postgres")


async def _admin(sql: str):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(ADMIN, isolation_level="AUTOCOMMIT")
    try:
        async with eng.connect() as c:
            await c.execute(text(sql))
    finally:
        await eng.dispose()


@pytest.fixture
async def scratch_db(monkeypatch):
    name = f"graphrecall_migtest_{uuid.uuid4().hex[:8]}"
    try:
        await _admin(f'CREATE DATABASE "{name}"')
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Postgres for migration tests: {e}")
    from backend.db.postgres_client import PostgresClient, PostgresSettings

    url = ADMIN.rsplit("/", 1)[0] + f"/{name}"
    client = PostgresClient(PostgresSettings(database_url=url.replace("postgresql+asyncpg://", "postgresql://")))
    await client.initialize()
    yield client, name
    await client.close()
    await _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def test_fresh_database_migrates_once(scratch_db):
    from backend.db import migrate as M

    pg, _ = scratch_db
    applied = await M.migrate(pg)
    assert applied[:2] == ["000a_legacy_columns", "000b_init"]
    assert len(applied) == len(M.discover())
    assert await M.migrate(pg) == []                      # second run is a no-op
    assert await M.pending(pg) == []
    rows = await pg.execute_query("SELECT to_regclass('public.notes') AS t, to_regclass('public.chunks') AS c")
    assert rows[0]["t"] and rows[0]["c"]


async def test_changed_migration_is_refused(scratch_db, tmp_path, monkeypatch):
    from backend.db import migrate as M

    pg, _ = scratch_db
    await M.migrate(pg)
    await pg.execute_update("UPDATE schema_migrations SET checksum = 'stale' WHERE version = '000b_init'")
    with pytest.raises(M.MigrationError, match="changed after it was applied"):
        await M.pending(pg)


async def test_production_refuses_to_start_when_behind(scratch_db, monkeypatch):
    from backend.db import migrate as M

    pg, _ = scratch_db
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(M.MigrationError, match="run `python -m backend.db.migrate`"):
        await M.ensure_schema(pg)
    monkeypatch.setenv("ENVIRONMENT", "development")
    await M.ensure_schema(pg)                              # development auto-migrates
    monkeypatch.setenv("ENVIRONMENT", "production")
    await M.ensure_schema(pg)                              # now up to date: starts


def test_production_settings_refuse_debug_bypass(monkeypatch):
    from backend.config import production as P

    monkeypatch.setenv("ENVIRONMENT", "production")
    for k in ("DATABASE_URL", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "GOOGLE_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "ios-client,web-client")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("SESSION_SECRET", "k" * 48)
    monkeypatch.delenv("APPLE_CLIENT_IDS", raising=False)
    monkeypatch.delenv("FEED_DEMO_CARDS", raising=False)
    monkeypatch.delenv("CHECKPOINTER", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    assert P.problems() == []
    monkeypatch.setenv("DEBUG", "true")
    assert any("test-token" in p for p in P.problems())
    monkeypatch.setenv("CORS_ORIGINS", "*")
    assert any("CORS_ORIGINS" in p for p in P.problems())
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("SESSION_SECRET", "short")
    assert any("SESSION_SECRET" in p for p in P.problems())
    monkeypatch.setenv("SESSION_SECRET", "k" * 48)
    monkeypatch.setenv("APPLE_CLIENT_IDS", "com.usnaveen.graphrecall")
    assert any("5.1.1(v)" in p for p in P.problems())  # Apple on without the revocation key
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert P.problems() == []                              # development is never blocked


def test_cloud_postgres_tls_verifies_certificates(monkeypatch):
    import ssl

    from backend.db.postgres_client import _tls_connect_args

    url, args = _tls_connect_args("postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/db?sslmode=require&application_name=gr")
    assert "sslmode" not in url and "application_name=gr" in url         # asyncpg rejects sslmode
    assert args["ssl"].verify_mode == ssl.CERT_REQUIRED and args["ssl"].check_hostname
    assert _tls_connect_args("postgresql+asyncpg://me@localhost:5432/graphrecall")[1] == {}   # local: no TLS
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PG_SSL_INSECURE", "1")
    with pytest.raises(RuntimeError):
        _tls_connect_args("postgresql+asyncpg://u@db.supabase.co/x")


def test_splitter_ignores_semicolons_in_comments_and_strings():
    from backend.db.postgres_client import PostgresClient

    sql = """-- a comment; with a semicolon
CREATE TABLE t (a TEXT DEFAULT 'x;y', b TEXT DEFAULT 'it''s; fine'); -- trailing; comment
CREATE FUNCTION f() RETURNS void AS $$ BEGIN PERFORM 1; END $$ LANGUAGE plpgsql;
SELECT '--not a comment';"""
    stmts = PostgresClient._split_sql_statements(sql)
    assert len(stmts) == 3
    assert "'x;y'" in stmts[0] and "'it''s; fine'" in stmts[0]
    assert "PERFORM 1; END" in stmts[1]
    assert stmts[2] == "SELECT '--not a comment'"

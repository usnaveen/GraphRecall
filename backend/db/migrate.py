"""Versioned schema migrations for PostgreSQL.

Before this, every API start re-ran init.sql and every file in migrations/ (they had to be
idempotent), plus nine ALTER TABLE patches in main.py, and swallowed any error. That is fine for a
laptop and wrong for production: a half-applied schema just limped on.

Now:
- Migrations are applied once, in order, each in its own transaction, and recorded in
  `schema_migrations` (version, checksum, applied_at).
- Order: `000a_legacy_columns.sql` (the old startup patches, for databases that predate init.sql's
  indexes), then `init.sql` as version `000b_init`, then `migrations/*.sql` by filename.
- A recorded migration whose file has changed is an error (fix forward with a new file).
- Development auto-migrates on start; production never does (`ENVIRONMENT=production`): the deploy
  runs `python -m backend.db.migrate`, and the API refuses to start while anything is pending.

Existing databases need no baseline step: every existing file was written to be re-runnable, so the
first run applies them all once and records them.

    python -m backend.db.migrate            # apply pending
    python -m backend.db.migrate --status   # list applied / pending, exit 1 if pending
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import text

logger = structlog.get_logger()

DB_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = DB_DIR / "migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def discover() -> list[Migration]:
    """All migrations in apply order."""
    found = [Migration("000a_legacy_columns", MIGRATIONS_DIR / "000a_legacy_columns.sql"),
             Migration("000b_init", DB_DIR / "init.sql")]
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if p.stem == "000a_legacy_columns":
            continue
        found.append(Migration(p.stem, p))
    return found


class MigrationError(RuntimeError):
    pass


async def _ensure_table(pg) -> None:
    async with pg.session() as s:
        await s.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY, checksum TEXT NOT NULL,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"))
        await s.commit()


async def applied(pg) -> dict[str, str]:
    await _ensure_table(pg)
    async with pg.session() as s:
        rows = (await s.execute(text("SELECT version, checksum FROM schema_migrations"))).all()
    return {r[0]: r[1] for r in rows}


async def pending(pg) -> list[Migration]:
    done = await applied(pg)
    out = []
    for m in discover():
        if m.version in done:
            if done[m.version] != m.checksum:
                raise MigrationError(f"migration {m.version} changed after it was applied; add a new migration instead")
            continue
        out.append(m)
    return out


async def migrate(pg) -> list[str]:
    """Apply every pending migration, each in its own transaction. Returns the versions applied."""
    from backend.db.postgres_client import PostgresClient

    todo = await pending(pg)
    done = []
    for m in todo:
        statements = PostgresClient._split_sql_statements(m.sql)
        async with pg.session() as s:
            try:
                for stmt in statements:
                    await s.execute(text(stmt))
                await s.execute(text("INSERT INTO schema_migrations (version, checksum) VALUES (:v, :c)"),
                                {"v": m.version, "c": m.checksum})
                await s.commit()
            except Exception as e:
                await s.rollback()
                raise MigrationError(f"migration {m.version} failed: {e}") from e
        logger.info("migration applied", version=m.version, statements=len(statements))
        done.append(m.version)
    return done


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development") == "production"


async def ensure_schema(pg) -> None:
    """Called at API start: auto-migrate in development, refuse to start in production if behind."""
    if not is_production():
        applied_now = await migrate(pg)
        if applied_now:
            logger.info("schema migrated", applied=applied_now)
        return
    left = await pending(pg)
    if left:
        raise MigrationError("database schema is behind the code; run `python -m backend.db.migrate` "
                             f"before starting ({len(left)} pending: {', '.join(m.version for m in left)})")


async def _main(argv: list[str]) -> int:
    from backend.db.postgres_client import close_postgres_client, get_postgres_client

    ap = argparse.ArgumentParser(prog="python -m backend.db.migrate")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    pg = await get_postgres_client()
    try:
        if a.status:
            done, left = await applied(pg), await pending(pg)
            for m in discover():
                print(f"{'applied' if m.version in done else 'PENDING'}  {m.version}")
            return 1 if left else 0
        for v in await migrate(pg):
            print(f"applied {v}")
        print("schema up to date")
        return 0
    finally:
        await close_postgres_client()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))

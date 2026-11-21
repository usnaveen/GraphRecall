"""PostgreSQL database client with async connection pooling."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import structlog
from pydantic_settings import BaseSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = structlog.get_logger()


class PostgresSettings(BaseSettings):
    """PostgreSQL connection settings."""

    database_url: str 

    model_config = {"env_prefix": "", "extra": "ignore"}


CLOUD_HOST_HINTS = ("neon.tech", "supabase", "render.com", "aivencloud", "rds.amazonaws.com")


def _tls_connect_args(db_url: str) -> tuple[str, dict]:
    """TLS for managed Postgres, with certificate and hostname verification.

    asyncpg doesn't accept libpq's `sslmode` query parameter, so it is removed from the URL and turned
    into an SSL context. The old code disabled verification (CERT_NONE, no hostname check), which lets
    anyone on the path impersonate the database. PG_SSL_INSECURE=1 restores that for local debugging
    only and is refused in production.
    """
    import os
    import ssl
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(db_url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    clean_url = urlunsplit(parts._replace(query=urlencode(query)))
    wants_tls = sslmode in ("require", "verify-ca", "verify-full") or any(h in (parts.hostname or "") for h in CLOUD_HOST_HINTS)
    if not wants_tls or sslmode == "disable":
        return clean_url, {}
    insecure = os.getenv("PG_SSL_INSECURE") == "1"
    if insecure and os.getenv("ENVIRONMENT", "development") == "production":
        raise RuntimeError("PG_SSL_INSECURE=1 is not allowed in production")
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return clean_url, {"ssl": ctx}


class PostgresClient:
    """Async PostgreSQL client with connection pooling."""

    def __init__(self, settings: Optional[PostgresSettings] = None):
        self.settings = settings or PostgresSettings()
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the database engine and session factory."""
        if self._initialized:
            return

        # Convert postgresql:// to postgresql+asyncpg:// if needed
        db_url = self.settings.database_url
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        db_url, connect_args = _tls_connect_args(db_url)
        connect_args["statement_cache_size"] = 0

        self._engine = create_async_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
            connect_args=connect_args,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        self._initialized = True
        logger.info("PostgreSQL client initialized", url=db_url.split("@")[-1])

    async def close(self) -> None:
        """Close the database connection pool."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._initialized = False
            logger.info("PostgreSQL client closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session from the pool."""
        if not self._initialized:
            await self.initialize()

        if not self._session_factory:
            raise RuntimeError("Session factory not initialized")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def health_check(self) -> dict:
        """Check database connectivity and return health status."""
        try:
            async with self.session() as session:
                result = await session.execute(text("SELECT 1"))
                result.scalar()
                return {
                    "status": "healthy",
                    "database": "postgresql",
                    "connected": True,
                }
        except Exception as e:
            logger.error("PostgreSQL health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "database": "postgresql",
                "connected": False,
                "error": str(e),
            }

    async def execute_query(self, query: str, params: Optional[dict] = None) -> list:
        """Execute a raw SQL query and return results."""
        async with self.session() as session:
            result = await session.execute(text(query), params or {})
            # Guard against non-returning statements (UPDATE/INSERT without RETURNING)
            if result.returns_rows:
                return [dict(row._mapping) for row in result.fetchall()]
            return []

    async def execute_insert(self, query: str, params: Optional[dict] = None) -> Optional[str]:
        """Execute an insert query and return the inserted ID (if RETURNING clause present)."""
        async with self.session() as session:
            result = await session.execute(text(query), params or {})
            # Only try fetchone if query has RETURNING clause — otherwise fetchone() throws
            # "This result object does not return rows"
            if result.returns_rows:
                row = result.fetchone()
                return str(row[0]) if row else None
            return None

    async def execute_update(self, query: str, params: Optional[dict] = None) -> None:
        """Execute an update/delete query without returning results."""
        async with self.session() as session:
            await session.execute(text(query), params or {})



    async def initialize_schema(self) -> None:
        """Initialize the database schema from SQL files."""
        import os
        
        async with self.session() as session:
            try:
                # Base directory for SQL files
                base_dir = os.path.dirname(os.path.abspath(__file__))
                
                # 1. Run init.sql
                init_sql_path = os.path.join(base_dir, "init.sql")
                if os.path.exists(init_sql_path):
                    logger.info("Running schema initialization...")
                    with open(init_sql_path, "r") as f:
                        sql_content = f.read()
                        
                    # Use smart splitting to handle $$ blocks
                    statements = self._split_sql_statements(sql_content)
                    
                    for statement in statements:
                        await session.execute(text(statement))
                        
                    logger.info("Schema initialization completed")
                
                # 2. Run migrations
                migrations_dir = os.path.join(base_dir, "migrations")
                if os.path.exists(migrations_dir):
                    migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith(".sql")])
                    for migration_file in migration_files:
                        logger.info(f"Running migration: {migration_file}")
                        with open(os.path.join(migrations_dir, migration_file), "r") as f:
                            migration_sql = f.read()
                            
                        # Use same smart splitter
                        statements = self._split_sql_statements(migration_sql)
                        for statement in statements:
                            await session.execute(text(statement))
                            
                    logger.info("Migrations completed")
                    
                await session.commit()
                
            except Exception as e:
                logger.error("Schema initialization failed", error=str(e))
                await session.rollback()
                logger.warning("Continuing application startup despite schema error")

    @staticmethod
    def _split_sql_statements(sql: str) -> list[str]:
        """
        Split SQL script into statements, preserving $$ blocks.
        
        This is a simple parser that mainly handles standard ;;
        vs $$...$$ blocks used in PL/pgSQL.
        """
        statements = []
        current_stmt = []
        in_dollar_quote = False
        in_string = False
        i = 0
        length = len(sql)

        while i < length:
            char = sql[i]

            # Check for $$ start/end
            if char == '$' and not in_string and i + 1 < length and sql[i+1] == '$':
                in_dollar_quote = not in_dollar_quote
                current_stmt.append("$$")
                i += 2
                continue

            if not in_dollar_quote:
                # '...' literals ('' escapes toggle twice, so they stay inside)
                if char == "'":
                    in_string = not in_string
                # -- comments run to end of line; a ';' in one must not split a statement
                elif not in_string and char == '-' and i + 1 < length and sql[i+1] == '-':
                    end = sql.find("\n", i)
                    i = length if end == -1 else end
                    continue

            # Split on semicolon only outside dollar quotes and string literals
            if char == ';' and not in_dollar_quote and not in_string:
                stmt = "".join(current_stmt).strip()
                if stmt:
                    statements.append(stmt)
                current_stmt = []
            else:
                current_stmt.append(char)
            i += 1

        # Append remaining
        if current_stmt:
            stmt = "".join(current_stmt).strip()
            if stmt:
                statements.append(stmt)
                
        return statements

# Global client instance
_postgres_client: Optional[PostgresClient] = None
_client_lock = asyncio.Lock()


async def get_postgres_client() -> PostgresClient:
    """Get or create the global PostgreSQL client instance."""
    global _postgres_client

    async with _client_lock:
        if _postgres_client is None:
            _postgres_client = PostgresClient()
            await _postgres_client.initialize()

    return _postgres_client


async def close_postgres_client() -> None:
    """Close the global PostgreSQL client."""
    global _postgres_client

    async with _client_lock:
        if _postgres_client:
            await _postgres_client.close()
            _postgres_client = None

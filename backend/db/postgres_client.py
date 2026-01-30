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

    database_url: str = "postgresql+asyncpg://graphrecall:graphrecall123@localhost:5432/graphrecall"

    model_config = {"env_prefix": "", "extra": "ignore"}


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

        self._engine = create_async_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
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
            return [dict(row._mapping) for row in result.fetchall()]

    async def execute_insert(self, query: str, params: Optional[dict] = None) -> Optional[str]:
        """Execute an insert query and return the inserted ID."""
        async with self.session() as session:
            result = await session.execute(text(query), params or {})
            row = result.fetchone()
            return str(row[0]) if row else None


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

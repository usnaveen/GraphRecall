import asyncio
import os
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Explicit credentials from user
DB_URL = "postgresql+asyncpg://postgres.gkhhecrbbyrautfuruuh:rAzD6ityq2Di9XSJ@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"
NEO4J_URI = "neo4j+s://9c171425.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASS = "dXbtaIRnFnkFh5ePsW_zEep738-4xgZfmImwko5oV48"

logger = structlog.get_logger()

async def verify_postgres():
    print(f"\n--- Testing Postgres (Supabase) ---")
    print(f"URL: {DB_URL.split('@')[-1]}")
    
    try:
        # Mimic the logic in postgres_client.py
        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        
        engine = create_async_engine(
            DB_URL,
            echo=False,
            connect_args={"ssl": ssl_ctx, "statement_cache_size": 0}
        )
        
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Success! Version: {version}")
        
        await engine.dispose()
        return True
    except Exception as e:
        print(f"❌ Postgres Failed: {str(e)}")
        return False

async def verify_neo4j():
    print(f"\n--- Testing Neo4j (Aura) ---")
    print(f"URI: {NEO4J_URI}")
    
    try:
        from neo4j import AsyncGraphDatabase
        
        driver = AsyncGraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASS)
        )
        
        await driver.verify_connectivity()
        print("✅ Success! Connected to Neo4j Aura.")
        
        await driver.close()
        return True
    except Exception as e:
        print(f"❌ Neo4j Failed: {str(e)}")
        return False

async def main():
    pg_ok = await verify_postgres()
    neo_ok = await verify_neo4j()
    
    if pg_ok and neo_ok:
        print("\n✨ ALL CLOUD CREDENTIALS VERIFIED!")
    else:
        print("\n⚠️ SOME CHECKS FAILED.")

if __name__ == "__main__":
    asyncio.run(main())

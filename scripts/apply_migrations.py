import asyncio
import os
from dotenv import load_dotenv

from pathlib import Path

# Ensure env vars are loaded from project root
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

from backend.db.postgres_client import get_postgres_client, close_postgres_client

async def run_migrations():
    print("Initializing Postgres Client...")
    client = await get_postgres_client()
    
    print("Running Schema Initialization...")
    try:
        await client.initialize_schema()
        print("Schema Initialization Completed Successfully.")
    except Exception as e:
        print(f"Schema Initialization Failed: {e}")
    finally:
        await close_postgres_client()

if __name__ == "__main__":
    asyncio.run(run_migrations())

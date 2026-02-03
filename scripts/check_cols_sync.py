
import asyncio
from sqlalchemy import create_engine, text
import os

# Use environment variable or default
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/graphrecall")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

async def check_columns():
    # Use standard engine for quick check
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("--- Checking 'notes' columns ---")
        res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'notes'"))
        cols = [r[0] for r in res]
        print(f"Columns in 'notes': {cols}")
        
        print("\n--- Checking 'proficiency_scores' columns ---")
        res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'proficiency_scores'"))
        cols = [r[0] for r in res]
        print(f"Columns in 'proficiency_scores': {cols}")

if __name__ == "__main__":
    # Standard engine is sync, no need for asyncio.run if using create_engine
    # But let's just do it sync for simplicity
    check_columns()

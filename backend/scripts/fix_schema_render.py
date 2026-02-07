import asyncpg
import asyncio
import os
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")

async def fix_schema():
    if not DATABASE_URL:
        print("DATABASE_URL not set")
        return

    print(f"Connecting to {DATABASE_URL.split('@')[1]}")
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # 1. Enable vector extension (might fail if not supported, but we try)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            print("✅ Extension 'vector' enabled")
        except Exception as e:
            print(f"⚠️ Could not enable vector extension: {e}")

        # 2. Add google_id to users if missing
        try:
            await conn.execute("""
                ALTER TABLE users 
                ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE,
                ADD COLUMN IF NOT EXISTS name VARCHAR(255),
                ADD COLUMN IF NOT EXISTS profile_picture TEXT,
                ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE;
            """)
            print("✅ Added missing columns to 'users'")
            
            # Create index for google_id
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);")
            print("✅ Created index for users.google_id")
            
        except Exception as e:
            print(f"❌ Failed to alter users table: {e}")

        # 3. Add embedding_vector to notes if missing
        try:
            await conn.execute("""
                ALTER TABLE notes 
                ADD COLUMN IF NOT EXISTS embedding_vector vector(3072);
            """)
            print("✅ Added 'embedding_vector' to 'notes'")
        except Exception as e:
            print(f"⚠️ Failed to add embedding_vector (vector ext might be missing): {e}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(fix_schema())


import asyncio
import os
import sys
from dotenv import load_dotenv

# Add directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'backend', '.env')
load_dotenv(env_path)

from backend.db.postgres_client import get_postgres_client

async def dump_users():
    try:
        pg = await get_postgres_client()
        # Fetch all users
        users = await pg.execute_query("SELECT * FROM users")
        
        output = []
        output.append(f"Total Users: {len(users)}")
        for u in users:
            output.append(f"User: {u.get('email', 'No Email')} | ID: {u.get('id')} | Name: {u.get('name')}")
            
        # Write to file
        with open("backend/scripts/users_dump.txt", "w") as f:
            f.write("\n".join(output))
            
        print("Dump complete.")
        
    except Exception as e:
        with open("backend/scripts/users_dump.txt", "w") as f:
            f.write(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(dump_users())

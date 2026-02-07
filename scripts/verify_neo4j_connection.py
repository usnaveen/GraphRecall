import asyncio
import os
from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv

# Load env variables explicitly
cwd = os.getcwd()
backend_dir = os.path.join(cwd, "backend")
# Load env variables explicitly
cwd = os.getcwd()
backend_dir = os.path.join(cwd, "backend")
# Load env variables explicitly
cwd = os.getcwd()
backend_dir = os.path.join(cwd, "backend")
# FORCE .env.local in root if exists (bypass permission issues), else backend
root_env = os.path.join(cwd, ".env.local")
if os.path.exists(root_env):
    env_path = root_env
elif os.path.exists(os.path.join(backend_dir, ".env.local")):
    env_path = os.path.join(backend_dir, ".env.local")
else:
    env_path = os.path.join(backend_dir, ".env")

print(f"CWD: {cwd}")
print(f"Target env path: {env_path}")

try:
    if os.path.exists(backend_dir):
        print(f"Listing {backend_dir}:")
        print(os.listdir(backend_dir)[:5]) # First 5 files
    else:
        print(f"Backend dir {backend_dir} DOES NOT exist!")

    if os.path.exists(env_path):
        print("File exists! Reading first line...")
        with open(env_path, 'r') as f:
            print(f"First line: {f.readline().strip()}")
    else:
        print("File DOES NOT exist!")
except Exception as e:
    print(f"Filesystem error: {e}")

load_dotenv(env_path)

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
# Check if URI is still empty
if not URI:
    # Manual parsing as fallback
    try:
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith("NEO4J_URI="):
                    URI = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("NEO4J_USER="):
                    USER = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("NEO4J_PASSWORD="):
                    PASSWORD = line.split("=", 1)[1].strip().strip('"').strip("'")
        print("Manually parsed .env")
    except:
        pass

PASSWORD = os.getenv("NEO4J_PASSWORD")

print(f"URI raw: '{URI}'")
print(f"User raw: '{USER}'")
# Mask password
print(f"Password: {'*' * len(PASSWORD) if PASSWORD else 'NONE'}")

async def verify_connection():
    driver = None
    try:
        driver = AsyncGraphDatabase.driver(
            URI,
            auth=(USER, PASSWORD)
        )
        print("\nAttempting verify_connectivity()...")
        await driver.verify_connectivity()
        print("✅ Connection Successful!")
        
        async with driver.session() as session:
            result = await session.run("RETURN 'Hello Neo4j' AS greeting")
            record = await result.single()
            print(f"Query Result: {record['greeting']}")
            
    except Exception as e:
        print(f"\n❌ Connection Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            await driver.close()

if __name__ == "__main__":
    asyncio.run(verify_connection())

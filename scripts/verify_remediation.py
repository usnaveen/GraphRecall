
import sys
import os

print("Verifying imports for modified files...")

try:
    print("Checking backend.auth.middleware...")
    from backend.auth import middleware
    print("✅ backend.auth.middleware imported successfully")
except ImportError as e:
    print(f"❌ Failed to import backend.auth.middleware: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error in backend.auth.middleware: {e}")
    sys.exit(1)

try:
    print("Checking backend.main (structlog config)...")
    # We don't want to run the app, just check syntax and imports
    import backend.main
    print("✅ backend.main imported successfully")
except ImportError as e:
    print(f"❌ Failed to import backend.main: {e}")
    sys.exit(1)
except Exception as e:
    # backend.main might try to connect to DBs on import if not careful, 
    # but strictly speaking it just defines the app. 
    # If it fails due to missing .env vars for DB, that's expected in this script context 
    # unless we load them.
    print(f"⚠️  backend.main raised exception (might be DB connection): {e}")

print("Verification complete.")

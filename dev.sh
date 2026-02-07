#!/bin/bash

# Kill background processes on exit
# Load environment variables (Prioritize .env.local if permission issues exist)
if [ -f ".env.local" ]; then
    echo "Loading environment variables from root .env.local..."
    set -a
    source .env.local
    set +a
elif [ -f "backend/.env.local" ]; then
    echo "Loading environment variables from backend/.env.local..."
    set -a
    source backend/.env.local
    set +a
elif [ -f "backend/.env" ]; then
    echo "Loading environment variables from backend/.env..."
    set -a
    source backend/.env
    set +a
fi

# Ensure .venv exists
if [ ! -d ".venv" ]; then
    echo "⚠️  .venv not found. Creating one..."
    python3 -m venv .venv
    echo "📦 Installing dependencies..."
    .venv/bin/pip install -r requirements.txt
fi

# Activate venv
source .venv/bin/activate

echo "Starting Backend..."
# We use uvicorn directly to allow hot reloading

# Activate venv if it exists
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Assuming .venv is active or handled by the user/IDE, 
# but let's try to be smart about it if possible, or just assume environment is set.
# Using 'python3 -m' usage is safer for path resolution.
python3 -m uvicorn backend.main:app --reload --port 8000 &

# 2. Start Frontend
echo "Starting Frontend..."
cd frontend
npm run dev &

# Wait for both
wait

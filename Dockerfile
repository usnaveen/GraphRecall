# GraphRecall API image.
#
# Build:  docker build -t graphrecall-api .
# Run:    docker compose up          (starts the API with Postgres + Neo4j)

FROM python:3.12-slim

# No .pyc files, unbuffered logs (so `docker compose logs` shows output immediately).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is cached and only rebuilds when requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code.
COPY backend ./backend

# Run as a non-root user.
RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000

# Cloud Run and similar hosts inject $PORT; locally it defaults to 8000.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# GraphRecall

**Lifetime Active Recall Learning System** - A multi-agent system that transforms your notes into an intelligent knowledge graph with spaced repetition learning.

## Features

- **Knowledge Graph**: Automatically extract concepts and relationships from your notes
- **Active Recall**: Quiz and flashcard generation calibrated to your proficiency
- **Spaced Repetition**: Smart scheduling based on the SM-2 algorithm and graph centrality
- **Living Notes**: Conflict detection when new information contradicts existing knowledge

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, LangGraph
- **Databases**: Neo4j (knowledge graph), PostgreSQL (user data, embeddings)
- **AI Models**: OpenAI GPT-4o/3.5, text-embedding-3-small
- **Frontend**: Next.js 14, React Flow, Tailwind CSS (Phase 3)

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker and Docker Compose

### Setup

1. **Clone and configure environment**:
   ```bash
   cd GraphRecall
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Start databases**:
   ```bash
   docker-compose up -d
   ```

3. **Install dependencies**:
   ```bash
   uv sync
   ```

4. **Run the API server**:
   ```bash
   uv run uvicorn backend.main:app --reload
   ```

5. **Access the API**:
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs
   - Neo4j Browser: http://localhost:7474

## Project Structure

```
GraphRecall/
├── backend/
│   ├── agents/          # LangGraph agent implementations
│   ├── db/              # Database clients and schemas
│   ├── graph/           # LangGraph state and workflow
│   ├── models/          # Pydantic models
│   ├── prompts/         # External prompt templates
│   ├── tests/           # Unit and integration tests
│   └── main.py          # FastAPI application
├── docker-compose.yml   # Neo4j + PostgreSQL
├── pyproject.toml       # uv package config
└── .env                 # Environment variables
```

## Development

### Running Tests

```bash
uv run pytest
```

### Code Quality

```bash
uv run ruff check backend/
uv run mypy backend/
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ingest` | Ingest markdown notes |
| GET | `/api/notes` | List all notes |
| GET | `/api/notes/{id}` | Get note by ID |
| GET | `/api/graph` | Get knowledge graph |
| GET | `/api/graph/concept/{id}` | Get concept details |
| GET | `/health` | Health check |

## License

MIT

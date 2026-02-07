# How to Use GraphRecall - Simple Guide

## 🚀 Quick Start

### Step 1: Make sure the server is running

Open a terminal and run:
```bash
cd "/Users/naveenus/Library/Mobile Documents/com~apple~CloudDocs/Projects/GraphRecall"
uv run uvicorn backend.main:app --reload
```

You should see: `INFO: Application startup complete`

---

## 📝 Option 1: Use the Simple Script (Easiest!)

### To ingest a note file:
```bash
python ingest_note.py your_note.md
```

### To ingest text directly:
```bash
python ingest_note.py --text "Your note content here"
```

**Example:**
```bash
python ingest_note.py example_note.md
```

---

## 🌐 Option 2: Use Swagger UI (Visual Interface)

1. **Open your browser** and go to: http://localhost:8000/docs

2. **Find the `/api/ingest` endpoint** (it's a POST request)

3. **Click on it** to expand

4. **Click "Try it out"** button

5. **In the Request body**, paste this:
```json
{
  "content": "# Your Note Title\n\nYour note content goes here...",
  "user_id": "00000000-0000-0000-0000-000000000001"
}
```

6. **Click "Execute"**

7. **See the results!** You'll see:
   - Note ID
   - Concepts extracted
   - Concepts created
   - Relationships created

---

## 🔍 View Your Knowledge Graph

### In Neo4j Browser (http://localhost:7474):

Run these queries to see your graph:

**See all concepts:**
```cypher
MATCH (c:Concept) RETURN c LIMIT 20
```

**See relationships:**
```cypher
MATCH (c1:Concept)-[r]->(c2:Concept) 
RETURN c1, r, c2 
LIMIT 20
```

**Find a specific concept:**
```cypher
MATCH (c:Concept) 
WHERE c.name CONTAINS "Neural" 
RETURN c
```

---

## 📊 View via API

**Get all notes:**
```bash
curl http://localhost:8000/api/notes
```

**Get the knowledge graph:**
```bash
curl http://localhost:8000/api/graph
```

**Search concepts:**
```bash
curl "http://localhost:8000/api/graph/search?query=Neural"
```

---

## 💡 Tips

- **Start small**: Try with one note first
- **Use markdown**: The system works best with markdown formatting
- **Check Neo4j Browser**: After ingesting, check Neo4j Browser to see your graph grow!
- **Multiple notes**: Each note you ingest will link concepts together automatically

---

## 🆘 Troubleshooting

**Server not running?**
- Make sure Docker containers are running: `docker-compose ps`
- Restart server: `uv run uvicorn backend.main:app --reload`

**Can't connect?**
- Check health: http://localhost:8000/health
- Make sure port 8000 is not used by another app

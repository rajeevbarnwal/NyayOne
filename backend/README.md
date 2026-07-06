# LegalSaathi Backend

FastAPI backend for LegalSaathi APIs, legal workflows, document ingestion, RAG/search, and persistence.

## Structure

```text
app/
  api/       HTTP routes and versioned API modules
  core/      Settings, security, logging, app wiring
  db/        Database sessions, migrations, repositories
  legal/     Legal-domain workflows and rule helpers
  rag/       Retrieval, embeddings, chunking, and citations
  schemas/   Pydantic request/response models
  services/  Business services used by APIs
```

## Local Run (dev port 1031)

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 1031
```

- Liveness: `GET http://localhost:1031/health`
- API v1 health: `GET http://localhost:1031/api/v1/health`

Run tests:

```bash
cd backend && python -m pytest -q
```

Requires Python >= 3.12. Every response carries an `X-Request-ID` correlation header.


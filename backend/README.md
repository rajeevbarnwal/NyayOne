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

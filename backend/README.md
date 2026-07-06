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

## Database (PostgreSQL + pgvector)

Local dev uses PostgreSQL 16 with the `pgvector` extension, on host port **1032 → 5432**
(LegalSaathi 1030-series convention). SQLAlchemy 2.x models share conventions in
`app/db/base.py` (UUID PK, `created_at`/`updated_at`, `deleted_at` soft-delete,
`metadata_json` audit field). The engine/session live in `app/db/session.py` (lazy —
no connection at import).

### Start the database

```bash
docker compose up -d postgres      # exposes localhost:1032
```

`DATABASE_URL` (see `.env.example`) defaults to:
`postgresql+psycopg://legalsaathi:legalsaathi@localhost:1032/legalsaathi`

### Migrations (Alembic)

```bash
cd backend
python -m alembic upgrade head        # apply migrations (creates pgvector extension)
python -m alembic current             # show current revision
python -m alembic downgrade base      # roll back
python -m alembic revision -m "msg"   # new migration (autogenerate with --autogenerate)
python -m alembic upgrade head --sql  # offline: print SQL without a live DB
```

### Reset the local database

```bash
docker compose down -v postgres && docker compose up -d postgres   # drops the pgdata volume
cd backend && python -m alembic upgrade head
```

### Database probe & tests

- Reachability probe: `GET http://localhost:1031/api/v1/health/db` (reports `ok`/`unavailable`, never crashes).
- Tests run against **SQLite in-memory** by default (no Postgres needed): `python -m pytest -q`.
  Set `TEST_DATABASE_URL` to run the suite against a real Postgres instead.

### Known limitations

- `pgvector` extension is created only on PostgreSQL; on SQLite (tests) that step is skipped.
- SQLite is a test-portability convenience only — production/dev must use Postgres+pgvector.
- Dev credentials in `docker-compose.yml` are for local use only; never reuse in production.



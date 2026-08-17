# NyayOne Backend

FastAPI backend for NyayOne APIs, legal workflows, document ingestion, RAG/search, and persistence.

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

## Local Run (host dev port 1131)

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 1131
```

- Liveness: `GET http://localhost:1131/health`
- API v1 health: `GET http://localhost:1131/api/v1/health`

Run tests:

```bash
cd backend && python -m pytest -q
```

Requires Python >= 3.12. Every response carries an `X-Request-ID` correlation header.

## Database (PostgreSQL + pgvector)

Local dev uses PostgreSQL 16 with the `pgvector` extension, on host port **1132 → 5432**
(NyayOne 1130-series convention). SQLAlchemy 2.x models share conventions in
`app/db/base.py` (UUID PK, `created_at`/`updated_at`, `deleted_at` soft-delete,
`metadata_json` audit field). The engine/session live in `app/db/session.py` (lazy —
no connection at import).

### Start the database

```bash
docker compose up -d postgres      # exposes localhost:1132
```

`DATABASE_URL` (see `.env.example`) defaults to:
`postgresql+psycopg://nyayone:nyayone_dev_only@localhost:1132/nyayone`

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

- Reachability probe: `GET http://localhost:1131/api/v1/health/db` (reports `ok`/`unavailable`, never crashes).
- Tests run against **SQLite in-memory** by default (no Postgres needed): `python -m pytest -q`.
  Set `TEST_DATABASE_URL` to run the suite against a real Postgres instead.

### Known limitations

- `pgvector` extension is created only on PostgreSQL; on SQLite (tests) that step is skipped.
- SQLite is a test-portability convenience only — production/dev must use Postgres+pgvector.
- Dev credentials in `docker-compose.yml` are for local use only; never reuse in production.

## Target-runtime gates (ONE command each)

The suite's oracle is SQLite. Some claims cannot be made there at all — real row
locking, partial-index predicates, `pg_constraint`, pgvector, TOASTed JSON. Those
live in gates that run against the approved runtime and that **refuse rather than
pretend** when the runtime is absent.

| Gate | Command | What it proves |
|---|---|---|
| Whole-repo database gate | `DATABASE_URL=… bash scripts/db_gate.sh` | suite + alembic + live schema + earlier-wave runtime gate, then the Wave 2 stage below |
| Wave 2 PostgreSQL 16 + pgvector | `DATABASE_URL=… bash scripts/wave2_db_gate.sh` | assertions A1..A8 — migration paths, drift, reversibility, schema surface, PRICE AUTHORITY, real-connection concurrency, raw-storage privacy, seed determinism. `--list` prints the contract. |
| Wave 2 media plane | `bash ../infra/video/scripts/livekit_turn_smoke.sh` | steps S1..S11 — health, room, join grant, two-browser join, camera/mic denial, reconnect, expiry/revocation, webhook + replay, forced-TURN, provider-unreachable, no raw token/SDP/ICE persisted. `--list` prints the contract. |

Every one of them prints the runtime it detected first and exits **78** with
`BLOCKED: prerequisite runtime absent` if that runtime is not there. **78 is not a
pass and not a failure — it means nothing was proven.** 0 is a pass, 1 is a real
failure.

CI runs the PostgreSQL gate on push and pull request against
`pgvector/pgvector:pg16` (`.github/workflows/wave2-tutoring-db-gate.yml`) and
fails the build if it reports BLOCKED there, because on a runner that HAS the
database, blocked means broken. The media smoke has no runtime in CI; CI asserts
that it refuses with 78, which is the only honest thing to assert.


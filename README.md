# LegalSaathi

LegalSaathi is a responsive legal-assistance application designed to run on desktop and mobile web, with the same React codebase prepared for native iOS and Android packaging through Capacitor.

## Repository Layout

```text
LegalSaathi/
  frontend/              React/Vite app, Capacitor-ready for iOS and Android
  backend/               FastAPI service for APIs, RAG, legal workflows, and storage
  docs/                  Product, architecture, domain, and release notes
  data/                  Local datasets and small samples only
  storage/               Runtime uploads and vector stores, ignored by git
  scripts/               Developer and operations scripts
  docker/                Dockerfiles and container helpers
  notebooks/             RAG and legal AI experiments
  tests/                 Cross-service and end-to-end tests
```

## App Direction

- `frontend/` is the single React codebase for desktop web, mobile web, and native app shells.
- Native builds should be handled with Capacitor after the web app is stable.
- `backend/` owns legal workflows, document ingestion, RAG/search, auth-facing APIs, and persistence.
- Large documents, vector stores, generated app builds, and secrets should stay out of git.

## Local Development

The structure is scaffolded first. Dependencies can be installed once implementation begins.

```bash
cd frontend
npm install
npm run dev
```

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Mobile Packaging Plan

Capacitor is configured from `frontend/`. Later, after installing dependencies:

```bash
cd frontend
npm run build
npm run cap:add:ios
npm run cap:add:android
npm run cap:sync
```

The generated `ios/` and `android/` folders can then be opened in Xcode and Android Studio for signing, testing, and store publication.

## Project Integrations

- GitHub: `rajeevbarnwal/legalsaathi`
- Jira: `SAATHI` project on `https://legalsaathi.atlassian.net`, board `2`
- Details: see `docs/integrations/github-jira.md`

Run `./scripts/check_integrations.py` after creating a local `.env` with any required API tokens.

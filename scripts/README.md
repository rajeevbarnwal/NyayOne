# Scripts

Automation and developer helper scripts live here.

| Script | Purpose |
|---|---|
| `render_video_infra_config.py` | Renders the Wave 2 video-plane service configs (LiveKit, coturn) from `infra/video/*.tmpl` plus the environment, into the gitignored `infra/video/rendered/`. Refuses to write when anything is missing or still a placeholder, so no secret is ever committed and no half-rendered config is ever deployed. See `infra/video/RUNBOOK.md`. |
| `check_integrations.py` | GitHub/Jira integration connectivity check. |
| `ingest_documents.py`, `seed_db.py` | Local data helpers. |
| `run_dev.sh` | Notes for running the dev servers. |
| `wave2_tutoring_browser_gate.sh` | Wave 2 tutoring real-browser closure gate (S-31…S-35, negative states, live-room geometry/a11y, privacy). |

## Target-runtime gates that live elsewhere

Neither of these can run in a sandbox without its runtime, and neither pretends
to. Both print what they detected and exit **78** with `BLOCKED: prerequisite
runtime absent` when it is missing — never 0.

| Gate | Command |
|---|---|
| Wave 2 PostgreSQL 16 + pgvector (assertions A1..A8) | `DATABASE_URL=… bash backend/scripts/wave2_db_gate.sh` |
| Wave 2 LiveKit + TURN media smoke (steps S1..S11, == `infra/video/RUNBOOK.md` § 9) | `bash infra/video/scripts/livekit_turn_smoke.sh` |

# Scripts

Automation and developer helper scripts live here.

| Script | Purpose |
|---|---|
| `render_video_infra_config.py` | Renders the Wave 2 video-plane service configs (LiveKit, coturn) from `infra/video/*.tmpl` plus the environment, into the gitignored `infra/video/rendered/`. Refuses to write when anything is missing or still a placeholder, so no secret is ever committed and no half-rendered config is ever deployed. See `infra/video/RUNBOOK.md`. |
| `check_integrations.py` | GitHub/Jira integration connectivity check. |
| `ingest_documents.py`, `seed_db.py` | Local data helpers. |
| `run_dev.sh` | Notes for running the dev servers. |

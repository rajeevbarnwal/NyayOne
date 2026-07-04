#!/usr/bin/env bash
set -euo pipefail

echo "Run frontend and backend dev servers in separate terminals for now."
echo "Frontend: cd frontend && npm install && npm run dev"
echo "Backend:  cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload"

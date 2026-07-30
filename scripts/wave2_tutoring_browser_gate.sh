#!/usr/bin/env bash
# Wave 2 tutoring REAL-BROWSER closure gate (SAATHI-124 / SAATHI-128, matrix I1/I2/J1).
#
# One invocation does everything and leaves nothing running:
#
#   1. builds a throw-away SQLite database with the real alembic head;
#   2. seeds the deterministic tutoring fixture plus the actors the browser
#      needs (backend/scripts/wave2_e2e_fixture.py);
#   3. boots the real backend on a free port with the DETERMINISTIC payment and
#      video providers (no LiveKit, no Razorpay, no network egress);
#   4. builds the real production frontend bundle pointed at that backend and
#      serves it with `vite preview`;
#   5. drives real Chromium through S-31 … S-35, the negative states, the
#      live-room geometry/a11y measurement and the privacy scan
#      (frontend/scripts/wave2-tutoring-e2e.mjs);
#   6. tears both servers down and reaps the process group.
#
#   Usage:
#     bash scripts/wave2_tutoring_browser_gate.sh
#     bash scripts/wave2_tutoring_browser_gate.sh --out /tmp/evidence
#     bash scripts/wave2_tutoring_browser_gate.sh --stages a,b,c --keep-db
#
#   Options:
#     --out DIR        artifact directory              (default: test-results/wave2-browser-gate)
#     --stages LIST    comma list of stages to run     (default: all)
#                      a=discovery b=detail c=book+pay+confirm e=live-room
#                      d1=reschedule d2=policy/cancel/refund
#                      d3=completion+attendance d4=attendance confirm+review
#                      neg=negative states rl=rate limit
#                      geo=I2 geometry/a11y priv=J1 privacy
#                      none=boot the servers, run no browser work
#     --search-limit N RATE_LIMIT_TUTOR_SEARCH_PER_MIN (default: 200)
#     --booking-limit N RATE_LIMIT_BOOKING_PER_MIN     (default: 400)
#     --stub-lib DIR   dir to PREPEND to LD_LIBRARY_PATH (arm64 libXdamage stub)
#     --keep-db        reuse the existing database and fixture (stage chaining)
#     --no-build       reuse frontend/dist as-is (it must already point at --api-port)
#     --api-port N     backend port                   (default: first free from 1731)
#     --web-port N     frontend port                  (default: first free from 1730)
#     --fee-paise N    VITE_TUTORING_SESSION_FEE_PAISE (default: 250000 = INR 2500.00)
#
#   Environment:
#     PYTHON           interpreter with backend deps installed (auto-detected)
#     LD_LIBRARY_PATH  prepend an arm64 libXdamage stub dir if Chromium needs one
#
# Nothing here weakens a test, and no production file is written. The two clock
# shifts the driver asks for (an expired hold, a session moved past its end) are
# performed on fixture ROWS by the fixture helper and are reported as clock
# shifts in the evidence, never as elapsed wall time.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

OUT="$REPO_ROOT/test-results/wave2-browser-gate"
STAGES="a,b,c,e,geo,d1,d2,d3,d4,neg,priv"
KEEP_DB=0
DO_BUILD=1
API_PORT=""
WEB_PORT=""
FEE_PAISE="250000"
SEARCH_LIMIT="200"
BOOKING_LIMIT="400"
STUB_LIB="${WAVE2_STUB_LIB:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --stages) STAGES="$2"; shift 2 ;;
    --keep-db) KEEP_DB=1; shift ;;
    --no-build) DO_BUILD=0; shift ;;
    --api-port) API_PORT="$2"; shift 2 ;;
    --web-port) WEB_PORT="$2"; shift 2 ;;
    --fee-paise) FEE_PAISE="$2"; shift 2 ;;
    --search-limit) SEARCH_LIMIT="$2"; shift 2 ;;
    --booking-limit) BOOKING_LIMIT="$2"; shift 2 ;;
    --stub-lib) STUB_LIB="$2"; shift 2 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${PYTHON:-}" ]]; then
  for cand in /tmp/lsvenv/bin/python "$REPO_ROOT/backend/.venv/bin/python" "$REPO_ROOT/.venv/bin/python" python3; do
    if command -v "$cand" > /dev/null 2>&1; then PYTHON="$cand"; break; fi
  done
fi
[[ -n "${PYTHON:-}" ]] || { echo "no python interpreter found; set PYTHON=" >&2; exit 2; }

free_port() {
  "$PYTHON" - "$1" <<'PY'
import socket, sys
start = int(sys.argv[1])
for port in range(start, start + 200):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
PY
}

[[ -n "$API_PORT" ]] || API_PORT="$(free_port 1731)"
[[ -n "$WEB_PORT" ]] || WEB_PORT="$(free_port 1730)"
[[ -n "$API_PORT" && -n "$WEB_PORT" ]] || { echo "could not find free ports" >&2; exit 2; }

mkdir -p "$OUT" "$OUT/shots" "$OUT/logs"
WORK="$OUT/work"
mkdir -p "$WORK"
# The database lives on LOCAL disk, never in --out: an --out on a FUSE/network
# mount cannot give SQLite the file locks it needs ("disk I/O error" on the very
# first CREATE TABLE). Artifacts are ordinary writes and stay in --out.
DB_DIR="${WAVE2_DB_DIR:-${TMPDIR:-/tmp}/wave2_browser_gate}"
mkdir -p "$DB_DIR"
DB_FILE="$DB_DIR/wave2_browser_gate.db"
FIXTURE="$WORK/fixture.json"
API_LOG="$OUT/logs/backend_uvicorn.log"
WEB_LOG="$OUT/logs/frontend_preview.log"

export DATABASE_URL="sqlite+pysqlite:///$DB_FILE"
export PAYMENT_PROVIDER=deterministic
export VIDEO_PROVIDER=deterministic
export BOOKING_HOLD_MINUTES=10
export REFUND_FREE_CANCEL_HOURS=24
export JOIN_CREDENTIAL_TTL_SECONDS=300
# The journeys legitimately burn far more than 10 booking mutations a minute.
# The 429 evidence is produced from the SEARCH limiter instead, which is left at
# a deliberately small value so the browser can reach it in one screen.
export RATE_LIMIT_BOOKING_PER_MIN="$BOOKING_LIMIT"
export RATE_LIMIT_TUTOR_SEARCH_PER_MIN="$SEARCH_LIMIT"
export RATE_LIMIT_REVIEW_PER_HOUR=200

# Chromium on this host needs an arm64 libXdamage stub; the caller supplies the
# directory (--stub-lib / WAVE2_STUB_LIB) and it is PREPENDED, never replacing an
# existing LD_LIBRARY_PATH.
if [[ -n "$STUB_LIB" ]]; then
  [[ -d "$STUB_LIB" ]] || { echo "--stub-lib $STUB_LIB is not a directory" >&2; exit 2; }
  export LD_LIBRARY_PATH="$STUB_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
export CORS_ORIGINS="[\"http://127.0.0.1:$WEB_PORT\",\"http://localhost:$WEB_PORT\"]"
export APP_ENV=development
export LOG_LEVEL=INFO

API_PID=""
WEB_PID=""
cleanup() {
  local status=$?
  for pid in "$WEB_PID" "$API_PID"; do
    [[ -n "$pid" ]] || continue
    kill -TERM "$pid" 2> /dev/null || true
  done
  sleep 0.4
  for pid in "$WEB_PID" "$API_PID"; do
    [[ -n "$pid" ]] || continue
    kill -KILL "$pid" 2> /dev/null || true
    wait "$pid" 2> /dev/null || true
  done
  # Anything the children spawned (vite's esbuild helper, uvicorn reloader).
  pkill -KILL -f "vite preview --port $WEB_PORT" 2> /dev/null || true
  pkill -KILL -f "uvicorn app.main:app --host 127.0.0.1 --port $API_PORT" 2> /dev/null || true
  return $status
}
trap cleanup EXIT INT TERM

step() { printf '\n=== %s\n' "$*"; }

# ---------------------------------------------------------------- 1. database
if [[ "$KEEP_DB" == "0" ]]; then
  step "database: fresh SQLite at $DB_FILE via alembic upgrade head"
  rm -f "$DB_FILE"
  (cd backend && "$PYTHON" -m alembic upgrade head) > "$OUT/logs/alembic.log" 2>&1 \
    || { echo "alembic upgrade failed; see $OUT/logs/alembic.log" >&2; exit 3; }
  tail -1 "$OUT/logs/alembic.log"

  step "fixture: seeding tutors, slots and browser actors"
  (cd backend && "$PYTHON" scripts/wave2_e2e_fixture.py seed --extra-tutors 12) > "$FIXTURE" \
    || { echo "fixture seed failed" >&2; exit 3; }
  "$PYTHON" -c "import json,sys; d=json.load(open(sys.argv[1])); print('tutors=%d slots=%d gt24h=%d lt24h=%d' % (d['tutor_total'], len(d['slots']), len(d['buckets']['gt24h']), len(d['buckets']['lt24h'])))" "$FIXTURE"
else
  step "database: reusing $DB_FILE (--keep-db)"
  [[ -f "$DB_FILE" && -f "$FIXTURE" ]] || { echo "--keep-db but no database/fixture in $WORK" >&2; exit 2; }
fi

# ---------------------------------------------------------------- 2. backend
step "backend: uvicorn app.main:app on 127.0.0.1:$API_PORT (payment=deterministic video=deterministic)"
(cd backend && exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --no-access-log) \
  >> "$API_LOG" 2>&1 &
API_PID=$!

for _ in $(seq 1 60); do
  if "$PYTHON" - "$API_PORT" <<'PY' > /dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=1).read()
PY
  then break; fi
  kill -0 "$API_PID" 2> /dev/null || { echo "backend died on boot:" >&2; tail -20 "$API_LOG" >&2; exit 3; }
  sleep 0.25
done
"$PYTHON" - "$API_PORT" <<'PY' || { echo "backend health never came up" >&2; tail -20 "$API_LOG" >&2; exit 3; }
import sys, urllib.request
print("health:", urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=2).read().decode())
PY

# ---------------------------------------------------------------- 3. frontend
if [[ "$DO_BUILD" == "1" ]]; then
  step "frontend: production bundle (vite build) pointed at http://127.0.0.1:$API_PORT"
  (cd frontend && VITE_API_BASE_URL="http://127.0.0.1:$API_PORT" \
     VITE_TUTORING_SESSION_FEE_PAISE="$FEE_PAISE" npx vite build) \
     > "$OUT/logs/vite_build.log" 2>&1 \
     || { echo "vite build failed; see $OUT/logs/vite_build.log" >&2; exit 3; }
  grep -E "built in|dist/assets/index-.*\.js" "$OUT/logs/vite_build.log" | tail -3
else
  step "frontend: reusing frontend/dist (--no-build)"
fi

step "frontend: vite preview on 127.0.0.1:$WEB_PORT"
(cd frontend && exec npx vite preview --port "$WEB_PORT" --strictPort --host 127.0.0.1) \
  >> "$WEB_LOG" 2>&1 &
WEB_PID=$!

for _ in $(seq 1 60); do
  if "$PYTHON" - "$WEB_PORT" <<'PY' > /dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/", timeout=1).read()
PY
  then break; fi
  kill -0 "$WEB_PID" 2> /dev/null || { echo "preview died on boot:" >&2; tail -20 "$WEB_LOG" >&2; exit 3; }
  sleep 0.25
done

# ---------------------------------------------------------------- 4. journeys
step "browser: driving Chromium through stages [$STAGES]"
E2E_WEB_URL="http://127.0.0.1:$WEB_PORT" \
E2E_API_URL="http://127.0.0.1:$API_PORT" \
E2E_OUT_DIR="$OUT" \
E2E_FIXTURE="$FIXTURE" \
E2E_STAGES="$STAGES" \
E2E_PYTHON="$PYTHON" \
E2E_REPO_ROOT="$REPO_ROOT" \
E2E_BACKEND_LOG="$API_LOG" \
E2E_FEE_PAISE="$FEE_PAISE" \
  node frontend/scripts/wave2-tutoring-e2e.mjs
DRIVER_RC=$?

step "result: driver exit $DRIVER_RC · artifacts in $OUT"
exit $DRIVER_RC

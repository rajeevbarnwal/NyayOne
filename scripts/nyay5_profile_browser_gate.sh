#!/usr/bin/env bash
# Isolated production-build browser gate for the NYAY-5 authority boundary.
# All credentials, ports, database names, raw service logs, and OTP/session
# fixtures remain in a mode-0700 temporary directory and never enter evidence.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${PYTHON:-python}"
CONTROL_URL="${NYAY5_POSTGRES_CONTROL_URL:?NYAY5_POSTGRES_CONTROL_URL is required}"
if [[ "$#" -ne 1 || -z "$1" ]]; then
  printf 'usage: %s /absolute/path/to/nyay5-browser/results.json\n' "$0" >&2
  exit 2
fi
OUTPUT_PATH="$1"
if [[ "$OUTPUT_PATH" != /* ]]; then
  printf 'NYAY5 evidence path must be absolute\n' >&2
  exit 2
fi
OUTPUT_DIR="$(dirname "$OUTPUT_PATH")"
SUMMARY_PATH="$OUTPUT_DIR/orchestrator-summary.json"
SCREENSHOT_DIR="$OUTPUT_DIR/screenshots"
mkdir -p "$OUTPUT_DIR" "$SCREENSHOT_DIR"

PRIVATE_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
PRIVATE_DIR="$(mktemp -d "$PRIVATE_ROOT/nyay5-profile-browser.XXXXXX")"
chmod 0700 "$PRIVATE_DIR"
STATE_FILE="$PRIVATE_DIR/scratch-state.json"
DENIAL_FILE="$PRIVATE_DIR/denial-fixtures.json"
API_LOG="$PRIVATE_DIR/api.log"
OTP_LOG="$PRIVATE_DIR/otp.log"
PREVIEW_LOG="$PRIVATE_DIR/preview.log"
BUILD_LOG="$PRIVATE_DIR/build.log"

API_PID=''
OTP_PID=''
PREVIEW_PID=''
CREATED=0
REMOVED=0
INVENTORY_MATCH=false
POSTGRES_READY=false
API_READY=false
OTP_READY=false
PREVIEW_READY=false
SERVICE_WORKER_ACTIVE=false
SERVICE_LOGS_CAPTURED=false
EXECUTED=false
BROWSER_EXIT_CODE=127
MAIN_SUCCESS=false

write_summary() {
  local status="$1"
  local temporary="$SUMMARY_PATH.tmp.$$"
  NYAY5_SUMMARY_STATUS="$status" \
  NYAY5_SUMMARY_EXECUTED="$EXECUTED" \
  NYAY5_SUMMARY_POSTGRES="$POSTGRES_READY" \
  NYAY5_SUMMARY_API="$API_READY" \
  NYAY5_SUMMARY_OTP="$OTP_READY" \
  NYAY5_SUMMARY_PREVIEW="$PREVIEW_READY" \
  NYAY5_SUMMARY_SW="$SERVICE_WORKER_ACTIVE" \
  NYAY5_SUMMARY_SERVICE_LOGS="$SERVICE_LOGS_CAPTURED" \
  NYAY5_SUMMARY_CREATED="$CREATED" \
  NYAY5_SUMMARY_REMOVED="$REMOVED" \
  NYAY5_SUMMARY_INVENTORY="$INVENTORY_MATCH" \
  NYAY5_SUMMARY_BROWSER_EXIT="$BROWSER_EXIT_CODE" \
  "$PYTHON" - "$temporary" <<'PY'
import json
import os
from pathlib import Path
import sys

boolean = lambda name: os.environ[name] == "true"
value = {
    "gate": "nyay5-profile-browser-orchestrator-v1",
    "executed": boolean("NYAY5_SUMMARY_EXECUTED"),
    "status": os.environ["NYAY5_SUMMARY_STATUS"],
    "services": {
        "postgresReady": boolean("NYAY5_SUMMARY_POSTGRES"),
        "apiReady": boolean("NYAY5_SUMMARY_API"),
        "otpCaptureReady": boolean("NYAY5_SUMMARY_OTP"),
        "productionPreviewReady": boolean("NYAY5_SUMMARY_PREVIEW"),
        "serviceWorkerActive": boolean("NYAY5_SUMMARY_SW"),
    },
    "serviceLogsCaptured": boolean("NYAY5_SUMMARY_SERVICE_LOGS"),
    "scratchCleanup": {
        "created": int(os.environ["NYAY5_SUMMARY_CREATED"]),
        "removed": int(os.environ["NYAY5_SUMMARY_REMOVED"]),
        "inventoryMatch": boolean("NYAY5_SUMMARY_INVENTORY"),
    },
    "browserExitCode": int(os.environ["NYAY5_SUMMARY_BROWSER_EXIT"]),
}
path = Path(sys.argv[1])
path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  mv -f "$temporary" "$SUMMARY_PATH"
}

cleanup() {
  local original_status=$?
  local cleanup_ok=true
  trap - EXIT
  set +e
  for process_id in "$PREVIEW_PID" "$API_PID" "$OTP_PID"; do
    if [[ -n "$process_id" ]]; then
      kill "$process_id" 2>/dev/null
      wait "$process_id" 2>/dev/null
    fi
  done
  if [[ -f "$STATE_FILE" ]]; then
    if PYTHONPATH="$ROOT/backend" "$PYTHON" \
      "$ROOT/backend/scripts/nyay5_browser_gate_control.py" drop \
      --control-url "$CONTROL_URL" --state-file "$STATE_FILE" \
      >"$PRIVATE_DIR/drop-summary.json" 2>"$PRIVATE_DIR/drop-error.log"; then
      REMOVED=1
      INVENTORY_MATCH=true
    else
      cleanup_ok=false
    fi
  fi
  if [[ "$PRIVATE_DIR" == "$PRIVATE_ROOT"/nyay5-profile-browser.* ]]; then
    rm -rf -- "$PRIVATE_DIR"
  else
    cleanup_ok=false
  fi
  local final_status='FAIL'
  local final_exit="$original_status"
  if [[ "$original_status" -eq 0 && "$MAIN_SUCCESS" == true \
    && "$SERVICE_LOGS_CAPTURED" == true && "$cleanup_ok" == true \
    && "$REMOVED" -eq 1 && "$INVENTORY_MATCH" == true ]]; then
    final_status='PASS'
    final_exit=0
  elif [[ "$final_exit" -eq 0 ]]; then
    final_exit=1
  fi
  write_summary "$final_status" || final_exit=1
  exit "$final_exit"
}
trap cleanup EXIT
write_summary 'FAIL'

for command_name in "$PYTHON" node npm curl; do
  command -v "$command_name" >/dev/null || {
    printf 'required local runtime unavailable\n' >&2
    exit 2
  }
done

read -r API_PORT WEB_PORT OTP_PORT < <("$PYTHON" - <<'PY'
import socket

sockets = []
try:
    for _ in range(3):
        current = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        current.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        current.bind(("127.0.0.1", 0))
        current.listen(1)
        sockets.append(current)
    print(*(item.getsockname()[1] for item in sockets))
finally:
    for current in sockets:
        current.close()
PY
)
for port in "$API_PORT" "$WEB_PORT" "$OTP_PORT"; do
  [[ "$port" =~ ^[1-9][0-9]{0,4}$ && "$port" -le 65535 ]] || exit 2
done
[[ "$API_PORT" != "$WEB_PORT" && "$API_PORT" != "$OTP_PORT" && "$WEB_PORT" != "$OTP_PORT" ]] \
  || exit 2

PYTHONPATH="$ROOT/backend" "$PYTHON" \
  "$ROOT/backend/scripts/nyay5_browser_gate_control.py" create \
  --control-url "$CONTROL_URL" --state-file "$STATE_FILE" \
  >"$PRIVATE_DIR/create-summary.json" 2>"$PRIVATE_DIR/create-error.log"
CREATED=1
SCRATCH_URL="$("$PYTHON" - "$STATE_FILE" <<'PY'
import json
from pathlib import Path
import sys

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
url = value.get("database_url")
if not isinstance(url, str) or not url.startswith("postgresql+psycopg://"):
    raise SystemExit("invalid private scratch state")
print(url)
PY
)"

(
  cd "$ROOT/backend"
  APP_ENV=testing DATABASE_URL="$SCRATCH_URL" \
    REGISTRATION_SECRET='nyay5-browser-synthetic-registration-key-v1' \
    REGISTRATION_LOOKUP_SECRET='nyay5-browser-synthetic-lookup-key-v1' \
    NYAY19_ISOLATED_MIGRATION_EXECUTE=1 \
    "$PYTHON" -m alembic upgrade head
) >"$PRIVATE_DIR/migration.log" 2>&1
POSTGRES_READY=true

APP_ENV=testing DATABASE_URL="$SCRATCH_URL" \
  REGISTRATION_SECRET='nyay5-browser-synthetic-registration-key-v1' \
  REGISTRATION_LOOKUP_SECRET='nyay5-browser-synthetic-lookup-key-v1' \
  PYTHONPATH="$ROOT/backend" "$PYTHON" \
  "$ROOT/backend/scripts/nyay5_browser_gate_control.py" seed-denials \
  --database-url "$SCRATCH_URL" --output "$DENIAL_FILE" \
  >"$PRIVATE_DIR/denial-summary.json" 2>"$PRIVATE_DIR/denial-error.log"

"$PYTHON" "$ROOT/backend/scripts/otp_capture_server.py" \
  --host 127.0.0.1 --port "$OTP_PORT" >"$OTP_LOG" 2>&1 &
OTP_PID=$!

(
  cd "$ROOT/backend"
  exec env \
    APP_ENV=testing \
    DATABASE_URL="$SCRATCH_URL" \
    CORS_ORIGINS="[\"http://localhost:$WEB_PORT\"]" \
    REGISTRATION_SECRET='nyay5-browser-synthetic-registration-key-v1' \
    REGISTRATION_LOOKUP_SECRET='nyay5-browser-synthetic-lookup-key-v1' \
    OTP_DELIVERY_ENABLED=true \
    OTP_PROVIDER=http \
    OTP_PROVIDER_URL="http://127.0.0.1:$OTP_PORT/send" \
    OTP_PROVIDER_TOKEN='nyay5-browser-synthetic-provider-token-v1' \
    OTP_PROVIDER_SUPPORTS_IDEMPOTENCY=true \
    OTP_RESEND_COOLDOWN_SECONDS=1 \
    OTP_ISSUE_IDENTITY_LIMIT=100 \
    OTP_ISSUE_IP_LIMIT=1000 \
    OTP_ISSUE_GLOBAL_LIMIT=100000 \
    "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 \
      --port "$API_PORT" --no-access-log
) >"$API_LOG" 2>&1 &
API_PID=$!

wait_http() {
  local endpoint="$1"
  local process_id="$2"
  for _ in $(seq 1 120); do
    if curl --fail --silent --show-error "$endpoint" >/dev/null 2>&1; then
      return 0
    fi
    kill -0 "$process_id" 2>/dev/null || return 1
    sleep 0.25
  done
  return 1
}
wait_http "http://127.0.0.1:$OTP_PORT/health" "$OTP_PID"
OTP_READY=true
wait_http "http://127.0.0.1:$API_PORT/health" "$API_PID"
API_READY=true

(
  cd "$ROOT/frontend"
  VITE_API_BASE_URL="http://localhost:$API_PORT" npm run build
) >"$BUILD_LOG" 2>&1
(
  cd "$ROOT/frontend"
  NYAY18_PREVIEW_ROOT="$ROOT/frontend/dist" \
    NYAY18_PREVIEW_PORT="$WEB_PORT" \
    exec node scripts/nyay18-preview-server.mjs
) >"$PREVIEW_LOG" 2>&1 &
PREVIEW_PID=$!
wait_http "http://127.0.0.1:$WEB_PORT/" "$PREVIEW_PID"
PREVIEW_READY=true

EXECUTED=true
set +e
(
  cd "$ROOT/frontend"
  NYAY5_WEB_BASE_URL="http://localhost:$WEB_PORT" \
  NYAY5_API_BASE_URL="http://localhost:$API_PORT" \
  NYAY5_OTP_CAPTURE_URL="http://127.0.0.1:$OTP_PORT" \
  NYAY5_DENIAL_FIXTURE_PATH="$DENIAL_FILE" \
  NYAY5_SCREENSHOT_DIR="$SCREENSHOT_DIR" \
  NYAY5_EVIDENCE_PATH="$OUTPUT_PATH" \
    npm run qa:nyay5:profile-boundary
)
BROWSER_EXIT_CODE=$?
set -e
[[ "$BROWSER_EXIT_CODE" -eq 0 ]]
"$PYTHON" - "$OUTPUT_PATH" <<'PY'
import json
from pathlib import Path
import sys

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("status") != "PASS" or value.get("executed") is not True:
    raise SystemExit("browser report did not pass")
PY
for service_log in "$API_LOG" "$OTP_LOG" "$PREVIEW_LOG" "$BUILD_LOG"; do
  [[ -f "$service_log" && ! -L "$service_log" ]] || {
    printf 'expected private service log was not captured\n' >&2
    exit 1
  }
done
SERVICE_LOGS_CAPTURED=true
SERVICE_WORKER_ACTIVE=true
MAIN_SUCCESS=true

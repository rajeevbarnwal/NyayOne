#!/usr/bin/env bash
# Isolated production-build Chromium producer for the NYAY-18 browser/mobile
# namespace boundary. Runtime logs stay in a mode-0700 temporary directory;
# only the sanitized, contract-validated report and screenshots enter evidence.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ "$#" -ne 1 || -z "$1" || "$1" != /* || "$1" != *.json ]]; then
  printf 'usage: %s /absolute/outside-repository/results.json\n' "$0" >&2
  exit 2
fi
OUTPUT="$1"
case "$OUTPUT" in
  "$ROOT"/*)
    printf 'NYAY-18 evidence must be outside the repository\n' >&2
    exit 2
    ;;
esac

for command_name in git node npm curl python3; do
  command -v "$command_name" >/dev/null || {
    printf 'required local runtime unavailable: %s\n' "$command_name" >&2
    exit 2
  }
done

PRIVATE_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
PRIVATE_DIR="$(mktemp -d "$PRIVATE_ROOT/nyay18-browser.XXXXXX")"
chmod 0700 "$PRIVATE_DIR"
BUILD_LOG="$PRIVATE_DIR/build.log"
PREVIEW_LOG="$PRIVATE_DIR/preview.log"
PREVIEW_PID=''

cleanup() {
  local original_status=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n "$PREVIEW_PID" ]]; then
    kill "$PREVIEW_PID" 2>/dev/null
    wait "$PREVIEW_PID" 2>/dev/null
  fi
  case "$PRIVATE_DIR" in
    "$PRIVATE_ROOT"/nyay18-browser.*) rm -rf -- "$PRIVATE_DIR" ;;
    *) original_status=1 ;;
  esac
  exit "$original_status"
}
trap cleanup EXIT INT TERM

PORT="$(python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as current:
    current.bind(("127.0.0.1", 0))
    print(current.getsockname()[1])
PY
)"
[[ "$PORT" =~ ^[1-9][0-9]{0,4}$ && "$PORT" -le 65535 ]] || exit 2
WEB_ORIGIN="http://127.0.0.1:$PORT"
EXACT_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
EXACT_TREE="$(git -C "$ROOT" rev-parse 'HEAD^{tree}')"
PREVIEW_SOURCE_SHA256="$(python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$ROOT/frontend/scripts/nyay18-preview-server.mjs")"
EXACT_PARENT='ROOT'
PARENT_LINE="$(git -C "$ROOT" rev-list --parents -n 1 HEAD)"
read -r -a HEAD_PARENTS <<< "$PARENT_LINE"
if [[ "${#HEAD_PARENTS[@]}" -gt 1 ]]; then
  EXACT_PARENT="${HEAD_PARENTS[1]}"
fi
[[ "$EXACT_COMMIT" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$EXACT_TREE" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$EXACT_PARENT" == 'ROOT' || "$EXACT_PARENT" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$PREVIEW_SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] || exit 2

mkdir -p "$(dirname "$OUTPUT")"
(
  cd "$ROOT/frontend"
  VITE_API_BASE_URL="$WEB_ORIGIN" npm run build
) >"$BUILD_LOG" 2>&1
(
  cd "$ROOT/frontend"
  NYAY18_PREVIEW_ROOT="$ROOT/frontend/dist" \
    NYAY18_PREVIEW_PORT="$PORT" \
    exec node scripts/nyay18-preview-server.mjs
) >"$PREVIEW_LOG" 2>&1 &
PREVIEW_PID=$!

preview_ready=false
for _ in $(seq 1 120); do
  if curl --fail --silent --show-error "$WEB_ORIGIN/" >/dev/null 2>&1; then
    preview_ready=true
    break
  fi
  kill -0 "$PREVIEW_PID" 2>/dev/null || break
  sleep 0.25
done
if [[ "$preview_ready" != true ]]; then
  printf 'NYAY-18 production preview did not become ready\n' >&2
  exit 1
fi

(
  cd "$ROOT/frontend"
  NYAY18_WEB_URL="$WEB_ORIGIN" \
    NYAY18_EVIDENCE_PATH="$OUTPUT" \
    NYAY18_EXACT_COMMIT="$EXACT_COMMIT" \
    NYAY18_EXACT_TREE="$EXACT_TREE" \
    NYAY18_EXACT_PARENT="$EXACT_PARENT" \
    NYAY18_PREVIEW_SOURCE_SHA256="$PREVIEW_SOURCE_SHA256" \
    npm run qa:nyay18:browser-namespace
)

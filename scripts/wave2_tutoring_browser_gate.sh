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
#                      neg=negative states (includes n45) rl=rate limit
#                      n45=media-plane disconnect/reconnect on the production
#                          live room, over its real VideoRoomClient boundary
#                      geo=I2 geometry/a11y priv=J1 privacy
#                      none=boot the servers, run no browser work
#     --search-limit N RATE_LIMIT_TUTOR_SEARCH_PER_MIN (default: 200)
#     --booking-limit N RATE_LIMIT_BOOKING_PER_MIN     (default: 400)
#     --stub-lib DIR   dir to PREPEND to LD_LIBRARY_PATH (arm64 libXdamage stub)
#     --keep-db        reuse the existing database and fixture (stage chaining)
#     --no-build       reuse frontend/dist as-is (it must already point at --api-port)
#     --api-port N     backend port                   (default: atomically allocated)
#     --web-port N     frontend port                  (default: atomically allocated)
#     --run-id S       isolation key for the database directory (default: derived)
#     --fee-paise N    the price the DRIVER expects the API to publish
#                      (default: 250000 = INR 2500.00, which is what
#                      app/services/tutoring/seed.py seeds). This is an
#                      ASSERTION, not a setting: the frontend no longer takes a
#                      fee from the environment — VITE_TUTORING_SESSION_FEE_PAISE
#                      is gone, and the price comes from the API.
#
#   Environment:
#     PYTHON           interpreter with backend deps installed. If set it is
#                      used VERBATIM. If unset, only PROJECT VIRTUALENVS are
#                      considered (see "python selection" below) — never a bare
#                      python3, never an interpreter under /tmp. Either way the
#                      chosen interpreter must (a) import every dependency
#                      declared in backend/requirements.txt and (b) match
#                      backend/requirements.lock version for version, or the run
#                      stops BEFORE any service starts with a prerequisite
#                      message naming exactly what is missing or mismatched.
#                      The project virtualenv is backend/.venv; build it with
#                        python3 -m venv backend/.venv
#                        backend/.venv/bin/python -m pip install -r backend/requirements.lock
#     LD_LIBRARY_PATH  prepend an arm64 libXdamage stub dir if Chromium needs one
#
#   Database isolation (F4.4):
#     Every invocation without --keep-db creates ONE NEW database in a directory
#     keyed by --run-id, migrates it with the real alembic head and seeds it with
#     the deterministic fixture. The reset boundaries are exactly:
#       * RUN boundary   — `--keep-db` absent: the file is deleted and rebuilt
#                          from alembic head + `wave2_e2e_fixture.py seed`, and
#                          the driver's state.json/journeys.json are cleared, so
#                          no row and no verdict survives from a previous run.
#       * STAGE boundary — `--keep-db` present: NOTHING is reset. The database,
#                          the fixture id map and the driver state carry across
#                          the chained 45s shells that make up one logical run.
#     There is no other reset point: no stage truncates, re-seeds or re-migrates.
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
RUN_ID="${WAVE2_RUN_ID:-}"

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
    --run-id) RUN_ID="$2"; shift 2 ;;
    -h|--help) sed -n '2,45p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# ------------------------------------------------------- F3: python selection
#
# Deterministic, in this order, and NEVER a silent fall-through:
#
#   1. an explicit PYTHON= — used verbatim, no search, no substitution;
#   2. otherwise the first PROJECT VIRTUALENV that exists, from a fixed list.
#
# A bare `python3` from PATH is deliberately NOT a candidate: on this host it is
# a different interpreter with a different fastapi and no psycopg/pgvector, and
# picking it up silently is precisely how a gate ends up testing the wrong tree.
# Whatever is chosen is then made to PROVE it can import every dependency
# declared in backend/requirements.txt before a single server is started.
PYTHON_SOURCE=""
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_SOURCE="explicit PYTHON= environment variable"
  [[ -x "$PYTHON" ]] || command -v "$PYTHON" > /dev/null 2>&1 || {
    cat >&2 <<EOF
PREREQUISITE NOT MET: PYTHON="$PYTHON" is not an executable interpreter.
  Point PYTHON= at a python that has the backend dependencies installed, e.g.
      PYTHON=/path/to/venv/bin/python bash scripts/wave2_tutoring_browser_gate.sh
EOF
    exit 2
  }
else
  # NOTE: no /tmp interpreter and no bare `python3`. An interpreter that the
  # repository does not own and does not declare must never be the DEFAULT —
  # that is how a gate silently reports on a dependency set nobody chose.
  #
  # PLATFORM-SCOPED FIRST. `backend/.venv` is a single path shared by every
  # machine that checks this repo out, and a virtualenv is machine-bound: its
  # pyvenv.cfg names a builder interpreter and its site-packages hold ABI-tagged
  # binaries (`*.cpython-310-aarch64-linux-gnu.so` is a Linux/arm64 ELF object).
  # Built on Linux and read on macOS, the SAME directory is healthy on one host
  # and unusable on the other, and the version-only lock check cannot say so.
  # `.venv-$(uname -s)-$(uname -m)` is a name two operating systems cannot
  # collide in; the shared `.venv` is still accepted, but ONLY after it proves
  # it belongs to this machine (check_runtime_lock.py --platform-only).
  PLATFORM_VENV=".venv-$(uname -s)-$(uname -m)"
  VENV_CANDIDATES=(
    "${VIRTUAL_ENV:-/nonexistent}/bin/python"
    "$REPO_ROOT/backend/$PLATFORM_VENV/bin/python"
    "$REPO_ROOT/$PLATFORM_VENV/bin/python"
    "$REPO_ROOT/backend/.venv/bin/python"
    "$REPO_ROOT/.venv/bin/python"
    "$REPO_ROOT/venv/bin/python"
  )
  PLATFORM_REJECTED=""
  for cand in "${VENV_CANDIDATES[@]}"; do
    [[ -x "$cand" ]] || continue
    if PLAT_REPORT="$("$cand" "$REPO_ROOT/backend/scripts/check_runtime_lock.py" --platform-only 2>&1)"; then
      PYTHON="$cand"
      PYTHON_SOURCE="project virtualenv (platform-verified)"
      break
    fi
    PLATFORM_REJECTED+="  REJECTED $cand"$'\n'"$(printf '%s\n' "$PLAT_REPORT" | sed 's/^/  | /')"$'\n'
  done
fi
if [[ -z "${PYTHON:-}" ]]; then
  cat >&2 <<EOF
PREREQUISITE NOT MET: no project virtualenv for THIS platform ($(uname -s)/$(uname -m))
was found, and PYTHON= was not set.
  Searched (in order):
$(printf '      %s\n' "${VENV_CANDIDATES[@]}")
${PLATFORM_REJECTED:+
  A candidate existed but does not belong to this machine:
$PLATFORM_REJECTED}
  A system python3 is NOT used as a fallback on purpose: it would silently run
  the gate against a different interpreter than the backend is installed into.
  Fix by creating the PLATFORM-SCOPED virtualenv and installing the lock into
  it (do NOT reuse a .venv another operating system built):
      python3 -m venv $REPO_ROOT/backend/${PLATFORM_VENV:-.venv}
      $REPO_ROOT/backend/${PLATFORM_VENV:-.venv}/bin/python -m pip install -r $REPO_ROOT/backend/requirements.lock
  or by setting PYTHON= explicitly.
EOF
  exit 2
fi

# ---- the chosen interpreter must import the DECLARED backend dependencies ----
# The list is read from backend/requirements.txt at run time, so a dependency
# added to the backend is checked here without anybody remembering to edit this
# script. Only the distribution->module names that differ are mapped.
DEP_REPORT="$("$PYTHON" - "$REPO_ROOT/backend/requirements.txt" <<'PY' 2>&1
import importlib.util, json, re, sys

OVERRIDES = {
    "pydantic-settings": "pydantic_settings",
    "python-multipart": "multipart",
    "uvicorn[standard]": "uvicorn",
    "psycopg[binary]": "psycopg",
}
missing, checked = [], []
try:
    lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
except OSError as exc:
    print(json.dumps({"error": f"cannot read requirements.txt: {exc}"}))
    raise SystemExit(0)
for line in lines:
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        continue
    spec = re.split(r"[<>=!~;]", line, 1)[0].strip()
    module = OVERRIDES.get(spec, OVERRIDES.get(spec.split("[")[0], spec.split("[")[0]))
    module = module.replace("-", "_")
    checked.append(f"{spec} -> import {module}")
    try:
        found = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        found = False
    if not found:
        missing.append({"requirement": line, "module": module})
print(json.dumps({"checked": checked, "missing": missing,
                  "executable": sys.executable, "version": sys.version.split()[0]}))
PY
)"
DEP_MISSING="$("$PYTHON" -c 'import json,sys; d=json.loads(sys.stdin.read()); print("\n".join("      %s  (missing module: %s)" % (m["requirement"], m["module"]) for m in d.get("missing", [])) or "")' <<< "$DEP_REPORT" 2> /dev/null)"
if [[ -n "$DEP_MISSING" || "$DEP_REPORT" != *'"missing"'* ]]; then
  cat >&2 <<EOF
PREREQUISITE NOT MET: the selected python cannot import the backend's declared
dependencies, so this gate would test something other than the real backend.

  interpreter : $PYTHON
  chosen via  : ${PYTHON_SOURCE:-unknown}
  declared in : $REPO_ROOT/backend/requirements.txt

  MISSING:
${DEP_MISSING:-      (the dependency probe itself failed: $DEP_REPORT)}

  Fix by installing them into THAT interpreter:
      $PYTHON -m pip install -r $REPO_ROOT/backend/requirements.txt
  or by pointing PYTHON= at an interpreter that already has them.
EOF
  exit 2
fi
PY_VERSION="$("$PYTHON" -c 'import sys; print(sys.version.split()[0])')"
printf 'python: %s (%s, %s) — all backend/requirements.txt imports resolve\n' \
  "$PYTHON" "$PYTHON_SOURCE" "$PY_VERSION"
HOST_PLATFORM="$(uname -s)/$(uname -m)"
printf 'platform: %s  platform-scoped venv: %s\n' \
  "$HOST_PLATFORM" "${PLATFORM_VENV:-<not searched: explicit PYTHON=>}"

# ---- and it must MATCH backend/requirements.lock, version by version (F2.5) --
# "It imports" is not "it is the tested set". This runs BEFORE the database, the
# migration, the backend and the frontend, so a mismatched interpreter cannot
# produce one line of gate evidence.
LOCK_FILE="$REPO_ROOT/backend/requirements.lock"
LOCK_REPORT="$("$PYTHON" "$REPO_ROOT/backend/scripts/check_runtime_lock.py" \
  --header --lock "$LOCK_FILE" 2>&1)"
LOCK_RC=$?
printf '%s\n' "$LOCK_REPORT"
if [[ $LOCK_RC -ne 0 ]]; then
  echo "refusing to boot the gate against an interpreter outside the lock" >&2
  exit 2
fi

# --------------------------------------------- F4.3: ATOMIC port allocation
#
# Both listening sockets are bound SIMULTANEOUSLY inside one process, so the
# kernel itself guarantees they are two different, currently-free ports; only
# then are they released and handed to uvicorn/vite. Allocating them one at a
# time (bind, close, bind, close) can hand back the same port twice, which is
# the collision this replaces. An explicitly supplied port is honoured but is
# still bind-tested, and the two are asserted DISTINCT before anything boots.
ALLOC="$("$PYTHON" - "${API_PORT:-0}" "${WEB_PORT:-0}" <<'PY'
import socket, sys

want = [int(sys.argv[1]), int(sys.argv[2])]
held = []
try:
    for wanted in want:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            s.bind(("127.0.0.1", wanted))
        except OSError as exc:
            s.close()
            print(f"ERROR port {wanted} is not bindable: {exc}")
            raise SystemExit(0)
        held.append(s)
    ports = [s.getsockname()[1] for s in held]
    if len(set(ports)) != len(ports):
        print(f"ERROR the kernel returned duplicate ports {ports}")
        raise SystemExit(0)
    print(f"OK {ports[0]} {ports[1]}")
finally:
    for s in held:
        s.close()
PY
)"
case "$ALLOC" in
  OK\ *) read -r _ API_PORT WEB_PORT <<< "$ALLOC" ;;
  *) echo "port allocation failed: ${ALLOC#ERROR }" >&2; exit 2 ;;
esac
if [[ -z "$API_PORT" || -z "$WEB_PORT" ]]; then
  echo "port allocation produced an empty port (api='$API_PORT' web='$WEB_PORT')" >&2; exit 2
fi
if [[ "$API_PORT" == "$WEB_PORT" ]]; then
  echo "PORT COLLISION: api and frontend were both allocated $API_PORT; refusing to boot" >&2
  exit 2
fi
printf 'ports: api=%s web=%s (allocated atomically, asserted distinct)\n' "$API_PORT" "$WEB_PORT"

mkdir -p "$OUT" "$OUT/shots" "$OUT/logs"
WORK="$OUT/work"
mkdir -p "$WORK"
# The database lives on LOCAL disk, never in --out: an --out on a FUSE/network
# mount cannot give SQLite the file locks it needs ("disk I/O error" on the very
# first CREATE TABLE). Artifacts are ordinary writes and stay in --out.
#
# ONE ISOLATED DATABASE PER RUN (F4.4). The directory is keyed by --run-id, which
# defaults to a stable hash of --out, so two gates driving two different evidence
# directories can never share rows, and the chained 45s shells of a single run
# (which all pass the same --out) deterministically find the same file.
if [[ -z "$RUN_ID" ]]; then
  RUN_ID="$("$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:12])' "$OUT")"
fi
DB_DIR="${WAVE2_DB_DIR:-${TMPDIR:-/tmp}/wave2_browser_gate}/$RUN_ID"
mkdir -p "$DB_DIR"
DB_FILE="$DB_DIR/wave2_browser_gate.db"
FIXTURE="$WORK/fixture.json"
ADMIN_SESSION_TOKEN_FILE="$DB_DIR/admin-session-token"
STUDENT_SESSION_TOKEN_FILE="$DB_DIR/student-session-token"
API_LOG="$OUT/logs/backend_uvicorn.log"
WEB_LOG="$OUT/logs/frontend_preview.log"

# M-01 is administrator-only in Sprint 1.  Its isolated browser bearer is
# generated into the database scratch directory (never --out/evidence), kept
# mode 0600 for chained --keep-db stages, and supplied only by environment.
# The fixture stores its keyed hash; neither fixture JSON nor logs contain it.
if [[ "$KEEP_DB" == "0" ]]; then
  umask 077
  "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))' \
    > "$ADMIN_SESSION_TOKEN_FILE"
  "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))' \
    > "$STUDENT_SESSION_TOKEN_FILE"
  chmod 600 "$ADMIN_SESSION_TOKEN_FILE"
  chmod 600 "$STUDENT_SESSION_TOKEN_FILE"
else
  [[ -f "$ADMIN_SESSION_TOKEN_FILE" ]] || {
    echo "--keep-db but the private administrator session bearer is absent" >&2
    exit 2
  }
  [[ -f "$STUDENT_SESSION_TOKEN_FILE" ]] || {
    echo "--keep-db but the private student session bearer is absent" >&2
    exit 2
  }
fi
ADMIN_SESSION_TOKEN="$(< "$ADMIN_SESSION_TOKEN_FILE")"
STUDENT_SESSION_TOKEN="$(< "$STUDENT_SESSION_TOKEN_FILE")"
[[ ${#ADMIN_SESSION_TOKEN} -ge 32 ]] || {
  echo "isolated administrator session bearer is malformed" >&2
  exit 2
}
[[ ${#STUDENT_SESSION_TOKEN} -ge 32 ]] || {
  echo "isolated student session bearer is malformed" >&2
  exit 2
}
[[ "$STUDENT_SESSION_TOKEN" != "$ADMIN_SESSION_TOKEN" ]] || {
  echo "student and administrator session bearers must be distinct" >&2
  exit 2
}

# --------------------------------------------- F3: the commit under judgement
# Stamped into every evidence row by the driver so a result produced at another
# commit cannot pass as this run's. Read-only; the worktree is never touched.
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD 2> /dev/null || echo '')"
if [[ -z "$COMMIT_SHA" ]]; then
  echo "PREREQUISITE NOT MET: cannot read the commit under test (git rev-parse HEAD failed)." >&2
  echo "  Evidence that cannot name its commit is not evidence; refusing to boot." >&2
  exit 2
fi
printf 'commit under test: %s\n' "$COMMIT_SHA"

# --------------------------------------- F3: RUN boundary for the raw logs
# The byte offset the backend-log oracle uses to judge each stage on the region
# IT produced lives in the driver's state.json. On a RUN boundary state.json is
# deleted, so the offset restarts at 0 — which means the log has to restart at 0
# too, or the new run would re-read the PREVIOUS run's bytes and attribute them
# to its own first stage. The previous file is kept as `.prev`, never discarded.
# On a STAGE boundary (--keep-db) nothing is rotated: offset and log both carry.
if [[ "$KEEP_DB" == "0" ]]; then
  for f in "$OUT/logs/backend_uvicorn.log" "$OUT/logs/frontend_preview.log"; do
    [[ -f "$f" ]] && mv -f "$f" "$f.prev"
  done
fi

# ------------------------------------------------- F2.4: provenance in the logs
# The interpreter and the RESOLVED version of every pinned package are stamped
# into each raw log this run appends to, so a log read on its own still names
# the dependency set that produced it. Appended (never truncating), because the
# chained 45s shells of one logical run share these files.
RUNTIME_HEADER="$(
  printf '==== runtime provenance (%s) ====\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'interpreter: %s (%s, %s)\n' "$PYTHON" "$PYTHON_SOURCE" "$PY_VERSION"
  printf 'host platform: %s  platform-scoped venv: %s\n' \
    "$HOST_PLATFORM" "${PLATFORM_VENV:-<not searched: explicit PYTHON=>}"
  printf 'runtime lock: %s\n' "$LOCK_FILE"
  printf '%s\n' "$LOCK_REPORT"
  printf '==== end runtime provenance ====\n'
)"
printf '%s\n' "$RUNTIME_HEADER" | tee "$OUT/logs/runtime_versions.log" \
  >> "$API_LOG"
printf '%s\n' "$RUNTIME_HEADER" >> "$WEB_LOG"
printf '%s\n' "$RUNTIME_HEADER" >> "$OUT/logs/alembic.log"
printf '%s\n' "$RUNTIME_HEADER" >> "$OUT/logs/vite_build.log"

export DATABASE_URL="sqlite+pysqlite:///$DB_FILE"
export PAYMENT_PROVIDER=deterministic
export VIDEO_CALLS_ENABLED=true
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
  step "database: ONE new isolated SQLite at $DB_FILE (run-id $RUN_ID) via alembic upgrade head"
  # RUN reset boundary. Everything derived from a previous run goes with it, so
  # a stale verdict cannot be mistaken for this run's evidence.
  rm -f "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"
  rm -f "$WORK/state.json" "$OUT/journeys.json"
  (cd backend && "$PYTHON" -m alembic upgrade head) >> "$OUT/logs/alembic.log" 2>&1 \
    || { echo "alembic upgrade failed; see $OUT/logs/alembic.log" >&2; exit 3; }
  tail -1 "$OUT/logs/alembic.log"

  step "fixture: seeding tutors, slots and browser actors (deterministic seed)"
  # --days 20 (not the 3-day default): the negative catalogue books a session per
  # accepted-review case and per grant/disconnect case, and every one of them
  # needs its OWN >24h slot. Running out mid-catalogue is a harness failure that
  # looks exactly like a product failure, so the calendar is sized for the whole
  # catalogue with headroom.
  (cd backend && WAVE2_E2E_ADMIN_SESSION_TOKEN="$ADMIN_SESSION_TOKEN" \
    WAVE2_E2E_STUDENT_SESSION_TOKEN="$STUDENT_SESSION_TOKEN" \
    "$PYTHON" scripts/wave2_e2e_fixture.py seed --extra-tutors 12 --days 20) > "$FIXTURE" \
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
  # No fee variable is injected: the bundle reads the price from the API.
  (cd frontend && VITE_API_BASE_URL="http://127.0.0.1:$API_PORT" npx vite build) \
     >> "$OUT/logs/vite_build.log" 2>&1 \
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
E2E_BACKEND_PID="$API_PID" \
E2E_COMMIT="$COMMIT_SHA" \
E2E_FEE_PAISE="$FEE_PAISE" \
E2E_RUN_ID="$RUN_ID" \
E2E_DB_FILE="$DB_FILE" \
E2E_SEARCH_LIMIT="$SEARCH_LIMIT" \
E2E_BOOKING_LIMIT="$BOOKING_LIMIT" \
E2E_REVIEW_LIMIT_PER_HOUR="$RATE_LIMIT_REVIEW_PER_HOUR" \
E2E_HOLD_MINUTES="$BOOKING_HOLD_MINUTES" \
E2E_JOIN_TTL_SECONDS="$JOIN_CREDENTIAL_TTL_SECONDS" \
E2E_FREE_CANCEL_HOURS="$REFUND_FREE_CANCEL_HOURS" \
E2E_ADMIN_SESSION_TOKEN="$ADMIN_SESSION_TOKEN" \
E2E_STUDENT_SESSION_TOKEN="$STUDENT_SESSION_TOKEN" \
  node frontend/scripts/wave2-tutoring-e2e.mjs
DRIVER_RC=$?

# ---------------------------------------- 5. F3: the log tail nobody else sees
#
# The driver judges the backend log as disjoint byte regions and stops at its
# own final harvest. Everything the backend writes AFTER that — a background
# task that blows up once the browser is gone, a shutdown handler that raises —
# is outside every region the driver owns, so this shell scans the remainder
# with the SAME pattern set before it tears anything down. The starting offset
# is the driver's own, read out of state.json, so the two scans meet exactly and
# neither re-reads the other's bytes.
TAIL_SCAN="$("$PYTHON" - "$API_LOG" "$WORK/state.json" <<'PY'
import json, re, sys

PATTERNS = [
    ("level_error", re.compile(r"(?:^|[^A-Za-z_])ERROR(?:[^A-Za-z_]|$)")),
    ("level_critical", re.compile(r"(?:^|[^A-Za-z_])CRITICAL(?:[^A-Za-z_]|$)")),
    ("traceback", re.compile(r"Traceback \(most recent call last\)")),
    ("unhandled_exception", re.compile(r"unhandled_exception")),
    ("asgi_exception", re.compile(r"Exception in ASGI application")),
    ("cannot_commit", re.compile(r"cannot commit", re.I)),
    ("index_error", re.compile(r"\bIndexError\b")),
]
log, state = sys.argv[1], sys.argv[2]
try:
    offset = int(json.load(open(state, encoding="utf-8")).get("backendLogOffset", 0))
except Exception:
    offset = 0
try:
    with open(log, "rb") as fh:
        fh.seek(offset)
        text = fh.read().decode("utf-8", "replace")
except OSError as exc:
    print(f"FAIL cannot read the backend log tail: {exc}")
    raise SystemExit(0)
hits = [
    f"[{','.join(i for i, p in PATTERNS if p.search(line))}] {line[:240]}"
    for line in text.splitlines()
    if any(p.search(line) for _, p in PATTERNS)
]
if hits:
    print("FAIL " + str(len(hits)) + " finding(s) after byte " + str(offset))
    for h in hits[:10]:
        print("    " + h)
else:
    print(f"OK no runtime-error line in the {len(text)} byte(s) written after the driver's final region (from byte {offset})")
PY
)"
printf 'backend log tail: %s\n' "${TAIL_SCAN%%$'\n'*}"
if [[ "$TAIL_SCAN" == FAIL* ]]; then
  echo "FAIL-CLOSED: the backend wrote a runtime error AFTER the driver stopped watching:" >&2
  printf '%s\n' "$TAIL_SCAN" >&2
  [[ "$DRIVER_RC" == "0" ]] && DRIVER_RC=5
fi
printf '%s\n' "$TAIL_SCAN" > "$OUT/logs/backend_log_tail_scan.txt"

# ------------------------------------------- 6. F3: backend liveness + EXIT CODE
#
# The driver checks liveness from the outside (pid + /proc state + /health) but
# it can never learn the backend's EXIT CODE: uvicorn is this shell's child, not
# the driver's, so only this shell can reap it. A backend that died or exited
# non-zero fails the run REGARDLESS of what the browser managed to assert before
# it went — a green stage list on top of a dead server is precisely the false
# pass this gate exists to prevent.
BACK_STATE="alive"
if [[ -r "/proc/$API_PID/stat" ]]; then
  # field 3 of /proc/<pid>/stat, read after the ")" so a comm with spaces or
  # parentheses cannot shift the columns.
  BACK_STATE="$(awk '{ s=$0; sub(/^.*\) /, "", s); split(s, f, " "); print f[1] }' "/proc/$API_PID/stat" 2> /dev/null || echo GONE)"
  [[ "$BACK_STATE" == "Z" || "$BACK_STATE" == "X" ]] && BACK_STATE="dead"
  [[ "$BACK_STATE" != "dead" && "$BACK_STATE" != "GONE" ]] && BACK_STATE="alive"
elif ! kill -0 "$API_PID" 2> /dev/null; then
  BACK_STATE="dead"
fi
BACK_RC=""
if [[ "$BACK_STATE" != "alive" ]]; then
  wait "$API_PID" 2> /dev/null
  BACK_RC=$?
fi
printf '{ "pid": %s, "state": "%s", "exitCode": %s, "driverExit": %s, "verdict": "%s" }\n' \
  "$API_PID" "$BACK_STATE" "${BACK_RC:-null}" "$DRIVER_RC" \
  "$([[ "$BACK_STATE" == "alive" ]] && echo 'backend survived the run' || echo 'BACKEND DIED DURING THE RUN')" \
  > "$OUT/logs/backend_exit.json"
if [[ "$BACK_STATE" != "alive" ]]; then
  cat >&2 <<EOF

FAIL-CLOSED: the backend process (pid $API_PID) did NOT survive the run.
  state     : $BACK_STATE
  exit code : ${BACK_RC:-unknown}
  last log  :
$(tail -12 "$API_LOG" 2> /dev/null | sed 's/^/      /')
  Recorded in $OUT/logs/backend_exit.json. The run FAILS whatever the driver said.
EOF
  [[ "$DRIVER_RC" == "0" ]] && DRIVER_RC=4
elif [[ -n "$BACK_RC" && "$BACK_RC" != "0" ]]; then
  echo "FAIL-CLOSED: the backend exited non-zero ($BACK_RC)." >&2
  [[ "$DRIVER_RC" == "0" ]] && DRIVER_RC=4
fi

step "result: driver exit $DRIVER_RC · backend $BACK_STATE${BACK_RC:+ (exit $BACK_RC)} · artifacts in $OUT"
exit $DRIVER_RC

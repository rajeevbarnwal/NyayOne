#!/usr/bin/env bash
# LiveKit Community + TURN live smoke test. SAATHI-451 / Wave 2 correction F8.
#
#   ONE command:  bash infra/video/scripts/livekit_turn_smoke.sh
#
# This script IS the definition of RUNBOOK § 9. Every step below carries a step
# id (S1..S11); RUNBOOK § 9 lists exactly those ids with exactly these titles,
# and backend/tests/test_wave2_runtime_gates.py fails the build if the two ever
# disagree — so the runbook and the script cannot drift apart.
#
# It FAILS CLOSED. Any step that does not produce its documented observable
# stops the run and exits non-zero. A prerequisite that is missing is NOT a
# failure and NOT a pass: it prints
#     BLOCKED: prerequisite runtime absent
# and exits 78, listing every missing prerequisite at once.
#
# Steps (== RUNBOOK § 9):
#   S1  container/service health                      (§ 9 item 1)
#   S2  server-created room                           (§ 9 item 2)
#   S3  short-lived participant-bound join grant      (§ 9 item 2)
#   S4  two-browser join smoke                        (§ 9 item 2 / item 3c)
#   S5  camera and microphone denial                  (§ 9 item 3c, browser)
#   S6  reconnect                                     (§ 9 item 4)
#   S7  token expiry and revocation                   (§ 9 item 4)
#   S8  webhook verification and replay rejection     (§ 9 item 6)
#   S9  FORCED-TURN smoke test (the media path)       (§ 9 item 3)
#   S10 provider unreachable, fail-closed             (§ 9 item 5)
#   S11 no raw token, SDP or ICE persisted            (§ 9 item 6, storage side)
#
# Options:
#   --out DIR        evidence directory (default: test-results/livekit-smoke)
#   --steps LIST     comma list of step ids to run  (default: all)
#   --list           print the step contract and exit 0
#   --skip-browser   run without S4/S5/S6 (they need Playwright + a media stack)
#
# Environment (all REQUIRED unless noted):
#   LIVEKIT_URL             http(s) base of the SFU, e.g. http://localhost:1039
#   LIVEKIT_API_KEY         the key in the rendered livekit.yaml `keys:` map
#   LIVEKIT_API_SECRET      its secret; also verifies webhooks
#   SMOKE_SESSION_ID        a CONFIRMED, PAID tutoring session id to join
#   SMOKE_AUTH_HEADER       an Authorization/X-Actor-Claims header for a
#                           participant of that session, e.g.
#                           'X-Actor-Claims: {"sub":"...","roles":["student"]}'
#   SMOKE_TUTOR_AUTH_HEADER the same for the other participant (second browser)
#   BACKEND_URL             default http://localhost:1031
#   DATABASE_URL            (S11 only) the backend's PostgreSQL URL
#   TURN_EXTERNAL_IP        (S9 only) the relay address clients are handed
#   PYTHON                  interpreter with backend/requirements.txt (S11)
#   LIVEKIT_CLIENT_BUNDLE   (S4/S5/S6) URL of the livekit-client UMD bundle the
#                           driver injects. Default:
#                           https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js
#   SMOKE_COMPOSE_OVERRIDE  optional compose overlay used by an isolated QA rig
#   SMOKE_BROWSER_LIVEKIT_URL browser-reachable signalling URL when it differs
#                           from the host/operator LIVEKIT_URL
#   SMOKE_BROWSER_ORIGIN      optional same-network HTTP(S) page origin used by
#                           an isolated browser; defaults to the SDK origin
#   SMOKE_CHROMIUM_CDP_URL  optional in-network Chromium CDP endpoint; S5 uses
#                           SMOKE_DENIED_CHROMIUM_CDP_URL for its denial browser
#
# Exit codes:  0 = every step passed
#              1 = a step FAILED (the run stopped there)
#             78 = BLOCKED: prerequisite runtime absent (nothing was proven)
set -uo pipefail

BLOCKED_EXIT=78
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$REPO_ROOT" || exit 2

OUT="$REPO_ROOT/test-results/livekit-smoke"
STEPS="S1,S2,S3,S4,S5,S6,S7,S8,S9,S10,S11"
SKIP_BROWSER=0
LIST_ONLY=0

# The step contract. ONE definition, consumed by --list, by the runbook check
# and by the runner below. Format: id|title
STEP_CONTRACT=(
  "S1|container/service health"
  "S2|server-created room"
  "S3|short-lived participant-bound join grant"
  "S4|two-browser join smoke"
  "S5|camera and microphone denial"
  "S6|reconnect"
  "S7|token expiry and revocation"
  "S8|webhook verification and replay rejection"
  "S9|FORCED-TURN smoke test (the media path)"
  "S10|provider unreachable, fail-closed"
  "S11|no raw token, SDP or ICE persisted"
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --skip-browser) SKIP_BROWSER=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    -h|--help) sed -n '2,60p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ $LIST_ONLY -eq 1 ]]; then
  for row in "${STEP_CONTRACT[@]}"; do printf '%s\n' "${row/|/  }"; done
  exit 0
fi

COMPOSE_BASE=(-f docker-compose.yml -f infra/video/docker-compose.video.yml)
if [[ -n "${SMOKE_COMPOSE_OVERRIDE:-}" ]]; then
  COMPOSE_BASE+=(-f "$SMOKE_COMPOSE_OVERRIDE")
fi
BACKEND_URL="${BACKEND_URL:-http://localhost:1031}"
LIVEKIT_CLIENT_BUNDLE="${LIVEKIT_CLIENT_BUNDLE:-https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js}"
RESULTS=()
FAILED=0

want() { [[ ",$STEPS," == *",$1,"* ]]; }

log()  { printf '%s\n' "$*"; }
step_head() { printf '\n-- %s %s --\n' "$1" "$2"; }

record() {
  # id | status | detail
  RESULTS+=("{\"step\":\"$1\",\"status\":\"$2\",\"detail\":\"${3//\"/\\\"}\"}")
  printf '  [%s] %s %s\n' "$2" "$1" "$3"
  if [[ "$2" == "FAIL" ]]; then FAILED=1; fi
}

fail_closed() {
  record "$1" "FAIL" "$2"
  write_summary "FAIL"
  log ""
  log "livekit_turn_smoke: FAILED at $1 — $2"
  log "  Fail-closed: the remaining steps were NOT run, because a media-plane"
  log "  smoke that continues past a failed step reports a green it did not earn."
  exit 1
}

write_summary() {
  mkdir -p "$OUT"
  {
    printf '{"gate":"livekit_turn_smoke","status":"%s","executed":%s,"steps":[' \
      "$1" "$([[ "$1" == "BLOCKED" ]] && echo false || echo true)"
    local first=1
    # `${arr[@]+...}` because bash 3.2 (macOS) treats an empty array as unset
    # under `set -u`, and a summary writer must never be the thing that crashes.
    for row in ${RESULTS[@]+"${RESULTS[@]}"}; do
      [[ $first -eq 1 ]] || printf ','
      printf '%s' "$row"
      first=0
    done
    printf ']}\n'
  } > "$OUT/summary.json"
  printf 'LIVEKIT_SMOKE_SUMMARY '
  cat "$OUT/summary.json"
}

# --------------------------------------------------------------------------- #
# S0. Runtime detection. Prints what it found, then refuses if anything the
#     smoke depends on is absent. Reports EVERY missing prerequisite at once.
# --------------------------------------------------------------------------- #
MISSING=()
have() { command -v "$1" > /dev/null 2>&1; }

DOCKER_BIN="$(command -v docker || echo '<absent>')"
LK_BIN="$(command -v lk || echo '<absent>')"
NODE_BIN="$(command -v node || echo '<absent>')"
CURL_BIN="$(command -v curl || echo '<absent>')"

log "== LiveKit Community + TURN smoke =="
log "  gate.script          : infra/video/scripts/livekit_turn_smoke.sh"
log "  runtime.docker       : $DOCKER_BIN"
log "  runtime.lk_cli       : $LK_BIN"
log "  runtime.node         : $NODE_BIN"
log "  runtime.curl         : $CURL_BIN"
log "  runtime.livekit_url  : ${LIVEKIT_URL:-<unset>}"
log "  runtime.backend_url  : $BACKEND_URL"
log "  runtime.rendered_cfg : $([[ -f infra/video/rendered/livekit.yaml ]] && echo present || echo '<absent>')"
if have docker && docker compose version > /dev/null 2>&1; then
  log "  runtime.compose      : $(docker compose version 2>/dev/null | head -1)"
  LIVEKIT_PS="$(docker compose "${COMPOSE_BASE[@]}" ps --format '{{.Service}} {{.Status}}' 2>/dev/null | tr '\n' ';')"
  log "  runtime.services     : ${LIVEKIT_PS:-<none running>}"
else
  log "  runtime.compose      : <absent>"
fi

have docker || MISSING+=("docker (the media plane runs in containers)")
if have docker && ! docker compose version > /dev/null 2>&1; then
  MISSING+=("docker compose v2")
fi
have curl || MISSING+=("curl")
[[ -f docker-compose.yml ]] || MISSING+=("docker-compose.yml at the repo root")
[[ -f infra/video/docker-compose.video.yml ]] || MISSING+=("infra/video/docker-compose.video.yml")
if [[ -n "${SMOKE_COMPOSE_OVERRIDE:-}" && ! -f "$SMOKE_COMPOSE_OVERRIDE" ]]; then
  MISSING+=("SMOKE_COMPOSE_OVERRIDE file")
fi
[[ -f infra/video/rendered/livekit.yaml ]] || MISSING+=("infra/video/rendered/livekit.yaml (run scripts/render_video_infra_config.py first)")
[[ -n "${LIVEKIT_URL:-}" ]] || MISSING+=("LIVEKIT_URL")
[[ -n "${LIVEKIT_API_KEY-}" ]] || MISSING+=("LIVEKIT_API_KEY")
[[ -n "${LIVEKIT_API_SECRET-}" ]] || MISSING+=("LIVEKIT_API_SECRET")
[[ -n "${SMOKE_SESSION_ID:-}" ]] || MISSING+=("SMOKE_SESSION_ID (a confirmed, PAID tutoring session)")
[[ -n "${SMOKE_AUTH_HEADER:-}" ]] || MISSING+=("SMOKE_AUTH_HEADER")
want S2 && { have lk || MISSING+=("the LiveKit CLI 'lk' (S2/S4 create and join rooms)"); }
if [[ $SKIP_BROWSER -eq 0 ]] && { want S4 || want S5 || want S6; }; then
  have node || MISSING+=("node (S4/S5/S6 drive two real browsers)")
  [[ -d frontend/node_modules/playwright ]] || MISSING+=("frontend/node_modules/playwright (npm ci && npx playwright install chromium)")
  [[ -n "${SMOKE_TUTOR_AUTH_HEADER:-}" ]] || MISSING+=("SMOKE_TUTOR_AUTH_HEADER (the second browser's participant)")
fi
want S11 && [[ -n "${DATABASE_URL:-}" ]] || { want S11 && MISSING+=("DATABASE_URL (S11 scans raw storage)"); }
want S9 && [[ -n "${TURN_EXTERNAL_IP:-}" ]] || { want S9 && MISSING+=("TURN_EXTERNAL_IP (S9 checks the selected relay address)"); }

if [[ ${#MISSING[@]} -gt 0 ]]; then
  log ""
  log "BLOCKED: prerequisite runtime absent"
  for item in "${MISSING[@]}"; do log "  - missing: $item"; done
  log "  This run proved NOTHING about LiveKit, TURN or media. It is not a pass,"
  log "  and it is not a product failure. Bring the stack up per RUNBOOK § 1,"
  log "  then re-run this exact command."
  write_summary "BLOCKED"
  exit "$BLOCKED_EXIT"
fi

mkdir -p "$OUT"

# --------------------------------------------------------------------------- #
# S1. Container / service health.   RUNBOOK § 9 item 1, § 2.
# --------------------------------------------------------------------------- #
if want S1; then
  step_head S1 "container/service health"
  docker compose "${COMPOSE_BASE[@]}" config -q > "$OUT/s1-config.log" 2>&1 \
    || fail_closed S1 "docker compose config -q did not exit 0"
  docker compose "${COMPOSE_BASE[@]}" ps > "$OUT/s1-ps.log" 2>&1
  # Compose includes a human running-duration between `Up` and `(healthy)`;
  # matching the rendered table text made this gate reject healthy services.
  # Judge the machine-readable State/Health fields instead.
  healthy=$(docker compose "${COMPOSE_BASE[@]}" ps --format json \
    | python3 -c 'import json,sys
required={"coturn","livekit"}; healthy=set()
for raw in sys.stdin:
    if not raw.strip(): continue
    row=json.loads(raw)
    if row.get("Service") in required and row.get("State")=="running" and row.get("Health")=="healthy":
        healthy.add(row["Service"])
print(len(healthy))')
  [[ "$healthy" -ge 2 ]] \
    || fail_closed S1 "expected coturn AND livekit 'Up (healthy)', saw $healthy"
  curl -fsS "$LIVEKIT_URL/" > "$OUT/s1-livekit-root.log" 2>&1 \
    || fail_closed S1 "GET LIVEKIT_URL did not return 2xx"
  # Probe the service inside its container. The host metrics port is an
  # observability convenience and may legitimately be occupied by another
  # local process; that must not redirect this proof to an unrelated service.
  docker compose "${COMPOSE_BASE[@]}" exec -T livekit \
    sh -c 'wget -q -O - http://127.0.0.1:6789/metrics' \
    2>/dev/null | grep '^livekit_' | head -50 > "$OUT/s1-metrics.log"
  grep -q 'livekit_' "$OUT/s1-metrics.log" \
    || fail_closed S1 "the metrics endpoint returned no livekit_* series"
  docker compose "${COMPOSE_BASE[@]}" exec -T coturn \
    turnutils_stunclient -p 3478 127.0.0.1 > "$OUT/s1-stun.log" 2>&1 \
    || fail_closed S1 "the STUN binding transaction against coturn failed"
  grep -q 'reflexive addr' "$OUT/s1-stun.log" \
    || fail_closed S1 "coturn answered STUN without a reflexive address"
  record S1 PASS "both services Up (healthy); livekit 2xx; livekit_* metrics; STUN reflexive addr"
fi

# --------------------------------------------------------------------------- #
# S2. Server-created room.   RUNBOOK § 9 item 2.
# --------------------------------------------------------------------------- #
ROOM_REF=""
if want S2; then
  step_head S2 "server-created room"
  ROOM_REF="ls-smoke-$(date -u +%Y%m%d%H%M%S)"
  # `lk` reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from the
  # environment, which the prerequisite check above already insisted on. They
  # are deliberately NOT re-assigned as a command prefix here: a credential
  # never appears on the left of an `=` in a committed file (asserted by
  # backend/tests/test_wave2_video_infra.py).
  lk room create --url "$LIVEKIT_URL" "$ROOM_REF" > "$OUT/s2-room-create.log" 2>&1 \
    || fail_closed S2 "lk room create failed for $ROOM_REF"
  lk room list --url "$LIVEKIT_URL" > "$OUT/s2-room-list.log" 2>&1 \
    || fail_closed S2 "lk room list failed"
  grep -q "$ROOM_REF" "$OUT/s2-room-list.log" \
    || fail_closed S2 "the server does not list the room it was asked to create"
  record S2 PASS "room $ROOM_REF created server-side and listed by the SFU"
fi

# --------------------------------------------------------------------------- #
# S3. Short-lived, participant-bound join grant.   RUNBOOK § 9 item 2.
#     The credential comes from the COMMITTED API, never from `lk token create`:
#     the point is that the backend mints it for an authorised, PAID participant.
# --------------------------------------------------------------------------- #
CRED_FILE="$OUT/.cred.json"   # deleted at the end of this step: raw token inside
if want S3; then
  step_head S3 "short-lived participant-bound join grant"
  curl -fsS -X POST \
    "$BACKEND_URL/api/v1/tutoring/sessions/$SMOKE_SESSION_ID/join-credentials" \
    -H "$SMOKE_AUTH_HEADER" -o "$CRED_FILE" 2> "$OUT/s3-issue.log" \
    || fail_closed S3 "POST join-credentials did not return 2xx"
  python3 - "$CRED_FILE" > "$OUT/s3-grant.json" <<'PY' || fail_closed S3 "the join credential is not participant-bound and short-lived"
import json, re, sys
from datetime import datetime, timezone

doc = json.load(open(sys.argv[1]))
problems = []
ref = doc.get("participant_ref", "")
if not re.fullmatch(r"[0-9a-f]{32}", str(ref)):
    problems.append(f"participant_ref {ref!r} is not a 32-hex opaque reference")
ttl = int(doc.get("ttl_seconds") or 0)
if not 0 < ttl <= 300:
    problems.append(f"ttl_seconds {ttl} is not a SHORT lifetime (0 < ttl <= 300)")
if not doc.get("room_ref"):
    problems.append("no room_ref")
if not doc.get("join_token"):
    problems.append("no join_token")
expires = doc.get("expires_at")
if expires:
    when = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    if (when - datetime.now(timezone.utc)).total_seconds() > 310:
        problems.append(f"expires_at {expires} is further out than the TTL allows")
# The token itself is NEVER echoed into evidence.
print(json.dumps({
    "participant_ref": ref,
    "room_ref": doc.get("room_ref"),
    "permissions": doc.get("permissions"),
    "ttl_seconds": ttl,
    "expires_at": expires,
    "join_token": "[redacted]",
    "problems": problems,
}, indent=2))
raise SystemExit(1 if problems else 0)
PY
  record S3 PASS "grant is 32-hex participant-bound with a TTL <= 300s; token not written to evidence"
fi

# --------------------------------------------------------------------------- #
# S4/S5/S6. Browser work. One driver, three steps, real Chromium x2.
# --------------------------------------------------------------------------- #
if [[ $SKIP_BROWSER -eq 0 ]] && { want S4 || want S5 || want S6; }; then
  step_head "S4/S5/S6" "two-browser join, media denial, reconnect"
  node --test "$HERE/runtime_redaction.test.mjs" \
    > "$OUT/s4-redaction-selftest.log" 2>&1 \
    || fail_closed S4 "the media log redaction self-test failed"
  browser_steps=""
  want S4 && browser_steps="${browser_steps}S4,"
  want S5 && browser_steps="${browser_steps}S5,"
  want S6 && browser_steps="${browser_steps}S6,"
  expected_ice_policy=""
  want S9 && expected_ice_policy="relay"
  LIVEKIT_CLIENT_BUNDLE="$LIVEKIT_CLIENT_BUNDLE" \
  SMOKE_OUT="$OUT" \
  SMOKE_BACKEND_URL="$BACKEND_URL" \
  SMOKE_STEPS="${browser_steps%,}" \
  SMOKE_EXPECT_ICE_POLICY="$expected_ice_policy" \
    node "$HERE/livekit_two_browser_smoke.mjs" > "$OUT/s4-s6-driver.log" 2>&1
  driver_rc=$?
  if [[ $driver_rc -eq "$BLOCKED_EXIT" ]]; then
    log ""
    log "BLOCKED: prerequisite runtime absent"
    log "  the two-browser driver could not start; see $OUT/s4-s6-driver.log"
    write_summary "BLOCKED"
    exit "$BLOCKED_EXIT"
  fi
  for sid in S4 S5 S6; do
    want "$sid" || continue
    if grep -q "^${sid} PASS" "$OUT/s4-s6-driver.log"; then
      record "$sid" PASS "$(grep -m1 "^${sid} PASS" "$OUT/s4-s6-driver.log" | cut -d' ' -f3-)"
    else
      fail_closed "$sid" "$(grep -m1 "^${sid} " "$OUT/s4-s6-driver.log" | cut -d' ' -f3- || echo 'the browser driver did not report this step')"
    fi
  done
fi

# --------------------------------------------------------------------------- #
# S7. Token expiry and revocation.   RUNBOOK § 9 item 4.
# --------------------------------------------------------------------------- #
if want S7; then
  step_head S7 "token expiry and revocation"
  RE_FILE="$OUT/.cred2.json"
  FINAL_FILE="$OUT/.cred3.json"
  curl -fsS -X POST \
    "$BACKEND_URL/api/v1/tutoring/sessions/$SMOKE_SESSION_ID/join-credentials" \
    -H "$SMOKE_AUTH_HEADER" -o "$RE_FILE" 2>> "$OUT/s7.log" \
    || fail_closed S7 "the first S7 issue call did not return 2xx"
  # S4/S5 may already have revoked the S3 grant through a genuine
  # participant_left webhook. Issue once to establish a known live baseline,
  # then immediately re-issue it: this makes the supersession proof independent
  # of earlier step ordering and also exercises the same-second JWT regression.
  curl -fsS -X POST \
    "$BACKEND_URL/api/v1/tutoring/sessions/$SMOKE_SESSION_ID/join-credentials" \
    -H "$SMOKE_AUTH_HEADER" -o "$FINAL_FILE" 2>> "$OUT/s7.log" \
    || fail_closed S7 "the superseding S7 issue call did not return 2xx"
  python3 - "$RE_FILE" "$FINAL_FILE" >> "$OUT/s7.log" 2>&1 <<'PY' || fail_closed S7 "a re-issue did not supersede and replace the previous grant within the five-minute TTL"
import base64, json, sys, time
first, second = (json.load(open(path)) for path in sys.argv[1:3])
problems = []
if int(second.get("superseded") or 0) < 1:
    problems.append("the re-issue reports superseded=0: the previous grant was NOT revoked")
if second.get("join_token") == first.get("join_token"):
    problems.append("the re-issue returned the SAME raw token")
for label, item in (("first", first), ("second", second)):
    segment = item["join_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    remaining = int(claims["exp"]) - int(time.time())
    if not 0 < remaining <= 300:
        problems.append(f"{label} provider JWT lifetime is {remaining}s, not 1..300s")
print(json.dumps({"superseded": second.get("superseded"), "ttl_bounded": not any("lifetime" in p for p in problems), "problems": problems}))
raise SystemExit(1 if problems else 0)
PY
  # Prove the application grant state at the owning database boundary. The
  # first token hash must name a revoked row; the replacement must name the one
  # live row. Hashes are safe to pass to psql; raw bearers are not.
  FIRST_HASH="$(python3 -c 'import hashlib,json,sys;print(hashlib.sha256(json.load(open(sys.argv[1]))["join_token"].encode()).hexdigest())' "$RE_FILE")"
  SECOND_HASH="$(python3 -c 'import hashlib,json,sys;print(hashlib.sha256(json.load(open(sys.argv[1]))["join_token"].encode()).hexdigest())' "$FINAL_FILE")"
  docker compose -f docker-compose.yml exec -T postgres psql -U legalsaathi -tAc \
    "select count(*) filter (where token_hash in ('$FIRST_HASH') and revoked_at is not null), count(*) filter (where token_hash in ('$SECOND_HASH') and revoked_at is null) from video_session_grants where token_hash in ('$FIRST_HASH','$SECOND_HASH');" \
    > "$OUT/s7-db-state.log" 2>&1 || fail_closed S7 "could not verify the two grant rows"
  [[ "$(tr -d '[:space:]' < "$OUT/s7-db-state.log")" == "1|1" ]] \
    || fail_closed S7 "the old/new database grants were not revoked/live respectively"
  unset FIRST_HASH SECOND_HASH

  # A self-hosted LiveKit bearer cannot be recalled from the SFU after minting;
  # the approved control is a <=5-minute TTL plus RoomService removal. Prove
  # that the real SFU rejects an expired, correctly signed participant bearer.
  PRIOR_ROOM="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["room_ref"])' "$FINAL_FILE")"
  if ! PAST_JOIN="$("${PYTHON:-python3}" - "$PRIOR_ROOM" <<'PY'
import base64, hashlib, hmac, json, os, sys
from datetime import datetime, timedelta, timezone
room = sys.argv[1]
now = datetime.now(timezone.utc)
def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, sort_keys=True, separators=(",", ":")).encode())
claims = {
    "iss": os.environ["LIVEKIT_API_KEY"], "sub": "expired-smoke",
    "nbf": int((now - timedelta(minutes=2)).timestamp()),
    "exp": int((now - timedelta(seconds=5)).timestamp()),
    "video": {"room": room, "roomJoin": True, "canSubscribe": True, "canPublish": False, "canPublishData": False, "roomAdmin": False},
}
body = b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
message = f"{header}.{body}".encode("ascii")
signature = b64(hmac.new(os.environ["LIVEKIT_API_SECRET"].encode(), message, hashlib.sha256).digest())
print(f"{header}.{body}.{signature}")
PY
)"; then
    fail_closed S7 "could not mint the ephemeral expired-token negative control"
  fi
  [[ -n "$PAST_JOIN" ]] || fail_closed S7 "expired-token negative control was empty"
  if lk room join --url "${LIVEKIT_URL/http/ws}" --token "$PAST_JOIN" "$PRIOR_ROOM" \
       > "$OUT/s7-expired-token.log" 2>&1; then
    fail_closed S7 "the real SFU accepted a correctly signed EXPIRED credential"
  fi
  unset PAST_JOIN
  rm -f "$CRED_FILE" "$RE_FILE" "$FINAL_FILE"
  record S7 PASS "re-issue revoked the old application grant, both JWTs are <=300s, and the real SFU refused an expired signed JWT; self-hosted live bearers remain bounded by TTL"
fi
rm -f "$CRED_FILE" 2>/dev/null

# --------------------------------------------------------------------------- #
# S8. Webhook verification and replay rejection.   RUNBOOK § 9 item 6.
# --------------------------------------------------------------------------- #
if want S8; then
  step_head S8 "webhook verification and replay rejection"
  # LiveKit runs at WARN because its INFO participant-init records contain
  # SDP/ICE diagnostics. Do not turn sensitive logging back on merely to prove
  # webhook delivery; prove the delivery at its durable owning boundary below.
  printf '%s\n' 'LiveKit log level intentionally WARN; delivery is verified by the backend event trail.' \
    > "$OUT/s8-livekit-webhook.log"
  docker compose -f docker-compose.yml logs backend 2>/dev/null \
    | grep -i 'video/webhook' > "$OUT/s8-backend-webhook.log"
  if grep -qi 'VIDEO_UNVERIFIED' "$OUT/s8-backend-webhook.log"; then
    fail_closed S8 "the backend refused a genuine delivery with VIDEO_UNVERIFIED (key/secret mismatch — RUNBOOK § 4)"
  fi
  # The event trail must have landed. § 9 item 6's own query.
  docker compose -f docker-compose.yml exec -T postgres psql -U legalsaathi -tAc \
    "select count(*) from session_status_history where reason like 'video:%';" \
    > "$OUT/s8-trail.log" 2>&1 || fail_closed S8 "could not read session_status_history"
  [[ "$(tr -d '[:space:]' < "$OUT/s8-trail.log")" -gt 0 ]] \
    || fail_closed S8 "no video:* row in session_status_history: no event was applied"
  # Replay: the same provider event id must be refused a second time. The SFU
  # retries on its own; a duplicate application would show up as a second row
  # for one event id, which uq_payment_events_provider_event_id and the video
  # event id guard both forbid.
  docker compose -f docker-compose.yml exec -T postgres psql -U legalsaathi -tAc \
    "select count(*) from (select reason, count(*) c from session_status_history where reason like 'video:%' group by reason having count(*) > 1) d;" \
    > "$OUT/s8-replay.log" 2>&1 || fail_closed S8 "could not run the replay query"
  [[ "$(tr -d '[:space:]' < "$OUT/s8-replay.log")" == "0" ]] \
    || fail_closed S8 "a video event id was applied more than once: replay is NOT rejected"
  record S8 PASS "a real delivery verified at the backend boundary (no VIDEO_UNVERIFIED); the durable trail landed; no event id applied twice"
fi

# --------------------------------------------------------------------------- #
# S9. Forced-TURN media path.   RUNBOOK § 9 item 3.
# --------------------------------------------------------------------------- #
if want S9; then
  step_head S9 "FORCED-TURN smoke test (the media path)"
  grep -m1 'LEGALSAATHI-VIDEO-MODE' infra/video/rendered/livekit.yaml > "$OUT/s9-mode.log" 2>&1
  grep -q 'forced-turn' "$OUT/s9-mode.log" \
    || fail_closed S9 "the rendered config is not in forced-turn mode"
  if docker compose "${COMPOSE_BASE[@]}" port --protocol udp livekit 7882 > "$OUT/s9-port.log" 2>&1; then
    fail_closed S9 "the SFU media port 7882/udp IS published — media is not forced through the relay"
  fi
  docker compose "${COMPOSE_BASE[@]}" logs coturn 2>/dev/null \
    | grep -E 'new allocation|realm' > "$OUT/s9-allocations.log"
  allocs=$(grep -c 'new allocation' "$OUT/s9-allocations.log" || true)
  # coturn deliberately runs without verbose/session logging because allocation
  # lines can carry addresses and usernames. Therefore logs are diagnostic,
  # never the oracle. The selected relay candidate plus bidirectional byte
  # counters below is the browser-observed proof that media crossed TURN.
  if [[ -s "$OUT/s4-candidate-pair.json" ]]; then
    python3 - "$OUT/s4-candidate-pair.json" "$TURN_EXTERNAL_IP" >> "$OUT/s9-candidate.log" 2>&1 <<'PY' \
      || fail_closed S9 "the selected candidate pair is not a relay pair on TURN_EXTERNAL_IP"
import json, sys

pairs = json.load(open(sys.argv[1]))
relay_ip = sys.argv[2]
problems = []
if not pairs:
    problems.append("no selected candidate pair was captured")
for entry in pairs:
    local = entry.get("localCandidateType")
    policy = entry.get("iceTransportPolicy")
    if policy != "relay":
        problems.append(
            f"{entry.get('participant')}: RTCPeerConnection policy is "
            f"{policy!r}, not 'relay'"
        )
    # Chrome may report the selected, NAT-mapped allocation as peer-reflexive
    # with coturn's private address even though the browser is relay-only. This
    # is the relay path only when the allocation and fixed SFU peer also match.
    if local not in {"relay", "prflx"}:
        problems.append(
            f"{entry.get('participant')}: selected local candidate type is "
            f"{local!r}, not relay/prflx"
        )
    address = str(entry.get("localAddress") or "")
    if relay_ip and address and address not in {relay_ip, "172.29.30.11"}:
        problems.append(
            f"{entry.get('participant')}: selected address {address} is neither "
            f"TURN_EXTERNAL_IP ({relay_ip}) nor coturn 172.29.30.11"
        )
    port = int(entry.get("localPort") or 0)
    if not 20500 <= port <= 20549:
        problems.append(
            f"{entry.get('participant')}: relay port {port} is outside the "
            "20500-20549 block"
        )
    if entry.get("remoteAddress") != "172.29.30.10" or int(entry.get("remotePort") or 0) != 7882:
        problems.append(
            f"{entry.get('participant')}: selected relay peer is "
            f"{entry.get('remoteAddress')}:{entry.get('remotePort')}, not SFU 172.29.30.10:7882"
        )
    if not any(str(url).startswith("turn:") for url in entry.get("iceUrls", [])):
        problems.append(f"{entry.get('participant')}: no TURN URL in RTC configuration")
    if not (entry.get("bytesSent") and entry.get("bytesReceived")):
        problems.append(
            f"{entry.get('participant')}: no media flowed (bytesSent="
            f"{entry.get('bytesSent')}, bytesReceived={entry.get('bytesReceived')})"
        )
print(json.dumps({"pairs": pairs, "problems": problems}, indent=2))
raise SystemExit(1 if problems else 0)
PY
  else
    fail_closed S9 "no selected-candidate-pair evidence from S4; run S4 before S9"
  fi
  record S9 PASS "forced-turn mode; no published media port; relay-only PC selected coturn allocation to the fixed SFU and carried bidirectional media ($allocs diagnostic allocation log line(s))"
fi

# --------------------------------------------------------------------------- #
# S10. Provider unreachable, fail-closed.   RUNBOOK § 9 item 5.
# --------------------------------------------------------------------------- #
if want S10; then
  step_head S10 "provider unreachable, fail-closed"
  before=$(docker compose -f docker-compose.yml exec -T postgres psql -U legalsaathi -tAc \
    "select count(*) from video_session_grants where session_id = '$SMOKE_SESSION_ID';" 2>/dev/null | tr -d '[:space:]')
  docker compose "${COMPOSE_BASE[@]}" --profile video stop livekit > "$OUT/s10-stop.log" 2>&1 \
    || fail_closed S10 "could not stop the livekit service"
  # Do not race the provider probe against container shutdown. The old gate
  # could send the request while LiveKit still accepted connections and then
  # falsely report that fail-closed behavior was broken. Require an observed
  # network outage before exercising the backend boundary.
  provider_offline=0
  attempt=0
  while [[ $attempt -lt 50 ]]; do
    if ! curl -fsS "$LIVEKIT_URL/" >> "$OUT/s10-provider-probe.log" 2>&1; then
      provider_offline=1
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.1
  done
  [[ $provider_offline -eq 1 ]] \
    || fail_closed S10 "livekit still accepted connections after docker compose stop"
  code=$(curl -sS -o "$OUT/s10-body.json" -w '%{http_code}' -X POST \
    "$BACKEND_URL/api/v1/tutoring/sessions/$SMOKE_SESSION_ID/join-credentials" \
    -H "$SMOKE_AUTH_HEADER" 2>> "$OUT/s10.log")
  docker compose "${COMPOSE_BASE[@]}" --profile video up -d livekit >> "$OUT/s10-stop.log" 2>&1
  after=$(docker compose -f docker-compose.yml exec -T postgres psql -U legalsaathi -tAc \
    "select count(*) from video_session_grants where session_id = '$SMOKE_SESSION_ID';" 2>/dev/null | tr -d '[:space:]')
  [[ "$code" != "500" ]] || fail_closed S10 "the backend answered 500 instead of a typed error"
  grep -q 'PROVIDER_UNAVAILABLE\|PROVIDER_UNREACHABLE' "$OUT/s10-body.json" \
    || fail_closed S10 "the error envelope is not PROVIDER_UNAVAILABLE/PROVIDER_UNREACHABLE (got $code)"
  [[ "$before" == "$after" ]] \
    || fail_closed S10 "a grant row was written despite the provider being down ($before -> $after)"
  record S10 PASS "typed PROVIDER_UNAVAILABLE (http $code), no 500, and NO new video_session_grants row"
fi

# --------------------------------------------------------------------------- #
# S11. No raw token, SDP or ICE persisted.   RUNBOOK § 9 item 6, storage side.
#      Reuses the DB gate's A7 shape patterns so the two scans cannot diverge.
# --------------------------------------------------------------------------- #
if want S11; then
  step_head S11 "no raw token, SDP or ICE persisted"
  PY="${PYTHON:-}"
  if [[ -z "$PY" ]]; then
    for cand in /tmp/lsvenv/bin/python backend/.venv/bin/python python3; do
      command -v "$cand" > /dev/null 2>&1 && { PY="$cand"; break; }
    done
  fi
  [[ -n "$PY" ]] || fail_closed S11 "no python interpreter for the storage scan"
  ( cd backend && PYTHONPATH="$PWD" DATABASE_URL="$DATABASE_URL" \
      "$PY" scripts/wave2_postgres_gate.py --privacy-only \
      --output "$OUT/s11-privacy.json" ) > "$OUT/s11.log" 2>&1
  scan_rc=$?
  if [[ $scan_rc -eq "$BLOCKED_EXIT" ]]; then
    log ""
    log "BLOCKED: prerequisite runtime absent: the storage scan found no PostgreSQL"
    write_summary "BLOCKED"
    exit "$BLOCKED_EXIT"
  fi
  [[ $scan_rc -eq 0 ]] \
    || fail_closed S11 "the raw-storage scan found a token/SDP/ICE/device-label shape (see $OUT/s11-privacy.json)"
  record S11 PASS "no raw token, SDP, ICE or device label in any Wave 2 text/JSON column"
fi

write_summary "$([[ $FAILED -eq 0 ]] && echo PASS || echo FAIL)"
log ""
if [[ $FAILED -eq 0 ]]; then
  log "livekit_turn_smoke: PASS  (evidence: $OUT)"
  exit 0
fi
log "livekit_turn_smoke: FAIL  (evidence: $OUT)"
exit 1

# RUNBOOK — Wave 2 video plane (LiveKit + coturn)

SAATHI-451, frozen matrix row H1. Owner: whoever is on call for tutoring.

This runbook covers the **infrastructure** behind the committed
`VideoSessionProvider` seam. It never asks you to change application code: the
backend's only knowledge of LiveKit lives in
`backend/app/services/providers/video_provider.py::LiveKitCommunityAdapter`, and
switching the provider back to `deterministic` is a one-line environment change
(§ "Rollback").

Contents: [0. Read first](#0-read-first-two-sharp-edges) ·
[1. Bring-up](#1-bring-up) · [2. Health and readiness](#2-health-and-readiness-verification) ·
[3. Forced-TURN](#3-forced-turn) · [4. Credential rotation](#4-credential-rotation) ·
[5. Provider unreachable](#5-when-the-provider-is-unreachable) ·
[6. Restart and reconnect](#6-restart-and-reconnect-behaviour) ·
[7. Rollback](#7-rollback) · [8. TURN over TLS](#8-turn-over-tls-reserved-not-enabled) ·
[9. Environment-blocked checks](#9-environment-blocked-checks)

---

## 0. Read first: two sharp edges

**(a) KNOWN GAP — the webhook signature transports do not match.** This is a real,
evidenced interoperability defect between the committed adapter and any real
LiveKit server. It is **fail-closed** (nothing is accepted that should not be),
so it is not a security hole, but it means room events will not be applied until
someone owns it.

* LiveKit signs a webhook by putting a **JWT in the `Authorization` header**,
  where the JWT carries a `sha256` claim holding the base64 SHA-256 of the exact
  request body. Evidence, `livekit/protocol` → `webhook/url_notifier.go`,
  `URLNotifier.send`:

  ```go
  sum := sha256.Sum256(encoded)
  b64 := base64.StdEncoding.EncodeToString(sum[:])
  at := auth.NewAccessToken(params.APIKey, params.APISecret).
      SetValidFor(5 * time.Minute).
      SetSha256(b64)
  token, err := at.ToJWT()
  ...
  r.Header.Set(authHeader, token)
  r.Header.Set("content-type", "application/webhook+json")
  ```

  and the upstream docs: *"these requests have an `Authorization` header
  containing a signed JWT token. The token includes a sha256 hash of the
  payload."*

* The committed code expects a **raw hex HMAC in `X-Video-Signature`**:
  `backend/app/api/v1/tutoring.py` reads
  `VIDEO_SIGNATURE_HEADER = "X-Video-Signature"`, and
  `LiveKitCommunityAdapter.verify_event` computes
  `hmac.new(api_secret, raw_body, sha256).hexdigest()` and compares it to that
  header.

* Consequence with the config in this directory: LiveKit POSTs to
  `/api/v1/video/webhook`, the header is absent, `signature == ""`, the adapter
  raises `SIGNATURE_INVALID`, the route answers **400 `VIDEO_UNVERIFIED`**
  having read and written nothing, and LiveKit retries and eventually abandons.
  `room_started` / `participant_joined` / `participant_left` / `room_finished`
  never reach `join_credentials.handle_event`, so event-driven revocation does
  not happen. Everything else — issuing credentials, joining rooms, media, TTL
  expiry, explicit revocation, `close_room`, `revoke_participant` — is
  unaffected.

  Not fixed here **on purpose**: it is an interoperability defect, not a security
  defect, and rewriting a committed verification path is a decision for the
  owner of the video seam, not for the infra ticket. It is reported on SAATHI-451
  with the evidence above. The `webhook:` block in the rendered LiveKit config is
  still pointed at the correct route with the correct signing key so that the
  moment the adapter learns LiveKit's transport, no infra change is needed.

  Until then: keep `video_provider=deterministic` in any environment whose tests
  depend on E2 room events (the deterministic adapter's HMAC-over-body scheme is
  what the automated business-contract suite exercises), and treat grant
  lifetime as TTL-driven rather than event-driven when running against LiveKit.

**(b) `LIVEKIT_URL` must be `http://` or `https://`, never `wss://`.** The
adapter uses it for server-side Twirp calls
(`{LIVEKIT_URL}/twirp/livekit.RoomService/RemoveParticipant`) via `httpx`. A
`wss://` value passes `Settings` validation and every fail-closed check, then
fails **every** `revoke_participant` / `close_room` call at runtime with
`PROVIDER_UNREACHABLE`. Nothing in the codebase enforces the scheme; this
runbook and `infra/video/.env.example` are the enforcement. The `wss://` URL the
browser needs is a frontend setting and is not this variable.

---

## 1. Bring-up

Prerequisites: a Docker-capable host, the root stack's `.env`, and UDP reachable
on the relay ports (see the port table in `docker-compose.video.yml`).

```bash
# 1. Generate secrets. Never reuse one between environments.
openssl rand -hex 32   # -> TURN_STATIC_AUTH_SECRET
openssl rand -hex 32   # -> LIVEKIT_API_SECRET   (>= 16 chars is enforced)
# LIVEKIT_API_KEY is an identifier, not a secret: [A-Za-z0-9_.-]+, e.g. APIls1.

# 2. Append the variables from infra/video/.env.example to the deployment's .env
#    and fill them in. .env is gitignored; infra/video/.env.example holds
#    placeholder NAMES only and its values ('changeme') are ones the app refuses.

# 3. Render the service configs. Nothing is written if anything is missing,
#    unresolved, or still a placeholder.
python3 scripts/render_video_infra_config.py --env-file .env
# -> mode=forced-turn
#    wrote infra/video/rendered/turnserver.conf mode=0o644
#    wrote infra/video/rendered/livekit.yaml mode=0o600
#    next: docker compose ...
# infra/video/rendered/ is gitignored. Re-render after ANY change to .env or a
# template; the containers mount these files read-only and do not reload them.

# 4. Bring the media plane up (forced-TURN is the default posture).
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d coturn livekit
# coturn starts first: livekit has `depends_on: coturn: service_healthy`,
# because LiveKit hands the TURN address to every client in its JoinResponse and
# must not advertise a relay that is not answering.

# 5. Point the backend at it, then restart the backend.
#    In .env:  VIDEO_PROVIDER=livekit
#              LIVEKIT_URL=http://livekit:7880     (from inside compose)
docker compose -f docker-compose.yml up -d --force-recreate backend
```

`--profile video` means none of this touches the existing dev bring-up:
`docker compose up` without the profile behaves exactly as it does today.

For the relaxed, direct-media posture see § 3.

---

## 2. Health and readiness verification

Both services carry a compose `healthcheck` with the same knobs the root compose
file uses for Postgres (`interval: 5s`, `timeout: 3s`, `retries: 10`).

| Service | Probe | Why this probe |
|---|---|---|
| `livekit` | `wget -q -O /dev/null http://127.0.0.1:7880/` | `GET /` on the signalling port is exactly what LiveKit's own Helm chart uses for both `livenessProbe` and `readinessProbe`. Body-agnostic: a non-2xx makes `wget` exit non-zero. `wget` is busybox's — the image is `FROM alpine`. |
| `coturn` | `turnutils_stunclient -p 3478 127.0.0.1 \| grep -q 'reflexive addr'` | A real STUN Binding transaction against the live listener, not a socket poke. `turnutils_stunclient` ships in the coturn image. This is also why the STUN responder stays enabled even in forced-TURN mode (§ 3). |

Readiness *of the pair* is the compose health state; readiness *trending* is the
Prometheus endpoint on host 1042.

```bash
# Container-level health (what depends_on gates on).
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml ps
# Expect STATUS "Up (healthy)" for both coturn and livekit.

# LiveKit application health, from the host.
curl -fsS http://localhost:1039/ ; echo " <- exit $?"
# Expect: a 2xx (body "OK") and exit 0.

# LiveKit metrics / readiness scrape target.
curl -fsS http://localhost:1042/metrics | head -20
# Expect: Prometheus text, including livekit_* series.

# STUN reachability from the host (proves 1043/udp is actually published).
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  exec coturn turnutils_stunclient -p 3478 127.0.0.1
# Expect a line containing "reflexive addr:".

# Backend's own view of the provider seam.
curl -fsS http://localhost:1031/api/v1/health
```

If `livekit` is unhealthy, read its log first: a config key the pinned version
does not accept is a hard boot failure by design (the server runs *without*
`--disable-strict-config`).

```bash
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  logs --tail=50 livekit
```

Known candidates for that failure and their fix:

| Log line contains | Cause | Fix |
|---|---|---|
| `filter_params` / unknown field under `webhook` | pinned livekit-server predates webhook event filtering | delete the `filter_params:` block from the template and re-render; cost is 400s in the backend log for event types the adapter does not map |
| `unknown api key in webhook config` | `webhook.api_key` is not one of the `keys:` entries | both come from `LIVEKIT_API_KEY`; you edited the rendered file instead of the template |
| `port_range_start` conflict | someone added a port range alongside `udp_port` | upstream forbids both; keep `udp_port` only |

---

## 3. Forced-TURN

### What "forced" means here

Media **must** traverse the relay because there is no other route, not because a
client politely chose one. Three independent mechanisms:

1. **No published SFU media ports.** `docker-compose.video.yml` publishes only
   1039 (signalling) and 1042 (metrics). LiveKit's RTC ports (7881/tcp,
   7882/udp) stay inside the `video` docker network. Direct media is opt-in via
   `docker-compose.video.direct.yml`, which is the *only* thing that publishes
   them — and because compose merges `ports` by appending, an overlay can never
   silently remove the relay path.
2. **No browser-reachable candidate.** `rendered/livekit.yaml` sets
   `rtc.use_external_ip: false` and `rtc.node_ip: 172.29.30.10` — the SFU's
   address on the private `video` network. That value is **hard-coded in
   `livekit.forced-turn.yaml.tmpl`, not templated**, precisely so no environment
   variable can widen it.
3. **No third-party STUN.** `rtc.stun_servers` points at our own coturn. LiveKit's
   documented behaviour when the list is empty is to hand clients Google's public
   STUN servers, which would both leak participant IPs to a third party and
   produce srflx candidates.

coturn itself is locked to a single destination: `denied-peer-ip=0.0.0.0-255.255.255.255`
followed by `allowed-peer-ip=172.29.30.10`. The relay can forward to the SFU and
to nothing else, in either mode, so a leaked TURN credential does not yield an
open proxy.

Optional client-side belt-and-braces (a frontend change, not required for the
above): pass `rtcConfig: { iceTransportPolicy: 'relay' }` to the LiveKit client's
`Room`. Useful when you want the *browser* to refuse to gather non-relay
candidates at all.

### Switching between the two modes

```bash
# FORCED-TURN (default). Base overlay only.
python3 scripts/render_video_infra_config.py --mode forced-turn --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d --force-recreate coturn livekit

# DIRECT media allowed (TURN still available as fallback). Requires
# LIVEKIT_ADVERTISE_IP — an address the CLIENT can reach.
python3 scripts/render_video_infra_config.py --mode direct --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  -f infra/video/docker-compose.video.direct.yml \
  --profile video up -d --force-recreate coturn livekit
```

### How to prove forced-TURN is in effect

Four checks, cheapest first. **Checks 1 and 2 are config-level; only checks 3 and
4 prove anything about live media. Do not report a config check as a media
result.**

```bash
# CHECK 1 (config). Which mode is deployed?
grep -m1 'LEGALSAATHI-VIDEO-MODE' infra/video/rendered/livekit.yaml
# Expect: # LEGALSAATHI-VIDEO-MODE: forced-turn

# CHECK 2 (config). The SFU media ports must NOT be published.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  port livekit 7882/udp
# Expect: a non-zero exit and no address printed. If it prints "0.0.0.0:1041"
# you have the direct overlay loaded and media is NOT forced through the relay.

# CHECK 3 (runtime). Watch relay allocations while a session connects.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  logs -f coturn | grep -E 'allocation|refresh'
# Expect: one "new allocation" per participant, with a relay port inside
# 20500-20549, appearing as each participant joins. Zero allocations while a
# call is up means media is bypassing the relay.

# CHECK 4 (runtime, authoritative). In the browser: chrome://webrtc-internals,
# select the PeerConnection, read the SELECTED candidate pair.
# Expect: local candidate type = "relay", protocol udp, and the relay address in
# the 20500-20549 block on TURN_EXTERNAL_IP. A selected pair with local type
# "host" or "srflx" means forced-TURN is NOT in effect.
```

The definitive negative control — physically blocking the direct path and showing
the call still connects — is the smoke test in § 9, item 3.

---

## 4. Credential rotation

Four independent secrets. None of them is stored in the repository, and none of
them appears in a log line, an audit row or an API response.

| Secret | Lives in | Rotation blast radius |
|---|---|---|
| `LIVEKIT_API_SECRET` | `.env` → rendered `livekit.yaml` (`keys:`) and the backend's `Settings` | Signs join tokens **and** verifies webhooks. Rotating invalidates every in-flight join token. |
| `LIVEKIT_API_KEY` | same | Identifier, not a secret; rotate with the secret. |
| `TURN_STATIC_AUTH_SECRET` | `.env` → coturn `--static-auth-secret` and rendered `livekit.yaml` (`rtc.turn_servers[].secret`) | Existing relay allocations survive until they expire; new ones fail until both sides agree. |
| Join credentials themselves | nowhere — only a SHA-256 hash, in `video_session_grants.token_hash` | Not rotated. They expire after `JOIN_CREDENTIAL_TTL_SECONDS` (default 300s) and a re-issue supersedes the previous one. |

### Rotating the LiveKit API key/secret

```bash
NEW_SECRET=$(openssl rand -hex 32)   # do not echo it
# 1. Update LIVEKIT_API_KEY / LIVEKIT_API_SECRET in .env.
# 2. Re-render and restart LiveKit, then the backend, IN THAT ORDER.
python3 scripts/render_video_infra_config.py --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d --force-recreate livekit
docker compose -f docker-compose.yml up -d --force-recreate backend
```

Expected impact: participants holding a token minted under the old secret are
rejected by the SFU and must call
`POST /api/v1/tutoring/sessions/{id}/join-credentials` again. Because the TTL is
300s and a re-issue revokes the previous grant, the exposure window is one TTL,
which is why rotation does not need a dual-key window. Do it between sessions if
you can; if you cannot, expect reconnects, not data loss.

**Order matters.** Restart LiveKit first: a backend minting tokens with the new
secret against a server still holding the old one fails every join. The reverse
(LiveKit new, backend old) fails the same way but for one restart's duration
rather than indefinitely.

### Rotating the TURN shared secret

```bash
# 1. Update TURN_STATIC_AUTH_SECRET in .env.
python3 scripts/render_video_infra_config.py --env-file .env
# 2. coturn AND livekit both carry it — restart both, coturn first.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d --force-recreate coturn livekit
```

Expected impact: in-progress relay allocations continue (coturn validated them at
allocation time); new allocations for the ~`TURN_CREDENTIAL_TTL_SECONDS` window
may fail while the two services disagree, which is why they are restarted
together. Symptom of a mismatch: coturn logs `401` / `check_stun_auth` failures
and clients report ICE failure.

### Never do this

* Never edit `infra/video/rendered/*` in place — the next render silently
  overwrites it and you will be debugging a config nobody can reproduce.
* Never commit a `.env`, a rendered file, or a real secret into
  `infra/video/.env.example`. `backend/tests/test_wave2_video_infra.py` fails the
  build if a value in that file is not a recognised placeholder.
* Never raise coturn's `verbose`. It logs per-session transport detail — peer
  addresses and allocation lifetimes — which is exactly the media-plane data
  frozen decision 21 forbids us from logging.

---

## 5. When the provider is unreachable

The application is already designed for this and does not need your help to fail
safely; your job is to confirm *which* failure it is.

What the code does, so you can match it to what you see:

* `build_video_provider()` returns `None` when `video_provider=livekit` but the
  URL/key/secret are missing or placeholders → `join_credentials._resolve_provider`
  raises `PROVIDER_UNAVAILABLE` (**not retryable**). No credential is minted.
* A transport failure inside `LiveKitCommunityAdapter._twirp` (connection refused,
  DNS, timeout) → `PROVIDER_UNREACHABLE`, **retryable**.
* LiveKit answering `5xx` or `429` → `PROVIDER_UNAVAILABLE`, **retryable**.
* LiveKit answering `4xx` → `PROVIDER_REJECTED`, not retryable — a request
  problem (wrong key, unknown room), not an outage.
* A credential is never minted on a provider error, and a failed issue leaves no
  partial write.

Triage:

```bash
# 1. Is it up at all?
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml ps
curl -fsS http://localhost:1039/ || echo "signalling port down"

# 2. Can the BACKEND reach it? (a wss:// LIVEKIT_URL fails exactly here — § 0b)
docker compose -f docker-compose.yml exec backend \
  python -c "import httpx,os;print(httpx.get(os.environ['LIVEKIT_URL'],timeout=5).status_code)"
# Expect: 200. A protocol error naming 'wss' is sharp edge (b).

# 3. Is the SFU refusing our admin JWT? (key/secret mismatch after a rotation)
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  logs --tail=100 livekit | grep -i 'invalid\|unauthorized\|token'
```

Degradation policy, in order of preference:

1. **Provider outage, sessions must continue** → set `VIDEO_PROVIDER=deterministic`
   and restart the backend (§ 7). Credentials are issued and the domain stays
   fully functional; there is simply no real media plane behind them. Appropriate
   for a staging environment, **not** for production sessions people paid for.
2. **Provider outage in production** → leave `video_provider=livekit`. Callers get
   a typed `PROVIDER_UNAVAILABLE`, which the UI is built to show, rather than a
   token no server will honour. Fix the plane; do not paper over it.
3. Never hand out a credential from one provider while the other is serving
   rooms: `room_ref` derivations differ (`ls_<sha…>` vs `det_room_<sha…>`), so a
   crossed configuration produces "room not found" for every join.

---

## 6. Restart and reconnect behaviour

**Media survives a signalling restart, briefly.** LiveKit clients reconnect
automatically; the SFU is the media anchor, so restarting `livekit` drops media
for every participant and the clients then perform a full reconnect (new
PeerConnection, new ICE). Restarting `coturn` drops only relayed flows, and
clients re-allocate.

Three configured values exist to keep a *transient* network blip from becoming a
credential problem, and they are the same in both modes:

* `room.departure_timeout: 300` — seconds the room is held open after the **last**
  participant leaves. This is load-bearing: `room_finished` makes
  `join_credentials.handle_event` revoke **every** grant for the session. With the
  upstream default of 20s, a 30-second mobile-network blip that dropped both
  participants would revoke both credentials and force a re-issue. 300s is longer
  than any reconnect the client SDK attempts.
* `room.empty_timeout: 300` — the tutor routinely joins before the student.
* `room.max_participants: 4` — student + tutor, plus headroom for the window
  during a reconnect when the stale connection has not been reaped yet. Setting
  this to 2 makes a reconnect race look like a full room.

What a reconnect looks like end to end:

1. Client loses ICE → LiveKit client SDK retries with the **same** join token.
2. If the token is still inside its TTL, the rejoin succeeds and nothing else
   happens. This is the common case and needs no server-side action.
3. If the TTL expired, the client must call
   `POST /api/v1/tutoring/sessions/{id}/join-credentials` again. That issue
   **revokes the previous grant** (`superseded` in the response), which is
   precisely what stops the old token being replayed.
4. `participant_left` / `participant_joined` are how the trail is recorded — see
   § 0(a): those events do not currently land.

`restart: unless-stopped` is set on both services. This is a deliberate deviation
from the root compose file, which sets no restart policy: for a dev database,
staying down is a useful signal; for a media plane carrying live paid sessions,
staying down is an outage.

Ordered restart:

```bash
# Least disruptive first. Both are safe at any time; both drop live media.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video restart coturn      # relayed flows re-allocate
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video restart livekit     # all participants reconnect
# Wait for health before announcing recovery:
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml ps
```

---

## 7. Rollback

Rollback is deliberately boring, and there are two independent levers.

**Lever 1 — take the application off LiveKit (seconds, no media plane change).**

```bash
# In .env:  VIDEO_PROVIDER=deterministic
docker compose -f docker-compose.yml up -d --force-recreate backend
# Verify: the seam resolves to the deterministic adapter.
docker compose -f docker-compose.yml exec backend python -c \
  "from app.services.providers.video_provider import build_video_provider as b; print(b().name)"
# Expect: deterministic
```

Nothing else changes: no migration, no data rewrite. `video_session_grants` rows
minted under LiveKit stay valid rows — their `room_ref` values simply refer to
rooms the deterministic adapter does not serve, so those participants re-issue.

**Lever 2 — take the media plane down (leaves the app configured).**

```bash
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video down
# Add -v ONLY if you also want coturn's state volume gone; it holds no
# credentials and no media, so there is normally no reason to.
```

If lever 2 runs without lever 1, the backend keeps `video_provider=livekit` and
starts answering `PROVIDER_UNAVAILABLE` on join-credential requests. That is the
correct behaviour, and it is the right choice in production (§ 5, policy 2).

**Rolling back an image bump.** Restore the previous `image:` line — tag *and*
digest — in `docker-compose.video.yml` and in `SBOM.md`, then
`up -d --force-recreate`. Because both are digest-pinned there is no ambiguity
about what "the previous image" was.

**Rolling back a config change.** Templates are versioned in git; rendered files
are not. `git checkout -- infra/video/*.tmpl`, re-render, recreate. Never restore
a rendered file from a backup: it may contain a secret that has since been
rotated.

---

## 8. TURN over TLS (reserved, not enabled)

Host port **1044** is reserved for coturn's 5349/tcp and is deliberately not
published; the rendered config sets `no-tls` and `no-dtls`. TURN/TLS needs a real
certificate for `TURN_REALM`, and there is no honest way to ship one in a
repository.

It matters for the exact population this ticket is about: a network that permits
only outbound 443 will block 3478/udp *and* 3478/tcp. Enabling it later:

1. Obtain a certificate for `${TURN_REALM}`; mount it into the coturn container
   (`*.pem`, `*.crt` and `*.key` are already gitignored, so a stray copy in the
   working tree cannot be committed).
2. Remove `no-tls` / `no-dtls` from `turnserver.conf.tmpl` and add
   `cert=` / `pkey=` and `tls-listening-port=5349`.
3. Publish `"1044:5349/tcp"` on the coturn service.
4. Add a third entry to `rtc.turn_servers` in **both** LiveKit templates with
   `protocol: tls` and `port: 5349` (443 in production, if you can have it).
5. Re-render, recreate, and re-run the § 3 proof — the selected candidate pair
   should still be `relay`.

---

## 9. Environment-blocked checks

The following were **NOT EXECUTED**. The sandbox this infrastructure was authored
in has no `docker` binary, runs unprivileged, and has no network path to a
LiveKit or TURN service. Every item below is UNEXECUTED / ENVIRONMENT-BLOCKED,
with the exact command an operator runs on a Docker-capable host and the exact
observable that constitutes a pass. **A config-file assertion is not a
substitute for any of these, and none of them may be reported as passing on the
basis of one.**

What *was* executed here is listed at the end of this section.

### 1. Bring-up and health — UNEXECUTED

```bash
python3 scripts/render_video_infra_config.py --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml config -q
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d coturn livekit
sleep 20
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml ps
```

Expected: `config -q` prints nothing and exits 0; `ps` shows both services
`Up (healthy)`; `curl -fsS http://localhost:1039/` exits 0; `curl -fsS
http://localhost:1042/metrics` returns Prometheus text containing `livekit_`.

### 2. Join a room with a real credential — UNEXECUTED

```bash
# Issue a credential through the committed API (authorised, paid participant).
curl -fsS -X POST http://localhost:1031/api/v1/tutoring/sessions/$SESSION_ID/join-credentials \
  -H "$AUTH_HEADER" | tee /tmp/cred.json | python3 -c \
  'import json,sys;d=json.load(sys.stdin);print(d["room_ref"],d["permissions"],d["expires_at"])'
# Connect with the LiveKit CLI using that token.
lk room join --url ws://localhost:1039 --token "$(python3 -c \
  'import json;print(json.load(open("/tmp/cred.json"))["join_token"])')" "$ROOM_REF"
```

Expected: the CLI reports `connected to room`, and
`docker ... logs livekit | grep participant_joined` shows one join whose identity
is the 32-hex opaque `participant_ref` — **never** an email, name or user id.
Delete `/tmp/cred.json` afterwards: it contains a raw join token, which must not
persist anywhere.

### 3. FORCED-TURN smoke test (the one that matters) — UNEXECUTED

The negative control: block the direct media path at the network layer and show
the call still connects, via the relay.

```bash
# a. Confirm the SFU media ports are not published at all.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  port livekit 7882/udp; echo "exit=$?"
#    Expected: no address printed, non-zero exit.

# b. Make the direct path impossible even inside the network, from the client host.
sudo iptables -I OUTPUT -p udp --dport 7882 -j DROP
sudo iptables -I OUTPUT -p tcp --dport 7881 -j DROP

# c. Join from a browser and read the selected candidate pair.
#    chrome://webrtc-internals -> the PeerConnection -> "Stats" ->
#    candidate-pair with state=succeeded and nominated=true.
#    Expected: local candidate type = "relay"; the relay address is
#    TURN_EXTERNAL_IP with a port inside 20500-20549; media flows both ways
#    (bytesReceived and bytesSent both climbing).

# d. Confirm from the relay's own side.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  logs coturn | grep -E 'new allocation|realm'
#    Expected: one "new allocation" per participant, relay port in 20500-20549,
#    peer address 172.29.30.10 and NOTHING else (the peer ACL allows only the SFU).

# e. Clean up.
sudo iptables -D OUTPUT -p udp --dport 7882 -j DROP
sudo iptables -D OUTPUT -p tcp --dport 7881 -j DROP
```

Pass criteria, all four: (a) no published media port, (c) selected local
candidate type `relay` with bytes flowing, (d) exactly one allocation per
participant with peer `172.29.30.10`, and audio/video actually usable in the
browser. Any one of these failing means forced-TURN is not in effect.

### 4. Restart / reconnect — UNEXECUTED

```bash
# With a call up:
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video restart coturn
#    Expected: brief media freeze, then recovery WITHOUT a new join credential;
#    coturn logs a fresh allocation per participant.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video restart livekit
#    Expected: clients report Reconnecting then Reconnected, reusing the SAME
#    token while it is inside its TTL. The room is NOT finished (departure_timeout
#    300 > restart time), so no grant is revoked.
# Kill the relay for longer than a credential TTL (>300s), then rejoin:
#    Expected: the client must re-issue; the response carries "superseded": 1 and
#    the previous grant is revoked. The OLD token now fails validation.
```

### 5. Provider-unreachable behaviour — UNEXECUTED

```bash
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video stop livekit
curl -sS -o /dev/stderr -w '%{http_code}\n' -X POST \
  http://localhost:1031/api/v1/tutoring/sessions/$SESSION_ID/join-credentials -H "$AUTH_HEADER"
```

Expected: an error envelope whose code is `PROVIDER_UNAVAILABLE` (never a 500,
never a minted token), and **no new row** in `video_session_grants`:

```bash
docker compose -f docker-compose.yml exec postgres psql -U legalsaathi -c \
  "select count(*) from video_session_grants where session_id = '$SESSION_ID';"
```

### 6. Webhook signature validation, end to end — UNEXECUTED **and expected to fail**

```bash
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  logs livekit | grep -i webhook
docker compose -f docker-compose.yml logs backend | grep -i 'video/webhook'
```

Expected **today**, because of the gap in § 0(a): LiveKit logs
`sent webhook ... statusCode 400` and the backend logs a `VIDEO_UNVERIFIED`
rejection. That is the fail-closed outcome, not a passing test. Do not record
this item as green until the adapter and LiveKit agree on a signature transport.

### 7. SBOM / image scanning — UNEXECUTED

```bash
docker buildx imagetools inspect livekit/livekit-server:v1.9.12
docker buildx imagetools inspect coturn/coturn:4.7.0
syft  livekit/livekit-server:v1.9.12 -o cyclonedx-json > /tmp/sbom-livekit.cdx.json
grype coturn/coturn@sha256:a00afb5b4890de4df22bbe70379c6b316685dffee297d53cac1271dcb91fab93
```

Expected: `imagetools inspect` reports the index digests recorded in `SBOM.md`.
(The digests themselves were resolved from the registry over HTTPS on
2026-07-30 and are *not* environment-blocked — only the local tooling is.)

### What WAS executed in the authoring sandbox

Config-level only, and every one of them is a static assertion:

* `scripts/render_video_infra_config.py` renders both modes; the output parses as
  YAML with the expected `keys` / `webhook` / `rtc.turn_servers` structure;
  it refuses `--mode direct` without `LIVEKIT_ADVERTISE_IP`; and it refuses the
  placeholder values in `infra/video/.env.example`.
* `backend/tests/test_wave2_video_infra.py` — compose files parse, images are
  tag+digest pinned with no `latest`, host ports do not collide with the root
  compose file, both services declare a healthcheck, no secret literal is
  committed, env var names match `Settings` exactly, the webhook URL matches the
  committed route, and the forced-TURN posture holds (no published media ports,
  hard-coded `node_ip`, single-destination peer ACL).

Neither of those starts a server, joins a room, or moves a byte of media.

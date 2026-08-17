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

**(a) The webhook signature transport is per-adapter. FIXED — was a known gap.**
Until the SAATHI-451 follow-up, the LiveKit adapter expected a raw hex HMAC in
`X-Video-Signature` (the *deterministic* adapter's scheme) and therefore refused
every genuine LiveKit delivery: fail-closed, so never a security hole, but room
events never reached `join_credentials.handle_event` and event-driven revocation
never happened. That is no longer the case — `LiveKitCommunityAdapter` now
verifies what LiveKit actually sends, and each adapter owns its own header:

| adapter | header it verifies | credential |
| --- | --- | --- |
| `DeterministicVideoAdapter` (default, dev/test) | `X-Video-Signature` | hex `HMAC-SHA256` of the raw body |
| `LiveKitCommunityAdapter` | `Authorization` | signed HS256 JWT whose `sha256` claim is the base64 SHA-256 of the raw body |

`POST /api/v1/video/webhook` reads NEITHER name: it forwards the raw body plus the
delivery's headers, and the configured adapter
(`VideoSessionProvider.signature_header`) reads the one it signs. So switching
`VIDEO_PROVIDER` switches the accepted transport with it, and no route change is
ever needed.

What the LiveKit adapter checks, in order — every failure raises the same
`SIGNATURE_INVALID`, is **non-retryable**, and reads/writes nothing:

1. a token is present in `Authorization` (a `Bearer ` prefix is tolerated);
2. it is three base64url segments decoding to JSON objects;
3. its header says `alg: HS256` — **pinned**, so `alg: none` and an
   RS256→HS256 confusion attempt are refused before any HMAC is computed;
4. `HMAC-SHA256(LIVEKIT_API_SECRET, "<header>.<payload>")` matches, compared in
   constant time;
5. `iss` is exactly `LIVEKIT_API_KEY` — another project's token is not ours;
6. `exp` is present and not past, and `nbf` (if present) is not in the future,
   both within a fixed 5-second skew allowance (not configurable on purpose);
7. the `sha256` claim equals `base64(SHA-256(raw body))` over the bytes exactly as
   received, again in constant time.

Implemented with `hmac` + `hashlib` (no JWT dependency exists in
`backend/requirements.txt`, and one HS256 verification does not justify adding one
to a fail-closed security path). Evidence for the transport —

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

* The verifier: `LiveKitCommunityAdapter._verify_webhook_token` in
  `backend/app/services/providers/video_provider.py`. Its tests build the
  `Authorization` JWT independently from the Go source above rather than from the
  adapter's own code — `backend/tests/test_wave2_video_webhook_livekit.py`.

**Still true, and still your problem if you get it wrong:** the signing key in the
rendered `webhook:` block must be one of the server's `keys:` (LiveKit will not
start a notifier for a key it does not hold — asserted by
`test_webhook_signing_key_is_one_of_the_declared_api_keys`), and
`LIVEKIT_API_SECRET` must be identical on both sides. After a rotation the
symptom is `400 VIDEO_UNVERIFIED` on every delivery — see § 4.

**What is still NOT proven:** no real LiveKit server has delivered a webhook to
this backend in any environment we control. The transport is verified against the
upstream algorithm, not against an observed delivery; § 9 step S8 is the live check
and stays UNEXECUTED until an operator runs it.

**(b) `LIVEKIT_URL` must be `http://` or `https://`, never `wss://` — now
enforced.** The adapter uses it for server-side Twirp calls
(`{LIVEKIT_URL}/twirp/livekit.RoomService/RemoveParticipant`) via `httpx`. A
`wss://` value used to pass `Settings` validation and every fail-closed check and
then fail **every** `revoke_participant` / `close_room` call at runtime with
`PROVIDER_UNREACHABLE`. It is now a **refusal to boot**: with
`VIDEO_PROVIDER=livekit`, `Settings` raises `ConfigurationError` naming
`LIVEKIT_URL` unless the value is an `http`/`https` URL **with a host**
(`app/core/config.py::_livekit_url_problem`; scheme-less values such as
`livekit:7880` are refused too). The `wss://` URL the browser needs is a frontend
setting and is not this variable.

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
Prometheus endpoint on host 1142.

```bash
# Container-level health (what depends_on gates on).
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml ps
# Expect STATUS "Up (healthy)" for both coturn and livekit.

# LiveKit application health, from the host.
curl -fsS http://localhost:1139/ ; echo " <- exit $?"
# Expect: a 2xx (body "OK") and exit 0.

# LiveKit metrics / readiness scrape target.
curl -fsS http://localhost:1142/metrics | head -20
# Expect: Prometheus text, including livekit_* series.

# STUN reachability from the host (proves 1143/udp is actually published).
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  exec coturn turnutils_stunclient -p 3478 127.0.0.1
# Expect a line containing "reflexive addr:".

# Backend's own view of the provider seam.
curl -fsS http://localhost:1131/api/v1/health
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
   1139 (signalling) and 1142 (metrics). LiveKit's RTC ports (7881/tcp,
   7882/udp) stay inside the `video` docker network. Direct media is opt-in via
   `docker-compose.video.direct.yml`, which is the *only* thing that publishes
   them — and because compose merges `ports` by appending, an overlay can never
   silently remove the relay path.
2. **No browser-reachable candidate.** `rendered/livekit.yaml` sets
   `rtc.use_external_ip: false`, `rtc.node_ip: 172.29.31.10`, and
   `rtc.ips.includes: [172.29.31.10/32]` — the SFU's address on the private
   `video` network. The IP filter is load-bearing because LiveKit also shares
   the default network for webhooks; without it, a TURN-forwarded ICE check can
   be answered from the wrong interface and the browser will reject the source
   mismatch. The fixed address is **hard-coded in
   `livekit.forced-turn.yaml.tmpl`, not templated**, precisely so no environment
   variable can widen it.
3. **No third-party STUN.** `rtc.stun_servers` points at our own coturn. LiveKit's
   documented behaviour when the list is empty is to hand clients Google's public
   STUN servers, which would both leak participant IPs to a third party and
   produce srflx candidates.

coturn itself is locked to a single destination: `denied-peer-ip=0.0.0.0-255.255.255.255`
followed by `allowed-peer-ip=172.29.31.10`. The relay can forward to the SFU and
to nothing else, in either mode, so a leaked TURN credential does not yield an
open proxy.

The forced-relay profile also requires the backend capability to make the
frontend pass `rtcConfig: { iceTransportPolicy: 'relay' }` to the LiveKit
client's `Room`. This makes the *browser* refuse to gather non-relay candidates.

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

The backend must expose `video_ice_transport_policy=relay` for this profile.
Both the product `LiveKitVideoRoomClient` and the two-browser smoke driver pass
that server-authoritative value to the browser's `RTCPeerConnection`. Merely
omitting host port 7882 is not proof inside a container network: S9 requires a
selected local `relay` candidate in the configured relay-port block with
bidirectional media bytes.

Four checks, cheapest first. **Checks 1 and 2 are config-level; only checks 3
and 4 prove anything about live media. Do not report a config check as a media
result.**

```bash
# CHECK 1 (config). Which mode is deployed?
grep -m1 'NYAYONE-VIDEO-MODE' infra/video/rendered/livekit.yaml
# Expect: # NYAYONE-VIDEO-MODE: forced-turn

# CHECK 2 (config). The SFU media ports must NOT be published.
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  port --protocol udp livekit 7882
# Expect: a non-zero exit and no address printed. If it prints "0.0.0.0:1141"
# you have the direct overlay loaded and media is NOT forced through the relay.

# CHECK 3 (runtime, diagnostic only). coturn allocation messages are absent at
# the privacy-preserving log level and are not the pass/fail oracle.

# CHECK 4 (runtime, authoritative). In the browser: chrome://webrtc-internals,
# select the PeerConnection, read the SELECTED candidate pair.
# Expect: `iceTransportPolicy=relay`, protocol UDP and an allocation in
# 21500-21549. Under Docker NAT Chromium may expose the selected post-map
# candidate as `prflx` on coturn's fixed 172.29.31.11; that is accepted only
# when policy remains relay and the peer is fixed SFU 172.29.31.10:7882.
# A `host`/`srflx` candidate or any other peer means forced-TURN is not proved.
```

The definitive negative control — physically blocking the direct path and showing
the call still connects — is § 9 step S9, run by
`bash infra/video/scripts/livekit_turn_smoke.sh --steps S1,S2,S3,S4,S9`.

---

## 4. Credential rotation

Four independent secrets. None of them is stored in the repository, and none of
them appears in a log line, an audit row or an API response.

| Secret | Lives in | Rotation blast radius |
|---|---|---|
| `LIVEKIT_API_SECRET` | `.env` → rendered `livekit.yaml` (`keys:`) and the backend's `Settings` | Signs join tokens **and** verifies webhooks. Rotating invalidates every in-flight join token. |
| `LIVEKIT_API_KEY` | same | Identifier, not a secret; rotate with the secret. |
| `TURN_STATIC_AUTH_SECRET` | `.env` → coturn `--static-auth-secret` and rendered `livekit.yaml` (`rtc.turn_servers[].secret`) | Existing relay allocations survive until they expire; new ones fail until both sides agree. |
| Join credentials themselves | nowhere — only a SHA-256 hash, in `video_session_grants.token_hash` | Not rotated. They expire after `JOIN_CREDENTIAL_TTL_SECONDS` (default 300s). Re-issue revokes the application grant; because self-hosted LiveKit JWTs are stateless, remove the participant/room for immediate provider-side termination or rely on the bounded TTL. |

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

Expected impact on **webhooks**: between the two restarts, LiveKit signs webhook
tokens with one secret while the backend verifies with the other, so every
delivery is refused `400 VIDEO_UNVERIFIED` and LiveKit retries. The refusal is
fail-closed and non-retryable from the backend's point of view — no event is
half-applied — but the events delivered inside that window are LOST, not queued.
This is the second reason to keep the two restarts back to back.

Expected impact on **joins**: participants holding a token minted under the old
secret are rejected by the SFU and must call
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
curl -fsS http://localhost:1139/ || echo "signalling port down"

# 2. Can the BACKEND reach it? (a wss:// LIVEKIT_URL can no longer get this far:
#    the backend refuses to boot naming LIVEKIT_URL — § 0b)
docker compose -f docker-compose.yml exec backend \
  python -c "import httpx,os;print(httpx.get(os.environ['LIVEKIT_URL'],timeout=5).status_code)"
# Expect: 200. A ConfigurationError naming LIVEKIT_URL at startup is sharp edge (b).

# 3. Is the SFU refusing our admin JWT? (key/secret mismatch after a rotation)
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  logs --tail=100 livekit | grep -i 'invalid\|unauthorized\|token'
```

Degradation policy, in order of preference:

1. **Provider outage, sessions must continue** → set `VIDEO_CALLS_ENABLED=false`.
   This blocks new grants with `VIDEO_CALLS_DISABLED` while already-connected
   calls drain normally. Never switch production to the deterministic adapter.
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
   **revokes the previous application grant** (`superseded` in the response).
   Self-hosted LiveKit JWTs are stateless: an already-minted bearer remains
   provider-valid until its five-minute expiry unless RoomService removes the
   participant or room. The TTL is the provider-side replay bound; the database
   revocation is immediate at NyayOne's own validation boundary.
4. `participant_left` / `participant_joined` are how the trail is recorded, and
   `participant_left` also revokes that participant's grant. Those events land now
   that the signature transports agree (§ 0(a)) — which also means a `room_finished`
   during a long relay outage revokes every grant for the session, so keep
   `room.departure_timeout` comfortably above the join-credential TTL (asserted by
   `test_departure_timeout_outlives_a_reconnect`).

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
# In .env:  VIDEO_CALLS_ENABLED=false
#           VIDEO_PROVIDER=livekit
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

Host port **1144** is reserved for coturn's 5349/tcp and is deliberately not
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
3. Publish `"1144:5349/tcp"` on the coturn service.
4. Add a third entry to `rtc.turn_servers` in **both** LiveKit templates with
   `protocol: tls` and `port: 5349` (443 in production, if you can have it).
5. Re-render, recreate, and re-run the § 3 proof — the selected candidate pair
   should still be `relay`.

---

## 9. Environment-blocked checks

Everything in this section is now a **step of one runnable script**:

```bash
bash infra/video/scripts/livekit_turn_smoke.sh          # all steps
bash infra/video/scripts/livekit_turn_smoke.sh --list   # the step contract
bash infra/video/scripts/livekit_turn_smoke.sh --steps S1,S2,S3
```

That script IS the definition of this section, and this section IS the
definition of that script: the step ids and titles below are asserted against
`STEP_CONTRACT` in the script by
`backend/tests/test_wave2_runtime_gates.py::test_runbook_section_9_matches_the_smoke_script_step_contract`,
so the two cannot drift. Do not add a step here without adding it there.

The script **fails closed**: a step that does not produce its documented
observable stops the run and exits non-zero. A missing prerequisite is neither a
pass nor a failure — it prints `BLOCKED: prerequisite runtime absent`, lists
every missing prerequisite at once, and exits **78**.

**Status in the authoring sandbox: every step below is UNEXECUTED /
ENVIRONMENT-BLOCKED.** That sandbox has no `docker` binary, no `lk` binary, runs
unprivileged, and has no network path to a LiveKit or TURN service; the script's
own refusal there is the recorded evidence. **A config-file assertion is not a
substitute for any of these, and none of them may be reported as passing on the
basis of one.** What *was* executed is listed at the end of this section.

### S1 container/service health — UNEXECUTED

```bash
python3 scripts/render_video_infra_config.py --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml config -q
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d coturn livekit
sleep 20
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml ps
curl -fsS http://localhost:1139/
curl -fsS http://localhost:1142/metrics | head -20
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  exec coturn turnutils_stunclient -p 3478 127.0.0.1
```

Pass: `config -q` prints nothing and exits 0; `ps` shows BOTH services
`Up (healthy)`; `curl` on 1139 exits 0; the 1142 scrape contains `livekit_`
series; the STUN transaction prints a line containing `reflexive addr`.

### S2 server-created room — UNEXECUTED

```bash
lk room create --url "$LIVEKIT_URL" "$ROOM_REF"
lk room list  --url "$LIVEKIT_URL"
```

Pass: `room create` exits 0 and the SFU then LISTS that room. A room the server
will not list is a room no participant can join.

### S3 short-lived participant-bound join grant — UNEXECUTED

```bash
curl -fsS -X POST http://localhost:1131/api/v1/tutoring/sessions/$SESSION_ID/join-credentials \
  -H "$AUTH_HEADER" -o /tmp/cred.json
```

Pass: `participant_ref` is a 32-hex opaque reference — **never** an email, name
or user id; `ttl_seconds` is `0 < ttl <= 300`; `expires_at` is no further out
than the TTL allows; `room_ref` and `join_token` are both present. The script
writes a REDACTED copy to evidence and DELETES `/tmp/cred.json`-equivalents at
the end of S7: a raw join token must not persist anywhere.

### S4 two-browser join smoke — UNEXECUTED

Driver: `infra/video/scripts/livekit_two_browser_smoke.mjs` (two real Chromium
contexts, fake camera/mic devices, the real `livekit-client` SDK).

Bare-metal Chromium is the default. For an isolated Docker/Colima rig, set
`SMOKE_CHROMIUM_CDP_URL`, `SMOKE_DENIED_CHROMIUM_CDP_URL`,
`SMOKE_BROWSER_LIVEKIT_URL`, `SMOKE_BROWSER_ORIGIN`, and (when host ports must
not collide) `SMOKE_COMPOSE_OVERRIDE`. The browser origin must still be a secure
context: use real TLS, or a loopback-only proxy inside each QA browser namespace
so the page and signalling URL are `http://localhost`. Do not use an HTTPS CDN
page with a `ws://` provider (mixed content), and do not report a joined client
as S4 PASS unless the driver observes two local publications and remote tracks.

Pass: the two participants receive **different** tokens for the **same**
`room_ref`; both connect; each SEES at least one remote participant and at least
one subscribed remote track; and the selected ICE candidate pair of both is
captured to `s4-candidate-pair.json` — which is what S9 then judges. The SFU log
shows one `participant_joined` per participant whose identity is the 32-hex
opaque `participant_ref`.

### S5 camera and microphone denial — UNEXECUTED

Pass: with camera AND microphone permission denied, the participant still
**joins** (a participant who cannot publish is still a participant), publishes
**zero** tracks, the capture attempt raises a denial error rather than hanging,
and `enumerateDevices()` exposes **no device labels** to the page.

### S6 reconnect — UNEXECUTED

```bash
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video restart coturn      # relayed flows re-allocate
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video restart livekit     # all participants reconnect
```

Pass: with a call up, both clients report `Reconnecting` then settle at
`connected`, **reusing the SAME token** while it is inside its TTL. The room is
NOT finished (`departure_timeout` 300 > restart time), so no grant is revoked and
no re-issue is needed. Restarting `coturn` produces a brief media freeze and a
fresh allocation per participant, again with no new credential.

### S7 token expiry and revocation — UNEXECUTED

```bash
curl -fsS -X POST http://localhost:1131/api/v1/tutoring/sessions/$SESSION_ID/join-credentials \
  -H "$AUTH_HEADER" -o /tmp/cred2.json
lk room join --url "${LIVEKIT_URL/http/ws}" --token "$OLD_TOKEN" "$OLD_ROOM"
```

Pass: the re-issue reports `superseded >= 1`, returns a DIFFERENT raw token, the
old/new database rows are revoked/live respectively, both JWTs expire within
300 seconds, and the real SFU refuses a correctly signed token whose `exp` is in
the past. The script deliberately does not claim that a still-unexpired
self-hosted JWT is instantly recalled: LiveKit does not introspect the
NyayOne database. Both transient credential files are deleted afterwards.

### S8 webhook verification and replay rejection — UNEXECUTED

```bash
docker compose -f docker-compose.yml logs backend | grep -i 'video/webhook'
docker compose -f docker-compose.yml exec postgres psql -U nyayone -d nyayone -c \
  "select reason from session_status_history where reason like 'video:%' order by created_at desc limit 5;"
```

Pass **now that the transports agree** (§ 0(a)): the backend logs NO
`VIDEO_UNVERIFIED`, a
`video:participant_joined:<id>` row appears in `session_status_history`, and **no
event id is applied more than once** (the script runs the grouping query that
proves it).

LiveKit deliberately runs at WARN. Its INFO participant-init messages include
SDP/ICE diagnostics, so enabling INFO merely to obtain a sender-side webhook log
would violate the privacy gate. The durable backend event trail is the owning
delivery proof.

This is the one item to read carefully: the committed adapter test verifies
LiveKit's *published signing algorithm*, but that is weaker than an observed
delivery. Record this green only after a real server delivery creates the
durable `video:*` event trail and the backend shows no `VIDEO_UNVERIFIED` error.

Failure triage: a `400 VIDEO_UNVERIFIED` here means the token did not verify —
in practice a `LIVEKIT_API_SECRET`/`LIVEKIT_API_KEY` mismatch between the rendered
`livekit.yaml` and the backend's environment (§ 4), a `webhook.api_key` that is not
in the server's `keys:` map, or clock skew beyond 5 s between the SFU host and the
backend host. The refusal is deliberately identical for all of them, so use the
two sides' *configuration* to tell them apart, not the response body.

### S9 FORCED-TURN smoke test (the media path) — UNEXECUTED

The negative control: block the direct media path and show the call still
connects, via the relay.

```bash
# a. Which mode is deployed, and are the SFU media ports really unpublished?
grep -m1 'NYAYONE-VIDEO-MODE' infra/video/rendered/livekit.yaml
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  port --protocol udp livekit 7882; echo "exit=$?"

# b. Confirm the backend-issued join response says
#    video_ice_transport_policy=relay. The browser enforces that policy.

# c. Join (S4) and read the SELECTED candidate pair. The driver reads it from
#    the live RTCPeerConnection stats; chrome://webrtc-internals shows the same
#    thing by hand.

# d. Confirm both participants exchanged remote audio/video tracks.
```

Pass, all four: (a) mode is `forced-turn` and the port command prints no address
and exits non-zero; (b) both join responses carry `relay`; (c) each selected
LOCAL candidate type is `relay`, its address is `TURN_EXTERNAL_IP`, its port is
inside 21500-21549, and both `bytesSent` and `bytesReceived` are non-zero; and
(d) each browser sees the other participant's published tracks. Docker NAT may
report the selected allocation as `prflx`/172.29.31.11; it is only accepted with
the relay-only PC policy, a relay-block port and the fixed SFU peer. Any failure
means forced-TURN is not proved. Config alone never counts as media proof.

### S10 provider unreachable, fail-closed — UNEXECUTED

```bash
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video stop livekit
curl -sS -o /dev/stderr -w '%{http_code}\n' -X POST \
  http://localhost:1131/api/v1/tutoring/sessions/$SESSION_ID/join-credentials -H "$AUTH_HEADER"
docker compose -f docker-compose.yml exec postgres psql -U nyayone -d nyayone -c \
  "select count(*) from video_session_grants where session_id = '$SESSION_ID';"
```

Pass: an error envelope whose code is `PROVIDER_UNAVAILABLE` (never a 500, never
a minted token), and the `video_session_grants` count for that session is
UNCHANGED across the attempt. The script restarts `livekit` afterwards.

### S11 no raw token, SDP or ICE persisted — UNEXECUTED

```bash
cd backend && DATABASE_URL=... python scripts/wave2_postgres_gate.py --privacy-only
```

Pass: zero findings. Every text/JSON column of every Wave 2 table is cast with
`::text` and matched against the SAME shape list the database gate's assertion
A7 uses (PAN, CVV/OTP keys, JWT-shaped raw tokens, `join_token`/`api_secret`
keys, SDP `v=0`/`m=audio`/`a=fingerprint:`, ICE `candidate:`/`typ relay`/
`a=ice-ufrag:`, and browser device labels). `video_session_grants` may hold a
`token_hash` and nothing else. One implementation backs both the smoke step and
the database gate, so the two can never disagree about what counts as a leak.

### Related gate: the Wave 2 database proof

Media is only half of Wave 2's target-runtime story. The other half is
PostgreSQL 16 + pgvector, and it is also ONE command:

```bash
DATABASE_URL=postgresql+psycopg://... bash backend/scripts/wave2_db_gate.sh
bash backend/scripts/wave2_db_gate.sh --list     # the A1..A8 assertion contract
```

Same honesty contract: it prints the runtime it detected and exits **78
BLOCKED** rather than reporting a pass it did not earn. It is also wired in as
the final stage of `backend/scripts/db_gate.sh` and runs in CI on push/PR
(`.github/workflows/wave2-tutoring-db-gate.yml`, `pgvector/pgvector:pg16`).
**Status in the authoring sandbox: UNEXECUTED / BLOCKED** — no PostgreSQL binary
and no reachable server.

### 7. SBOM / image scanning — UNEXECUTED

Not part of the smoke script (it proves nothing about media), kept here because
it is the same class of blocked check.

```bash
docker buildx imagetools inspect livekit/livekit-server:v1.13.5
docker buildx imagetools inspect coturn/coturn:4.7.0
syft  livekit/livekit-server:v1.13.5 -o cyclonedx-json > /tmp/sbom-livekit.cdx.json
grype coturn/coturn@sha256:a00afb5b4890de4df22bbe70379c6b316685dffee297d53cac1271dcb91fab93
```

Expected: `imagetools inspect` reports the index digests recorded in `SBOM.md`.
(The digests themselves were resolved from the registry over HTTPS on
2026-07-30 and are *not* environment-blocked — only the local tooling is.)

### What WAS executed in the authoring sandbox

Config-level and static-analysis only, plus the two gates' own REFUSALS:

* `bash infra/video/scripts/livekit_turn_smoke.sh` → `BLOCKED: prerequisite
  runtime absent`, exit 78, listing docker / `lk` / the rendered config /
  `LIVEKIT_*` / `SMOKE_*` as missing. Nothing about media was proven.
* `bash backend/scripts/wave2_db_gate.sh` → `BLOCKED: prerequisite runtime
  absent`, exit 78 (DATABASE_URL unset; and, when pointed at a PostgreSQL URL,
  "no PostgreSQL server answered"). Nothing about PostgreSQL was proven.
* `bash -n` on both shell gates and `node --check` on the browser driver.
* `scripts/render_video_infra_config.py` renders both modes; the output parses as
  YAML with the expected `keys` / `webhook` / `rtc.turn_servers` structure;
  it refuses `--mode direct` without `LIVEKIT_ADVERTISE_IP`; and it refuses the
  placeholder values in `infra/video/.env.example`.
* `backend/tests/test_wave2_video_webhook_livekit.py` — an `Authorization` JWT
  rebuilt from LiveKit's own signing algorithm is accepted through the real
  `POST /api/v1/video/webhook` route and drives the E2 effects, and ~30 near-miss
  deliveries (no header, malformed JWT, wrong secret, `alg: none`, expired,
  not-yet-valid, wrong issuer, absent `sha256`, one-byte body mutation, replay)
  are each refused fail-closed with nothing read or written. This is a claim about
  BYTES matching the upstream algorithm, not about an observed delivery.
* `backend/tests/test_wave2_config_failclosed.py` — `VIDEO_PROVIDER=livekit` with a
  `wss://` or scheme-less `LIVEKIT_URL` refuses to construct `Settings`.
* `backend/tests/test_wave2_video_infra.py` — compose files parse, images are
  tag+digest pinned with no `latest`, host ports do not collide with the root
  compose file, both services declare a healthcheck, no secret literal is
  committed, env var names match `Settings` exactly, the webhook URL matches the
  committed route, and the forced-TURN posture holds (no published media ports,
  hard-coded `node_ip` plus matching RTC IP filter, single-destination peer ACL).
* `backend/tests/test_wave2_runtime_gates.py` — the two gate scripts exist, carry
  the BLOCKED contract and exit code 78, and this section's step ids/titles match
  the smoke script's `STEP_CONTRACT` exactly.

None of those starts a server, joins a room, or moves a byte of media.

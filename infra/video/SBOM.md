# SBOM — Wave 2 video plane (SAATHI-451, frozen matrix row H1)

Scope: the container images `infra/video/docker-compose.video.yml` runs. It does
**not** cover the backend/frontend images (built from `docker/*.Dockerfile`, whose
dependencies are pinned in `backend/requirements.txt` and
`frontend/package-lock.json`).

Format: a human-readable table plus the exact commands to regenerate machine
formats. There is no pre-existing SBOM in this repository to match, so this file
sets the shape: **one row per image, tag AND digest, no `latest` anywhere.**

Resolved against Docker Hub on **2026-07-30**. Every digest below was read from
the registry, not transcribed from memory.

## Pinned images

| Component | Image reference (as committed) | Multi-arch index digest | Upstream release | Base | Licence | Role |
|---|---|---|---|---|---|---|
| LiveKit server (community) | `livekit/livekit-server:v1.9.12` | `sha256:2c13cbf2edcbf13ea7b20d05c10b394d04d8fb3fe358269cff845a90b4de9576` | v1.9.12, pushed 2026-03-05 | `alpine` (static `CGO_ENABLED=0` Go binary, no extra apk packages) | Apache-2.0 | SFU + signalling + RoomService (Twirp) + webhook notifier |
| coturn | `coturn/coturn:4.7.0` | `sha256:a00afb5b4890de4df22bbe70379c6b316685dffee297d53cac1271dcb91fab93` | 4.7.0, pushed 2025-12-18 | `debian:trixie-slim` | BSD-3-Clause | STUN responder + TURN relay |

Per-architecture manifest digests (what actually gets pulled on a given host):

| Image | linux/amd64 | linux/arm64 |
|---|---|---|
| `livekit/livekit-server:v1.9.12` | `sha256:051ac3adcce0f4901e03269f97eb5f3423154456215a5c2927754c1450a6134c` | `sha256:eeb9bedb1d029ee45cf78c5a47d002ba363d419ccdfd6068d06086b1451f1d56` |
| `coturn/coturn:4.7.0` | `sha256:94f732f319463c94769b30b5cca1c02baa2d106fe3d3210159840c1372b162de` | `sha256:2ee13c79236cb51570121390b805e30625dad858afa46c2c53e115e6055636a3` |

The compose file pins the **index** digest (`image: repo:tag@sha256:<index>`), so
one reference is correct on both the arm64 Macs used for development and the
amd64 hosts used for staging. `backend/tests/test_wave2_video_infra.py` asserts
that every image in every video compose file carries a tag *and* a
`@sha256:` digest, that no reference is `latest`, and that the digests here match
the digests there.

## Notable components inside the images

Recorded because these are the parts a CVE feed will name, and because two of
them (OpenSSL, libevent) are on coturn's network-facing path.

* `livekit/livekit-server:v1.9.12` — a single statically linked Go binary
  (`/livekit-server`, `ENTRYPOINT`) on an unmodified `alpine` base. No package
  manager layers are added by the upstream Dockerfile, so the image's attack
  surface is busybox + the Go binary. Go module inventory:
  `go list -m all` in `github.com/livekit/livekit@v1.9.12`.
* `coturn/coturn:4.7.0` — coturn built from source with
  `--prefix=/usr --sysconfdir=/etc/coturn`, running as `nobody:nogroup`, against
  the Debian runtime libraries: `libssl3t64` (OpenSSL 3), `libevent-2.1-7t64`
  (+ `-core`, `-extra`, `-openssl`, `-pthreads`), `libatomic1`, `libpq5`,
  `libmariadb3`, `libsqlite3-0`, `libhiredis1.1.0`, `libmongoc-1.0-0t64`,
  `libmicrohttpd12t64`, `ca-certificates`, `dnsutils`. The image also ships the
  `turnutils_*` helper binaries — `turnutils_stunclient` is what the compose
  healthcheck uses, so do not switch to a `-slim`-style variant that strips them
  without changing that probe.

## Regenerating / verifying (Docker-capable host)

```bash
# Confirm the committed digest is still what the tag resolves to.
docker buildx imagetools inspect livekit/livekit-server:v1.9.12
docker buildx imagetools inspect coturn/coturn:4.7.0
# Expected: "Digest:" matches the index digest in the table above. If it does
# NOT, upstream has re-pushed the tag — investigate before re-pinning; a moving
# version tag is exactly what the digest pin exists to catch.

# Machine-readable SBOM per image (CycloneDX and SPDX).
syft livekit/livekit-server:v1.9.12 -o cyclonedx-json > /tmp/sbom-livekit.cdx.json
syft coturn/coturn:4.7.0            -o spdx-json     > /tmp/sbom-coturn.spdx.json

# Vulnerability scan against the pinned digests, not the tags.
grype livekit/livekit-server@sha256:2c13cbf2edcbf13ea7b20d05c10b394d04d8fb3fe358269cff845a90b4de9576
grype coturn/coturn@sha256:a00afb5b4890de4df22bbe70379c6b316685dffee297d53cac1271dcb91fab93
```

`syft` / `grype` / `docker buildx` are **not available in the sandbox this file
was written in** (no docker binary, no privileged uid). The commands above are
therefore UNEXECUTED here — see RUNBOOK § "Environment-blocked checks". The
digests in the tables above are *not* in that category: they were resolved from
`registry.hub.docker.com` over HTTPS on 2026-07-30.

## Upgrade policy

1. Bump the tag **and** the digest together, in the compose file and this table.
   A tag without a digest is not a pin.
2. Re-run `backend/tests/test_wave2_video_infra.py` — it fails if the compose
   file and this SBOM disagree.
3. LiveKit minor upgrades can add config keys and, more importantly, can
   *reject* config keys: the server runs without `--disable-strict-config`, so an
   upgrade that removes a key we set is a hard boot failure, visible immediately
   in the healthcheck. That is intentional. Read the LiveKit release notes for
   `rtc.*`, `room.*` and `webhook.*` before bumping.
4. coturn patch upgrades are usually drop-in; check `turnutils_stunclient` is
   still present (the healthcheck depends on it).

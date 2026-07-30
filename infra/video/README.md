# infra/video — self-hosted video plane (SAATHI-451, matrix row H1)

Infrastructure-as-code for the LiveKit SFU and the coturn TURN relay that sit
behind the committed `VideoSessionProvider` seam. No application code lives here
and none is changed by it: the backend still only ever sees `VideoCredential` /
`VideoEventData`, and `VIDEO_PROVIDER=deterministic` remains the mandatory
adapter for automated business-contract testing.

| File | What it is |
|---|---|
| `docker-compose.video.yml` | Compose overlay: `livekit` + `coturn`, healthchecks, host ports, fixed `video` network. **Forced-TURN by default** — publishes no SFU media ports. |
| `docker-compose.video.direct.yml` | Opt-in overlay that publishes the SFU media ports, allowing direct (non-relayed) media. |
| `livekit.forced-turn.yaml.tmpl` | LiveKit config template, relay-only posture. Documented line by line. |
| `livekit.direct.yaml.tmpl` | LiveKit config template, direct-media posture. Differs from the above in three marked ICE lines only. |
| `turnserver.conf.tmpl` | coturn config template. Identical in both modes: TURN REST auth, 50-port relay block, single-destination peer ACL. |
| `.env.example` | Placeholder **names** only. Its secret-shaped values are ones the app's fail-closed validator rejects, so a copied-but-unedited file cannot boot. |
| `SBOM.md` | Pinned images: exact tags **and** digests, per-arch digests, notable components, upgrade policy. |
| `RUNBOOK.md` | Bring-up, health verification, forced-TURN proof, credential rotation, provider-outage triage, restart/reconnect, rollback, and the list of environment-blocked runtime checks with exact operator commands. |
| `rendered/` | Generated at deploy time by `scripts/render_video_infra_config.py`. **Gitignored.** Never edited by hand, never committed. |
| `scripts/livekit_turn_smoke.sh` | The live media smoke, ONE command. Steps S1..S11 == `RUNBOOK.md` § 9. Fails closed; prints `BLOCKED: prerequisite runtime absent` and exits 78 when the stack is not there. |
| `scripts/livekit_two_browser_smoke.mjs` | Playwright driver behind steps S4 (two-browser join), S5 (camera/mic denial) and S6 (reconnect). Never run directly — the shell gate owns the prerequisite contract. |

Start here:

```bash
python3 scripts/render_video_infra_config.py --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d coturn livekit
```

Then read `RUNBOOK.md` § 0 — two sharp edges, both now enforced in code rather
than by convention: the webhook signature transport is **per adapter** (LiveKit
signs an `Authorization` JWT; the deterministic dev adapter signs
`X-Video-Signature`, and the route reads neither name itself), and `LIVEKIT_URL`
must be an `http://`/`https://` URL with a host — a `wss://` value is refused at
startup. Both will still cost you an afternoon if you meet them by surprise.

Validation that runs in CI: `backend/tests/test_wave2_video_infra.py` (static
infra assertions) and `backend/tests/test_wave2_runtime_gates.py` (the gate
scripts' BLOCKED contract, and the runbook-vs-script step-contract check that
stops `RUNBOOK.md` § 9 and `scripts/livekit_turn_smoke.sh` drifting apart).

The two live gates, each ONE command, each refusing rather than pretending when
its runtime is absent:

```bash
bash infra/video/scripts/livekit_turn_smoke.sh            # media plane  (§ 9)
DATABASE_URL=postgresql+psycopg://... \
  bash backend/scripts/wave2_db_gate.sh                   # PostgreSQL 16 + pgvector
```

Both are **UNEXECUTED / ENVIRONMENT-BLOCKED** in the authoring sandbox: it has no
`docker`, no `lk`, no `psql` and no reachable PostgreSQL. Their refusals are the
recorded evidence, and a refusal is never a pass.

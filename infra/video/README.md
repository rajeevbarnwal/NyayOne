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

Start here:

```bash
python3 scripts/render_video_infra_config.py --env-file .env
docker compose -f docker-compose.yml -f infra/video/docker-compose.video.yml \
  --profile video up -d coturn livekit
```

Then read `RUNBOOK.md` § 0 — there are two sharp edges (the LiveKit webhook
signature transport does not match the committed adapter's, and `LIVEKIT_URL`
must not be a `wss://` URL) that will cost you an afternoon if you meet them
by surprise.

Validation that runs in CI: `backend/tests/test_wave2_video_infra.py`.

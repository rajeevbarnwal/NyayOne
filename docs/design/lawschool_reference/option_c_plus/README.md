# Option C+ reference package (curated) — S-27..S-30 canonical visual reference

Curated from `docs/design/NEW_S27_S30_OPTIONS/lawschool_s27_s30_option_c_plus_corrections_2026-07-27`
(approved Option C+ "Guided Confidence", F1–F4 correction cycle) for SAATHI-63/118/121
integration. Zips, `.DS_Store` and reviewer/debug tooling are excluded from
production/evidence surfaces; the reference artifact's reviewer rig is build-only and is
hidden in all baseline captures via baseline mode (`&baseline=1` in the hash query or
`body[data-baseline="1"]`).

Contents
- `OPTION_C_PLUS_GUIDED_CONFIDENCE.html` — reference frames (all 48 states via `window.__opt`)
- `OPTION_C_PLUS_TOKEN_COMPONENT_SPEC.md` / `option_c_plus_tokens.css` — tokens (light/dark)
- `OPTION_C_PLUS_STATE_MATRIX.md`, `OPTION_C_PLUS_MOTION_SPEC.md`, `OPTION_C_PLUS_CLOSURE_REPORT.md`
- `CAPTURE_MANIFEST.json` — 40 native-viewport baseline definitions + Playwright recipe
- `QA_HARNESS_C_PLUS.html` — executable QA harness (CORRECTED here, 2026-07-28)

Harness correction (root cause)
The shipped harness's `reload(hash)` assigned `stage.src` to the same document plus a
fragment; same-document fragment navigation never fires the iframe `load` event, so
`await reload()` hung on the first call (and again at the theme-persistence step).
Fixed with a cache-buster query param (forces a full navigation every call) plus an
explicit ready handshake (readyState + `__opt` boot polling, 15s hard timeout that
REJECTS into a failing row — the harness can no longer hang and never fabricates JSON).

Run: `python3 -m http.server 8080` in this folder → open
`http://localhost:8080/QA_HARNESS_C_PLUS.html` → Run all checks → Download JSON report.

Shared deterministic fixture contract (SAATHI-121 oracle closure, 2026-07-28)
-----------------------------------------------------------------------------
The reference frames are now GENERATED from the repository-owned fixture
contract so both sides of the visual oracle render the identical semantic
fixture:

- contract (single source): `frontend/scripts/lawschool_fixture_contract.json`
  (+ loader `frontend/scripts/lawschool_fixture_contract.mjs`)
- generator: `cd frontend && node scripts/generate-lawschool-reference-fixture.mjs`
  (deterministic + idempotent; rewrites the embedded LSKIT resource inside
  `OPTION_C_PLUS_GUIDED_CONFIDENCE.html`, patches the hard-coded state ids in
  the bundled template with anchored count-verified replacements, refreshes
  `QA_HARNESS_C_PLUS.html` expectations and `SHA256SUMS.txt`)
- readable output for review: `OPTION_C_PLUS_LSKIT_GENERATED.js`

School ids in the reference are now the BACKEND catalog slugs (frozen
12-school catalog), fact rows byte-match the backend seed
(`law_school_service.seed_law_schools`), and `window.LSKIT.FIXTURE.checksum`
embeds the contract checksum. `frontend/scripts/lawschool-e2e.mjs` refuses to
capture any visual pair when the developed API fixture checksum, the embedded
reference checksum and the contract checksum are not all equal
(`FIXTURE_CONTRACT_MISMATCH`), and fails any pair whose two feature-region
captures differ in size (`CAPTURE_DIMENSION_MISMATCH`) — percentages are never
computed over padded canvases.

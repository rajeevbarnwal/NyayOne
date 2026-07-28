# MAC_RUN_ORACLE — SAATHI-118/120/121 valid visual oracle: Mac-delegated gates

Branch: `engineer/wave1-lawschool-option-c-plus-integration` (oracle commit on top of 60fe345).
Sandbox push attempt recorded 2026-07-28: `git push` RC=128, `git ls-remote` RC=128
(`git@github.com: Permission denied (publickey)` — no SSH identity in the Linux
sandbox) → push/PR/CI are Mac-delegated, step 0 below.
Scope of this cycle: ORACLE VALIDITY ONLY — no visual remediation of production
CSS/JSX was performed (QA at 60fe345 invalidated the previous oracle: unequal
capture bounds + unequal semantic fixtures; percentages from padded canvases
are retired). The Linux sandbox has no Chromium/PG16/network, so the following
gates are delegated to the Mac in this exact order.

## 0) Push + PR + CI (blocking precondition)
```
git push -u origin engineer/wave1-lawschool-option-c-plus-integration
git ls-remote origin engineer/wave1-lawschool-option-c-plus-integration   # record RC + remote hash
```
Open/refresh the PR, record PR URL + CI run. QA will not accept a local-only
hash (prior QA blocked on exactly this).

## 1) One corrected-harness run → VALID baseline manifest (no code changes)
```
docker compose up -d db   # PG16 + pgvector on port 1032 (volume pgdata)
# backend on :1031 against PG16, frontend production build served on :1050
cd frontend && npm ci && npx playwright install chromium
QA_BASE_URL=http://127.0.0.1:1050 QA_API_BASE_URL=http://127.0.0.1:1031 \
QA_EVIDENCE_DIR=<abs>/QA/mac_oracle_baseline npm run qa:lawschool
```
The corrected oracle enforces, per pair (40 = S-27..S-30 x 390/430/768/1024/1440 x light/dark):
- fixture gate BEFORE capture: contract checksum == developed API checksum ==
  reference embedded checksum (else FIXTURE_CONTRACT_MISMATCH, no captures);
- feature-region element captures only (`section.st-screen` vs `#frame`,
  reference frame width pinned to the developed region width; both bounding
  boxes/selectors/PNG sizes recorded in the manifest);
- CAPTURE_DIMENSION_MISMATCH (no percentage, no padding) when sizes differ;
- <2% strict threshold; N/A/advisory/missing never PASS; non-zero exit after
  evidence when any pair fails.
The FIRST run's manifest is the VALID BASELINE — archive it verbatim
(`lawschool_c_plus_visual_manifest.json` + PNGs) before touching any code.

## 2) THEN the targeted remediation loop (measure → fix → re-run)
Work ONLY from measured baseline deltas, smallest surface first, re-running the
harness after each step until 40/40 < 2%:
1. typography/tokens/spacing + dark palette (option_c_plus_tokens.css parity);
2. card geometry (S-27 result cards, S-29 attr cards, S-30 cards);
3. responsive behaviour at 390/430/768/1024/1440 (region widths, wrap points);
4. screen-specific: S-27 tray/pagination band, S-28 fact rows (labels for the
   six contract fact keys; keep sample/source/disclosure labels — sample
   values must never read as verified claims), S-29 fact cards (13-row schema
   incl. established/location/intake/hostel/legal_aid_clinics/moot_teams),
   S-30 saved/followed groups (2+2 fixture).
Expect honest CAPTURE_DIMENSION_MISMATCH failures at baseline where developed
region height differs from the reference — fix content/spacing, never the oracle.

## 3) PG16 gate (mandatory — SQLite is NOT PG proof)
QA at 60fe345 saw three SQLite-only concurrency failures:
`TC-63-04-concurrent-save` (parallel_saves_single_row),
`TC-63-04-concurrent-follow` (parallel_follows_single_row),
`TC-63-04-concurrent-compare-create` (parallel_compare_creations_bounded) —
500s/404s under SQLite lock contention (one 200 payload showed uniq=3 items).
These are classified as SQLite lock-contention artifacts, NOT confirmed PG
defects; QA's binding position is that PostgreSQL is the authoritative
concurrency runtime. On the Mac the harness MUST run against PG16 and these
three cases must be all-200 with exactly-one-row / 4-unique-items semantics.
If any of them fails ON PG16, that IS a genuine defect — fix backend
transaction code then, not before.

## 4) Registration regression
`npm run qa:registration` with otp_capture_server → 48/48 required.

## 5) Evidence
Archive: lawschool report+manifest+PNGs+traces, registration report, PG16
concurrency output, pushed hash + CI link, SHA256SUMS. Update Jira
SAATHI-120/121 with the baseline numbers (no transitions).

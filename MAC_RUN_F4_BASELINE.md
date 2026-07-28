# MAC_RUN_F4_BASELINE — SAATHI-63/118/119/120/121: F4 Mac-delegated gates

Branch: `engineer/wave1-lawschool-option-c-plus-integration`.
This commit closes QA F1–F3 from
`QA/independent_option_c_42f07a9_2026-07-28/INDEPENDENT_QA_REPORT.md`:
- F1: reference-bundle generator root fix — JSON payloads are re-escaped
  (`</script` -> `<\u002Fscript`, `<!--` -> `\u003C!--` inside the JSON payloads), the LSKIT resource is
  stored uncompressed base64 (Node/zlib-independent bytes), the generator
  refuses to emit a bundle with a literal `</script>` inside a payload, and the
  regenerated `OPTION_C_PLUS_GUIDED_CONFIDENCE.html` is committed (5 close
  tags, was 7). Generator is byte-idempotent (two runs, zero diffs).
- F2: `0006_lawschool_fact_backfill` reconciles upgraded databases to the 12
  schools x 6 approved facts (72 rows) + `seed_law_schools` is now per-record
  reconciliation (no global early-return). Proven by
  `backend/tests/test_lawschool_fact_upgrade.py` (real 0005 parent DB with the
  old 24-fact seed -> upgrade head -> 12/72 contract match; idempotent;
  downgrade/re-upgrade clean).
- F3: the visual manifest is fail-closed truthful:
  approvedPairs/attemptedPairs/capturedPairs/scoredPairs/passedPairs/failedPairs
  (gate failure reads 40/40/0/0/0/40 — never `captured: 40`), unit-tested in
  `frontend/scripts/lawschool_visual_manifest.test.mjs`.

Sandbox limits (recorded 2026-07-28): no SSH identity (push/ls-remote RC=128
previously), no root, chromium headless_shell present but cannot load
`libXdamage.so.1` — the real boot test therefore skips ONLY on such hosts and
runs for real on Mac/CI. F4 below is Mac-delegated in this exact order.

## 0) Push + PR + CI (blocking precondition)
```
git push -u origin engineer/wave1-lawschool-option-c-plus-integration
git ls-remote origin engineer/wave1-lawschool-option-c-plus-integration   # record RC + remote hash
```
Open/refresh the PR, record PR URL + CI run. QA will not accept a local-only hash.

## 1) Real chromium boot test (must PASS before any visual run)
```
cd frontend && npm ci && npx playwright install chromium
npx vitest --run scripts/lawschool_reference_boot.test.mjs
```
Required: 3/3 (no skip on Mac) — window.__opt boots, no `#__bundler_err`, no
console/page errors, `window.LSKIT.FIXTURE.checksum ==
49f3bce98b8ae00e7073b6899c6ec65d5dee4d3b9d2ba82f012e6172ba0c74c9`, and
`__opt.apply/render/setFrame/focusHeading` all functions. If this fails, STOP:
the reference is broken again — do not capture anything.

## 2) One corrected-harness run → FIRST VALID baseline manifest (no code changes)
```
docker compose up -d db   # PG16 + pgvector on port 1032 (volume pgdata)
# backend on :1031 against PG16, frontend production build served on :1050
QA_BASE_URL=http://127.0.0.1:1050 QA_API_BASE_URL=http://127.0.0.1:1031 \
QA_EVIDENCE_DIR=<abs>/QA/mac_f4_baseline npm run qa:lawschool
```
Per pair (40 = S-27..S-30 x 390/430/768/1024/1440 x light/dark): fixture gate
BEFORE capture (checksum triple-equality); feature-region element captures
(`section.st-screen` vs `#frame`, frame width pinned); dimension-strict; <2%
threshold; N/A/advisory never PASS; non-zero exit after evidence. The manifest
now reports the truthful sextuple — a valid baseline REQUIRES
`capturedPairs == attemptedPairs == 40` (scored may be lower only via honest
CAPTURE_DIMENSION_MISMATCH entries). Archive the first manifest + PNGs
verbatim before touching any code.

## 3) Targeted remediation loop (measure → fix → re-run) to 40/40 < 2%
Work ONLY from measured baseline deltas, smallest surface first, re-running
after each step until `passedPairs == 40`:
1. typography/tokens/spacing + dark palette (option_c_plus_tokens.css parity);
2. card geometry (S-27 result cards, S-29 attr cards, S-30 cards);
3. responsive behaviour at 390/430/768/1024/1440 (region widths, wrap points);
4. screen-specific: S-27 tray/pagination band, S-28 fact rows (six contract
   fact keys; sample values must never read as verified claims), S-29 fact
   cards (13-row schema), S-30 saved/followed groups (2+2 fixture).
Fix content/spacing, never the oracle.

## 4) PG16 concurrency gate (mandatory — SQLite is NOT PG proof)
`TC-63-04-concurrent-save`, `TC-63-04-concurrent-follow`,
`TC-63-04-concurrent-compare-create` must be all-200 on PG16 with
exactly-one-row / 4-unique-items semantics. A failure ON PG16 is a genuine
backend defect — fix transaction code then, not before. Also verify the
upgraded-DB path on PG16: `alembic upgrade head` on the existing volume, then
`SELECT count(*) FROM law_school_facts` == 72 with contract values.

## 5) Registration regression
`npm run qa:registration` with otp_capture_server → 48/48 required.

## 6) Evidence
Archive: lawschool report + truthful manifest + PNGs, boot-test output,
registration report, PG16 concurrency output + fact backfill query, pushed
hash + CI link, SHA256SUMS. Update Jira SAATHI-63/118/119/120/121 with the
baseline numbers (no transitions).

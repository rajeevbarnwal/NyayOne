# MAC_RUN_FINAL — SAATHI-63/118/119/120/121: Option C+ final closure (mandatory 11-step execution)

Branch: `engineer/wave1-lawschool-option-c-plus-integration`.
This commit closes QA F1–F4 from
`QA/independent_option_c_e843116_2026-07-28/INDEPENDENT_QA_REPORT.md`:

- **F1** — self-contained PG harness: `backend/scripts/seed_e2e_actors.py` is the
  repository-owned, idempotent setup seam that provisions the exact dev-claims
  actors (`…00de` student, `…00b2` student, `…00c3` lawyer — active) plus the
  catalog and the S-30 contract fixture by direct FK-honouring inserts. The
  harness now runs a typed actor preflight (`PREFLIGHT-ACTORS`) and FAILS with
  `ACTOR_SETUP_MISSING` before any browser case if the actors are absent.
  Idempotency is unit-proven (`backend/tests/test_seed_e2e_actors.py`: run
  twice → zero duplicate rows) and run twice on PG16 in
  `.github/workflows/wave1-foundation-gate.yml`.
- **F2** — approved 13-row S-29 schema (State, Institution type, Accreditation,
  Entrance exam, Fees, NIRF rank, Programmes, Established, Location, Intake,
  Hostel, Legal aid clinics, Moot teams) rendered from the SHARED formatter
  `frontend/src/features/student/schools/lawschoolFormat.mjs` (also drives the
  fixture contract and the reference generator — INR-vs-lakh unified: lakh on
  S-27 cards/S-30 metalines, INR-raw band on S-28/S-29). Compare endpoint
  projection is deterministic (facts by key, programmes by degree; API tests
  assert 13 derivable row keys for 2- and 4-school compares). Harness asserts
  `cards === 13` + exact label order.
- **F3** — REAL shell isolation: a TEST-ONLY stylesheet hides `.ls-topbar` /
  `.ls-bnav` before every developed capture; a per-pair executable assertion
  verifies the shell is hidden, intersects nothing, and the first/last visible
  children of `section.st-screen` are feature-local chrome. Violation ⇒
  `SHELL_ISOLATION_VIOLATION` (fail-closed). Production AppShell untouched.
- **F4** — fixture contract v2 (`2.0.0-option-c-plus-oracle`, checksum
  `942ff09e326428405a364c89aa5ccb513526c11314d092673f845a25e931809e`): the
  checksum now covers every visible S-27 card (incl. fees lakh strings), the
  full S-28 identity/fact rows with source+freshness copy, ALL 13 S-29 rows ×
  school order × labels × formatted values, S-30 group order/names/metalines/
  CTAs, and the `option_c_plus_tokens.css` hash. A unit test proves a 7-row
  S-29 projection FAILS the v2 checksum. Reference bundle regenerated from v2
  (generator byte-idempotent).

Sandbox limits (recorded 2026-07-28): no SSH identity (push/ls-remote RC
recorded), chromium headless_shell cannot load `libXdamage.so.1`. All
browser/PG16 gates below are Mac-mandatory.

## The 11 mandatory steps (in this exact order)

### 1) Provenance + push (blocking)
```
git rev-parse HEAD                     # must equal the reviewed commit
git push -u origin engineer/wave1-lawschool-option-c-plus-integration
git ls-remote origin engineer/wave1-lawschool-option-c-plus-integration   # record RC + hash
```
Open/refresh the PR, record PR URL + CI run. QA will not accept a local-only hash.

### 2) Frontend native gates
```
cd frontend && npm ci && npm run typecheck && npm run lint && npm run test:run && npm run build
```
All zero-exit; vitest includes the new formatter/13-row and contract-v2 suites
(7-vs-13 checksum regression must PASS-as-in-fail-detected).

### 3) Backend native gate
```
cd backend && python -m pytest -q     # 187 base + new seed/13-row tests, 0 failures
```

### 4) SQLite alembic gate
```
cd backend && DATABASE_URL=sqlite+pysqlite:///$(mktemp -d)/gate.db \
  sh -c 'python -m alembic upgrade head && python -m alembic check && \
         python -m alembic downgrade base && python -m alembic upgrade head'
```

### 5) Clean PostgreSQL 16 + actor setup (F1 — SELF-CONTAINED, one command each)
```
docker compose up -d db                       # PG16 + pgvector :1032
cd backend && python -m alembic upgrade head
python scripts/seed_e2e_actors.py             # idempotent setup seam
python scripts/seed_e2e_actors.py             # second run: MUST create nothing
```
Record both outputs; `SELECT count(*) FROM users WHERE id IN (…00de,…00b2,…00c3)` == 3;
`law_school_facts` == 72.

### 6) Real chromium boot test (must PASS before any visual run)
```
cd frontend && npx playwright install chromium
npx vitest --run scripts/lawschool_reference_boot.test.mjs   # 3/3, no skip
```
`window.LSKIT.FIXTURE.checksum` must equal
`942ff09e326428405a364c89aa5ccb513526c11314d092673f845a25e931809e`. If this
fails, STOP — do not capture anything.

### 7) One-command law-school suite (functional + preflight)
```
# backend :1031 on PG16, frontend production build served on :1050
QA_BASE_URL=http://127.0.0.1:1050 QA_API_BASE_URL=http://127.0.0.1:1031 \
QA_EVIDENCE_DIR=<abs>/QA/mac_final npm run qa:lawschool
```
`PREFLIGHT-ACTORS` must PASS (a clean checkout + steps 5–7 is the whole
self-contained recipe; if it fails with `ACTOR_SETUP_MISSING`, step 5 was
skipped — fix the runbook, not the FKs). Functional target: 0 FAIL.

### 8) Visual baseline manifest (fail-closed truth)
Per pair (40 = S-27..S-30 × 390/430/768/1024/1440 × light/dark): v2 fixture
gate BEFORE capture (checksum triple-equality + DOM label/order probes incl.
the 13 S-29 labels); TEST-ONLY shell hide + per-pair isolation assertion;
feature-region element captures (`section.st-screen` vs `#frame`, frame width
pinned); dimension-strict; <2% threshold. Manifest sextuple must read
`capturedPairs == attemptedPairs == 40` with zero
`SHELL_ISOLATION_VIOLATION`. Archive the first manifest + PNGs verbatim
before touching code.

### 9) F5 remediation loop (measure → fix → re-run, to 40/40 < 2%)
Work ONLY from measured per-screen bounding boxes and diffs; smallest surface
first; re-run step 8 after each change. Known deltas and their code-level
resolutions (reconcile each IN CODE — never mask, crop, resize, pad, or weaken
the 2% threshold, and never edit the reference):
1. **INR-raw vs lakh fees** — FIXED in this commit (shared formatter: lakh on
   S-27 "Costs about" and S-30 metalines; verify in diffs, no action expected).
2. **Action labels** (e.g. S-28 Save/Follow wording vs reference) — align the
   developed button/CTA copy in `SchoolScreens.tsx` to the reference frame.
3. **Source/freshness copy** — S-29 footer now uses the reference
   source+responsible copy; align remaining `ls-src`/foot lines per screen.
4. **Saved/followed order + city/state formatting** — lists are now
   deterministically ordered (created_at); the reference metaline uses CITY
   while the developed summary carries `state` — if the diff exceeds budget,
   expose `city` via the list/summary projection (backend join on the
   `location` fact or a summary column), never by parsing display strings in
   the UI.
5. **Footer/disclosure copy** — align `RESPONSIBLE_COPY`/`DPDP_COPY` composites
   to the reference `C.source`/`C.responsible`/`C.dpdp` per screen.
Each loop iteration: record pair, delta %, changed file(s), re-run result in
the evidence dir.

### 10) PG16 concurrency + registration regression
- `TC-63-04-concurrent-save/follow/compare-create` all-200 with
  exactly-one-row / 4-unique-items semantics ON PG16.
- `npm run qa:registration` with otp_capture_server → 48/48 required.

### 11) Evidence + Jira
Archive: lawschool report + truthful manifest + PNGs, boot-test output, both
seed_e2e_actors outputs, PG16 queries, registration report, pushed hash + CI
link, SHA256SUMS.txt. Update SAATHI-63/118/119/120/121 with the numbers (NO
status transitions).

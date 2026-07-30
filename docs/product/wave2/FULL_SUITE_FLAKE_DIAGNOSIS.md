# Full-suite concurrency flake — diagnosis (Wave 2, item 5)

Reported by Independent QA against exact commit `c9cd6b1`: two complete
invocations, each `235 passed, 1 failed, 2 skipped`; the failure was in the
existing concurrent follow/saved HTTP tests, returning a transient 404 or 405.
Base `93dc585` passed `236 passed, 2 skipped`; isolated reruns passed.

Constraint honoured: every result below comes from a **single complete pytest
invocation** over all 238 tests. No chunking, no deselect, no xdist.

## What the 404 and 405 can actually be

* `404` — `_school_or_404()` in `app/api/v1/law_schools.py` is the only 404 on
  that path: the school row was not visible to that request's session.
* `405` — cannot come from a handler. It is emitted by the router when a path
  matches but the method does not, i.e. the app's effective route table was
  incomplete at the moment the request was routed.

The 405 is therefore the load-bearing clue: it points at route resolution, not
at the database.

## Hypothesis 1 — lazy route materialisation race. FALSIFIED

FastAPI 0.141.1 (`starlette` 1.3.1) expands `include_router` **lazily**:
`api_router.routes` holds `_IncludedRouter` objects and
`_IncludedRouter.effective_candidates()` builds the real route list on first
request, behind a lock with a **lock-free fast path**. Every test in this suite
shares the single module-level `api_router` and builds a fresh `FastAPI()` per
test, so first-request materialisation happens inside the 8-thread race.

Tested directly (`probe_lazy_routes.py`): cold app per round, 8 threads released
by a `threading.Barrier`, 150 rounds × 3 targets = **3600 barrier-synchronised
requests on cold apps**. Result: `GET /health` → `{200: 1200}`, unauthenticated
`PUT …/{id}/follow` → `{401: 1200}`, `PUT …/{id}/saved` → `{401: 1200}`. One
distinct status per target, zero 404/405. Publication order in
`effective_candidates()` (list assigned before version) is also correct, and
`_get_routes_version()` cannot return `None`, so the empty-default cache can
never be served. **Not the cause.**

## Hypothesis 2 — reproducible in isolation. FALSIFIED

`repro_conc.py` replicates the test wiring exactly (serialized file engine,
`BEGIN IMMEDIATE`, `NullPool`, production-style session dependency): 25
iterations × 2 surfaces = 50 rounds, 400 requests → `{200: 400}`, one row per
round. **Zero failures in isolation.**

## Hypothesis 3 — state from earlier tests in suite order. NOT REPRODUCED

pytest 9.1.1 runs with **no plugins** (no `pytest-randomly`, no `xdist`), so
collection order is deterministic. The exact ordered prefix up to and including
`test_wave1_law_schools.py` was run as one invocation: **172 passed**. The four
files collected after it contain no import-time global side effects (no global
SQLAlchemy event listeners, no env mutation).

## A real defect found while hardening (kept out of the tree)

Rewriting the non-PostgreSQL branch of `_idempotent_insert` to use
`with session.begin_nested():` (SAVEPOINT) looks strictly better — it would keep
a racing writer's rollback private to the insert instead of discarding the
caller's whole transaction. It is wrong on pysqlite: pysqlite opens no
transaction for a `SAVEPOINT` statement, so `RELEASE SAVEPOINT` **durably
commits the row**, and a later failure of the request commit can no longer undo
it. `test_commit_failure_put_follow_rolls_back_and_retries` failed with 1
persisted follow row where 0 are required. Reverted; the reasoning is recorded
in the function docstring so it is not "fixed" again. The full-transaction
rollback is safe there because callers write nothing before that call.

## Hardening applied (assertions strengthened, never relaxed)

`test_http_concurrent_put_all_200_one_row_one_audit`:

1. The 8 callers are released by `threading.Barrier(8, timeout=20)`, so they
   provably enter the endpoint together instead of depending on thread-pool
   scheduling. The timeout turns a lost racer into a test failure rather than a
   hang.
2. `_materialise_routes(app)` resolves the effective route table **once, in the
   main thread**, and asserts it is non-empty. Route construction is therefore
   no longer part of the measured race, and a wiring regression fails loudly.
3. `assert uuid.UUID(sid)` — a missing seed row now fails at setup instead of
   surfacing later as a request 404.

The contract is unchanged and still enforced: **all eight requests 200, exactly
one row, exactly one audit row.**

## Evidence — complete unchunked runs at head

| Run | Command | Result |
|---|---|---|
| pre-hardening | one complete invocation | `236 passed, 2 skipped in 39.91s` |
| post-hardening | one complete invocation | `236 passed, 2 skipped in 32.42s` |
| A (08:51:12Z) | one complete invocation | `236 passed, 2 skipped in 26.99s` |
| B (08:51:46Z) | one complete invocation | `236 passed, 2 skipped in 24.72s` |
| C (08:52:20Z) | one complete invocation | `236 passed, 2 skipped in 27.17s` |

A, B and C are the three **consecutive** complete-suite green runs, back to back.
Reproducible via `backend/scripts/full_suite.sh 3 <evidence_dir>`.

## The flake IS reproducible — on the unpinned interpreter, not on the pinned one

The sandbox has two interpreters, and this is the finding that matters:

| Interpreter | fastapi | Complete runs | Result |
|---|---|---|---|
| `/tmp/lsvenv/bin/python` (installed from `requirements.txt`) | 0.141.1 | 5 | green every time (3 consecutive: A, B, C) |
| `/usr/bin/python3` (system, unpinned) | **0.139.0** | 5 | **2 × `235 passed, 1 failed, 2 skipped`**, 2 green, 1 exceeded the shell cap |

`235 passed, 1 failed, 2 skipped` is exactly the shape Independent QA reported.
On the system interpreter **the failing test differs from run to run**:

* run 1 — `test_notifications.py::test_safe_log_view_excludes_recipient_and_values`
* run 2 — `test_wave3_credentials.py::test_tampered_unknown_malformed_expired_are_minimal`

Neither is the defect:

* Both pass in isolation on that same interpreter.
* `test_safe_log_view_excludes_recipient_and_values` is a **pure function call**
  with no I/O, no DB, no threads and no clock; its only ordering input is
  `sorted(self.variables.keys())`. It cannot fail from test interaction.
* A `PYTHONHASHSEED` sweep (0, 1, 2, 3, 5, 8, 13, 21, 34, 55) passes on every
  seed, so set/dict iteration order is not the mechanism either.

A pure, seed-independent test failing only inside a complete run, with the
identity of the victim changing between runs, is the signature of a fault
surfacing at an arbitrary point and being attributed to whichever test happens
to be executing — not of a defect in the named test. The concurrent follow/saved
tests specifically did **not** fail here: 3/3 green in a tight loop on both
interpreters, plus 400/400 requests green in the isolated repro.

**Conclusion.** The flake tracks the dependency environment, not the Wave 2
schema commit. `93dc585` green vs `c9cd6b1` failing is consistent with run-to-run
environment noise on the unpinned interpreter, and not with a head regression:
`c9cd6b1` adds only model classes plus migration `0008`, and no test that failed
touches them.

**Required follow-up for QA (not substitutable by the above):** re-run on the
pinned dependency set (`pip install -r backend/requirements.txt`) and, if a
failure recurs, capture the full traceback. `backend/scripts/full_suite.sh`
writes a complete per-run log for exactly this reason — the earlier evidence only
carried the one-line summary, which is why the mechanism is still open.

## Honest status

The QA-observed `235 passed, 1 failed, 2 skipped` was **not reproduced here** in
any complete run. Two candidate mechanisms are falsified by direct measurement
rather than by argument, and one class of nondeterminism (scheduling-dependent
overlap plus first-request route construction inside the race) has been removed
from the test. If the failure recurs, the barrier and the route assertion narrow
it to the database/idempotency boundary, and the failure message already prints
every status code with its response body.

Environment note: the sandbox caps a single shell call at 45s, and the complete
suite takes 25–50s depending on filesystem and CPU variance, so runs were
executed one per call. `PYTEST_DEBUG_TEMPROOT` on tmpfs (pytest temp dir only —
no semantic change) is what brings the wall time reliably under the cap.

---

# Runtime: getting the complete 603-test suite inside one 45s shell call

Follow-on work, same constraint as everything above: the gate is **ONE pytest
invocation that collects and runs the whole suite**. No chunking, no `-k`, no
deselect, no sharding, no xdist, no new skips or xfails, no reduced iteration
counts, no weakened assertions.

## Before / after

| | Wall time | Result |
|---|---|---|
| Before (P3 merged, 602 tests) | **47–50 s**, killed by the 45 s shell cap at 83–96 % | never completed |
| After (603 tests) | **28.9–31.8 s** | completes, green |

Collected count went **up**, not down: `603 tests collected` (602 pre-existing +
one new equivalence test, `test_db.py::test_schema_template_is_identical_to_create_all`,
which guards the optimisation below). `scripts/full_suite.sh` now prints the
collected count before every run so the "whole suite in one invocation" claim is
visible in the evidence.

## Measured profile (what was actually attacked)

Per-phase `--durations=0` totals, aggregated per file, over the complete run:

| Cost | Before | Mechanism |
|---|---|---|
| `Base.metadata.create_all` + `drop_all` per test | ~26 ms + ~8 ms **per test**, most of 602 tests | 53 tables / 147 CREATE statements walked per fixture, plus one existence probe per table |
| `python -m alembic <cmd>` subprocesses | ~20 runs × ~0.75–0.85 s ≈ **16 s** | ~0.45 s of interpreter + alembic/SQLAlchemy import before any work; `test_lawschool_fact_upgrade.py`'s `parent_db` re-ran `upgrade 0005_language_check` for every test |
| First request against a fresh `FastAPI()` | ~**38 ms per test** in 3 fixtures (~79 tests) | FastAPI ≥ 0.141 expands `include_router` lazily; the first request builds the whole effective route table |
| Cyclic GC | ~10 % of the run | collection imports every model/route/schema, so the old generation is large and permanent and got re-walked all run |

## What changed (fixture/setup plumbing only — no assertion touched)

* **`backend/tests/dbtemplate.py` (new)** — builds the schema ONCE per session with
  the real `Base.metadata.create_all`, then produces every later database with
  `sqlite3.Connection.backup()` (~0.6 ms vs ~26 ms). Provably equivalent: the new
  `test_db.py::test_schema_template_is_identical_to_create_all` compares the full
  `sqlite_master` catalogue (all 243 rows: tables, views, triggers, and explicit
  *and* implicit indexes, with their exact DDL) against a database built by
  `create_all`, so the shortcut cannot rot silently.
* **`backend/tests/apptemplate.py` (new)** — builds a mounted app + `TestClient`
  once per module and materialises the route table eagerly (asserting it is
  non-empty, so a wiring regression still fails loudly, and now fails at setup).
  Per-test state stays per-test: `dependency_overrides` is re-pointed for every
  test and the cookie jar is cleared. Same arrangement `wave2_helpers.ApiRig`
  already used for the Wave 2 API files.
* **`backend/tests/conftest.py`** — `db_session` resets the shared engine from the
  schema template instead of `create_all` + `drop_all`; new session-scoped
  `alembic_snapshots` / `alembic_snapshot_run` / `alembic_db` fixtures build the
  `0004_wave1_foundation`, `0005_language_check` and `head` databases in ONE
  subprocess that walks them through the real alembic CLI entry point
  (`alembic.config.main`, which is exactly what `python -m alembic` calls),
  snapshotting the file after each step; and `pytest_collection_finish` does
  `gc.collect(); gc.freeze(); gc.set_threshold(50_000, 50, 50)`. All fixtures are
  backward compatible — no existing consumer changed its signature.
* **Wired to the template/snapshot fixtures** (per-test `create_all` → template
  copy, redundant teardown `drop_all` → `engine.dispose()`, provisioning-only
  alembic upgrades → snapshot copy): `test_http_contract.py`,
  `test_pii_log_scan.py`, `test_registration_api.py`,
  `test_student_registration.py`, `test_wave1_law_schools.py`,
  `test_wave1_settings_privacy.py`, `test_wave2_schema.py`,
  `test_wave3_credentials.py`, `test_lawschool_fact_upgrade.py`,
  `wave2_helpers.py`.
* **`backend/scripts/full_suite.sh`** — defaults to the pinned interpreter
  (`/tmp/lsvenv/bin/python` first), sets a tmpfs `PYTEST_DEBUG_TEMPROOT` in the
  same invocation that creates it (`/dev/shm` is recreated per shell call in this
  sandbox), prints the collected test count and a per-run wall time, and its
  comments now name where each optimisation actually lives. The no-chunking
  guarantee is unchanged: still exactly one `pytest` invocation per run, default
  order, `-p no:cacheprovider`.

## Coverage explicitly preserved

Nothing was skipped, deselected, xfailed, shortened or de-asserted. The `alembic`
CLI is still exercised end to end by **14 real `python -m alembic` invocations
inside test bodies** (4 + 6 + 4 below), plus the one batched snapshot subprocess.
These tests keep their own:

* `test_wave2_schema.py::test_alembic_lifecycle_upgrade_check_downgrade_reupgrade`
  — the flagship lifecycle test, untouched: real `alembic check`, `downgrade`
  to 0008's parent, `upgrade head`, and a second `alembic check`, with the table
  set and `alembic_version` asserted between every step.
* `test_lawschool_fact_upgrade.py` — `test_upgrade_head_backfills_parent_state_db`
  (real `upgrade head` on the parent-state DB),
  `test_upgrade_is_idempotent_and_seed_reconciliation_changes_nothing`,
  `test_downgrade_then_reupgrade_clean` (real `upgrade head`, `downgrade
  0005_language_check`, re-`upgrade head`) and
  `test_upgrade_head_is_safe_on_fresh_db` (a real one-shot `upgrade head` over the
  whole chain from an empty database). Only the `parent_db` fixture's three
  duplicate `upgrade 0005_language_check` provisioning runs were removed.
* `test_wave1_settings_privacy.py::test_f2_migration_maps_legacy_and_guards_unknown`
  — all four asserted invocations stay real: `upgrade head` (legacy labels map),
  `downgrade 0004_wave1_foundation` (data survives), the clean re-`upgrade head`,
  and the must-fail `upgrade head` on the unmapped `Klingon` value. Only the two
  identical `upgrade 0004_wave1_foundation` provisioning runs were replaced by a
  snapshot copy.

## Two pre-existing flakes the completed suite exposed — and fixed

Both live in the tail of the suite (past the 83 % mark), i.e. in the region the
45 s cap had been truncating, which is why neither had ever been observed here.
Both are coincidence bugs in test *inputs*, not in the code under test; both fired
during this work.

**1. `test_wave2_sessions.py::test_no_card_media_or_token_canary_can_reach_storage_logs_or_payloads`
— measured ~5.8 % per run (7 failures in 120 clean booking flows).**
`CVV = "123"` is scanned as a substring against every persisted TEXT/JSON value.
`_every_persisted_value` already documented that UUID/timestamp text must not be
scanned "or a 3-digit CVV canary would collide with random hex by chance" — but
identifiers re-enter through JSON columns (`audit_events.after_state['refund_id']`,
`payment_orders.provider_order_ref`, `payment_events.payload_digest`, …). One
booking flow persists ~250 random hex characters. Fix: mask machine identifiers
before scanning — dashed UUIDs, and hex runs of 16+ characters **that contain at
least one `a-f` letter**, so a purely numeric run is never masked and the
decimal-only `PAN`/`CVV`/`PAYMENT_OTP` canaries stay findable. Verified: 0/120
false positives after masking, and all six canaries still detected in all three
realistic leak shapes (own value, JSON value, delimited inside a string). Residual
stated in the code: a canary concatenated with no delimiter directly onto a
letter-bearing 16+ char hex identifier. Parts (1) and (3) of the same test — the
provider seams raising on PAN/CVV/OTP and `assert_payload_safe` rejecting
forbidden keys and PAN-shaped values — are deterministic and untouched.

**2. `test_wave3_credentials.py::test_tampered_unknown_malformed_expired_are_minimal`
— ~6.25 % per run. This is the mechanism left open above.**
The "tampered" token was built as `token[:-1] + "A"`, which is a **no-op whenever
the token already ends in `A`** — and it does about 1 token in 16, because the
token is `urlsafe_b64encode(32-byte digest)` with padding stripped, so its final
character carries only 4 significant bits and comes from a 16-character alphabet.
When that happened the "tampered" token *was* the valid token, and the endpoint
correctly returned 200 where the test asserted 404. The earlier diagnosis noted
this exact test failing intermittently and recorded it as unexplained; it is now
explained. Fix: choose a replacement character that differs from the one it
replaces, plus `assert tampered_token != token["token"]` so a future no-op
mutation fails loudly. Lookup is `keyed_hash(token)` over the raw ASCII string, so
any single-character change is a genuine tamper — the case is unchanged, it is
merely now guaranteed to happen.

## One more latent flake, measured but NOT changed

`test_wave2_api.py::test_booking_trail_and_audit_carry_ids_and_codes_only` scans a
lowercased JSON blob for the canary `"4111"`. Measured on the real blob: 606
four-character windows inside UUID/hex-shaped regions, i.e. **~0.9 % per run** of
a coincidental match. It has not fired in ~12 complete runs. It is left alone
because fixing it means editing a test's canary list, which is outside this
change's remit. Recommended fix when someone owns it: run the same
`_mask_identifiers` de-noising over that blob (promote the helper into
`tests/wave2_helpers.py` so there is one implementation). The sibling three-letter
canaries (`pan`, `cvv`, `sdp`, `otp`) cannot collide with hex and are safe as-is.

## Considered and rejected (would have reduced what is proven)

* **Serving `test_upgrade_head_is_safe_on_fresh_db` from the `head` snapshot.** The
  snapshot is built incrementally (`0004` → `0005` → `head`); the test's subject is
  a single one-shot `upgrade head` over the whole chain from an empty database.
  Different invocation shape, so it keeps its own real run (~0.75 s).
* **A long-lived "alembic worker" subprocess** (or `os.fork()` from the warm pytest
  process) to amortise the ~0.45 s import across all 13 remaining invocations,
  worth ~5 s. Rejected: the asserted error text for the must-fail migration can
  reach `stderr` via logging handlers bound at first `fileConfig`, so repeated
  in-process `alembic.config.main()` calls are not reliably equivalent to separate
  `python -m alembic` processes, and forking a process that has run
  `TestClient`/anyio threads risks inheriting a held lock. Not worth trading
  migration-test fidelity or run-to-run determinism for 5 s.
* **Batching `test_downgrade_then_reupgrade_clean`'s first two commands** into one
  subprocess (allowed: only return codes are asserted between them). Worth ~0.75 s
  and left undone once the target was comfortably met — available if needed.
* Chunking, sharding, `-k`, `--deselect`, xdist, new skip/xfail marks, and reducing
  the thread counts or iteration counts in the concurrency tests: all off the table
  by construction. `full_suite.sh` still runs one invocation over everything.

## Evidence — three CONSECUTIVE complete-suite green runs

Commit `1344e09`, `/tmp/lsvenv/bin/python` (fastapi 0.141.1), one complete
invocation per shell call, back to back, `603 tests collected` verified before
each:

| Run | Start (UTC) | Result line | Shell wall |
|---|---|---|---|
| A | 12:19:09 | `601 passed, 2 skipped, 1 warning in 29.22s` | 31 s |
| B | 12:19:46 | `601 passed, 2 skipped, 1 warning in 28.92s` | 31 s |
| C | 12:20:23 | `601 passed, 2 skipped, 1 warning in 31.79s` | 34 s |

(`601 passed, 2 skipped` = 603 collected; the 2 skips are
`test_wave3_postgres_runtime.py`, which needs a live PostgreSQL and skipped before
this work too.) Seven further complete runs were executed while the work was in
progress; the only two non-green results in the whole exercise were the two flakes
described above, each of which fired once and is now fixed.
Reproducible via `PYTHON=/tmp/lsvenv/bin/python backend/scripts/full_suite.sh 3 <evidence_dir>`,
or one run per call with `... full_suite.sh 1 <evidence_dir>` where the 45 s cap
applies.

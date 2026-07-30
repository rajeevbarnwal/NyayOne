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

# NYAY-23 — native cookie readiness (quarantine retained)

The native PostgreSQL gate adapts the NYAY-26/37 arm-before-observation pattern
to synchronous TestClient HTTP/body settlement and independent committed-row
read-back. It does not substitute a browser readiness signal for server authority.

One timing client owns the transport portal; known and decoy flows retain
separate server-issued cookie jars. Both observers are armed before requests.
Sampling starts only after canonical start and state responses are fully consumed,
the exact class-specific authority graph is visible in a fresh transaction,
the known provider receipt is committed (or the decoy no-delivery branch is
proven), and the secure host-only cookie is present. The decoy namespace remains
independent of real-account authority. No private values enter diagnostics.

All 120 seeded event orders execute once. Every incomplete prefix fails closed;
late observations cannot resurrect an expired observer. No sleep or retry grants
authority. The timing oracle remains 40 samples per class, nearest-rank p95,
strict ratio <= 2.0. It is not calibrated from synthetic schedules.

## Validation record

- Accepted RED: 14 intentional failures plus five preservation passes.
- GREEN: 19/19 contracts; the test loader is cached so repeated imports share
  the same exception class. This fixes exception identity, not any assertion.
- Full backend: 3,356 passed, five skipped, five subtests passed.
- Full frontend: typecheck, lint, production build; 1,586 Vitest tests passed.
- CI-unit discovery: 289 passed; workflow verifier: ten workflows passed.
- Three consecutive complete strict PostgreSQL gate runs: each 17/17 assertions,
  27/27 mutants. In run order, p95 ratios 1.047, 1.229, 1.171.
- Full native matrix: migration lifecycle, pgvector, Wave-2/3/4/5 and
  NYAY-2/3/4/5/9/11/16/17/19/22 gates passed.

An earlier local matrix was invalidated by missing frontend dependencies: the
cookie assertion passed, but the required frontend harness proof failed. Its
failed log is retained and is not counted among the three successful runs.

## Re-promotion is a separate decision

The quarantined assertion and its manual evidence workflow are unchanged.
Local green is not Linux timing proof. Before any separately approved promotion:
retain the published distinct-head/consecutive-run campaign, exact inventory
and observer-coverage proof, no sleeps/retries as readiness, unchanged p95 oracle,
and independently reviewed privacy-safe evidence. No re-promotion is authorized
by this tooling change. NYAY-21 remains HOLD/NO-GO.

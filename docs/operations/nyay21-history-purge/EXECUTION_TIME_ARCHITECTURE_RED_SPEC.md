# NYAY-21 execution-time architecture — RED specification only

Base: merged main `040f9a74a7f75503f7790ace0210800340f01fbe`.
No implementation, execution approval, new historical seal, or production
snapshot is delivered here. Historical R2–R5/audit artifacts remain immutable.

## New version boundary

Add an execution/v2 policy/API beside historical validators, not by replacing
historical constants with arbitrary untrusted input. A reusable validator has
no deployment-specific head/count; each execution snapshot and both approvals
remain exact-head/exact-inventory/digest bound. The original v1 paths continue
to validate the immutable history they actually record.

The proposed interfaces in `test_nyay21_execution_time_seal.py` are pure planning
and validation functions. Injected observations are synthetic fixtures, not
claims that GitHub, a signer, or the owner has approved anything. Production
integration must independently acquire authenticated source/readback records,
verify approval provenance/consumption with the existing strict registry, and
compose all unchanged backup, retention, ruleset, gate and execution prerequisites.
No API PASS here may set `executionAuthorized=true` or perform a mutation.
The positive fixtures do not replace execution-day independent attestations.

## Contract inventory

| Tests | Boundary |
| --- | --- |
| 01–10,30,33 | Two-read stable closed-world capture; new heads without code reseal; canonical ordering; HEAD/ref drift; no empty/duplicate inventories; strict numeric types; exact repository/targets; no writes/spawns |
| 11–16,31–32 | Distinct R/F exact-seal approval scopes, expiry and consumption; no truthiness; changed head invalidation |
| 17–20 | Atomic dry-run command plan with one explicit old-OID lease per sealed ref; missing/extra/stale rows denied |
| 21–24,34–35 | Watchdog current-head/seal/payload rebind; failed GET, stale heartbeat and invalid retry budget deny readiness |
| 25–26 | Explicit single-operator risk attestation and technical approval, no fictional second person; all three PROCEED pause points |
| 27–29,36 | Workflows:write is an explicit owner decision and observed permission requirement for changed workflow paths; unrelated privileges refused |

These 36 tests currently fail at named missing-interface assertions, not because
the tests ran a destructive command. Their downstream behavioral assertions are
the GREEN acceptance target; they have not yet been proven against an implementation.

## Required independent review before fresh GO

Validate real snapshot collection and signer/registry provenance, strict types
across all executable numeric inputs, actual minimum token scope and expiry,
closed-world leases, trap/watchdog failed-GET/PUT/SIGKILL paths, custody/access
logs, live ruleset restoration and exact-head campaign/receipt rebinding. Keep
plan-only default, protected-checkout isolation and pause-point authority.
Live proof or rewrite is separately authorized; these tests do not run either.

## Hold

No GREEN until owner authorization. No commit/push in this RED kickoff. No
rewrite, backup, freeze, token creation, ruleset change, or visibility change.

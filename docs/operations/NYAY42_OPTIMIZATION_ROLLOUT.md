# NYAY-42 optimization rollout — observation stage

## State and authority

This change is **incomplete implementation / observe-only**, not a claim of
minute savings, runner migration, or completion of NYAY-42. The owner's current
authorization permits optimization implementation and migration after the
optimization PR merges; NYAY-21 execution is not a prerequisite and remains on
HOLD. No existing producer is skipped, reduced, rerouted, or cancelled by this
observer. No quarantine or seven-context ruleset changes are made.

The additional workflow is non-required and has read-only repository permission.
Its result is not consumed as passing execution evidence by any required
aggregator. Existing producer/workflow bytes and assertion inventories remain
unchanged. The policy verifier seals the new workflow independently.

## Implemented and tested

- Exact base/head/diff/code-bound proposed selection with privacy-safe diagnostics.
- Conservative root-document-only candidate; shared, unknown, security,
  architecture, incomplete history and empty-diff cases propose full closure.
- Main, nightly-event and manual-event plans propose full closure. The observer
  does not itself create a nightly schedule or move any matrix row.
- Execution remains the complete producer set even for a narrow proposal.
- Existing workflows cancel superseded PR runs in isolated workflow/PR groups;
  main evidence campaigns are not cancelled by PR activity.
- Plan-only hosted fallback: strictly more than 600 seconds offline, at most one
  hosted attempt, exact-head invalidation, and late pilot result rejection. This
  is **not** an installed watchdog or dispatch service.
- Synthetic 14-day measurement arithmetic includes failure/cancellation/retry
  overhead, job-minute rounding, and both weekly and per-merged-campaign metrics.
  Self-hosted-only merged campaigns remain in the denominator. The calculator
  never certifies inventory completeness, billed usage, or program completion.

## Remaining work before this optimization PR is merge-ready

1. Collect observation records from complete hosted campaigns. Independently
   compare every proposed affected-surface closure against the executed assertion
   inventory. Add negative fixtures for omitted dependencies and unknown paths.
2. Extend dependency mapping only with coverage proof. Preserve explicit
   NOT_APPLICABLE versus executed PASS distinction; never rely on GitHub's
   skipped-job success as a producer assertion result.
3. Introduce explicit PR-core versus full-main/nightly campaign contracts before
   relocating mutant, axe or geometry rows. Preserve failure-digest and privacy
   coverage in every selected producer. Verify all seven required contexts still
   enforce their intended closure; names alone are not evidence of preservation.
4. Consolidate duplicate installs/builds only with platform/runtime/lockfile-bound
   caches. Never cache authority, credentials, mutable database state, or evidence.
   Existing pip/npm caches already cover most producers; the new observer uses a
   hash-locked parser dependency and a lockfile-keyed pip cache.
5. Validate the complete change and publish an exact-head contact sheet and sealed
   package. Do not mark Ready on the strength of observation tests alone.

## Migration sequence after the completed optimization PR merges

1. Read back current main, pilot ID 21, isolation, patch versions and font hashes;
   repeat same-head Wave-1/3/5 and NYAY-5 assertion parity. Rendering tolerance is
   limited to evidence rendering, never weakened product/accessibility oracles.
2. The pilot is an isolated Linux VM with no protected-checkout mounts. Jobs need
   fresh workdirs and ephemeral containers. Existing service-container workflows
   must not be moved by exposing the VM Docker socket to untrusted job code.
   Prove per-job PostgreSQL/service cleanup and least-privilege lifecycle first.
3. Implement a trusted bounded dispatcher for hosted fallback. A plain rerun uses
   the original workflow routing and cannot perform this fallback. Verify run/head
   lineage, offline duration, idempotent one-attempt dispatch and late-result
   rejection; keep policy/namespace/aggregators GitHub-hosted.
4. Migrate only verified producers/native gates; record the actual migration UTC
   timestamp. No measurement start is inferred from this PR or a calendar date.
5. Acquire complete all-attempt job inventories and independently join actual
   merge records. Include unmerged work plus allocated main/nightly overhead,
   comparable throughput and assertion coverage. Reconcile owner billing data
   separately; reconstructed minutes are not billed minutes.
6. Post weekly snapshots for two seven-day windows. The target is at least 70%
   reduction for both hosted minutes per merged-PR campaign and weekly total.
   Report local resource cost and fallback overhead separately. Roll back routing
   on isolation, parity, availability or provenance failure; never bypass a gate.

## Independent publisher

NYAY-43 needs a separately administered operator/provider, GitHub App identity,
key/policy custodian and pinned verifier trust root. Those choices remain open.
An executor-created key or pilot-runner identity is not independent. Receipt
integration stays observe-only, and blocking promotion requires owner approval.

## Date holds

Sprint 5 closure is requested for 2026-09-15, not the implementation date.
Sprint 6 remains Future. No rewrite, freeze, production backup, visibility change,
ruleset relaxation or independent-publisher promotion is authorized by this file.

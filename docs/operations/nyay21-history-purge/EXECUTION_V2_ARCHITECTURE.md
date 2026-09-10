# NYAY-21 execution/v2 — fresh snapshots, immutable history

This is tooling for independent review, not an execution approval. The historical
validator and the new pure planning APIs remain non-mutating. The new runtime has
explicit effectful bindings: only a future, independently digest-bound owner GO
can enable them. Import and default CLI are plan-only. No production rewrite,
backup, freeze, push or ruleset change has been performed in this release cycle.
The accepted 36-contract RED specification remains an immutable acceptance input.
The original v1 planning constants and R2–R5 evidence remain historical, not live
execution prerequisites. No v1 assertion or historical artifact is resealed here.

Source-seal transitions for this additive release:

- Validator `8602051e2c89ee9dec05285bd0e0df912b45e41ca00028d574b84d151d3a26f0`
  → `b62659b037e3a77cbb00f64d2c89fe5280772edca8917c8023845d153babac40`;
  new execution/v2 APIs beside unchanged historical checks.
- Policy job semantic digest `a71b647eca26aaba7923a029979a1bbe57b7ff24ff720e7615dbea1d2b0c4da5`
  → intermediate working-tree `e499780255169a1d90c91b5457987547a0215280fbb82606f60e64a4654726d2`;
  two pure-validator test commands. Additional adapter/runtime test wiring and
  the final publication seal remain pending owner approval. No ruleset changes.
- New test seals pin the accepted 36 contracts and additive adversarial coverage.
  All historical contract/document/test seals are unchanged.

## New boundary

`capture_execution_seal` accepts two independently collected, complete readbacks
and computes canonical ref, target, observation, policy and seal digests. Commit
and signature counts are derived, not pinned to a past production head. Both
main and side-ref changes invalidate capture. Maximum snapshot age is 300 seconds.
Repository, visibility, allowed target identities and filter-repo version remain
policy invariants. Another head needs new observations and new approvals, not a
code edit. Inventory order alone does not change the digest.

An injected observation is not an authenticated GitHub claim. The production
adapter must obtain full remote ref pages and commit reachability in an isolated
scratch checkout, compare two reads, retain signed raw readbacks, and verify target
identity/size and actual tool version. Missing remote pages or failed commands are
BLOCKED, never a partial inventory PASS. No imports/bytecode in Desktop checkout.

Both R and F require distinct UUIDs, exact seal/head/ref scope, strict booleans,
unconsumed registry entries, owner/technical-approver role separation and current
expiry. `validate_execution_approvals` recognizes declared bindings, not signatures;
the adapter must independently verify their provenance and consume the existing
append-only approval registry before using them. Never set live approval from a
JSON `verified` field alone.

`plan_execution_leases` emits **only an atomic dry-run argv** with an explicit old
OID and new refspec for every sealed ref. A dry-run plan is not permission to push.
Any missing, duplicate, foreign or stale ref rejects the entire plan. Ref movement
requires recapture and renewed approvals; do not refresh leases silently.

`prepare_execution_push` is the combined planner: it refuses to produce even
the dry-run argv until the separately digest-bound scope read-back and both
exact-seal approvals validate. Missing scopes or an otherwise valid foreign
approval cannot be compensated by a valid lease list. It never returns a live
force-update argv or execution authority.

## Scope and operator decisions

Owner decision NYAY-21 comment 14992 extends 14954: Contents:write,
Workflows:write, Metadata:read, Actions:read and Administration:write,
repository-only. Administration:write requires the complete five-permission set
and `restorationWorkflow=reviewed-ruleset-restoration/v1`; absent or foreign
bindings and Actions:write remain rejected. The narrower historical push-only
scope remains valid for push validation, not for restoration operations.
Expiry is day-granular; no fictional four-hour UI
expiry. The validator accepts a bounded remaining lifetime and requires a recent
independent scope receipt, separately digest-bound to the seal/head and decision
comment. Exact permissions, successful integer exit status and current expiry are
checked. No token bytes are accepted in receipts or diagnostics. If a provider
cannot attest fine-grained permissions, obtain the owner UI read-back plus an
independent technical receipt; never infer scopes from an OAuth header or a
successful contents GET. Missing verified receipt blocks every push step.

### CI dispatch authority — owner-operated (NYAY-21 comment 14996)

GitHub's `Create a workflow dispatch event` API requires Actions:write, which is
not in the currently authorized five-permission execution credential. Workflows:write
permits workflow-file changes; it is not workflow-dispatch authority. No fallback
to ambient `gh` credentials and no silent privilege expansion is permitted.
The owner chose an explicitly owner-operated dispatch step. The
`prepare_owner_ci_dispatch` binding prints the twelve exact workflow commands,
including the quarantined NYAY-4 manual campaign, and the GitHub Actions UI URL.
Each printed command first checks the expected post-push main head. The executor
does not run these commands and never borrows ambient `gh` authentication.
The owner uses their own UI session or separate CLI authentication.
`validate_owner_ci_dispatch_readback` requires twelve unique workflow/run IDs,
the exact post-push head, repository and workflow_dispatch event. Head drift
invalidates the handoff. Successful dispatch does NOT claim successful CI.
Pause C still requires the owner's PROCEED after dispatch evidence is posted.
The concrete adapters below are implemented and tested with synthetic local Git
and injected network/process boundaries. This is not live restoration proof or
independent re-audit approval; neither can be inferred from local tests.

Reference: https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

Single-operator mode is explicit: Rajeev owns the accepted risk, independent
technical approval remains required, support/fresh-clone recovery and power/network
checks are attested, and all three owner PROCEED pauses remain mandatory.

## Watchdog and navigation integration contract

Watchdog receipts bind the live source head, seal, full canonical ruleset GET and
restoration payload digest. Failed GET, stale heartbeat, boolean exit status,
zero/unbounded PUT retries or missing escalation cannot report ready. A new head
must re-arm and independently attest the watchdog; an old receipt cannot be reused.

The following is implemented by `nyay21_executor_adapters.Executor` using
`nyay21_executor_runtime.Runtime`, **not the legacy navigator**. Independent re-audit
must inspect each concrete adapter and its artifact digest before fresh GO. No
adapter may treat this table or a passing pure validator as execution authority.

| Step | Required executor binding | Required evidence / next boundary |
| --- | --- | --- |
| 6 | independent watchdog arm + restoration trap adapter | Live seal, complete GET, exact PUT pair, heartbeat/GET proof; no relaxation yet |
| 7 | isolated rewrite adapter pinned to filter-repo | Verified backup/drill plus owner PROCEED; complete target/retention/signature map |
| 8 | atomic dry-run + force-update adapter | Fresh remote OIDs, every explicit lease/refspec, independently verified scope receipt; Gate F consumed exactly once |
| 9 | restoration adapter and independent GET reader | Always-run restoration; exact canonical GET equality; bounded retry/escalation |
| 10 | post-push readback adapter | Complete new ref inventory, ancestry/target reachability proof |
| 11 | owner pause B | Evidence posted; independent owner PROCEED after rewrite/push/restoration |
| 12 | owner-operated exact-head CI dispatch | prepare_owner_ci_dispatch; Actions:read retained; no executor dispatch |
| 13 | owner pause C + dispatch read-back | validate_owner_ci_dispatch_readback; owner PROCEED after dispatch, not a CI PASS |
| 14 | immutable evidence rebinding adapter | Old records retained; old→new mapping, new exact-head results and digests |
| 15 | closure/custody adapter | Owner + technical signatures, destruction deadline/access log and read-back |

## Runtime input and operator trust boundary

Run from an isolated reviewed source checkout, with bytecode disabled, not the
protected Desktop checkout. The scratch root must be canonical (no symlink) and
mode 0700; its `mirror.git` must be a self-contained bare mirror. The CLI never
creates the production backup or drill. A missing step-5 receipt blocks step 6.
The operator supplies the canonical SHA-256 of `execution-permit.json` from the
independent owner decision record, never by hashing an unreviewed local file and
passing that value as authority. A digest is an integrity binding, not a signature.
The runtime does not impersonate the owner or independently verify Jira identity.

The permit binds repository, owner, technical approver, decision `EXECUTION-GO`,
integer `notBefore` / `expiresAt`, credential digest, exact source-file digests
(`reviewedCodeSha256`: validator, adapter, runtime), seal, two approvals, scope
receipt, backup-drill receipt and relaxation/restoration payload digests.
The following separate files must exist and match those bindings:

- `seal.json`: pure v2 capture of two complete independent observations, max age
  300 seconds at rewrite/push approval validation; actual remote refs are read
  again immediately before rewrite, dry-run and live push.
- `approvals.json`: distinct owner rewrite/force-update approvals, roles and
  exact head/ref scope; consumed UUID records are created exclusively before use.
- `scope-readback.json`: independently attested exact five-permission model,
  bound to the credential by the owner permit. No inferred GitHub permission.
- `step-5.json`: completed verified backup/restore-drill and pause-A receipt,
  reviewed and explicitly digest-bound in the owner permit. A local boolean alone
  is not authority. Actual backup and restore drill remain execution-day work.

Post-push receipts do not exist before execution. At each pause, preserve the
previous permit externally and obtain a new independently reviewed permit digest
binding the same seal/code/approvals plus the newly available receipt digests.
Never invent future signatures to make the navigator advance. The new permit
may bind `proceedReceiptSha256` for `rewrite-push` and `ci-dispatch`, then
`campaignEvidenceSha256` and `closureSignaturesSha256`. Owner receipt revisions
do not refresh or relax Git ref leases, expired pre-push seals or approvals.

## Ordered runtime modes and refusal handling

The safe default, used during this publication cycle, is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/ci/nyay21_executor_runtime.py
```

For a future approved run, `--execute-rewrite-phase` runs steps 6–10 as one
bounded segment, so the watchdog parent stays alive until restoration and
post-push verification. It requires `--root` and `--owner-permit-sha256` and an
explicit environment credential. It stops before pause B; it does not dispatch
CI or continue into closure. `--execute-step` accepts only 11–15 and requires the
preceding immutable receipt. Steps 11 and 13 require owner PROCEED receipts.
Step 12 prints commands only. Owner UI/CLI dispatch uses separate owner authority;
the execution credential stays Actions:read. All twelve run readbacks must match
the new head before pause C. Step 14 requires completed successful runs plus a
separately reviewed exact-head campaign evidence receipt with positive integer
assertions; relabeling old evidence is not re-validation. Step 15 requires both
owner and technical closure receipt provenance, not a generated signature.

Git filter-repo is pinned to 2.47.0 / `a40bce548d2c`. `--no-fetch` prevents a
post-seal implicit fetch, especially server-managed pull refs; heads/tags are the
closed approved force-update inventory. Server pull refs remain a separately
owned residual surface, never silently included. All non-target trees and parent
edges are checked against the complete commit map; a pruned commit needs explicit
single-parent/equal-non-target-tree proof. Dry-run and push use the same complete
explicit leases and refspecs. Git HTTPS credentials use Basic authentication in
the subprocess environment, not argv; REST uses Bearer over fixed-host HTTPS.
Same-user/root environment visibility is an operator risk, not a secret vault.

## Restoration and failure evidence

The separate watchdog process survives executor SIGKILL, detects parent death or
a heartbeat older than 30 seconds, and runs the same bounded restoration path.
Before each PUT it GETs the complete ruleset; failed GET means no blind PUT.
Foreign concurrent configuration changes are refused and require owner recovery.
Three failed PUT attempts trigger a canonical break-glass event. A watchdog is
not protection against host power loss, network loss or an expired credential;
owner support/fresh-clone recovery and execution-day attestation remain mandatory.

Full GET comparison normalizes **only** GitHub's server-managed `updated_at` clock,
which cannot be restored by PUT. Every other field must match. Evidence preserves
both raw GET digests and the normalized canonical digest; never claim raw bytes
match when the update clock changed. Ruleset relaxation suspends only the three
push-blocking rules; all remaining rules and bypass actors are preserved.

Custody events are exclusive-mode 0600, flock-serialized, fsynced and hash-chained
inside a 0700 root. Publish each pause's chain digest independently: local root
can rewrite a whole local chain, so this is not WORM storage. Historical R2–R5
records are not modified. Rebinding creates a new exclusive immutable revision.

**Execution hold:** independent re-audit must inspect these concrete bindings,
scope provenance, restoration trap, SIGKILL failure path, operator receipts and
remaining host-level limitations. Publication is not GO. No fresh owner execution
decision has been issued for this implementation. An uncovered adapter or receipt
path is a re-audit GAP, never hidden behind a pure-function PASS.

# NYAY-21 Formal Rewrite Execution Request

Request status: **NOT APPROVED — HOLD**
Requested action: rewrite and guarded force-update of approved NyayOne refs
Repository: `rajeevbarnwal/NyayOne`
Required visibility throughout: **PRIVATE**
Planning head: `454a40784ee2e084d9a756a713f287b627f1c4d4`
Tool contract: `nyay21-history-purge/v1`
Authoritative ref inventory: **42 concrete refs** (43 rows including symbolic
`HEAD`), SHA-256
`292a8bbaeba262de21c700546790e3c2b0e6c55f0174b4f5e9098b125be7edc7`

## Decision requested

Approve a single, controlled production execution that removes exactly:

- `backend/legalsaathi_dev.db-shm`, blob
  `c3d899c19aa30ca15b2d3c952c0f98f96c6e5337`; and
- `backend/legalsaathi_dev.db-wal`, blob
  `9b2634ba5293ee2ceb0a28c19a448e9714c0799e`

from every explicitly approved publishable branch/tag ref. The execution uses a
fresh private bare mirror and a pinned `git-filter-repo` invocation. It then
force-updates only the approved refs with exact old-object leases.

This document is intentionally unsigned. Tooling development, local synthetic
tests, and local mirror proof do not grant production authority. The operator
must receive **both** the named repository-owner and named Security/Privacy
approvals below. Rewrite approval and force-update approval must be two
distinct, single-use records; neither implies a visibility decision.

## Named approval gates

### Gate R — local production-mirror rewrite

| Field | Required value |
|---|---|
| Repository owner | Rajeev Barnwal |
| Owner decision/signature/time | **UNSIGNED** |
| Named technical Security/Privacy approver | **Claude Code — per-execution, digest-bound; approval pending Round 2** |
| Legally accountable signatory | **Rajeev Barnwal** |
| Human countersign | **Required only if counsel requires; otherwise record N/A rationale** |
| Security/Privacy decision/signature/time | **UNSIGNED** |
| Rewrite approval ID | **REQUIRED, unique and single-use** |
| Bound source head | `454a40784ee2e084d9a756a713f287b627f1c4d4`, or a newly sealed head if `HEAD_CHANGED` |
| Bound ref-inventory SHA-256 | **REQUIRED** |
| Bound target-manifest SHA-256 | **REQUIRED** |
| Approved action | `rewrite-local-mirror` |

### Gate F — remote force update

Gate F is signed only after Gate R completes and all mirror checks pass.

| Field | Required value |
|---|---|
| Repository owner | Rajeev Barnwal |
| Owner decision/signature/time | **UNSIGNED** |
| Same named technical Security/Privacy approver | **Claude Code — per-execution, digest-bound; approval pending Round 2** |
| Legally accountable signatory | **Rajeev Barnwal** |
| Human countersign | **Required only if counsel requires; otherwise record N/A rationale** |
| Security/Privacy decision/signature/time | **UNSIGNED** |
| Force-update approval ID | **REQUIRED, unique, single-use, and different from Gate R** |
| Bound commit-map SHA-256 | **REQUIRED after mirror proof** |
| Bound ref-map SHA-256 | **REQUIRED after mirror proof** |
| Bound exact old/new refs | **REQUIRED; no wildcard or host-managed ref** |
| Approved action | `atomic-force-with-lease` |

Any missing name, signature, digest, exact ref, or distinct ID is a hard
`BLOCKED`. An authoritative remote-head/ref change is `HEAD_CHANGED`, consumes
neither approval, and requires a newly sealed request.

## Pre-flight checklist

Every item must have a privacy-safe artifact ID and SHA-256 digest.

- [ ] Repository read-back is `PRIVATE`; no visibility mutation is present in
      the plan.
- [ ] Change freeze is active; the owner has announced the push blackout and
      collaborator acknowledgement deadline.
- [ ] The authoritative remote head, every branch/tag/protected ref, symbolic
      `HEAD`, peeled tag target, and every host-managed `refs/pull/*` have been
      inventoried and typed.
- [ ] Ref-inventory digest matches Gate R and no unclassified relevant ref
      exists.
- [ ] The target paths, blobs, sizes, source commit
      `9d6d56cc84b4f3fe9e2b223631f8a5e96c815374`, and deletion commit
      `d58d1fbac48db5a29158ca5b3b168b8951d526d1` match the sealed contract.
- [ ] Protected Desktop checkout remains at its recorded head with exactly 299
      status entries and digest
      `2bddf5cb49dd5c49919226c21be65fa32df2b1d7328f7e3d105a0dac42080a27`.
- [ ] Execution and backup roots are outside the protected checkout; the
      execution root is a fresh bare mirror and has no writable production
      remote during rewriting.
- [ ] Pinned `git-filter-repo` build `a40bce548d2c` is independently verified.
- [ ] The owner and Security/Privacy approver explicitly accept the disclosed
      rewrite effect: 40 embedded GPG commit signatures are stripped by
      `git-filter-repo`, causing 267 of 321 source commit identities to change
      (266 rewritten and one expected pruned-empty deletion commit).
      The old signed objects remain restricted in the recovery backup, and new
      release/merge attestations will be freshly signed.
- [ ] The owner-approved restricted plain backup is created before rewrite, has mode
      `0600` under a `0700` directory, includes every sealed ref, passes
      `git bundle verify`, and restores into a fresh repository that passes
      `git fsck --full`.
- [ ] The backup owner, named technical Security/Privacy approver, access log,
      verified disposable-drill deletion, and **actual execution close + 7 days**
      retention policy are recorded. Bind the actual deadline and verification
      schedule at close; final retained-backup deletion proof is separate and
      later. Use the three-stage schema in `BACKUP_AND_ROLLBACK.md`; no passphrase
      or premature final-deletion claim. The human countersign path is recorded
      if counsel requires; a binding legal-erasure override is not waived.
- [ ] The rollback authority and exact rollback triggers in
      `BACKUP_AND_ROLLBACK.md` are accepted.
- [ ] The complete GitHub ruleset and branch-protection response is sealed,
      including all seven strict required checks.
- [ ] A minimal ruleset-relaxation payload and byte-for-byte restoration
      payload have been reviewed and sealed. The restoration trap is installed
      as code before relaxation. Full canonical GitHub GET digest equality—not
      an abstracted policy projection—is required after restoration. Required
      checks are not deleted or weakened.
- [ ] GitHub is confirmed to support an atomic update for the exact ref set. If
      not, stop; non-atomic fallback is not authorized.
- [ ] `git push --atomic --dry-run` has completed with an exact old-SHA lease
      for every publishable ref; a closed-world read-back covers all 42 concrete
      refs; the dry run proves `remoteUpdated=false`.
- [ ] The rendered push has one explicit old-SHA lease and one explicit new SHA
      per approved branch/tag; it contains no `--force`, wildcard, `--all`,
      `--mirror`, ref deletion, or `refs/pull/*`.
- [ ] Collaborator notice instructs re-clone or approved exact-tip reset and
      forbids merging/rebasing/cherry-picking old history.
- [ ] Host residuals are inventoried, including GitHub object retention,
      cached views, pull refs, forks, Actions logs/artifacts/caches, Codespaces,
      package/release assets, other clones, and quarantined evidence.
- [ ] GitHub Support escalation inputs are ready: repository, affected PR
      count, First Changed Commit output, and any reported orphaned LFS list.
- [ ] CI budget is approved for **one complete 22-check exact-head run** on the
      rewritten `main` plus **one rerun of failed jobs only**. Another full run
      requires new owner approval.
- [ ] The evidence-rebinding template is staged. Old evidence remains immutable
      and every new gate requires nonzero assertions at the new exact head.
- [ ] Gate R contains two named signatures. Gate F is not signed prematurely.

## Exact ordered runbook

The steps are indivisible and ordered. An operator must not skip forward.

### 1. Freeze and input seal

Announce the freeze, reject new pushes, and acquire collaborator
acknowledgements. Read repository visibility, authoritative refs, rulesets,
required checks, open PRs, forks, Actions retention settings, artifacts, caches,
and deployments. Canonicalize and hash the inventory.

Compare source head and ref-inventory digest to Gate R. On any mismatch, emit
`HEAD_CHANGED`, stop, and issue a new request. Do not update this request in
place.

### 2. Seal the protected-checkout boundary

Read the protected checkout's head and status using NUL-safe inventory. Verify
299 entries and the approved digest. Record the seal; perform no command that
writes inside that checkout.

### 3. Create and prove the restricted backup

Create the all-ref recovery bundle/snapshot outside all repositories, encrypt
it with a per-execution key, and record its exact contained refs and digest.
Restore it once into a second temporary location; require bundle verification,
`git fsck --full`, exact ref equality, and presence of both target objects.
Remove the temporary restore after the privacy-safe result is sealed.

If the backup or restore proof fails, stop before any rewrite.

### 4. Create the fresh private bare mirror

Create a new bare mirror in a fresh temporary directory from the private
repository. Verify repository identity, visibility, source head, all refs,
absence of local work, and no writable production destination for the rewrite
phase.

### 5. Re-run preflight and approve Gate R

Verify target origin/reachability across branches, tags, pull refs, and merge
parents. Render the operation list and prove its only mutation is the local
mirror rewrite. Obtain the two Gate R signatures if not already signed.

### 6. Rewrite the local mirror only

Execute the pinned equivalent of exactly:

```text
git filter-repo --sensitive-data-removal --invert-paths \
  --preserve-commit-hashes --replace-refs delete-no-add \
  --prune-empty auto --prune-degenerate auto \
  --path backend/legalsaathi_dev.db-shm \
  --path backend/legalsaathi_dev.db-wal
```

No `--force`, `--partial`, `--refs`, `--no-fetch`, `--no-gc`, wildcard,
`--mirror`, or broad database path is permitted. Capture privacy-safe raw
stdout/stderr, exit status, First Changed Commit output, affected PR count, and
any orphaned-LFS report.

### 7. Prove mirror correctness

Generate and validate a complete 321-row commit map, exactly 267 changed/pruned
identities at the sealed baseline (266 rewritten plus one pruned-empty), complete
approved-ref map, and explicit `pruned-empty` disposition for the deletion
commit if applicable. Verify:

- both target object IDs and paths are unreachable from every rewritten ref,
  reflog, and internal retention ref;
- no approved ref was renamed or dropped;
- non-target objects/files, topology, and metadata match the sealed boundary;
- exactly the disclosed 40 GPG commit signatures are absent after rewrite,
  their old objects are covered by the restricted backup, and no other
  metadata drift exists;
- side-branch, annotated-tag, and second-parent merge canaries are clean;
- the protected checkout remains unchanged; and
- the repository remains PRIVATE.

Any failure stops before Gate F.

### 8. Prove atomic dry-run, then render and approve the exact remote transaction

First read back all 42 concrete refs and require exact equality with the sealed
inventory. Render the exact lease-bound transaction with `--atomic --dry-run`.
The dry run must succeed, advertise atomic support, and prove the remote did not
change. A missing ref, mismatched old object, nonzero exit, or any remote change
is `BLOCKED`; no executable non-dry-run path is rendered by this prep packet.

Only the later, separately signed Gate F execution record may remove
`--dry-run` from the already sealed transaction.

Produce the closed list of `<ref, old SHA, new SHA>` entries. The generated
transaction must have the semantic shape:

```text
git push --atomic --dry-run production \
  --force-with-lease=<EXACT_REF_1>:<EXACT_OLD_SHA_1> \
  --force-with-lease=<EXACT_REF_2>:<EXACT_OLD_SHA_2> \
  <EXACT_NEW_SHA_1>:<EXACT_REF_1> \
  <EXACT_NEW_SHA_2>:<EXACT_REF_2>
```

The actual command must enumerate every approved ref; the ellipsis above is a
format illustration, not an executable command. Seal the exact rendered
command and commit/ref-map digests. Re-read remote refs once more. Any drift is
`HEAD_CHANGED`.

Only now may the owner and named Security/Privacy approver sign Gate F with a
new approval ID distinct from Gate R.

### 9. Apply the minimal ruleset transaction

Read back and seal the ruleset again. Use the least-privilege GitHub-supported
mechanism available at execution time: preferably a named, time-boxed bypass
actor for only the exact force update. If that is unavailable, remove/relax
only the non-fast-forward prohibition for the shortest possible transaction.
Do not change required-check definitions, strictness, conversation resolution,
review dismissal, deletion prohibition, or visibility.

The exact PATCH payload and expected response digest must be attached to Gate F
before use. A broader mutation is not authorized.

### 10. Execute one atomic exact-lease update

Execute the sealed command once. Do not retry on a lease or atomicity failure.
Capture the privacy-safe remote response. A rejected transaction proceeds to
the no-update rollback branch; any partial update is an incident.

### 11. Restore protections immediately

Apply the sealed restoration payload even if the push failed. Read the ruleset
back independently and require exact semantic equality with the preflight
snapshot, including the seven strict required checks. Failure keeps the change
freeze active and invokes the incident path.

### 12. Verify the remote and enumerate residuals

Read every remote ref through Git and API. Prove target path/blob
unreachability from publishable refs, verify ref-map equality, and confirm
visibility remains PRIVATE. Inventory host-managed pull refs, cached views,
forks, Actions artifacts/logs/caches, releases/packages, Codespaces, and
external clones. Open the GitHub Support case where eligible and record its
case ID. Apply `HOST_RESIDUAL_SURFACES.md`; unresolved rows remain `BLOCKED`.

### 13. Rerun exact-head gates and rebind evidence

Trigger one complete 22-check CI campaign against the new exact `main` head.
Every required gate must execute nonzero assertions, pass without an oracle
change, and be independently read back. A failed-job-only rerun is allowed once
under the stated budget; another full run requires owner approval.

Complete the new immutable revision
`EVIDENCE_REBINDING_MANIFEST_20260904.json`: retain each historical artifact at
its truthful old SHA with invalidated-by-rewrite status, attach the old-to-new
mapping layer, and add separate fresh evidence IDs and digests for the new head.

### 14. Realign collaborators and audit

Issue the signed new-head notice. Require re-clone or an owner-approved clean
exact-tip reset; collect every acknowledgement and dispose of old clones under
the device policy. Conduct an independent privacy/history audit of origin and
the residual register. This audit hands off a future visibility decision; it
does not make one.

### 15. Close or roll back and schedule verified backup deletion

Owner and Security/Privacy jointly decide closure versus a controlled rollback
using the triggers below. At actual close, record the signed close receipt and
schedule verification for **execution close + 7 days**. At that deadline, delete
the exact plain backup and temporary copies and verify path absence/unreadability,
artifact-scoped Trash and snapshots, then seal a separate destruction receipt.
Do not delete unrelated Trash/shared snapshots or claim physical SSD erasure.
Never pre-attest destruction at closure. Confirm the protected-checkout seal and
PRIVATE visibility; record whether counsel required a human countersign.

## Rollback triggers and actions

The authoritative rollback procedure is `BACKUP_AND_ROLLBACK.md`. Summary:

- `HEAD_CHANGED`, approval mismatch, backup/restore failure, unsafe root, or
  mirror-validation failure: stop before remote mutation; discard disposable
  work under the retention policy.
- Atomic push rejected: verify zero changed refs, restore protections, stop;
  never retry blindly.
- Partial/unexpected update: freeze all writes, restore protective rules, use
  the verified backup and separately accepted rollback authority to restore
  only exact affected refs with current-object leases.
- Target remains reachable, non-target content drifts, protection restoration
  fails, host residual is unaccounted, CI/oracle verification fails, or old
  history is reintroduced: keep PRIVATE, block visibility and further pushes,
  preserve evidence, and require a joint owner/Security decision.
- Any visibility change: treat as an incident, return to PRIVATE immediately,
  and stop.

## Privacy and regulatory note

The origin rewrite reduces the active repository exposure surface; it does not
delete other people's clones or prove immediate physical erasure from every
GitHub cache. The owner-approved restricted plain backup deliberately contains the old
objects for disaster recovery and is governed as a separate surface with named
custody and destruction. Historical QA records remain immutable because they
truthfully record the old exact SHA, but no old record can be presented as
validation of a rewritten commit. Security/Privacy must accept this layered
posture and every unresolved residual before the ticket can hand off a separate
public-visibility decision.

## Go/no-go record

Current decision: **NO-GO**

- Gate R owner signature: **missing**
- Gate R Security/Privacy signature: **missing**
- Gate F owner signature: **missing**
- Gate F Security/Privacy signature: **missing**
- Mirror proof and map digests: **pending**
- Production ref inventory and ruleset transaction: **pending execution-day
  read-back**
- Public visibility authority: **not requested and not granted**

The execution operator must remain at HOLD until an owner issues an explicit
go decision tied to the completed Gate R and Gate F records. Approval of the
tooling PR, CI, Jira status, or this document alone is not execution authority.

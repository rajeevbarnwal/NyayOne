# NYAY-21 Backup Governance and Rollback Plan

Status: path-to-GO execution template; no production backup or rewrite has occurred
Repository: `rajeevbarnwal/NyayOne` (**PRIVATE**)
Destruction rule: **force-push + 30 days**, with earlier destruction required
when the jointly signed closure or a legal-erasure override requires it.

## Why the backup is sensitive

The pre-rewrite backup necessarily retains the two contaminated WAL/SHM blobs.
It is not an ordinary build artifact and must never be attached to Jira,
uploaded to GitHub Actions, committed, copied into a publishable ref, or placed
in a generally accessible shared drive.

For this ticket's operational posture, erasure from the origin surface is
treated as satisfied once the exact production refs are rewritten, remote
reachability checks pass, and GitHub-hosted residuals are dispositioned. The
backup remains a separately inventoried, tightly restricted disaster-recovery
surface until its scheduled destruction. Security/Privacy approval is required
for this limited exception; this statement is an operational control, not a
legal conclusion.

## Custody and access control

- Data owner and primary custodian: **Rajeev Barnwal, repository owner**.
- Technical Security/Privacy approval: **Claude Code**, acting per execution
  against the exact packet digest. Rajeev Barnwal remains the legally
  accountable signatory. A human countersign is required if counsel requires
  one; that upgrade path does not weaken the technical approval gate.
- Access is limited to those two named approvers and the designated execution
  operator for the duration of the approved restore test.
- Store the backup outside every Git repository, encrypted at rest with a
  unique per-execution key. Store the key separately from the encrypted backup.
- Directory mode: `0700`; backup and manifest modes: `0600`.
- Do not include credentials, tokens, decrypted database rows, or blob content
  in logs. Evidence records only path, size, object ID, digest, and exit status.
- Every access is logged with actor, timestamp, reason, and resulting artifact
  digest. Unlogged access is a rollback/incident trigger.
- The backup classification is
  `restricted-private-pre-rewrite`; `publiclyPublishable` must remain false.

The execution packet is invalid unless it names the per-execution technical
Security/Privacy approver and operator and records the accountable owner
signature. Role-only placeholders are insufficient for a real rewrite.

## Creation and restore proof

Before any rewrite operation:

1. Re-read authoritative refs and source head; stop with `HEAD_CHANGED` on
   drift.
2. Create an all-ref Git bundle or equivalent recoverable bare snapshot in the
   restricted backup directory.
3. Seal its SHA-256 digest, byte size, creation timestamp, encryption metadata,
   and exact contained-ref inventory.
4. Run `git bundle verify` against the backup.
5. Restore it into a second fresh, isolated directory.
6. Run `git fsck --full` and verify every sealed ref and both target blobs are
   present in the restore. Their presence proves backup completeness; their
   content must not be emitted.
7. Verify the restored repository has no writable production remote.
8. Delete the restore-test directory after recording privacy-safe results. The
   encrypted recovery backup remains under the retention controls below.

No local rewrite and no ruleset transaction may begin if either bundle
verification or restore testing fails.

## Retention window and destruction rule

- Operational rollback window and maximum destruction deadline:
  **force-push + 30 days**.
- The effective deadline is the earlier of: force-push + 30 days; jointly
  signed operational closure; or a binding legal-erasure override.
- The former fixed 2026-09-23/2026-09-30 planning dates are deliberately
  dropped. The actual force-push timestamp is the only clock origin.
- Early destruction is required once the owner and Security/Privacy approver
  jointly confirm: remote refs are correct, rules are restored, exact-head CI
  and evidence reruns pass, collaborator realignment is complete, and rollback
  is no longer necessary.

Destruction uses cryptographic erasure of the per-execution encryption key,
followed by deletion of the encrypted backup and every temporary restore. This
avoids making unsupported secure-overwrite claims for SSD storage. The operator
then verifies that the paths are absent and records a destruction certificate
containing the former artifact digest, destruction time, actor, and approver.

If no production rewrite is authorized, no contaminated recovery backup may be
created under this packet.

## Rollback triggers

Stop immediately, keep the repository PRIVATE, and invoke the applicable
rollback branch if any of these occurs:

- the authoritative head or ref inventory differs from the approved seal;
- the backup is incomplete, unreadable, unverified, or cannot be restored;
- an approval is missing, expired, reused, or shared between the rewrite and
  force-update gates;
- the execution root is not a fresh bare mirror or overlaps the protected
  checkout;
- the pinned tool or literal target manifest does not match;
- a non-target file/object, topology record, tag, or branch is unexpectedly
  changed or dropped;
- the signature inventory differs from the disclosed boundary of 40 embedded
  GPG signatures stripped and 267 of 321 commit identities changed/pruned, or
  any non-signature metadata drifts;
- the commit/ref mapping is incomplete;
- either target path or blob remains reachable from a clean ref;
- an atomic push cannot be guaranteed or a force-with-lease check fails;
- the ruleset or any of the seven strict required checks cannot be restored
  exactly;
- origin visibility differs from PRIVATE;
- fresh exact-head gates fail, execute zero assertions, or use weakened oracle
  digests;
- old history is reintroduced by a clone, fork, branch, pull ref, cache, or
  evidence package;
- any unapproved person accesses the restricted backup.

## Rollback branches

### Before any remote update

Abandon the disposable mirror, retain the sealed diagnostic record, destroy
temporary decrypted material, and leave origin untouched. No remote rollback
is required. Restore any temporarily adjusted local configuration and verify
the protected-checkout seal.

### Atomic push rejected before updates

Treat the operation as not executed. Read every remote ref to prove none
changed, restore the ruleset from its sealed snapshot, and invalidate the plan
as `HEAD_CHANGED` or `BLOCKED`. Never retry without a newly reviewed plan.

### Unexpected partial or incorrect remote update

1. Freeze writes and keep the repository PRIVATE.
2. Record the actual remote state without deleting evidence.
3. Restore the exact pre-rewrite ruleset if possible; otherwise use the
   preapproved incident-only protective rule that blocks all writes.
4. Obtain both named approvers' confirmation to use the rollback authority
   included in the execution request.
5. From the verified recovery backup, prepare exact old/new ref pairs.
6. Restore only the affected approved refs with atomic, exact
   `--force-with-lease=<ref>:<observed-current-sha>` updates. No wildcard,
   `--all`, `--mirror`, unguarded `--force`, ref deletion, or host-managed pull
   ref is allowed.
7. Read back every ref and the full ruleset, rerun required checks, and retain
   the incident timeline.

### Post-update verification or CI failure

Do not automatically restore contaminated history. Keep the repository PRIVATE
and block public readiness. The owner and Security/Privacy approver decide
whether the failure requires (a) a corrected clean rewrite, (b) ruleset-only
repair, or (c) controlled restoration under the previous branch. This prevents
a test-infrastructure failure from silently reintroducing the target blobs.

## Recovery completion record

A rollback or successful rewrite is not closed until the record includes:

- execution/incident ID and approver identities;
- pre- and post-operation ref inventories and digests;
- backup digest and restore-test results;
- exact commands as rendered and their privacy-safe exit records;
- ruleset before/after digests;
- origin visibility read-back;
- disposition of host residuals;
- protected-checkout seal read-back;
- final decision and destruction-certificate due date.

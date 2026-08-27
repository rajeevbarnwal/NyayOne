# NYAY-21 WAL/SHM History Purge — Execution Plan

Status: tooling-only plan; no real-origin rewrite authorized
Contract: `nyay21-history-purge/v1`
Repository: `rajeevbarnwal/NyayOne`
Required visibility throughout: **PRIVATE**
Sealed planning head: `422b3dbbeddb25c6735cd093003ccaef335cb60a`

## Purpose and authority boundary

NYAY-21 removes exactly the following committed SQLite sidecars from reachable
Git history:

| Path | Blob | Size |
|---|---|---:|
| `backend/legalsaathi_dev.db-shm` | `c3d899c19aa30ca15b2d3c952c0f98f96c6e5337` | 32,768 bytes |
| `backend/legalsaathi_dev.db-wal` | `9b2634ba5293ee2ceb0a28c19a448e9714c0799e` | 457,352 bytes |

The material first entered history at
`9d6d56cc84b4f3fe9e2b223631f8a5e96c815374`. The later deletion commit
`d58d1fbac48db5a29158ca5b3b168b8951d526d1` removed the files from the
working tree but not from history.

This packet authorizes development and mirror-only validation of the tooling.
It does **not** authorize any mutation of `origin`, any force update, any
ruleset change, or any repository-visibility change. Real execution requires
the separately signed request in `REWRITE_EXECUTION_REQUEST.md`.

## Invariants enforced by the tool

- An invocation without an execution approval is plan-only and non-mutating.
- Rewrite approval and force-update approval are distinct records with
  distinct approval IDs. One cannot satisfy the other.
- The protected Desktop checkout is an observation-only surface. The tool
  refuses it as an execution root or backup root and proves its 299-entry seal
  unchanged before and after local work.
- Rewrite work occurs only in a fresh, bare, private mirror whose source head
  and ref-inventory digest match the signed plan.
- The complete remote ref set is closed-world and typed. Unknown refs,
  wildcards, `--all`, `--mirror`, `HEAD`, and host-managed pull refs cannot
  enter the publishable ref allowlist.
- The rewrite command uses a reviewed, pinned `git-filter-repo` build
  (`a40bce548d2c`) and exactly two literal paths. It does not use `--force`,
  `--partial`, `--refs`, `--no-fetch`, `--no-gc`, a wildcard, or a broad path.
- Force updates, if separately approved later, are exact-ref,
  old-object-bound `--force-with-lease` updates. No unguarded `--force` is
  permitted.
- The repository remains PRIVATE before, during, and after every phase.
- Historical evidence is immutable. A mapping and fresh exact-head reruns are
  added; old evidence is never relabelled.
- The sealed source contains **31 GPG-signed commits**. `git-filter-repo`
  cannot carry those embedded signatures onto rewritten commit objects, so the
  closed-world mirror proof changes 243 of 297 commit identities and strips
  those 31 signatures. The old signed objects remain verifiable only in the
  restricted recovery backup; rewritten release/merge attestations must be
  freshly signed. No other metadata loss is permitted.

## Inputs that must be sealed before real execution

1. Repository identity, visibility, default branch, and authoritative remote
   head.
2. Every branch, tag, symbolic head, protected ref, and host-managed pull ref,
   including peeled annotated-tag targets.
3. SHA-256 digest of the canonical ref inventory.
4. Exact target path/blob/size manifest.
5. Protected-checkout head, 299-entry count, and status digest
   `2bddf5cb49dd5c49919226c21be65fa32df2b1d7328f7e3d105a0dac42080a27`.
6. Full branch-protection/ruleset document and the seven strict required
   checks.
7. Rewrite approval and, separately, force-update approval.
8. Backup custody, retention, destruction date, and restore-test record.
9. An exact allowlist of publishable branch/tag refs. Server-managed pull refs
   are inventoried as residuals but are never pushed.

Any authoritative-head or ref-inventory drift produces `HEAD_CHANGED`. The
plan is invalidated and must be regenerated and reapproved; execution cannot
continue on a best-effort basis.

## Mirror-only validation sequence

This is the only execution allowed during tooling development.

1. Record the protected-checkout seal without changing that checkout.
2. Capture repository visibility and authoritative refs read-only.
3. Create a new temporary directory outside the protected checkout.
4. Create a fresh bare clone of a local synthetic contaminated repository or
   a private, read-only source mirror. Never configure the production origin
   as a writable destination.
5. Verify the pinned `git-filter-repo` artifact before use.
6. Render and independently inspect the plan. With no real-origin execution
   authorization, the tool must report plan-only and no mutation operations.
7. For synthetic/mirror proof only, invoke the pinned tool with the equivalent
   of:

   ```text
   git filter-repo --sensitive-data-removal --invert-paths \
     --preserve-commit-hashes --replace-refs delete-no-add \
     --prune-empty auto --prune-degenerate auto \
     --path backend/legalsaathi_dev.db-shm \
     --path backend/legalsaathi_dev.db-wal
   ```

8. Produce the commit map and ref map. Record the deletion commit as
   `pruned-empty` if it becomes empty; do not silently drop a commit or ref.
9. Scan every clean ref, reflog, and internal retention ref for both target
   paths and both target blob IDs.
10. Verify non-target objects, unrelated files, topology, and metadata against
    the sealed retention boundary. Require exactly 31 disclosed signature
    removals, a 297-row commit map, exactly 243 changed/pruned identities, and
    no other metadata difference.
11. Prove that planted contamination on a side branch, annotated tag, and
    second-parent merge is detected by the preflight and absent after the
    mirror rewrite.
12. Render, but do not execute, the exact force-with-lease plan.
13. Recheck the protected-checkout seal and repository visibility.
14. Seal raw logs, plans, mappings, validation results, and their SHA-256
    manifest. A PASS requires exact inventory equality and nonzero assertions.

## Real-origin phases held for separate approval

After owner and Security/Privacy approval, the operator would run the exact
ordered procedure in `REWRITE_EXECUTION_REQUEST.md`. The high-level phases are:

1. change freeze and collaborator notice;
2. authoritative read-back and `HEAD_CHANGED` guard;
3. restricted, encrypted, restore-tested backup;
4. fresh private mirror and local rewrite;
5. exhaustive mirror verification and map sealing;
6. exact ruleset-relaxation transaction;
7. atomic, exact-ref force-with-lease update;
8. immediate ruleset restoration and read-back;
9. remote reachability and host-residual audit;
10. fresh exact-head CI/evidence reruns and rebinding;
11. collaborator re-clone/realignment acknowledgements;
12. independent pre-public audit and controlled backup destruction.

Passing NYAY-21 does not authorize making the repository public. Public
visibility remains a separate owner decision after all residual surfaces are
resolved and independently audited.

## Required evidence inventory

- signed input seal and canonical ref inventory;
- plan-only output and operation classification;
- tool provenance and pinned-tool verification;
- backup plan, encrypted-backup digest, bundle verification, and restore-test
  log (real execution only);
- mirror rewrite stdout/stderr and exit status;
- before/after object, path, ref, topology, and metadata reports;
- side-branch/tag/merge canary results;
- complete commit and ref maps plus their digests;
- rendered exact force-with-lease plan (not an execution log until approved);
- before/after ruleset read-backs;
- host-residual inventory and dispositions;
- fresh exact-head required-check read-backs;
- evidence-rebinding manifest;
- protected-checkout before/after seal;
- collaborator acknowledgements;
- independent Security/Privacy audit and backup-destruction certificate.

All evidence must exclude secret material and row-level data. Object IDs and
repository-relative target paths are permitted identifiers; blob content is
never copied into evidence.

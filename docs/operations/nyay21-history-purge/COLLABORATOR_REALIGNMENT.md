# NYAY-21 Collaborator Re-clone and Realignment Runbook

Status: advance notice; do not use until the owner announces that the rewrite
has completed
Repository: `rajeevbarnwal/NyayOne` (**PRIVATE**)

## Mandatory rule

After the production history rewrite, the safest supported method is a fresh
clone. A collaborator must never merge, rebase, or cherry-pick an old-history
branch into rewritten history. One merge can make the removed WAL/SHM blobs
reachable again.

The rewrite announcement will provide the new exact `main` SHA, a signed
old-to-new commit/ref map, and a deadline for acknowledgement. Do not infer a
new SHA from this template.

## Before the freeze

Each collaborator must:

1. Stop pushing at the announced freeze time.
2. Inventory every clone, worktree, fork, local branch, stash, patch, bundle,
   CI workspace, and cached archive derived from NyayOne.
3. Report unpushed work to the execution operator before the input seal. Do not
   push it after the seal.
4. Export necessary uncommitted work as a reviewed patch that excludes
   database files, `.db-wal`, `.db-shm`, credentials, tokens, OTPs, and PII.
5. Record the old clone location and head for later disposal; never attach its
   Git directory or bundle to Jira or CI.

## Preferred recovery: re-clone

After receiving the signed completion notice:

```text
git clone git@github.com:rajeevbarnwal/NyayOne.git NyayOne-rewritten
cd NyayOne-rewritten
git remote get-url origin
git fetch --prune --tags origin
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor <NEW_MAIN_SHA> origin/main
```

Require all of the following before work resumes:

- the remote URL is the intended private repository;
- `origin/main` equals or contains the announced `<NEW_MAIN_SHA>`;
- both target paths are absent from `git log --all --` results;
- both target object IDs fail reachability checks from all fetched refs;
- required branch-protection and check read-backs match the closure record.

Do not copy `.git`, refs, objects, stashes, worktrees, or branches from the old
clone into the new clone.

## Narrow alternative: fetch and reset a disposable clean clone

This method is allowed only for a clone with no uncommitted work, no local-only
branches, no stashes, and no evidence that must be retained. The owner must
approve it for the specific clone.

```text
git fetch --prune --tags origin
git branch --show-current
git status --porcelain=v1
git rev-parse origin/main
git reset --hard <NEW_MAIN_SHA>
git reflog expire --expire=now --all
git gc --prune=now
```

Before `reset --hard`, a human must confirm the status output is empty and the
current branch is the intended local `main`. This template does not authorize
running the command against the protected Desktop checkout. Re-clone is
required whenever those conditions cannot be proven.

## Preserving legitimate unpushed work

Never merge, rebase, or cherry-pick an old commit. Instead:

1. inspect the pre-freeze patch as data, not as Git history;
2. scan it for target filenames, database payloads, credentials, and PII;
3. apply only the reviewed text changes to a new branch based on the rewritten
   head;
4. create a fresh commit with a new identity;
5. rerun the affected gates and publish new exact-head evidence.

If the patch cannot be proven clean, quarantine it and seek Security/Privacy
review rather than importing it.

## Old clone and cache disposition

- Keep old clones disconnected and read-only until the owner confirms rollback
  is no longer required.
- Do not push any ref from an old clone.
- Once released for disposal, remove the clone through the organization's
  approved device-erasure process. SSD-backed systems should use managed or
  cryptographic erasure rather than unsupported overwrite claims.
- Delete old CI workspaces, caches, local bundles, and downloaded evidence only
  under their recorded retention/destruction policy.
- Fork owners must rewrite or delete affected forks; the main repository owner
  cannot purge another person's clone or fork.

## Required collaborator acknowledgement

Each person records:

- name and timestamp;
- old clone/fork/worktree inventory and disposition;
- new clone path and verified `<NEW_MAIN_SHA>`;
- confirmation that no old-history merge, rebase, or cherry-pick occurred;
- target-path and target-object reachability result;
- any quarantined patch or unresolved cache;
- acknowledgement that the repository remains PRIVATE.

Any missing acknowledgement, unresolved fork, or detected old-history
reintroduction blocks public-readiness handoff and triggers the incident path in
`BACKUP_AND_ROLLBACK.md`.

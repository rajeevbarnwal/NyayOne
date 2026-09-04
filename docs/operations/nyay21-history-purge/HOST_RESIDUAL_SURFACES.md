# NYAY-21 Host-Side and External Residual-Surface Register

Status: pre-execution register; every row requires a post-rewrite read-back
Repository: `rajeevbarnwal/NyayOne` (**PRIVATE**)
Public-readiness default: **BLOCKED** until all applicable rows have a recorded
disposition

A force update changes publishable refs; it does not prove that every old
object or SHA has disappeared from GitHub, another clone, or an evidence
system. This register separates active-origin erasure from residual retention.
No undocumented automatic-expiry assumption may be used as evidence.

## Surface register

| Surface | Expected behavior after ref rewrite | Required action and exit evidence |
|---|---|---|
| Publishable branches and tags | Exact approved refs move to rewritten object IDs. | Read every ref through both Git transport and GitHub API. Both target paths and blobs must be unreachable. Seal the ref map and scan output. |
| GitHub object store and cached commit views | Unreferenced objects/cached views may remain available for an unspecified period; force-push alone is not proof of physical expungement. | Open a GitHub Support request for sensitive-data removal/garbage collection when eligible. Record the case ID, First Changed Commit output, affected PR count, and Support disposition. Until confirmed or explicitly risk-accepted by Security/Privacy, status is `BLOCKED`. |
| Host-managed pull-request refs, diffs, and cached PR views | Pull refs are not operator-pushable and may retain old objects. | Inventory every `refs/pull/*`, affected open/closed PR, and cached view. Ask GitHub Support to dereference/delete affected PR refs and cached views where eligible. Record before/after reachability. |
| Forks | A fork retaining old history can keep the blobs reachable indefinitely. The upstream owner cannot clean another owner's fork. | Inventory GitHub-reported forks; obtain owner rewrite/deletion acknowledgement. Any unaccounted fork is a blocker. |
| GitHub Actions run logs | Logs normally expire under the repository/org retention setting, but the actual setting and each run must be read back. Completed logs can be deleted separately. | Search logs for target paths/object IDs and any copied content. Delete affected logs through the supported UI/API if required; verify the delete response and that log download is unavailable. Retain only a privacy-safe deletion record. |
| GitHub Actions artifacts | Artifacts have an `expires_at` value and can be deleted before expiry. Changing the repository default is not retroactive. | Enumerate artifacts for every old-SHA run, record ID/name/size/expiry, inspect privately, and delete contaminated artifacts. Read back absence. Do not upload the recovery backup as an artifact. |
| GitHub Actions caches | Cache eviction is retention/configuration dependent and caches can be deleted manually/API. A branch rewrite does not prove eviction. | Enumerate cache keys/refs, delete any cache able to contain a clone, object database, database file, or evidence archive, then read back an empty applicable inventory. |
| Checks, deployments, and workflow metadata | Historical metadata may truthfully retain an old commit identity even when logs/artifacts are removed. Metadata alone is not proof that the blobs remain. | Preserve immutable historical identity where required, label it invalidated by rewrite, and link it through the rebinding manifest. Scan associated payloads separately. |
| Releases, source archives, and release assets | Rewritten tags change generated source archives, but old release assets are independent objects and old-SHA archives may remain while objects remain cached. | Inventory releases/assets and old-SHA download URLs. Delete/reissue any contaminated independent asset and include old-SHA archive behavior in the GitHub Support case. |
| Packages and container registries | A package, image layer, source map, or SBOM may embed an old checkout independently of Git refs. | Inventory packages/images built from affected SHAs; scan layers/artifacts; delete or supersede contaminated versions per registry policy. Record immutable package digests and disposition. |
| Codespaces, prebuilds, runner workspaces, and hosted caches | Existing environments may hold complete old clones beyond the ref rewrite. | Enumerate and delete/rebuild relevant Codespaces/prebuilds; ensure ephemeral runners are destroyed; record self-hosted runner workspace cleanup separately. |
| Webhooks, mirrors, integrations, and deployment clones | External systems may have fetched old refs and retain them indefinitely. | Inventory hooks, bots, deployment hosts, backup services, search indexes, and mirrors. Require cleanup acknowledgement and exact new head read-back. |
| Collaborator clones, worktrees, stashes, and local bundles | These are outside GitHub's control and have no automatic expiry. | Follow `COLLABORATOR_REALIGNMENT.md`; prefer re-clone and obtain acknowledgements. Never merge, rebase, or cherry-pick old history. |
| Quarantined QA/evidence packages and Jira attachments | A sealed historical package may contain logs, screenshots, source archives, or Git metadata independent of the origin. | Inventory by attachment/artifact ID and SHA-256. Historical reports may remain immutable if content-scanned clean; packages containing target blobs/data are restricted or destroyed under their own approved retention. Never silently relabel old evidence. |
| Restricted recovery backup | Deliberately retains the contaminated history for disaster recovery. | Apply `BACKUP_AND_ROLLBACK.md`: named custodians, encryption, access log, and destruction by force-push + 30 days or an earlier jointly signed/legal-erasure boundary. |
| Local tooling mirror and temporary restore | The mirror contains old objects before rewriting; a restore test necessarily does too. | Keep outside publishable refs, restrict permissions, destroy temporary restore immediately after evidence capture, and destroy the mirror after completion/rollback decision. |

## GitHub behavior references

The operator must re-read current authoritative documentation at execution
time; these links are references, not a frozen service-level guarantee:

- [Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) explains that cached views, pull-request references, forks, and other clones can retain old data and describes the GitHub Support path.
- [Removing workflow artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts) documents explicit artifact deletion and API `expires_at` read-back.
- [Using workflow run logs](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs) documents explicit workflow-log deletion.
- [Managing GitHub Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository) documents configurable log/artifact and cache retention, including that changed artifact/log defaults are not retroactive.
- [Managing caches](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manage-caches) documents manual/API cache inventory and deletion.

At the time this packet was authored, GitHub documents a 90-day default for
Actions artifacts/logs, with private-repository configuration up to 400 days,
and a 7-day default Actions-cache retention with private-repository
configuration up to 365 days. The actual repository and organization settings,
artifact `expires_at` timestamps, and cache inventory are authoritative. Never
substitute these defaults for read-back evidence.

GitHub Support may determine that a request is not eligible for server-side
sensitive-data removal. Such a response is a disposition, not proof of purge;
Security/Privacy must explicitly assess the remaining risk, and the repository
must remain PRIVATE unless a separate visibility decision is later approved.

## Closure statuses

Each row receives exactly one of:

- `PURGED_AND_READ_BACK` — removal and absence were directly verified;
- `EXPIRED_AND_READ_BACK` — host expiry occurred and absence was directly
  verified;
- `RETAINED_RESTRICTED_UNTIL_<DATE>` — a named, controlled exception exists;
- `NOT_APPLICABLE_WITH_EVIDENCE` — inventory proves the surface did not exist;
- `BLOCKED` — unresolved, unaccounted, or unverifiable.

Only the first four are closable, and a restricted retention item still needs
Security/Privacy acceptance. An unaccounted surface or `BLOCKED` row prevents
the pre-public handoff. No row grants public-visibility authority.

## Per-surface execution disposition record

The operator must create one immutable row for every surface above at execution
time. The planning default is `BLOCKED`; a blank cell is invalid. This packet
does not pre-claim any host-side purge or expiry.

| Surface key | Planning disposition | Execution artifact ID | Read-back SHA-256 | Reviewed by |
|---|---|---|---|---|
| publishable-refs | `BLOCKED` | pending | pending | pending |
| github-object-store | `BLOCKED` | pending | pending | pending |
| pull-refs-and-pr-cache | `BLOCKED` | pending | pending | pending |
| forks | `BLOCKED` | pending | pending | pending |
| actions-logs | `BLOCKED` | pending | pending | pending |
| actions-artifacts | `BLOCKED` | pending | pending | pending |
| actions-caches | `BLOCKED` | pending | pending | pending |
| checks-deployments-metadata | `BLOCKED` | pending | pending | pending |
| releases-and-assets | `BLOCKED` | pending | pending | pending |
| packages-and-images | `BLOCKED` | pending | pending | pending |
| codespaces-and-runners | `BLOCKED` | pending | pending | pending |
| integrations-and-mirrors | `BLOCKED` | pending | pending | pending |
| collaborator-clones | `BLOCKED` | pending | pending | pending |
| qa-and-jira-evidence | `BLOCKED` | pending | pending | pending |
| restricted-backup | `BLOCKED` | pending | pending | pending |
| local-mirror-and-restore | `BLOCKED` | pending | pending | pending |

Closing evidence must replace each planning row with exactly one allowed closure
status, an artifact ID, a full digest, and a named reviewer. Any other value
keeps NYAY-21 at `NO-GO`.

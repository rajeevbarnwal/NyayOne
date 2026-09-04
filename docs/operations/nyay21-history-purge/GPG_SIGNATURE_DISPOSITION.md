# NYAY-21 GPG Signature Disposition

Status: path-to-GO template; no history rewrite, signature mutation, or signing
configuration change has occurred

Decision: **document the historical-attestation break and sign forward**. This
is the selected **signing forward** posture.
Bulk re-signing is not selected because it would manufacture a new signature
history that did not exist when the original commits were reviewed.

## Execution-day signer identity and verification-status inventory

Before Gate R can be signed, record one row for every one of the **40** embedded
signatures in the authoritative source history. The sealed inventory must have
exactly these fields and no unclassified row:

| Old commit | Signer identity | Key fingerprint | Verification status | Signature status after rewrite | New commit |
|---|---|---|---|---|---|
| `<40-char SHA>` | `<display identity>` | `<full fingerprint>` | `GOOD / BAD / UNKNOWN_KEY / ERROR` | `STRIPPED_AS_DISCLOSED` | `<mapped SHA or PRUNED_EMPTY>` |

`GOOD` is not inferred from the presence of a `gpgsig` header. It requires a
recorded verifier result, signer identity, fingerprint, tool version, and
verification time. A mismatch from 40 rows, a duplicate old commit, or an
unclassified verification status is `BLOCKED`.

## Signing-forward canary plan

After the rewritten exact head exists—but before collaborator release—create a
non-publishable canary commit in the isolated mirror using the owner's intended
signing identity. Verify the canary independently and record the fingerprint and
`GOOD` result. Destroy the canary ref. Then enable commit signing for all owner
commits from execution day forward and require the first rewritten-main release
attestation to verify against the same fingerprint. Failure of the canary or the
release attestation keeps the freeze active.

The canary is not a replacement for the old-to-new commit map. Historical
evidence keeps its old SHA and original verification truth; the v2 rebinding
manifest links it to fresh exact-head evidence without relabelling it.

## Five execution-day evidence requirements

1. Sealed 40-row signer identity and verification-status inventory.
2. Complete old-to-new map, including the one expected `PRUNED_EMPTY` row.
3. Explicit attestation-break acceptance signed by the owner and digest-bound
   technical Security/Privacy approver.
4. Passing signing-forward canary with the intended owner fingerprint.
5. Signed post-rewrite head/release attestation and independent verification.

## Attestation template

```text
NYAY-21 HISTORICAL-ATTESTATION BREAK
Execution ID: <id>
Pre-rewrite head: <sha>
Post-rewrite head: <sha>
Commit-map SHA-256: <digest>
Signer-inventory SHA-256: <digest>
Embedded signatures before/after: 40 / 0
Expected changed/pruned identities: 267 (266 rewritten, 1 pruned)
Signing-forward canary: PASS <fingerprint> <artifact digest>
First signed forward attestation: PASS <commit/tag> <fingerprint>
Owner: Rajeev Barnwal <signature/time>
Technical Security/Privacy approver: Claude Code <digest-bound approval/time>
Human countersign: <required only if counsel requires; identity/time or N/A rationale>
Verdict: PASS / BLOCKED / HEAD_CHANGED
```

This template grants no rewrite, force-update, ruleset, freeze, backup, or
visibility authority.

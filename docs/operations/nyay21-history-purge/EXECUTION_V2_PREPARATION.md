# Execution/v2 preparation and signed registry contract

Status: tooling for independent review, **HOLD / NO-GO**. This recipe does not
authorize a backup, freeze, ruleset change, rewrite, push, or dispatch. Historical
R2–R5 records are immutable. Owner decisions 15044, 15047 and 15050 govern this revision.

## Authority and isolation

The operator provides `NYAY21_PROTECTED_ROOT`, an absolute, resolved existing Git
checkout. The runtime verifies its Git top-level and binds the canonical path's
SHA-256 in the independently approved execution permit as
`protectedRootSha256`. Unset, fake, symlinked, or mismatched roots refuse. The
original protected Mac checkout and the runtime source checkout are additional
exclusion roots, not substitutes for configuration. Both ancestors and descendants
are excluded. The Mac's 299-entry baseline and digest
`2bddf5cb49dd5c49919226c21be65fa32df2b1d7328f7e3d105a0dac42080a27`
remain unchanged. No imports or bytecode caches may be written there.

After fresh owner GO only, prepare a fresh 0700 scratch directory with a bare
`mirror.git` using `git clone --mirror --no-local` from the reviewed private
repository. Clone creation is an operator step, not implicit runtime behavior.
Keep all executable tooling in a separately reviewed scratch checkout. Verify
the mirror's exact heads/tags against authenticated remote refs and the target
manifest. No alternates, external Git dir, credential helpers, include directives,
URL rewrites, extra headers, or unreviewed hooks are permitted. Do not fetch after
capture: any ref movement invalidates the seal and approvals. Pin git-filter-repo
2.47.0 (executable version a40bce548d2c) from the hash-locked policy dependency.

## Reviewed capture CLI

Only after explicit authorization for the read-only capture step:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/ci/nyay21_executor_runtime.py \
  --capture-seal --root "$NYAY21_SCRATCH_ROOT"
```

Set the protected-root configuration and execution credential through the approved
operator process, never in command arguments or evidence. Capture makes two equal
Git/object and authenticated GitHub repository/ruleset observations. It writes a
new seal, policy and capture receipt exclusively; existing files refuse. It does
not create a backup, rewrite, push, or change a ruleset. A partial capture requires
an owner-reviewed fresh directory, never silent overwrites.

The capture-to-push window is at most 2700 seconds (45 minutes). Each runtime
receipt obtains Date from an authenticated TLS GET to the fixed GitHub repository.
The request identifier is hashed. Request duration and local monotonic-derived
clock drift must each remain within five seconds. Caller timestamp parameters
are absent from the live runtime API. The historical pure validator's injected
`now` remains a planning/test input, not execution authority. Scope read-back's
separate five-minute freshness bound remains enforced. Expiry refuses, including
resume; restoration safety handling must still run after expiry.

## Signed snapshot format — nyay21-registry-snapshot/v2

The v1 parser remains available for historical inspection only. The runtime
requires v2; no v1 receipt can authorize an execution or continuation step.

No Jira credential is provisioned or stored on the executor. At each applicable
PROCEED pause the owner or Claude reads the full NYAY-21 comment chain through an
authenticated session and produces an independently signed snapshot. A local
claim of successful Jira read-back is not accepted without the approved signature.

The independently digest-bound GO permit must include `registrySigners`, mapping
`owner` and/or `claude` to `{publicKey, accountId}`, and `registryAnchor` containing
`{index: -1, digest: "0000…0000"}` (64 zeroes). Full registration/consumption
history is required; arbitrary truncated anchors refuse. Public keys use SSH Ed25519; account identifiers bind the
authenticated publisher. Select/provision production signing identities outside
this executor and only under owner authority. Private signing keys must not be
stored on the executor. Synthetic test keys carry no production authority.

`registry-snapshot.json` contains exactly `{payload, signature}`. The execution payload has
exactly these fields:

- `schemaVersion`: `nyay21-registry-snapshot/v2`.
- `issue`: `NYAY-21`; `repository`: `rajeevbarnwal/NyayOne`.
- `sealSha256`: exact canonical seal digest.
- `signer`: `owner` or `claude`; `accountId`: approved authenticated identity.
- `commentId`: positive decimal Jira comment ID of the authenticated registry
  read-back source (the chain-head entry or approved empty-chain anchor record).
- `serverTimestamp`: integer authenticated server-time read-back.
- `expiresAt`: integer, greater than serverTimestamp and at most 2700 seconds
  later; authenticated current time must precede expiry.
- `authority`: `execution`; SSH signature domain `nyay21-registry-execution-v2`.
- `executionId`: the R registration's canonical identity hash.
- `registrations`: full ordered UUID identity inventory.
- `chainHead`: canonical SHA-256 of the last entry (or approved empty anchor).
- `entries`: full ordered consumption chain from the zero anchor.

Each registration contains exactly `sealedPlanSha256`, `approvalId` (UUIDv4),
`nonce` (64 hex digits chosen by the owner), `executionId`, `custodyRootSha256`.
`executionId` is the canonical hash of `{sealedPlanSha256, approvalId, nonce}`.
`custodyRootSha256` hashes the canonical resolved scratch-root path. Register
both R and F UUIDs using the same plan/nonce/root; each has its own identity hash.
The permit's `executionIdentity` is the complete R registration. A changed root,
nonce or plan cannot reuse a UUID. `register_execution` is the pure publisher-side
uniqueness contract: exact registration replay is idempotent, any changed binding
for the same UUID refuses. The owner/Claude publisher serializes append/read-back
in NYAY-21; conflicting publisher updates must be rejected, not independently signed.

Each entry contains exactly `index`, `previous`, `sealSha256`, `approvalId`,
`action`, `event`, `commentId`, `serverTimestamp`, `effectReceiptSha256`, `executionId`.
Indices are consecutive integers; UUIDv4 approval IDs cannot repeat; action is
`rewrite` or `force-update`; event is `consumed`. Each entry matches its registered
UUID/plan/identity; times are nondecreasing and no later than the signed snapshot.
The execution snapshot is usable only within the original seal window. The post-push F entry
must bind `effectReceiptSha256` to the runtime's immutable `push-verified.json`,
not a prediction of successful push. Rewrite consumption binds the immutable
`rewrite-intent.json` (which binds the reviewed drill receipt, identity, and
fresh signed UNCONSUMED registration snapshot).

Stage the claim at GO, **before watchdog arming**, using the independently
approved permit digest:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/ci/nyay21_executor_runtime.py \
  --prepare-rewrite-claim --root "$NYAY21_SCRATCH_ROOT" \
  --owner-permit-sha256 "$NYAY21_OWNER_PERMIT_SHA256"
```

This stages evidence only, never Git/ruleset mutations. Owner/Claude then appends
the R consumption entry bound to that intent and imports the signed snapshot.
Step 6 verifies both the fresh original signed unconsumed snapshot and the current
claim, identity, UUID uniqueness and no prior local use. Only then may the
uninterrupted watchdog-protected 6–10 segment start. A missing staging step refuses
before arming; no operator signing pause is hidden inside the relaxed-ruleset period.
Step 7 writes the one-use local marker before rewrite. Re-executing it refuses;
only independently verified completed effects may use the explicit resume path.

Canonical JSON is UTF-8 `json.dumps(payload, sort_keys=True,
separators=(',', ':'))`, no trailing newline. Sign these exact bytes using
`ssh-keygen -Y sign` with the authority-specific namespace; import the armored
signature without modifying the payload. The executor uses only the permit's
public-key allowlist and verifies with `ssh-keygen -Y verify`. A signed snapshot
is the publisher's attestation of authenticated read-back, **not a Jira server
signature**. Review the account/key bindings independently before GO. Obtain the
source comment ID from the authenticated registry read-back, sign the snapshot,
then publish its envelope as a new comment. The envelope does not recursively
contain its own as-yet-unassigned comment ID; do not edit older comments.

Accepted snapshots and their signed envelopes are immutable local revisions. Each newer snapshot must extend
all previously accepted entries and registrations and cannot roll its timestamp back. Signature,
identity, comment, chain, seal or freshness mismatches fail closed. This chain
does not prevent a privileged custodian rewriting an entire local environment;
external comment anchors and independently approved keys are the trust boundary.

## Push, consumption and pause ordering

The executor imports and verifies the snapshot before the dry run and again
immediately before live push. F must be unconsumed. Explicit per-ref leases and
atomic push remain mandatory. Following push, restoration is attempted immediately,
before any freshness/registry check. Then remote refs, private status and restored
ruleset are verified; one `push-verified.json` binds the execution identity and
exact `restoration-proof.json` digest. F is consumed only after this combined proof.
Git and GitHub REST cannot be a distributed atomic transaction: the guarantee is
an indivisible success attestation after BOTH effects, backed by finally/watchdog
restoration on all interrupted/failing paths. No success receipt is emitted while
restoration is unverified. Clock failures cannot prevent the restoration attempt.
If the signed consumption entry is absent, the executor writes an unsigned
`consumption-request-<UUID>.json`, emits `REGISTRY_CONSUMPTION_PAUSE`, refuses
completion, and runs restoration. The owner/Claude posts the digest-bound entry
to Jira and imports the new signed continuation snapshot. No automatic Jira posting is implied.

## Continuation-only authority

`continuation-snapshot.json` uses the same envelope and ledger fields but
`authority: continuation`, signature namespace `nyay21-registry-continuation-v2`,
and two additional mandatory fields: `pushProofSha256`, `restorationProofSha256`.
They bind the already verified push and its restoration proof exactly. This
receipt can be issued after seal expiry; it is fresh for at most 2700 seconds from
its own authenticated server timestamp. It never refreshes the original seal,
R/F approvals, execution permit, lease plan or watchdog authority. Relabeling or
reusing its signature in the execution domain fails cryptographic verification.

Steps 10–15 require a fresh continuation snapshot; step 9 safety restoration is
never window-gated. The dispatch step remains read-only parameter preparation,
not an Actions write. Expiry during continuation pauses with restoration already
complete; owner/Claude issues a fresh continuation-only snapshot to resume the
next uncompleted step. The original owner-PROCEED/campaign/closure digest bindings
remain required. Rewrite/push resume after the original seal expiry still refuses.

## Resume and refusal handling

Within the original window only:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/ci/nyay21_executor_runtime.py \
  --resume-rewrite-phase --root "$NYAY21_SCRATCH_ROOT" \
  --owner-permit-sha256 "$NYAY21_OWNER_PERMIT_SHA256"
```

Resume validates the custody hash chain and completed receipt digests. It does
not rerun a verified successful push; it imports the post-verification consumption
entry and continues to the rewrite-push pause. Incomplete capture, ambiguous
partially rewritten Git state, dead/unbound watchdog, changed head, changed output,
receipt gaps or expired authority require owner recovery, not a blind retry.
Completed effects are never inferred solely from a caller's status flag.

Every concurrent-edit refusal is emitted to custody and escalates. Ruleset reads
receive at most one extra GET across transport/concurrent-edit failures; no blind
PUT may overwrite unrelated state. Restoration PUTs remain bounded. Watchdog
stdout/stderr writes are SHA-bound by the child into the fsynced custody chain,
including after parent SIGKILL; raw diagnostics are not published. Canonical
refusal and escalation events accompany those digests. Restoration must not be
disabled by seal expiry, an operator pause, or a failed consumption import.

Steps 11–15 remain owner-PROCEED gated. Step 12 prepares dispatch parameters only;
owner performs dispatch with separate authority. The execution credential remains
repository-scoped Contents:write, Workflows:write, Administration:write,
Actions:read, Metadata:read. This document does not grant fresh execution GO.

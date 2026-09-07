# NYAY-13 — independent exact-head QA, observe-only rollout

The 47 accepted policy contracts define an independent trust gate, not a way for
an implementation agent to mark its own work independently approved. Existing
NYAY-14 evidence validation and NYAY-40 failure-digest controls remain mandatory.

## Trust boundary and interfaces

`validate_review(evidence, facts)` is a policy-core API. `facts` is privileged
adapter input: it must never be accepted from the same untrusted package as
`evidence`. Its booleans represent already-verified facts, not credentials.
The synthetic fixtures intentionally exercise this boundary in isolation.

The signed-review CLI verifies an independently signed canonical JSON envelope
against a SHA-256-pinned public key and separately administered policy. The key
and policy must be outside implementation-agent write authority; public keys are
not secrets. Private signing keys never enter this repository or evidence.
The signature binds every evidence and read-back field plus a maximum-one-hour
validity window. The CLI independently reads the live PR head through `gh` and
invalidates a signed receipt on HEAD_CHANGED. Duplicate JSON keys, invalid
signatures, mismatched identities, expired/revoked trust and malformed receipts
fail closed with canonical diagnostics; raw exceptions/URLs are not echoed.

A valid signature authenticates the reviewer's claims, not the underlying test
execution. The independent publisher must acquire raw artifacts, NYAY-14
validation, exact inventory, current required-check URLs/identities, pagination,
and NYAY-40 seeded failure-export read-backs itself before signing. It must not
copy booleans from an implementer's JSON into a signed receipt.

**No independently administered production publisher/key has been provisioned
by this change.** The CLI always emits `mode=observe-only, mergeAuthorized=false`,
even for a policy PASS. It has no active-mode switch, merge execution, signing,
check-write, ruleset-write or Jira-transition capability. The policy library's
command renderer is only for a future trusted integration and never executes.
This PR is not evidence that automated independent approval is operational.

## Observation

```
python scripts/ci/nyay13_independent_qa_gate.py \
  --envelope independent-receipt.json --signature receipt.sig \
  --public-key reviewer-public.pem --trust-policy externally-managed-policy.json \
  --pr PR_NUMBER
```

Receipt fields: `evidence`, `facts`, `issuedAt`, `expiresAt` (UTC integer epoch).
Sign canonical JSON (sorted keys, compact separators, ASCII escaping, no NaN)
with SHA-256 using the separately controlled signing key. Policy fields:
`publicKeySha256`, `issuer=trusted-independent-publisher`, `reviewer`,
`implementer`, `revoked=false`. Reviewer and implementer must be distinct.
The contract fixture provides the full evidence/read-back structure, not an
approved real-world receipt. A local synthetic key never establishes trust.

An isolated workflow gains only a non-required observation job, not a new
required status context. There is no continue-on-error or required dependency.
All seven ruleset-required contexts remain untouched. Existing policy/evidence
checks remain blocking. Observation-job
failures are visible in Actions logs and require investigation; they are not
silently described as independent QA PASS.

## Promotion criteria — separate owner approval required

1. Provision a truly independent operator/publisher identity and external trust
   root; prove the implementer cannot edit keys/policy or mint the QA context.
2. Independently validate NYAY-14 evidence, privacy/contact-sheet/raw metrics and
   NYAY-40 seeded failure diagnostics; bind signed receipts to those read-backs.
3. At least five consecutive complete Linux observations across three distinct
   reviewed heads, with expired/revoked/forged/self-certified/head-change,
   missing-artifact/zero-assertion and failure-digest-negative canaries rejecting.
4. Prove the unique publisher-owned context cannot be spoofed by PR code, fork
   credentials or another GitHub App; scoped credentials never enter evidence.
5. Independent review and explicit owner approval of required-context promotion
   and rollback. Do not alter the seven existing contexts in this rollout.

One required approval and last-push approval are recommendations only after a
genuinely separate trusted reviewer is available. Sole-owner configuration must
not use self-approval or bypass to avoid lockout. Until promotion, retain the
existing manual independent QA and guarded merge process.

## PR evidence format

Record reviewed head, base, prospective merge, independent run ID/operator,
manifest/contact-sheet digests, exact required-check/run URLs, canonical known
limitations, PASS/FAIL/BLOCKED/HEAD_CHANGED and observe-only status. Use
`render_pr_comment` only after validated policy facts; do not publish untrusted
free-form error payloads. Post-merge closure separately verifies reviewed-head
and merge ancestry, exact main-push head and run/check URL read-backs.

## Scope and holds

No product code, existing gate weakening, quarantine change, visibility change,
history rewrite, backup or freeze. NYAY-21 remains HOLD/NO-GO. Protected checkout
299-entry/digest baseline is checked outside the isolated worktree.

The existing ten workflows and their semantic seals are byte-identical. A new
whole-file seal covers only `nyay13-independent-qa-observe.yml`; the workflow
inventory expands to eleven. Any byte change to the observation workflow fails
its dedicated policy check. No existing assertion, digest or required context
changes. The initial local step-level observation attempt was rejected by the
existing fail-open policy and discarded, not exempted from that policy.

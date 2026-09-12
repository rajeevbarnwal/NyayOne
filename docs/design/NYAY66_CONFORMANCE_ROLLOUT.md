# NYAY-66 progressive visual conformance

## Approved model

Owner records: NYAY-66 comments 15380 (progressive enforcement) and 15382
(numeric tolerances, cached references, masks, and three-stage QA).
Reference source is unchanged Option 3.2.1 Revision L HTML, SHA-256
`338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252`.
Historical evidence and original SHA labels remain unchanged.

Same-host limits are counted pixel mismatch <= 0.10%, RGB mean absolute
difference <= 0.25/255, geometry <= 1 CSS px, zero unexplained text/control
changes and zero serious/critical accessibility violations. Pixelmatch uses
threshold 0.1 and excludes antialiasing-only differences; raw RGB mean remains
an independent check. Both full viewports and heading/control crops are checked.

The workflow captures live application screens only. It loads the committed
reference cache, verifies every PNG and the manifest, and refuses Chromium,
Playwright, platform, source or font-hash mismatches. Node 22.21.1, Chromium
149.0.7827.55 and Playwright 1.61.1 are the initial Linux x64 capture pins.
Viewports are 390x844 and 1440x1024 at DPR 1, en-IN, Asia/Kolkata. Fonts, images,
response bodies and application readiness settle before capture; no timed sleeps
or retries are used. Deterministic synthetic fixtures intercept API traffic.

## Progressive enforcement and evidence

`frontend/scripts/nyay66-policy.json` contains the enforced screen set. Every
PR reports all screens, but uncorrected screens remain explicitly NONCONFORMANT.
Capture errors and pin/inventory failures block regardless of that set. Once a
screen is enforced, removing it relative to the PR base (or push event's
previous head) is rejected. Dispatch uses the current commit's first parent;
an absent/unavailable/zero comparison base refuses rather than resetting the
enforced set. Its next
unapproved regression blocks the job. The owner merges each screen PR that
expands the set; a green job does not mean all reported screens conform.

Initial hosted capture at 6a0833c reports 32 NONCONFORMANT light screen/state
rows and 42 DESIGN-GAP rows, with no capture failures. No screen is yet declared
conformant, so the initial enforced set is empty. S-03's implementation PR must
make its two viewport rows pass and add S-03 to the set. Do not manufacture a
conformant baseline from the current application to make this gate green.

The artifact includes exact implementation head, reference and live PNG hashes,
reference/live/diff sheets, regional pixel metrics, DOM surfaces, structural
failures, accessibility violations and SHA256SUMS. DESIGN-GAP rows are marked
`executed: false`; they are never represented as executed evidence.

Seventeen canonical routes plus S-07 popup are reported. S-10 has two reference
states; S-07 landing shares s14 and its popup uses s14p. S-01/S-02/S-06 have no
approved Revision L reference. All dark variants remain DESIGN-GAP pending
NYAY-50/51 approval. The S-09 fixture currently captures pending verification
where the prototype displays success; its state mismatch is disclosed, not an
assertion of a product regression. Screen-specific fixture reconciliation must
precede promotion of S-09.

## Dynamic regions

S-05 has exactly two OTP clock leaf regions. Only their changing digit pixels
are excluded. Region count, clock format, location and dimensions remain
structurally checked (<=1 CSS px). Other screens have no masks. Non-finite,
out-of-viewport or >5%-of-viewport masks are refused. Text outside clocks,
control names/roles/disabled state, headings and overflow remain checked.
New dynamic masks need a screen-specific contract and reviewed PR; arbitrary
regions cannot be supplied through the exception register.

## Owner PR-comment exceptions

NYAY-47 comment 15208 approves categories, not blanket exemptions: email channel,
scoped NYAY-8 header supersession, masked destinations and S-17 disclosure.
The initial effective register is empty. A proposed entry contains screen,
viewport, light theme, exact reference/live PNG SHA-256, checks to waive and
`approvalPr`. Use `approveException(entry, null)` from
`frontend/scripts/lib/nyay66-enforcement.mjs` to compute its canonical hash.
The owner posts `NYAY66-EXCEPTION <hash>` on that PR. The workflow reads comments
from GitHub and requires author `rajeevbarnwal`; changed entry bytes require a
new approval. No private signing key or receipt ceremony is involved.
Accessibility, dynamic-region integrity and overflow cannot be waived.

## Owner-approved re-baseline runbook

1. Open a dedicated pin-update PR and explain the version/font/source change.
   Obtain owner approval for recalibration; do not silently overwrite a cache.
2. On the proposed pinned Linux hosted environment, run
   `node scripts/nyay66-calibrate.mjs` from frontend. This explicit bootstrap is
   not part of normal PR runs. It captures three contexts for each of 30
   view/viewport pairs; validate the 90 PNGs and 60 repeat comparisons.
3. Download the artifact and verify `SHA256SUMS`. Compare old/new references and
   publish the repeatability measurements plus structural and accessibility
   review. A pin upgrade is not authorization to accept application drift.
4. From frontend, run `node scripts/nyay66-import-reference.mjs <artifact-dir>
   <new-cache-dir> <owner-approval-comment>`; use a new versioned cache directory.
   The importer verifies the calibration and refuses an existing output path.
5. Update the policy cache/manifest hash and dependency pins in that PR. Run
   negative pin tests and live verification for all enforced screens. Owner
   approves and merges; preserve old reference/evidence artifacts.

## Three-stage screen QA

1. Codex implements one screen per PR (shared root-cause components may be
   grouped), runs CI, and moves its Jira ticket to Testing. Attach before/after
   versus reference, gate verdict, accessibility delta and comparison sheet.
   The handoff lists navigation, expected Revision L elements, approved
   exceptions and tester remarks. It includes the exact branch/head.
2. Owner relays the handoff to Claude. Claude tests independently on the PR
   branch, publishes its own sheet/evidence and moves the ticket to In Review
   on pass, or In Progress with findings. Codex fixes and resubmits failures.
3. At In Review, owner reviews, approves any intentional exception by PR comment,
   then executes the exact-head merge command. Codex starts the next screen only
   after owner confirmation. Codex merges nothing, including NYAY-66.

After NYAY-66 owner merge: standalone S-01/S-02/S-06 R2 reference-integration
PR per NYAY-50 comment 15422, then S-01 -> S-02 -> S-03 -> S-04 -> S-05 ->
S-06 -> S-07/popup -> S-10 through S-13/S-17 -> S-14 -> S-15/S-16.
Dark references remain deferred under NYAY-51. Tester handoffs include real
mobile-keyboard, backend-connected flow, and accessibility tests; the R2 source
review covered layout only. No R2 reference is added by this corrective PR.

## Seven-finding corrective: trusted evaluator and owner approval

The GitHub default-branch `pull_request_target` workflow reads the candidate as
data. It loads `nyay66_trust.py` from the event base, never from the candidate.
PR #37 is the one-time bootstrap: main does not yet contain this gate, so its
reviewed workflow pins an immutable first-install reader commit. The owner must
review that bootstrap workflow as well as its content approval before merging.
After installation, the PR-trigger bootstrap path is disabled except for this
specific PR/base pair; candidate workflow edits do not replace the target run.
This is not branch protection and does not prevent an owner from changing or
disabling workflows directly on main.

The trusted reader computes SHA-256 for every gate script, gate contract, workflow,
reference-cache file, original design source, font and package/lock file directly
from Git blobs. The policy's approved settings are included in that bundle digest.
It rejects symlinks and checks progressive enforcement and the unchanged approved
numeric tolerances. `integrityApproval` in the policy binds `pr`, `commentId`, and
`bundleSha256`. The owner posts exactly `NYAY66-INTEGRITY <bundleSha256>` on that
PR. The reader fetches all comment pages and requires that exact ID, PR, author
and body. A changed evaluator, reference or tolerance-setting bundle cannot reuse
an older approval. Unrelated screen implementation or additive enforcement does
not require a new bundle approval. Exception entries retain their separate owner
PR-comment approval. No private key, signed receipt or new ceremony is involved.

Only the trusted reader receives the read token. It emits public approval data,
then materializes the approved gate blobs into a separate directory. Application
Vite/npm configuration is not exported there. Evaluator dependencies install from
the approved lock with lifecycle scripts disabled. Candidate application builds
run in a disposable read-only container with explicit input/output mounts, no
host secrets/environment, no Docker socket, and no access to the evaluator.
Symlink build output is rejected. The approved evaluator captures the build with
the unchanged browser/font pins, masks, cached references and numeric limits.

Reference import validates the checksum inventory and each selected PNG against
its calibration sample hash before creating output, then writes the verified bytes
without rereading a mutable source. Runtime continues to hash every reference at
use. Cross-origin requests are refused before API-path matching, including requests
whose paths resemble legitimate API routes.

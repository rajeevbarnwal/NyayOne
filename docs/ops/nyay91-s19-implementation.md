# S-19 implementation work in progress

S-19 is the next screen after the S-18 merge. This draft begins its state and
projection boundaries; it is **not** a completed screen, measured conformance
result, enforcement promotion, or independent QA handoff. The state module is
now connected to the S-19 route through its own controller and Revision L view.

## Frozen authority

- Design: v3.2.1.08, `S-19` in `source/continuation-states.json` inside
  `frontend/test-baselines/nyay66/v3.2.1.08/NYAYONE_S01_S35_v3.2.1.08.zip`.
- Canonical ZIP SHA-256:
  `0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`.
- 26 states × mobile390/desktop = 52 source-only S-19 rows. None is claimed as
  measured by this draft. Optional manual-save mode is not the shipped default.
- Backend: `backend/app/api/v1/student_settings.py`,
  `backend/app/services/otp_flow_service.py` and existing frontend typed adapters.

## Initial tests-first slice

`privacySettingsState` defines S-19-only rules for:

- Exact canonical consent inventory; pending drafts separate from confirmed
  values; a newer server version and matching saved consent required before
  announcing success; rollback after failure and reload-gated version conflict.
- Current-visit export references and the five actual server statuses:
  pending, processing, complete, failed and cancelled. A replayed POST can
  return the original request's current status. `complete` does not promise
  an email or a download; `cancelled` does not invent a cancellation endpoint.
- Exact typed DELETE plus a current recovery-purpose verified projection and
  no failed authority read/in-flight submit. The server remains the authority
  and consumes proof at deletion. Its verified projection has a null client
  expiry budget; the UI must not invent one.

The new focused suite was authored before the module (RED: missing module),
then all 59 cases passed. Full frontend matrix: 166 files / 2,600 tests passed;
TypeScript and ESLint passed. These are local unit checks, not live-backend QA
or a visual-gate result.

## Remaining work and approval boundaries

1. Implemented focused deletion substates replacing the overview (not appended
   below it), confirmed consent cache/rollback/conflict reload, and truthful
   export request/status handling. Shared auth transitions and the deletion
   adapter remain unchanged. Recovery start → verify → privacy/delete; never
   recovery/complete. Failed recovery-authority reads still hide confirmation
   and prevent Send/deletion until a fresh valid read.
2. Owner approved narrow S-19 browser/census/inventory alignment on 2026-10-17.
   Legacy negative control moved to unchanged S-20; security assertions stay
   intact. Source-based authority tests follow the extracted controller.
3. Owner approved a separate capture-only calibration prerequisite. It adds
   `s19-v32108` to the existing owner-dispatched path. Owner integrity approval,
   Terminal merge and dispatch precede hash-verified import; no dispatch by Codex.
4. Disposition transient session/deletion-accepted and optional-manual rows
   explicitly. Do not manufacture delays or mark absent coverage as passing.
5. Hosted measurement, geometry/accessibility corrections, scoped exact-image
   owner exceptions if necessary, independent Claude QA and the six-file
   evidence pack (including `preview.svg`) precede Testing handoff.

Existing evaluator, references, exception approvals, tolerances, and the 74
blocking light rows remain unchanged. S-18's measured/report-only rows retain
their merged disposition. This draft changes no backend or other screen.

## 2026-10-17 local validation (not hosted conformance)

- Presentation regression RED before the new view; census RED before S-19 was
  classified Revision L; recovery-authority regression RED before correction.
- Frontend: 167 test files, 2,621 passed, one existing skipped test. Typecheck
  and lint pass. Namespace scan PASS including 17/17 negative controls.
- Real Chromium / synthetic API: 12/12 S-19 tests; independent census fixture:
  22/22. Includes duplicate toggles, version/conflict/reload, malformed 2xx,
  same-component query/hash settlement, export truth, recovery-proof failure
  and focused deletion, focus restoration, 320/390/1440 overflow, 48px targets,
  and zero serious/critical axe on overview/mobile-entry states.
- These do not certify all S-19 states, live backend behavior, physical mobile,
  screen-reader output, hosted pixel parity, or independent Claude QA.

## 2026-10-17 owner calibration and candidate reference import

- Successful first-attempt owner dispatch: run `39029544967`, artifact
  `12099474372`. Both actor and triggering actor are `rajeevbarnwal`;
  `workflow_dispatch` on `main`, control revision
  `3d0e1201ea672c6f96b7a86703def2d3bffa69f5`.
- Reviewed source revision: `32573e0333baa5bea6098e8399b4a7108770fac0`.
- Downloaded archive SHA-256 recomputed locally and matched to GitHub:
  `42e208402d032613183474711c629efb4488a6613b4450f1e93d139d9dcf9030`.
- 52/52 PNG hashes and decoded dimensions, 54/54 checksum entries, and all
  156 sample hashes verify. Chromium `149.0.7827.55`, Playwright `1.61.1`,
  Node `v22.21.1`, `linux-x64`, approved font bytes and frozen source hashes
  match. The two viewports are 390x844 and 1440x1024.
- Candidate cache:
  `frontend/test-baselines/nyay66/s19-v32108-chromium-149.0.7827.55-39029544967/`.
  `SHA256SUMS` contains every PNG digest. Manifest SHA-256:
  `b3e1637089633cef983824d0fd65341e73de1497f0fa77f8ca515d6cb305f32c`;
  provenance SHA-256:
  `5d999acbbfae032d266047221c62ee8add9b488062412a3f878595ec01431bbf`.

The new S-19-only importer recomputes the ZIP digest, checks its exact member
inventory without extracting paths or executing helpers, validates all input
before writing, and refuses to replace an existing cache. Its loader rechecks
all PNGs, manifest, provenance and runtime pins at use. Tests include archive
tampering, PNG tampering despite recomputed outer checksums, missing states,
wrong source/control heads or pins, extra members, symlink input, unsafe cache
names and post-import cache corruption. Import tests were RED before support;
the real-cache binding test was RED before the policy binding.

This commit adds only the reference cache, S-19 import/load support and tests,
the `s19` cache binding, and this additive record. Existing 74-row enforcement,
the 18 measured S-18 rows, old references, exceptions, evaluator and tolerances
are unchanged. The prior integrity approval is deliberately not reused for the
new bundle; a fresh owner top-level approval on PR #70 is required.

**Reference ingestion is not product measurement.** The live producer is not
extended by this import-only step; all 52 S-19 product rows remain DESIGN-GAP.
Capturing the two optional-manual design rows does not approve manual-save
product behavior. Transient session/deletion-accepted coverage still needs an
explicit disposition; no production delays or navigation freezes are added.
NYAY-91 stays In Progress, with no conformance or independent-QA pass claimed.

Local candidate validation: 169 frontend files / 2,636 tests passed, one existing
skip; trust/calibration Python contracts 50/50 passed; workflow policy passed
all 14 workflows. The new protected bytes require owner approval before hosted
conformance can accept this candidate.

## 2026-10-17 owner binding and additive measurement wiring

Owner PR #70 comment `6233524485` was read back: author `rajeevbarnwal`, exact
`NYAY66-INTEGRITY 0f871ce8128a03fa4901a533c3d219d8429f4e29daaf39b92a22343008f27613`.
Binding commit `195eea69bf117715a99215db9fe6fb7d237abc7c` was pushed.
Hosted conformance run `39030676385` succeeded at that head. All 278 artifact
checksums verify; report: 30 PARITY + 62 PARITY-WITH-DISCLOSED-DELTA, zero
blocking failures, 74 enforced rows. S-19 still correctly had 52 DESIGN-GAP
rows at this import-only head. The independent policy job rejected three new
EOF blank lines in the importer files; this follow-up removes those lines.

The owner subsequently authorized product measurement and explicitly approved
component-plus-route evidence for transient session/deletion acceptance in the
chat, recorded at `NYAY-91:16160`. The new protected wiring adds:

- S-19-only synthetic API fixtures exercising the real compiled route/controller
  via normal user actions; exact request shape and negative HTTP diagnostics.
  Held loading/saving responses are observed before capture, not timed sleeps.
  Recovery inputs are validated but redacted in the published request record.
- An additive producer using the existing pixel, region, structure and axe
  comparison functions with unchanged tolerances, reference bytes and masks.
- 46 stable live-route rows; two session presentation-component rows plus
  genuine typed-401 redirect/anonymous-session evidence; two **actual S-03
  deletion-accepted destination captures**, with successful 202, anonymous
  session and accepted-notice checks. The latter is not relabeled as a stable
  S-19 page or a component invented from the prototype's gateway placeholder.
- A separate test-only S-19 session component build using the actual
  `PrivacySettingsView`; production build/navigation are unchanged. Existing
  S-01/S-18 component outputs and build invocations are preserved.
- Additive registry/finalizer/report support, strict transient evidence labels,
  missing/duplicate-row checks, and explicit preservation of the two deferred
  optional-manual DESIGN-GAP rows. No new enforcement promotion or exception
  approval. Existing 92-row inventory, old exception bytes and reference bytes
  remain unchanged. Tests permit future structurally valid S-19 proposals only;
  the hosted gate still requires the exact owner comment for every proposal.

Coverage goal after authorization: 50 S-19 measured rows, 2 S-19 manual gaps;
142 measured light rows overall (74 blocking + 18 S-18 + 50 S-19), 314 remaining
continuation light gaps, and unchanged dark gaps. A failed capture is never a
passing row. Wrong-case DELETE / invalid-mobile scenarios capture the actual
disabled controls, not fabricated inline server errors or forced submissions.

Tests-first evidence: missing measurement modules were RED; the 50-row browser
test exposed an unobserved held PATCH and is GREEN after awaiting that request;
the additive exception test and recovery-input redaction test were RED before
their corrections. Final local checks: 108 focused unit tests; full frontend
171 files / 2,654 passed + 1 existing skip; 40 trust regressions and 10
calibration-workflow contracts; policy validates 14 workflows; typecheck,
lint, production/component builds and base-to-worktree diff checks pass.
The real Chromium synthetic-API rehearsal executes all 50 rows, with zero
serious/critical axe findings and zero horizontal overflow at the two capture
viewports. It is a **local macOS diagnostic**, not a pinned hosted verdict,
live-backend certification, exception approval, or independent QA result.

This new capture/coverage bundle requires a fresh owner integrity approval.
The import approval is not reused to authorize it. Hosted S-19 verdicts and
exact-image exceptions remain pending that approval; NYAY-91 stays In Progress.

## 2026-10-17 first hosted measurement and presentation correction

Owner comment `6233689134` binds bundle
`695cb020fc1384e5c05c524d118db18cafe60849e0fbd1148aa70fe02ec54205`
at binding head `2fc2815e8c75331419ccd6d11ff019b65cdd155e`.
Run `39031658251` successfully measured all 50 S-19 default rows, with no
serious/critical axe findings; all 50 are NONCONFORMANT before exceptions.
The two manual rows remain DESIGN-GAP. Existing 74 blocking rows still pass;
the successful report-only S-19 job is not a claim of visual parity.

The owner-authorized presentation correction is confined to S-19's view/CSS:
19px flex deletion headings, 12px field labels, 1.4 helper line-height,
8px paired-action spacing, prototype OTP field sizing, .55 disabled opacity,
centered session-error frame, frozen status icons/colors, and error placement
after the relevant input. Loading/session retain their frozen overview copy.
No settings/controller, recovery authority, routes, evaluator, reference,
tolerance, enforcement, or existing exception bytes change.

Tests were RED before correction: semantic error-frame/notice placement and
mobile/desktop heading/action/OTP geometry. All existing behavioral assertions
remain. The synthetic browser test now observes its held PATCH before asserting
its count, eliminating a test-side scheduling race without changing behavior.
Local frontend: 171 files, 2,658 PASS plus one existing skip. S-19 browser:
14/14 PASS, including 320/390/1440 reflow, 48px controls and serious/critical
axe checks. Local widths differ from Linux reference widths: no width override
was introduced to compensate for that platform difference.
Corrected hosted images and scoped owner exceptions are still pending.

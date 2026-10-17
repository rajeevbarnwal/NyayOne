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

## 2026-10-17 owner-approved deletion-conflict correction

Hosted capture exposed a fixture/notice mismatch: privacy deletion actually
returns `409 concurrent_state_changed`, not `settings_version_conflict`, and
the exclusive auth-transition remount restored a generic failure instead of
the already-defined conflict message. The owner approved a narrow correction.

- RED: a transport regression observed the wrong fixture code; a real-Chromium
  synthetic-API regression could not find the specific conflict message after
  the genuine auth-transition remount. The 422 and generic 503 controls passed.
- GREEN: a sanitized, memory-only `account_deletion_conflict` notice restores
  that existing message across the remount. No recovery inputs, authority or
  request identifiers are carried. The exclusive transition, adapter, session
  reconciliation and redirects are unchanged. The confirmation input resets,
  a fresh authority read remains required, and deletion is not retried silently.
- The protected fixture now uses the real backend code and explicitly requires
  both conflict sentences; generic deletion failure can no longer satisfy the
  conflict capture. Its new transport regression preserves all prior checks.
- Local validation: 171 frontend files / 2,660 PASS + one existing skip; focused
  fixture/notice tests 16/16; S-19 browser checks 17/17, including 409/422/503
  remount outcomes and the unchanged successful 202 redirect. All 50 capture
  rows execute with their original evidence-kind labels and zero serious or
  critical axe findings. This is local synthetic-API evidence, not final pinned
  hosted measurement or independent Claude QA.
- Typecheck, lint, production and component builds pass. Trust/calibration
  contracts pass 50/50; policy/evidence tests pass 94/94; workflow policy passes
  all 14 workflows. Existing 74 blocking rows, 18 S-18 rows, all references,
  tolerances, evaluator and enforcement settings are byte-unchanged by this fix.

The protected-bundle delta is limited to `nyay66-s19-fixtures.mjs` and its
regression test. A fresh owner integrity comment is required before final
hosted measurement; the earlier approval is not reused for these new bytes.
NYAY-91 remains In Progress. No new exceptions are approved or bound here.

## 2026-10-17 final-measurement presentation follow-up

Owner comment `6235897983` was read back and bound at `5b05a119` to bundle
`305c6832bd6bcf0f7c2442790250ea67e5b7e80961d886651a23ac3dfcb22441`.
Hosted run `39046240355` executed all 50 S-19 rows; all 428 artifact file hashes
verified. The 92 earlier measured rows retain their verdicts and reference
hashes. The two optional manual rows remain DESIGN-GAP. No S-19 exception has
been approved, and a report-only job success is not visual conformance.

Screenshot and computed-style review found genuine remaining presentation
defects, corrected before proposing exceptions:

- The frozen desktop deletion stack uses 14px gaps, versus mobile's 13px.
  Retaining 13px on desktop accumulated a 3px field / 4–5px action shift.
- The rejected-code inline error belongs at the field's 5px helper gap, not
  the outer form's 13/14px gap. Both viewports now preserve that field spacing.
- Deletion conflict uses the reference warning border, not the risk border;
  the exact conflict text, auth-transition remount and recovery authority stay
  unchanged.

Tests-first: three browser spacing assertions and the conflict-tone assertion
failed before their respective fixes; the 19-check browser suite and 24 view
tests pass after correction. Product changes are S-19-only presentation; test
changes are outside the protected fixture bundle. References, tolerances,
evaluator, enforcement and existing exceptions remain untouched. Fresh hosted
captures are required for the final exact-image proposals; these earlier
captures remain historical diagnostic evidence, not rebound approvals.

## 2026-10-17 exact owner exception binding

The 50 top-level PR #70 comments below were read back through GitHub's API.
Each was authored by `rajeevbarnwal`, belongs to this PR, and contains exactly
the proposed `NYAY66-EXCEPTION <hash>` line. The policy adds only the 50
previously disclosed entries for the `cbb750e8` hosted image pairs. Existing
exception values/order and every other policy field remain unchanged.

The two request-not-found rows retain their explicitly approved design-variant
scope, not an antialiasing classification. Session component evidence and real
deletion-redirect destination evidence keep their distinct labels. Per-row
icon baseline offsets remain explicit. The two optional manual-save rows stay
DESIGN-GAP; S-19 is not silently promoted to blocking enforcement.

All six measurement-pack attachments (16804–16809) were downloaded through
Jira's native bulk export and matched their uploaded SHA-256 hashes, including
the manifest. The SVG rendered in Jira. Detailed numbers, privacy inspection
limits and corrective evidence are recorded privately on the implementation
ticket; private Jira links are not cross-posted to the public PR.

Local binding verification replayed the verified hosted measurements:
50/50 PARITY-WITH-DISCLOSED-DELTA, zero remaining checks. Removing one owner
approval fails closed. This replay does not replace the fresh exact-head
hosted capture or independent Senior QA. Testing remains conditional on final
hosted conformance and all CI checks passing.

| State | Viewport | Owner comment ID | Approved hash |
| --- | --- | --- | --- |
| S-19-loading | mobile390 | 6236423848 | 900917b81a33794dba8260a9f3b35e68c41a044f7b1ce41f95bdb0d9da3caa7a |
| S-19-loading | desktop | 6236426280 | b37279e5c1159d9038be702daddf8707c0802df05475ae029f29d11068a643cd |
| S-19-loaded | mobile390 | 6236428625 | e70d3a49591198a1c34743233e2d59c7882bf8cb15949f41b1f855ba7fe2a4e7 |
| S-19-loaded | desktop | 6236431477 | 3aa0f788969121f1532b56d88286188bd0e02a3596f092817493bcf6db6c2764 |
| S-19-saving | mobile390 | 6236433898 | 0795c39022705a3d9e60ec22649a0f71aca8a6d86af7bab997f39a39b42d5ef7 |
| S-19-saving | desktop | 6236435986 | cd8ab1f80b6a2180178c4b0cbab8bc9cd7a6111f914a269755ee353e477ea905 |
| S-19-saved | mobile390 | 6236438702 | 135f1a8363f130c204400d4d79bc80e86b2aadf9a1a624427e59f57e983a281d |
| S-19-saved | desktop | 6236440179 | aca2a7b517d9bc819e3c2060d927eea2b667a94e831c6f3c15906d5981c4954e |
| S-19-conflict | mobile390 | 6236441563 | 72fc1a6db54b808616099430e900ecf6cacb092bc94a6539abf7ddfe96dbe1d1 |
| S-19-conflict | desktop | 6236442924 | 23aa2c3ccadacf455319955630c2dd92da4c53e3b60996c132075828087ba304 |
| S-19-network | mobile390 | 6236444458 | 409319841ede3c7276bcff3ac2564607d7642a933df5f2e0a773db46dd8ca811 |
| S-19-network | desktop | 6236446255 | f6db39297730392167be528bc6b6ecf957e239a1c611bd75afd2c3752a1a2b0b |
| S-19-export-accepted | mobile390 | 6236447449 | 1da6abc29331f9b8986884df29a4d3be3a30c7dd6fefcf882f274f8b461806b7 |
| S-19-export-accepted | desktop | 6236448648 | 2301ee4525fdd840cdbb7433b4a2a47db1790a0ebfbe09189cdceef668aa0755 |
| S-19-export-processing | mobile390 | 6236449935 | 5e59b876711c9e27c045740d33e6909768067cd04581cbfb16e8a187eb3d6742 |
| S-19-export-processing | desktop | 6236451376 | 58ca959210dbfc027d1d0f7124442489e81dda4740f47a246dec988da77fda54 |
| S-19-export-complete | mobile390 | 6236453888 | 9f64bbf977322ecbcd9def25f931e2639def65869e8658747cae4a60de1624f9 |
| S-19-export-complete | desktop | 6236455371 | f0c6d13069b17df111ed1cf3be69bf1d066cd7ddd26d6f5e9d829b5aa00aa45b |
| S-19-export-failed | mobile390 | 6236457077 | e513dce36964f0558e49faf69d19aa1565ee59719be1048aa44866ac567fb385 |
| S-19-export-failed | desktop | 6236458563 | 37727b3b5056da4b015c26620950f0dd8e4ae1bb908ebc3b9728a29d7bbdb08b |
| S-19-request-not-found | mobile390 | 6236460347 | 7bc4a9d2c466f45c793b9d0ab482a2badfbfe446a3c9e221360468202f693609 |
| S-19-request-not-found | desktop | 6236462007 | a515ef2ba4f3b7c056875eb5cba5e88f741d8c91879eec0503ecff1f628a1fb2 |
| S-19-delete-confirm | mobile390 | 6236463287 | 176b2fa5dfa16409bb736a91a656ddaec42bc4f7848bfaf437a9bc8030f97210 |
| S-19-delete-confirm | desktop | 6236464626 | 7958d43ef404cfadfb3350c1fdfa6f58d750c1c6b491320036891bc96778a19f |
| S-19-delete-invalid | mobile390 | 6236466052 | c1ce39ceb95623837ad8c87951bcbd82ad5593a4a3f2804ecb36206398eec2d9 |
| S-19-delete-invalid | desktop | 6236467420 | 2e6573872a90eb00bc89d491cd3d75047413abf3681c0f5272974cb1cf16fb15 |
| S-19-delete-reauth | mobile390 | 6236468596 | cbb52663588111d76e5a1c91123ed73a530ab7e152a53e8ae4101b4c16242550 |
| S-19-delete-reauth | desktop | 6236469731 | 1afa20436e24c36f5242b0af4b718ab5dddedf5efeb7b9a17e36a843cb35a766 |
| S-19-delete-reauth-rejected | mobile390 | 6236470720 | 94ffad6c1ef1010a9e86c331d0cd52623ff9517d59641f0f222ba1b773000127 |
| S-19-delete-reauth-rejected | desktop | 6236472106 | 158779595447ffaddb9aabfb4aa86f6d9e640633d76ed47df1f6d3c27da60668 |
| S-19-delete-reauth-required | mobile390 | 6236473378 | d3290ca92eb3e90ba87f69c48533d11da1af02eb59217934477f249e3a3ef9c6 |
| S-19-delete-reauth-required | desktop | 6236474525 | 50f733551f1095149ef902f2aeeedf8b5df667af79f00b446f76b5e38b9b7d24 |
| S-19-delete-conflict | mobile390 | 6236476117 | 0b2ae83f6a71959392bf36a27855be2f06f9f9efa91d89fa1e043acbab3bec90 |
| S-19-delete-conflict | desktop | 6236477572 | 2d80cd11070a09649caa3330f12ccfb818d88f6598312b4e93977c037479df35 |
| S-19-delete-accepted | mobile390 | 6236478996 | 19352f9d4113cbe6f110abecdae4a1fb9bb1a8fafd7eca786871681f428bb267 |
| S-19-delete-accepted | desktop | 6236480703 | 1380b6eaf1c6f96685c2507a1751f31fed1d6ff957eaf78db46a6dd8e296b394 |
| S-19-session | mobile390 | 6236482185 | bf2c532a1ac14ca729acc5926fabf2f288ef8f5ed183417be4111da497861db9 |
| S-19-session | desktop | 6236483470 | e8c4c778c3963c3d548d567ee3fc758427cfa18861dcbf1f619e375129ac598a |
| S-19-export-check-failed | mobile390 | 6236484728 | 1773f5a8944d23c1272ce97ea2508121f7325c74c943754724c2066eccb60ff9 |
| S-19-export-check-failed | desktop | 6236485858 | dea53570e946ba07a9d3f1fb13a62d0f2bb0afa9e41fda586164c1ac1298d980 |
| S-19-delete-mobile-invalid | mobile390 | 6236487202 | 5e28fc11bc87a79cd8d99e504df90a485dacb7cba430c9bb10be0c70fd1cc6ea |
| S-19-delete-mobile-invalid | desktop | 6236488440 | b5a1faf63d74ecba6a2c2339ecd2f143fcdd14a5fc715f545b05a524295a4942 |
| S-19-delete-start-failed | mobile390 | 6236489947 | f7265c0b91587b879ee6ece3f1e6f6c212302dd9ae6065115f02db56ebfda41e |
| S-19-delete-start-failed | desktop | 6236491516 | 39db1bd1b72688e7452c0840771dd65b197fa9404c89fd8dab6236a71222f583 |
| S-19-delete-rate-limited | mobile390 | 6236492974 | d5b7ee691af79ca0cd35e9ce8eaf7d42d73e6a023d354908c1660ee3f2365ebc |
| S-19-delete-rate-limited | desktop | 6236494352 | 98e2f796e0ee198216a88fe286e0d66add02d7d2c0e64bef2d9cb7d979901e52 |
| S-19-delete-code-expired | mobile390 | 6236495841 | 16e2c42225f60b39cb3919953e32adb1984c45f88aa7bb774ab39ebfbd7c97ce |
| S-19-delete-code-expired | desktop | 6236497412 | cf4aa504a46f11c9c4ddbe8adc08722048819dfc8fce86c6b6b19e705538546d |
| S-19-delete-typed | mobile390 | 6236498969 | c50117ab9b69df418aa96b54e3ed2884ad639d3d7e90d6b3de5a816164b96b32 |
| S-19-delete-typed | desktop | 6236499956 | 72e06b248a2d8f67d928ea61a9c9a35dd9cabb687eaffa12ebdd70527b492076 |

## Senior QA corrective pass — 17 October 2026

The independent review of `695ce69a` failed on three blocking S-19 defects.
This correction does not supersede that historical verdict with a QA pass.

- QA-F1: explicit consent/export/recovery retries retain focus on a stable
  heading during pending work, then restore the relevant control or message.
  A user who moves focus elsewhere or leaves the route keeps control; background
  polling does not acquire the explicit action's focus intent. Identical recovery
  failures can be focused again. No navigation delay or timer was added.
- QA-F2: Verify is enabled only with a usable server recovery projection, not
  six digits alone. Uniform `401 recovery_failed` with unavailable/missing
  authority offers Start again; it does not invent an expiry/lock reason. A
  server-projected expiry or lock is shown specifically. A still-usable pending
  projection remains retryable after a wrong code.
- QA-F3: a sanitized, memory-only reauthentication-required notice survives the
  existing auth-transition remount. A deletion `401` is not a connection failure;
  Start again re-enters recovery without automatically resubmitting deletion.

Tests-first evidence: 14 focus regressions failed before the correction; the
recovery/reauth group had four failures and two passing controls; the six-digit
without-authority view test also failed. A negative focus-ownership test caught
and corrected a focus-stealing edge during implementation. Final browser suite:
41/41 pass (real Chromium, synthetic APIs), preserving all 19 original checks.
These developer regressions do not replace the required fresh independent QA.
Private independent evidence and downloaded-hash receipts remain on the ticket.

No CSS, backend, navigation contract, reference, tolerance, evaluator, fixture,
exception binding or enforcement configuration changes are part of this fix.
The existing protected bundle and all historical captures remain unchanged.
Hosted exact-head revalidation and fresh independent Senior QA are required
before owner merge; PR #70 remains Draft.

Additional QA-F3 negative control waits for the remount's recovery-state read
and paint before asserting no contradictory `Identity confirmed` banner.
It failed before the rejection guard and passes afterward: the deletion-proof
rejection keeps the route on reauthentication until Start again, even if the
recovery projection still reports verified. Missing/unavailable verify authority
also cannot reactivate Verify from a stale pending projection. All 41 S-19
browser regressions pass after this guard; no reference or fixture changes.

Hosted inspection of the first corrective run identified two mobile export
rows whose result focus changed the viewport scroll position (job success alone
was not claimed as parity). A regression reproduced the scroll jump. Result
focus now uses `preventScroll` to retain the pending viewport position while
still restoring the semantic focus target. References and exact-image approvals
are not changed to accommodate that implementation defect.

### Focus visibility correction after owner review

The owner rejected the proposed scroll-composition exception. It was never
bound. Functional/accessibility defects remain code fixes, not visual waivers.

The action handlers retain meaningful focus through success and failure. An
additional short-mobile-viewport regression exposed that blanket preventScroll
could leave a failed action's focused recovery notice below the visible fold.
Failed actions now allow native focus scrolling to reveal that notice and its
recovery actions. Successful reads still preserve the user's viewport, including
a successful status response reporting that the server-side export failed; that
status is not a failed Check status transport request. No fixed scroll offset,
capture-specific branch, timer, CSS change or navigation delay was introduced.

RED: the short-viewport notice visibility assertion failed; three repeated-error
focus controls passed. A separate negative control caught unwanted scrolling
for a successfully retrieved terminal status before the distinction was fixed.
GREEN: 47/47 browser regressions, including all original behavior assertions;
2,663 frontend tests pass plus one existing skip; typecheck, lint and build pass.
Consent Try again, Check status, Request again, Dismiss across eight states and
recovery Try again have explicit focus assertions. Repeated failed responses,
held requests, user-moved focus and successful-result scrolling are covered.
The three Senior QA blockers still require fresh independent verification.

All existing exact-image exception entries, references, tolerances, evaluator
and enforcement configuration remain unchanged. Final hosted per-row results
must confirm conformance before the fresh Senior QA handoff is released.

## Senior QA Round 2 follow-up — 18 October 2026

Independent retesting at `f4f23767` confirmed QA-F2 and QA-F3, but found QA-F1
still blocking: first export activation was not covered, background reads
disabled focused actions, and the generic alert effect reclaimed focus on
unrelated updates. The earlier corrective record remains historical, not an
independent pass. All six original Round 2 files were uploaded and downloaded
byte-for-byte; both SVG and PNG previews render in the private Jira record.

This S-19-only correction gives first export activation the same explicit focus
ownership as retries. Moving to another element relinquishes that ownership;
alerts no longer acquire focus merely because state updates. Existing alert
roles and messages remain. Background GETs leave controls enabled and deduplicate
with a manual check. Dismiss invalidates a background result by generation, so
its late response cannot restore a dismissed notice or overwrite a newer
export. Foreground requests retain synchronous duplicate/competing-action
guards. No authentication, recovery authority, routing, CSS or backend changes.

RED: the initial 13 new browser cases produced 12 failures and one passing
control. The expanded suite covers 320/390/1440px initial activation, mobile and
desktop polling success/failure, deliberately moved focus/scroll, consent Space
with an existing export error, recovery retry plus later updates, joining a
background read, and dismiss/new-export isolation. All 47 previous browser
assertions remain. The existing S-19 source test now expects the focus-wrapped
export callback while preserving its visibility/accessibility assertions.

Local validation: 70/70 browser regressions and 2,664 frontend tests pass; trust regressions 40/40 and namespace
policy 21/21 pass. All 50 unchanged capture fixtures execute with zero
serious/critical axe findings and their original evidence labels. This is local
Chromium/synthetic-API evidence, not hosted parity or independent QA.

The protected bundle remains
`305c6832bd6bcf0f7c2442790250ea67e5b7e80961d886651a23ac3dfcb22441`.
Policy, all 50 bound exceptions, references, tolerances, evaluator and
enforcement are byte-unchanged. No new visual exception is proposed. Exact-head
hosted measurement and independent Senior QA Round 3 remain release conditions.

# NYAY-58 — S-11 Revision L interests profile

## Scope and authority

S-11 light mode only. Approved Revision L source SHA-256:
`338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252`.
R2 applies to S-01/S-02/S-06, not this screen. Existing cached references,
tolerances, evaluator, and historical evidence are unchanged. Dark remains NYAY-51.

Base main: `a9da72a61e0e0473d177c3b02a6fc68c90612f3d` (PR #53 merge),
the same tested S-10 tree as `4c911e0addaca36a8aa42e4036fb44c51599c54d`.
NYAY-57 closure is Jira comment 15832.

## Implementation

- Reuse the Revision L profile frame for step 3 with the teal spark, approved
  heading, practice-interest chip anatomy, responsive header and desktop guidance.
- Only `/s-11` leaves the old continuation shell. S-10 frame output is unchanged;
  its two existing presentation regressions remain in the suite.
- Keep server-hydrated interests, actual career-goal options, empty initial
  selections, version-bound mutation, validation/conflict and reauthentication
  handling, authoritative completion, and both existing save destinations.
- No fabricated Aditi Nair identity, preselected interests, prototype goals,
  unconditional Finish/Back navigation, or fake completion.

## Owner-approved test alignment

Approved in the current task: S-11 heading/font/logo census and necessary seals,
all behavioral assertions preserved. S-12 is the unchanged legacy negative control.

Alignment commit: `940e51ae5c5e74a61a248adc881e1447db0a6d01`.
Focused expectation suite RED: 3 failed / 99 passed, then GREEN: 102 passed.
Real Chromium census RED: 1 failed / 7 passed, then GREEN: 8 passed.
The additional S-11 row expands coverage; no existing negative assertion is removed.

Necessary seals:

| File | Old SHA-256 | New SHA-256 |
| --- | --- | --- |
| frontend/scripts/nyay5-profile-browser.mjs | cfdfe5b3c9105bfd32101ba425f1955c6deec00c98bf82cf3220b8a6e2bfe6de | cdd25cab0c46bb897f6071bce6d75e4f110a260676f210ec9f60bcaa1e176525 |
| frontend/scripts/lib/nyay5-profile-browser-contract.test.mjs | bbec26a88f0cb20eb144d5516054a0a37f0ed0f017db1818cd71f2cc6d1eed70 | 5081000b5f42faa01cb5a5bbdfbaddb82d07af55e3f0586021135bc283e3e9bd |

The separate Chromium fixture has no independent seal constant. Only the two
existing seal constants above changed. NYAY-66 protected bundle is byte-identical:
`62fc24976923eec862129dc25449caecd51903753b74d2c338a998132f659020`.
No new integrity approval is needed for this implementation.

## Validation and evidence limitations

- New presentation tests: 4 RED before implementation, then 4 GREEN.
- Initial full frontend: 2,031 passed / 1 existing skipped; typecheck and lint pass.
- Policy suite: 600 passed. The first sandboxed run had three denied `ps` calls;
  rerunning with process inspection available passed without changing tests.
- Local production build passes; workflow policy verifier passes 14 workflows.
- Synthetic browser smoke: 26 checks pass (selection, keyboard, required values,
  focused errors, failed-save retention, version-bound retry and both destinations).
- Local diagnostic captures: mobile 320/360/390 and desktop 1440; no overflow,
  zero serious/critical axe findings. Headings align exactly to cached geometry
  at 390 and 1440. Local macOS pixels are NOT hosted conformance results.
- Hosted results and exact-image exception proposals are pending. Do not mark
  Testing based on report-only/nonconformant rows.

First hosted capture at `3702659ca603c66452b1ae42ea57430312b3a8cf`, run
35215744803, artifact 10494981393: archive SHA-256
`08c34ba0329c11162fc3802ee3e417929833702219c9625cac11b1b95c6aa1a9`,
224/224 entries verified. S-11 report-only rows are NONCONFORMANT (390:
6.305444% counted / 11.022227 mean; desktop: 3.560859% / 6.061021).
All five interest-chip boxes and the heading match reference geometry exactly.
The capture exposed a label baseline and desktop guidance line-height mismatch.
Two further presentation regressions fail before their S-11-only CSS correction
(normal label line height and 1.55 guidance paragraph line height), then pass.
These are corrected, not waived; the next hosted capture must verify them.

Intentional differences requiring scoped owner disposition: real identity/initials,
unselected interests, current single career-goal control/options instead of demo
multi-select goals, existing Save and exit / Finish setup actions, and authoritative
completion indicator. No reference, tolerance, header/heading geometry or a11y waiver.

Independent Claude QA remains pending. Its handoff must cover real-backend
persistence, hydration, validation, error/conflict paths, keyboard, responsive
behavior and accessibility, and distinguish inherited shared-controller findings
(including NYAY-84 P12–P15) from defects introduced here. Physical-device and
screen-reader coverage must be labeled honestly. Attach preview.svg with the
comparison HTML and evidence pack; a presentation derivative is not a new test.

Owner merges every PR. This ticket stays In Progress until the measured verdict,
owner exception approvals where needed, and full CI justify Testing.

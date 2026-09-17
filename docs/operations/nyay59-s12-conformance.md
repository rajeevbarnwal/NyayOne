# NYAY-59 — S-12 Revision L profile completion

## Scope

Light-mode S-12 only, from approved Revision L. R2 governs S-01/S-02/S-06,
not S-12. Base main is `ef28148dadeb9a9ab40fadb55c66488677b867e1`.
Owner merges; PR #55 stays Draft and NYAY-59 stays In Progress until actual
conformance/approved deltas, full CI and the Testing evidence pack are ready.

Implementation `3989b86bdc812c1319680bbdfb469c5a2f51ad02` preserves the
server-authoritative incomplete-profile redirect, identity and institutional-email
status. It supplies the Revision L completion layout and Go to Dashboard /
Review Profile presentation. Tests-first correction
`0abdcf47261bbff5b0bd84c6e7f0070e7f75e0fa` fixes the real 1px Review Profile
icon baseline mismatch; that defect is not waived.

## Owner-approved exact-image exceptions

Read back from the owner account `rajeevbarnwal` on PR #55:

| Row | Comment | Exact approval hash |
| --- | --- | --- |
| mobile390 | [5719285317](https://github.com/rajeevbarnwal/NyayOne/pull/55#issuecomment-5719285317) | `43e00275bf920aa2590b46714d5f6e76dcd1301938057f3ae655ff54e1490d7c` |
| desktop | [5719286192](https://github.com/rajeevbarnwal/NyayOne/pull/55#issuecomment-5719286192) | `1036dc3efd3e9ba13ba145825420d4fa8b87c8425c7dea9f9031f96e1a960ee6` |

Each body is exactly `NYAY66-EXCEPTION <hash>`. The entries in
`frontend/scripts/nyay66-policy.json` bind the reference/live PNG pair, reason,
viewport, light theme, checks and PR number; hosted approval read-back checks
the owner comment. Scope is actual initials/avatar accessible identity and
truthful institutional-email status, not fabricated prototype identity/pending
verification. No geometry, heading, accessibility, navigation or tolerance waiver.
No enforcement-setting, reference or protected evaluator changes.

## Pre-binding hosted measurement and local validation

Run [35253078895](https://github.com/rajeevbarnwal/NyayOne/actions/runs/35253078895),
artifact `10511476877`, head `0abdcf47261bbff5b0bd84c6e7f0070e7f75e0fa`:
archive SHA-256 `728b5e460b2e574cf3222776de2d607c3420c6bf464a342a32fbecb3bc05e0e2`;
224/224 internal hashes verified. These original reports remain unchanged.

| Row | Counted mismatch | RGB mean /255 | Original verdict |
| --- | --- | --- | --- |
| 390x844 | 0.249119% | 0.300830 | NONCONFORMANT, report-only |
| 1440x1024 | 0.055610% | 0.067656 | NONCONFORMANT, report-only |

Both have 820 counted pixels, confined to initials/status text. Common control
and heading boxes match exactly; heading/dashboard/review crops are identical.
Zero serious/critical axe, overflow and console findings. Sixty other executed
rows retain passing dispositions. A post-binding exact-head hosted run is still
required; a report-only workflow success is not a passing S-12 verdict.

Local validation at that product head: 2045 frontend tests pass, one existing
skip; 11 presentation tests; typecheck/lint pass; 35 synthetic browser checks
pass. These are not independent QA, physical-device, screen-reader or real
backend evidence. Protected bundle is byte-identical to base:
`62fc24976923eec862129dc25449caecd51903753b74d2c338a998132f659020`.

## Remaining approvals and handoff

The exception approvals do not authorize the separately requested S-12 sealed
heading/font/logo/action-label test alignment, S-13 legacy negative-control move,
or mechanical fourth-logo inventory/seals. Those remain pending, with every
behavioral assertion to be preserved. Existing CI currently fails those legacy
expectations; no test is weakened or changed without the requested disposition.

The six-file diagnostic pack is staged locally, including preview.svg, PNG,
HTML, results JSON, ZIP and manifest. Text findings are zero; the scanner cannot
automatically clear visual files (16 image-capability errors). The preview was
visually inspected as synthetic/prototype data; explicit upload disposition is
pending. It is not yet attached, and is not a Testing handoff. Final handoff must
include downloaded-hash verification, independent Claude test cases and the
standing preview.svg attachment. Historical evidence stays unchanged.

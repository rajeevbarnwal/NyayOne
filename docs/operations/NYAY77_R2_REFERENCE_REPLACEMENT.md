# Approved R2 full-viewport reference replacement

The owner approved all 42 replacement light-mode reference PNGs after review of
NYAY-77 comment 15484 and attachments 15870–15873. This is reference-content
approval, not self-approval of the resulting NYAY-66 integrity bundle. A fresh
owner top-level `NYAY66-INTEGRITY` PR comment is required before merge.

## Provenance and downloaded-byte verification

- Owner-dispatched calibration run: 34755127479.
- Workflow commit: `162ccf11ddd54879ee5ac8f6b0a065062fdcc9f0` (PR #41 merged).
- Unchanged approved source: `643fb83b7f8316eeca01a020521b97f55856ba08`.
- Artifact: 10316149677; ZIP size: 3,071,391 bytes.
- ZIP SHA-256 (downloaded bytes equal GitHub artifact digest):
  `b57d3af175be25d8ec33b2fe030155125c893f3ef08948d4695d0f9f1b23e773`.
- Manifest SHA-256:
  `84d8791e260ec4460e3babfac80aa2746416c670e9bb58724b3152daa164c0ed`.
- Verified all 44 checksum entries, 42 PNG hashes/dimensions and 126 repeated
  sample hashes. The importer independently recomputed the ZIP digest and
  validated the complete inventory before writing this new cache.
- Chromium 149.0.7827.55, Playwright 1.61.1, Node v22.21.1, Linux x64;
  all 12 font hashes unchanged. Per-PNG hashes are in the new cache's SHA256SUMS
  and manifest.json; provenance.json binds the run and archive.
- Premature run 34753289153 is excluded.

## Owner disposition: not strictly corner-confined

All 42 panels retain matching text, controls and geometry. The owner explicitly
accepts the 30/42 small raw interior anti-aliasing differences and the 12/42
S-06 counted interior differences as rendering artifacts. The latter are confined
to unchanged disabled-button labels (Sending…, Resend code, Verify and continue),
113–248 counted interior pixels per affected panel. No blanket claim of strictly
corner-only changes is made. Full per-PNG counts and locations remain in the
immutable hosted diff report attached to NYAY-77.

## Scope and coverage

The active R2 cache pointer changes from `chromium-149.0.7827.55-r2` to
`chromium-149.0.7827.55-r2-unclipped`. The old R2 cache and Revision L cache remain
byte-for-byte untouched. No application styling, evaluator, tolerances, masking,
pinning, enforcement mode, exception entries or historical evidence changes.

There are still 9 measured entry-state/viewports and 33 explicitly unmeasured
state/viewports. This import does not make report-only screens conformant or
promote any screen. PR #40 must be reevaluated after this PR merges; NYAY-77 stays
In Progress until real conformance and remaining state coverage support Testing.

Jira attachment identity/name/size reconciliation is distinct from the verified
GitHub archive download: downloaded Jira attachment bytes have not been rehashed.

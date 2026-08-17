# NyayOne Option 3.2 provenance

## NyayOne baseline

- Repository: `rajeevbarnwal/NyayOne`
- Baseline branch: `main`
- Baseline commit: `7943d11c153223de2e5f2e6c71699cac0e795e3c`
- Handoff date: 2026-08-17

## Claude visual source

The visual reference was selected from Claude Design Option 3.2. It was reviewed as a visual prototype and not accepted as application behavior.

Imported visual files:

- `visual-reference/NYAYONE_OPTION3_2_VISUAL_REFERENCE_ONLY.html`
- `visual-reference/shot-s05-390.png`
- `visual-reference/shot-s07-profile-popup-390.png`

The selected Claude artifact had SHA-256 `b067931f3c4e73851bba0601eee751a3520d47e33f2d5471ba43d8b5f1a76077`. The privacy-safe imported HTML has SHA-256 `868754498dd565ac12f3a99f11fead825e63bb55c578665b95af4e7c337e06c7` after these bounded transformations:

- 18 em dash characters in nonfunctional wrapper text and comments were normalized to permitted punctuation.
- One trailing-space sequence was removed.
- Eight raw institutional-email fixture occurrences were changed to `student.demo@example.edu`.
- Five full student-name occurrences were changed to `Demo Student`.
- Six remaining given-name occurrences were changed to `Demo`.
- Two abbreviated guardian-name occurrences were changed to `Demo Guardian`.
- Four remaining family-name occurrences were changed to `Student`.
- Two masked institutional-email occurrences were changed to `s•••••t@example.edu`.
- Four occurrences of one mentor fixture name were changed to `Adv. Demo Mentor`.

Layout, components, embedded prototype behavior, and non-identity copy were otherwise unchanged.

`shot-s05-390.png` was regenerated in live Chromium from the privacy-safe HTML at the 390 by 844 mobile setting, then re-encoded without resizing as PNG. The capture shows only the synthetic masked mobile destination already present in the prototype. No reviewer toolbar or source-correlated email fixture is present in the sealed screenshot.

The source prototype called the popup `S-14p`. This handoff renames the screenshot and overrides that mapping. The approved implementation hosts the popup on S-07 and preserves S-14 as the full dashboard.

The prototype source file, stale Option 3.1 map, self-authored measurements, and prototype README were intentionally not imported.

## Brand source

Eight official NyayOne SVG files were copied without redrawing:

- three marks,
- two lockups,
- app icon,
- standard favicon,
- 16 px favicon.

The original brand README was not imported because this handoff contains the current usage rules and typography decision.

## Review findings resolved by this contract

- S-07 and S-14 route ambiguity.
- Hard-coded and non-authoritative profile progress.
- Empty OTP acceptance in prototype logic.
- Fail-open registration consent.
- Demo-only S-10 validation bypass.
- Client-authored guardian and verification presentation.
- Unreliable prototype evidence claims.

These findings are resolved in the contract, not yet in application code.

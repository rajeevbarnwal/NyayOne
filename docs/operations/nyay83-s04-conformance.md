# NYAY-83 — S-04 light Revision L conformance

S-04-only implementation, starting from PR #45 merge
`5d2e64b3dba1e8c7beb8dfc6c381ce39537ee819`. The repository is public;
the owner merges all PRs. Historical evidence and reference files stay unchanged.

## Narrow corrections

- Read the desktop top bar before the brand panel and main content, matching
  their visual order. Other screen call sites are unchanged.
- Use the prototype's visible `Mobile Number` label casing.
- Centre each channel icon and label with the prototype's 7px gap. The CSS rule
  is scoped to S-04; shared channel styling is unchanged.

Tests-first: the initial 11 contracts produced 2 expected failures (DOM order
and field label), then 11 passes. The additional channel-layout contract failed
before the scoped CSS correction, then all 12 passed. Assertions distinguish
server-rendered/source contracts from executable cancellation-helper tests.

## Preserved authentication behavior

Mobile input starts empty. Channel availability is server-projected and
fail-closed; email is enabled only by the existing server projection. Keep
numeric telephone entry, validation, non-enumerating copy, existing OTP endpoints,
and navigation to S-05 after accepted OTP start. Change retires server OTP
authority before returning to S-03 and refuses navigation on cancellation
failure. No browser identity persistence, password mode or new auth feature.

## Reference differences requiring disposition

The original NYAY66 Revision L reference has no Student/Change/English row and
contains an example mobile value. NYAY-8's approved authentication-context
supersession requires that row and an empty field. The context adds 48px plus
the existing 13px form gap: the subsequent form controls move down by 61px.
NYAY-12's server-enabled email projection also changes the mobile helper copy.
These are intentional functional deltas, not permission to remove controls,
populate a real input with a sample, disable email, or modify references.

## Owner-approved narrow correction

Owner approved the S-04-only plain-text legal footer and `Send Code` accessible
name, recorded on NYAY-83 comment 15577. Privacy Notice, Terms and Accessibility
are now inert spans without links, buttons or tab stops. The shared footer's
default is unchanged; only S-03 and S-04 opt into plain text. OTP endpoints,
validation, cancellation, channel projection and navigation are unchanged.

Tests-first product proof: three expected failures / 17 passes before the
correction, then 20/20 passes across S-04 and NYAY-12 contracts. The prior OTP
action assertion is retained with the approved accessible name; inert footer
coverage is additive. Necessary S-04 producer selector updates preserve existing
assertions and retain S-08's distinct `Send one time code` action name. The
previous hosted registration failure was an exact `MOBILE NUMBER` selector
against S-04's approved `Mobile Number` label, not an auth failure; its S-04
selector is aligned without changing the S-08 label expectation.

The unexcepted S-04 gate is **NONCONFORMANT**, not a strict PARITY result. Exact-head
hosted screenshots and numbers must be reviewed before any owner-approved
exception is added. No exceptions, tolerances, evaluator rules, enforced-screen
settings or reference bytes are changed by this implementation. A green
report-only workflow is not sufficient to move NYAY-83 to Testing.

### Owner exception binding

After the narrow correction, the owner approved the two exact-image entries on
PR #47. Their bodies and `rajeevbarnwal` authorship were read back before binding:

- Mobile: comment [5665196346](https://github.com/rajeevbarnwal/NyayOne/pull/47#issuecomment-5665196346),
  `NYAY66-EXCEPTION e923dcafe953eae567879b328cfd9d13845fd3927d81f1ac192e44824f3af9ff`.
- Desktop: comment [5665197698](https://github.com/rajeevbarnwal/NyayOne/pull/47#issuecomment-5665197698),
  `NYAY66-EXCEPTION fae7c5b8bc25eeed1165addf76f044eb955fe78436ea020ff39d737d705ed450`.

`nyay66-policy.json` now contains those exact proposals, with `approvalPr: 47`.
The entries bind reference/live PNG digests and the existing pixels, text,
controls and geometry categories. Comment IDs are recorded here; adding them
to the hashed entries would change the owner's approved payload. This is
category-level approval for the exact image pairs, not a rectangular mask.
Accessibility, overflow, dynamic-region and heading-text checks remain active.
References, tolerances, enforced-screen settings and evaluator code are unchanged.

Disclosed deltas are the retained Student/Change/English context, its 61px
vertical displacement, truthful verified-email helper and empty live identifier
versus the reference sample. Corrected hosted captures at `7c79acb` show these
differences, zero accessibility findings and zero overflow. The expected bound
verdict is PARITY-WITH-DISCLOSED-DELTA, not strict PARITY; it must be verified by
the hosted job at the new binding head before Testing. Source code is unchanged
by the binding commit. The protected integrity bundle excludes exception entries
and remains `d87f89d14e8f56427e1e9e921864c887d193c87f92961186936fba64e5195bb1`.

### Necessary seal transitions

Only these five existing hash constants change in `verify_nyayone_ci.py`;
no policy rule, workflow, required context or unrelated seal changes.

| Existing constant | Old SHA-256 | New SHA-256 |
| --- | --- | --- |
| `EXPECTED_NYAY19_BROWSER_GATE_SHA256` | `9becbdf0e47201eceed8fe36b1311be28a21831c7ffb14d81247b7fd137e89c4` | `f8b547fa696761225a4f4130e42e80656171b05fd42f5713ac06825876c9e0df` |
| `EXPECTED_NYAY5_BROWSER_GATE_SHA256` | `045927b95ab47bec86718d1a6e22d0f7eea164d448b861bf3919ae30060f6e78` | `c3e3a59be8d43ac5944bb3db5a41aee170dcff37b74dbf0ee505e1b8c48d6627` |
| `EXPECTED_NYAY5_BROWSER_CONTRACT_TEST_SHA256` | `797ee22a74559fdca56e8e43a6711227dfb6e979c3fabfc05f3326fbabeed32b` | `b0820c673409b9ac75be5552683617f68783362f45940ad185f6ad4b9fd7e37a` |
| `EXPECTED_NYAY18_BROWSER_GATE_SHA256` | `39850c55d708250e072594825c893bf000d19f84b159d0af53ccb357b18adb67` | `6de1d5540a666f75a19832357ce1658f6491e9252e8b4061edff1a3e3c07133f` |
| `EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_SHA256` | `31d913674781c111d5365cb1fa175b8c0cad73d902cc115673d4b3b52f2a4140` | `1bab1304261d5afaa376d3f2d759ce70ea1ce1f484d9d58248c7c20b03039374` |

Local corrective validation: full frontend 1769 PASS / one inherited skip;
S-04 and NYAY-12 product contracts 20/20; affected producer contracts 194/194;
workflow policy 14/14; policy contracts 44/44; evidence contracts 49/49;
integrity regressions 40/40. Hosted exact-head evidence is recorded additively
on NYAY-83, not inferred from these local results.

## Validation and handoff boundary

Local checks include frontend typecheck/lint/build and the complete frontend
suite, policy/security contracts, workflow/namespace checks and synthetic
browser diagnostics at 390x844, 360x800 and 1440x1024. Same-host macOS reference
renders are diagnostic only, not the pinned Linux hosted gate result. Synthetic
API/emulated-browser checks are not real-backend, physical-device or spoken
screen-reader evidence.

The protected NYAY66 bundle remains byte-identical at
`d87f89d14e8f56427e1e9e921864c887d193c87f92961186936fba64e5195bb1`.
No namespace inventory update is required: the new test file is excluded by
the existing test-source rule; no new production path is added.

Move to Testing only after genuine S-04 conformance or explicit owner-approved
exact-image exceptions. The eventual handoff must include reference/before/after
comparisons, actual gate numbers, accessibility findings, channel and OTP routing,
validation/retry/cancellation and keyboard tests, real mobile-keyboard/backend
cases and explicit coverage gaps. Attach a self-contained `preview.svg` alongside
the HTML sheet (PNG companion where useful), verify downloaded hashes, and
require the same preview attachment for independent Claude QA.

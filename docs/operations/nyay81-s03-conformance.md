# NYAY-81 — S-03 light Revision L conformance

Scope: S-03 only. The approved Revision L source, references, tolerances,
enforcement settings, other screens and historical evidence are unchanged.

## Product correction

- The top bar precedes the brand panel in DOM reading order, matching desktop
  visual order. The existing CSS layout is unchanged.
- The S-03 Privacy Notice link uses regular-weight text, retaining its underline,
  destination, keyboard focus and existing 44px hit target.
- Accessible button names match the visible Revision L labels: `Sign In Securely`
  and `Create Student Account`. Authentication destinations remain S-04/S-08.
- Persona/language behavior, safe return focus and account-deletion notice remain.

## Tests-first proof

The initial four contracts produced two expected failures (reading order and
S-03-only typography) and two passes; the layout correction produced 4/4 PASS.
The two added label/producer contracts then produced two expected failures and
four passes before the label correction. All six are included in the frontend
suite. Existing assertions were not deleted or weakened.

## Owner-approved producer compatibility

Owner approved exactly the accessible-name alignment, corresponding selectors,
and necessary seals during the NYAY-81 implementation conversation; recorded on
NYAY-81 comment 15516.

| File | Old SHA-256 | New SHA-256 |
| --- | --- | --- |
| `frontend/scripts/nyay5-profile-browser.mjs` | `5ec659792697230444aa21b1d59fd93a1b389ad557b82386e13aca921d2db783` | `56e12579d2285dc2b048ae323c4ff09df7201f41fb9f53e88daf4ca2079c8373` |
| `frontend/scripts/v34-s01-s10-e2e.mjs` | `d8954a36161f29cc27d7d90ab49734ebf78cee5e01018e756ee2cc9b399f83db` | `3ba55b8cedb3b3f6586c63eacc3c71cb2700cbeef368166b51b3be2dd36f069e` |

The first producer has four exact selector substitutions; the second has one.
Applying only these substitutions to the original bytes reproduces the new
files exactly: all assertions and execution inventories are unchanged. Only the
NYAY-5 browser-producer constant in `verify_nyayone_ci.py` requires a seal update;
the journey producer has no corresponding sealed constant. No unrelated seals
or verifier rules change.

## Conformance status — not a Testing handoff

Local same-host diagnostic (macOS, Chromium 149.0.7827.55) passes pixel limits:

| Viewport | Counted pixels | RGB mean /255 | axe violations |
| --- | ---: | ---: | ---: |
| 390×844 | 0.046178% | 0.055901 | 0 |
| 1440×1024 | 0.012817% | 0.018583 | 0 |

These are local diagnostics, not hosted pin-parity evidence. The final hosted
artifact must be downloaded and verified at the PR head.

The reference renders legal notices as inert text. The application retains one
working Privacy Notice link on mobile and four legal links on desktop (inline
Privacy Notice, footer Privacy Notice, Terms, Accessibility). These extra
controls cause the current evaluator's `controls` and `geometry` differences.
No exception is self-approved. Exact hosted hashes, screenshots and control
coordinates must be presented for the owner's PR-comment approval before
claiming conformance or moving NYAY-81 to Testing.

## Independent QA scope after conformance approval

Verify Sign In Securely → S-04 and Create Student Account → S-08; neither action
requests an OTP on S-03. Verify persona/language listbox keyboard navigation,
disabled coming-soon options, Escape/refocus, and safe persona return from OTP.
Verify no identity/preferences are newly persisted by this change, all legal
links remain keyboard reachable, and deletion-accepted status survives its
intended single-use handoff. Test responsive layout and accessibility; clearly
distinguish real backend/device/screen-reader checks from mocked/emulated checks.
Do not attribute pre-existing S-04/S-08 defects to S-03 without a causal link.

Owner merges; Draft PR and In Progress remain until the actual gate disposition.

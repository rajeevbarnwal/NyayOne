# NyayOne auth and profile Option 3.2 engineering handoff

Status: approved visual direction, controlled engineering contract, not implemented application code.

Baseline: NyayOne `main` at `7943d11c153223de2e5f2e6c71699cac0e795e3c`.

Date: 2026-08-17.

## Decision

Option 3.2 is approved for its visual direction:

- Aptos, Calibri, Carlito, and system UI heading stack.
- Official NyayOne logo assets.
- Indigo, paper, ink, and restrained gold brand palette.
- Colourful two-tone SVG label and action icons.
- Editorial auth composition on desktop and mobile.
- Shared mobile and verified-email OTP presentation.
- Optional profile completion dialog and persistent profile card.
- Accessible 44 px mobile controls, visible errors, and compact mobile layouts.

Option 3.2 prototype behavior is not approved as application logic. The JavaScript inside the visual reference must not be copied into React or backend code.

## Security non-regression floor

Existing NyayOne security, privacy, ownership, migration, and evidence controls are a non-regression floor. This design handoff cannot weaken them. When two rules differ, the stricter security or privacy rule wins and the conflict must be recorded for review.

## Artifact precedence

After applying the non-regression floor, use this order for design and interaction conflicts:

1. `ENGINEERING_CONTRACT.md`
2. `SCREEN_MAP.md`
3. `ACCEPTANCE_MATRIX.md`
4. `IMPLEMENTATION_PLAN.md`
5. The visual reference HTML

The visual reference controls appearance only. It does not control routing, authentication, authorization, progress, validation, timing, persistence, or security.

## Package contents

- `ENGINEERING_CONTRACT.md`: product, interaction, security, and state rules.
- `SCREEN_MAP.md`: canonical route and overlay mapping.
- `ACCEPTANCE_MATRIX.md`: mandatory implementation and QA outcomes.
- `IMPLEMENTATION_PLAN.md`: bounded delivery sequence.
- `PROVENANCE.md`: baseline, source hashes, exclusions, and privacy-safe transformations.
- `brand/`: official NyayOne SVG assets copied without redrawing.
- `visual-reference/NYAYONE_OPTION3_2_VISUAL_REFERENCE_ONLY.html`: visual review artifact only.
- `visual-reference/README.md`: adjacent warning for known prototype contradictions.
- `visual-reference/shot-s05-390.png`: mobile OTP visual reference.
- `visual-reference/shot-s07-profile-popup-390.png`: mobile post-login dialog visual reference. The source prototype called this `S-14p`; the approved route is an overlay hosted by S-07.
- `SHA256SUMS.txt`: final package integrity manifest.

## Explicitly rejected prototype behaviors

- S-14 as the popup route.
- Hard-coded 67 percent profile completion.
- Empty or malformed OTP acceptance.
- Fixed delays as readiness or success signals.
- Unchecked Terms consent.
- A reviewer-only control that marks invalid fields as corrected.
- Student-authored guardian or institutional verification state.
- Client-only security or completion decisions.
- Navigation after a failed or skipped persistence request.
- Direct implementation of demo state from the prototype HTML.

## Release boundary

This package is ready to guide PR A through PR C2 in `IMPLEMENTATION_PLAN.md`. PR D remains decision-blocked for positive guardian completion until Product and Security approve the authority ceremony. PR E remains disabled until verified-email identity security closes. This package does not certify authentication, email identity, guardian consent, institutional verification, production security, or release readiness. Those outcomes require application code, target-runtime tests, exact-head CI, and independent QA.

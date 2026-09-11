# NYAY-66 progressive visual conformance

## Current stage: calibration, not application parity

The owner approved progressive enforcement in NYAY-66 comment 15380: report all
screens, block regressions on conformant screens, expand the enforced set with
each screen PR. Numeric tolerances still require owner approval. This initial
PR stage runs reference-only calibration; it must not be represented as the
completed or activated conformance gate and must not merge before activation.

Source: unchanged Option 3.2.1 Revision L HTML, SHA-256
`338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252`.
Historical evidence and original SHA labels remain unchanged.

## Measurement

`frontend/scripts/nyay66-calibrate.mjs` creates three independent browser
contexts per reference view and viewport. There are 15 selectable reference
views, 30 view/viewport pairs, 90 PNGs and 60 reference-repeat comparisons.
Viewports are 390×844 and 1440×1024, DPR 1, light, locale en-IN, Asia/Kolkata.
Node is pinned to 22.21.1; npm's existing lock pins Playwright/Chromium.
The job records actual versions and loaded font faces. Reference bytes include
the embedded font resources; external requests fail the capture.

No timed sleeps or retries: wait for the prototype API, fonts, image decoding
and animation frames before capture. Capture errors, missing/duplicate rows,
unknown views, wrong dimensions and malformed metrics fail validation. Output
creation is exclusive, preventing historical-directory overwrite. SHA256SUMS
binds all screenshots and the report; download verification must precede use.

Local repeatability is not cross-host portability or reference/live parity.
Report cross-host differences separately. The proposed live gate will render
reference and application on the same pinned hosted environment. A renderer
or font update requires recalibration, not automatic baseline replacement.

## Activation work remaining after calibration

1. Obtain owner approval for numeric regional pixel tolerances from measurements.
2. Finish the deterministic reference/live producer and independently validate
   structure, text, controls, accessibility and overflow (not hidden by pixels).
3. Validate exact owner-approved exception bindings; no blanket region masks.
4. Identify the initially conformant set from actual measurements, report all
   others explicitly NONCONFORMANT or DESIGN-GAP, and exercise regression tests.
5. Activate progressive enforcement, validate CI, then merge NYAY-66 first.

The pure verdict classifier is unit-tested scaffolding, not a substitute for
steps 2–4. It accepts proof booleans only from a future validated producer.
No live screen has been declared conformant by this calibration stage.

## Exceptions and gaps

NYAY-47 comment 15208 approves exception categories, not arbitrary render-wide
exemptions: email channel, specifically scoped NYAY-8 header supersession,
masked destinations, and S-17 collapsed disclosure. Effective entries need
screen/state/viewport/theme, source revision, implementation binding, exact
element, allowed delta and owner approval provenance. NYAY-48's later S-05
decision remains separate; category approval cannot override it silently.
No executor-generated signature or execution ceremony is introduced.

Seventeen canonical routes plus the S-07 popup are reported. S-10 has two
reference states; S-07 landing shares s14, and its popup uses s14p. S-01/S-02/S-06
have no approved Revision L reference; all dark variants remain DESIGN-GAP.

After gate merge: S-03 → S-04 → S-05, then STOP at S-06 for design inputs.
One screen PR at a time unless a demonstrably shared component requires a
tightly coupled change. Existing conformant screens need proof, not invented
frontend modifications. No screen implementation starts before gate merge.

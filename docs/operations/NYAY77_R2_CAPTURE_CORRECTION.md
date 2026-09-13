# R2 reviewer-frame capture correction

This change affects reference capture only. It removes the reviewer `.vp`
border radius (26px mobile / 8px desktop), retaining viewport dimensions,
scroll behavior and descendant application styles. It does not change product
code, pixel tolerances, enforcement mode, source HTML, imported references,
or historical evidence. PR #40 remains a separate S-01 implementation.

The manual R2 workflow now runs the capture script from its reviewed `control`
checkout, while its working directory and design/font inputs remain the exact
`candidate` source commit. Otherwise dispatching the approved old source head
would keep executing the old capture script. Revision L capture is unchanged.

## Source and workflow digest

- Source head: `643fb83b7f8316eeca01a020521b97f55856ba08`.
- Standalone HTML SHA-256: `3bfdbaac7536d8ceeae660c57286b58f1b03cdc6a53545c458b3bc7636198a07`.
- Calibration workflow SHA-256, old:
  `172371c662b9c6271bfeeae6cacfd30b3ac5c1424075109106fb3adbac83e846`.
- Calibration workflow SHA-256, new:
  `ee80122ee42f3ca254c8123d6c28c736fdb1718dc363b31a9b5d5c7d5a8e662a`.
- Only this workflow allowlist hash changes in the verifier.

## Tests and local rehearsal disclosure

Tests-first: the capture regression initially failed two assertions; the
control/candidate workflow regression initially failed one test. After the
fix: frontend 1,728 passed / 1 skipped; policy 570 passed; all 14 workflows
verified; lint and typecheck passed.

Local Mac and Linux ARM64 Chromium rehearsals compared all 42 state/viewport
pairs. Dimensions and structural measurements stayed identical. **Raw pixel
differences are not confined to corners.** Under the unchanged anti-alias-aware
pixel metric, 30/42 Linux comparisons have zero counted differences outside
corners; the 12 submitting/challenge/wrong/expired S-06 comparisons do not.
These are diagnostic captures, not hosted Linux x64 calibration or import
approval. Do not label this a successful corner-only proof. No masks or
tolerances were changed to conceal these differences.

## Owner-operated sequence

1. Owner approves the exact changed evaluator bundle using a top-level
   `NYAY66-INTEGRITY <digest>` PR comment. Bind only after read-back.
2. CI/review, then owner merges the capture-config PR. No automatic merge.
3. Owner dispatches the standing calibration workflow from merged main:

   ```sh
   gh workflow run nyay66-calibration.yml \
     --repo rajeevbarnwal/NyayOne --ref main \
     -f reference=r2 \
     -f source_head=643fb83b7f8316eeca01a020521b97f55856ba08
   ```

4. Verify the run archive and every PNG against the new manifest; compare all
   42 PNGs with the immutable previous hosted artifact (run 34719114626).
   Report raw and counted changed pixels, corner coordinates/counts, interior
   differences, geometry/text/control differences, dimensions and pins. Any
   interior differences must be disclosed; a corner-only verdict is not assumed.
5. Stop for owner disposition of that actual hosted diff report. Only then open
   a separate reference-import PR and obtain fresh integrity approval including
   the replacement PNG hashes. Keep old evidence and SHA labels intact.
6. After owner merge, refresh PR #40 and complete S-01 state coverage. NYAY-77
   must remain In Progress until actual conformance and the QA handoff are ready.

Jira attachment upload awaits the owner's explicit sign-in confirmation.

# NYAY-66 manual reference calibration

This permanent workflow generates **unimported reference artifacts only**.
It has only `workflow_dispatch`, runs on GitHub-hosted Ubuntu 24.04, grants only
`contents: read`, and does not commit, push, merge or import baselines. Existing
live-conformance jobs, tolerances and enforcement settings are unchanged.

## First installation

GitHub requires a newly dispatched workflow to exist on the default branch.
The owner therefore merges the workflow-only bootstrap PR first. The separate
R2-loader/reference PR supplies the capture script and approved source. No R2
reference or coverage is activated by this bootstrap PR.

## Owner-operated generation

Run from the owner's authenticated Terminal after selecting a reviewed exact
source commit containing the chosen capture adapter:

```sh
gh workflow run nyay66-calibration.yml \
  --repo rajeevbarnwal/NyayOne --ref main \
  -f reference=r2 -f source_head=<EXACT_40_CHARACTER_SOURCE_COMMIT>
```

Use `reference=revl` for the existing Revision L capture adapter. Dispatch is
owner-only and its workflow revision must be `main`. Candidate source is checked
out by the exact input SHA, with no persisted checkout credential. Dependencies
come from the reviewed workflow revision, not from candidate install scripts.

Current immutable runtime pins: Playwright 1.61.1, Chromium 149.0.7827.55,
`linux-x64`, Node 22.21.1. Font files are hashed against the manifest bound by the
reviewed control policy. Any Chromium/Playwright/platform/font mismatch stops
generation. Runtime pins and font hashes are included in the artifact. The R2
source additionally binds all embedded fonts through its exact standalone hash.

## Download, verify, import, approve

1. Owner supplies the run ID; verify successful run, input SHA, workflow revision
   and artifact identity. Download into a new local directory.
2. Verify `SHA256SUMS`, actual PNG digests/dimensions, complete state inventory,
   source digest, runtime pins and repeat-capture results. Generation is not
   evidence that the live application conforms.
3. Use the source-specific hash-validating import script into a new cache;
   never overwrite a historical cache or change historical SHA labels.
4. In a separate owner-reviewed PR, bind the cache manifest in policy and
   compute the evaluator bundle digest, which includes every PNG digest.
5. **Every import needs a fresh owner PR comment:**
   `NYAY66-INTEGRITY <exact-bundle-sha256>`. Read back and bind that comment's
   PR/ID. A successful calibration, source-design approval or old integrity
   comment does not authorize a new import; the existing gate fails closed.
6. Owner merges only after CI and review. A Chromium/font upgrade requires an
   explicit owner-approved pin-update and re-baseline PR, never an automatic
   refresh. Default tolerances and progressive enforcement are not changed.

R2 light content approval: NYAY-50 comment 15422. Dark remains NYAY-51 deferred.
Initial R2 live coverage is three entry states × three viewports. The other
33 state/viewports remain explicitly unmeasured and block screen promotion.

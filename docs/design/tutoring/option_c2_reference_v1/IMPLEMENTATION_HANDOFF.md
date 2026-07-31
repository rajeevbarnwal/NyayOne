# Implementation handoff

**This package changes no production code.** Nothing under `frontend/src` or `backend/` was
touched. The native gates were run to prove exactly that.

## 1. What an implementer may rely on

| Artefact | Use it for | Label |
|---|---|---|
| `STATE_INVENTORY.json` | the authoritative list of 82 states with 13 attributes each | `PRODUCT_APPROVED` ids and screens; `PROPOSED` typed labels |
| `tests/state_inventory_equality.test.mjs` | a CI gate that fails on a missing, duplicate, renamed or extra state | executable |
| `DETERMINISTIC_FIXTURE_CONTRACT.json` | the frozen fixture values and the checksum to assert before any visual comparison | `PRODUCT_APPROVED` |
| `RESPONSIVE_GEOMETRY_BUDGETS.md` + `MEASURED_GEOMETRY_RESULTS.json` | the budgets an implementation must also meet, and the measured proof they are meetable | `BROWSER_MEASURED` |
| `ACCESSIBILITY_AND_INTERACTION_SPEC.md` | roles, names, focus, live regions, non-colour cues | mixed, labelled per section |
| `TOKEN_COMPONENT_MOTION_SPEC.md` | tokens and component contracts | `PRODUCT_APPROVED` tokens |
| `VISUAL_BASELINE_MANIFEST.json` + `captures/` | side-by-side reference baselines with their own SHA-256 | `BROWSER_MEASURED` |
| `NEGATIVE_TEST_RESULTS.md` | 81 executable negative cases with input / expected / actual | `BROWSER_MEASURED` |
| `reference/rules.js` | the client-side validation obligations, as pure functions | `PROPOSED` |

## 2. What an implementer must not do

- Do not copy a typed error identifier marked `(PROPOSED label)` into an API contract. Reconcile
  it in Priority 2 first.
- Do not implement attendance authority (W2-6) or a video-provider seam (W2-9) from this package.
  Both are `PENDING_PRIORITY2_CONTRACT`.
- Do not claim visual parity from a baseline whose fixture checksum differs from
  `d45aa35d5614afe2`, or whose state/viewport/theme triple differs.
- Do not treat `reference/index.html?state=...` as a product route. Product routes are `/s-31`
  … `/s-35`.
- Do not lift `reference/*.js` into the application. It is a reference renderer, not a component
  library: it uses string templating and global objects deliberately so that it stays a single
  offline artefact.

## 3. Order of work suggested for Priority 2

1. Reconcile the typed-error vocabulary and the S-32 composition (D-15, D-16) with Product.
2. Land the route/state skeleton for S-31…S-35 with the 82 state ids as the state machine's
   vocabulary; wire `tests/state_inventory_equality.test.mjs` into CI against the implementation's
   own state list.
3. Port the token layer verbatim, then the component layer.
4. Port the live-room composition **rules first** (§5 of `TOKEN_COMPONENT_MOTION_SPEC.md`), then
   the content. The three grid rules are the load-bearing part.
5. Re-run the geometry budgets against the implementation with the same assertions.

## 4. Native gate results for this branch

Run in `frontend/` on the worktree branch. Recorded verbatim in `NATIVE_GATE_RESULTS.json`.

| Gate | Command | RC |
|---|---|---|
| install | `npm ci` (fell back to `npm install` — see the JSON for which ran) | recorded |
| typecheck | `npm run typecheck` | recorded |
| lint | `npm run lint` | recorded |
| unit tests | `npm run test:run` | recorded |
| build | `npm run build` | recorded |

Priority 1 must not change production frontend behaviour. If a gate reports a pre-existing
production defect it is recorded as a separate Priority 2 finding in `NATIVE_GATE_RESULTS.json`
and is **not** fixed here.

## 5. Reproducing everything

```
cd docs/design/tutoring/option_c2_reference_v1
node tests/state_inventory_equality.test.mjs      # 82-state set equality
node tools/gen_state_inventory.mjs                # regenerate STATE_INVENTORY.json
node tools/measure_before.mjs                     # reproduce the historical defect
node tools/measure.mjs                            # full matrix + captures (real Chromium)
node tools/merge_measurements.mjs <partials-dir>   # if the matrix was sharded
node tools/run_negative_matrix.mjs                # 81 negative cases
node tools/gen_checksums.mjs                      # SHA256SUMS.txt (idempotent)
```

`tools/measure.mjs --units list` prints the 25 work units; `--units 0-5` runs a shard. Sharding
exists only because the execution environment caps a single command at 45 s; the output is
identical either way because the merge sorts deterministically.

Every tool resolves its own paths at runtime: the repository root comes from
`git rev-parse --show-toplevel` (with a structural fallback), playwright from `--playwright`,
`PLAYWRIGHT_MODULE` or `<repo>/frontend/node_modules`, and anything underivable raises a typed
fail-fast error naming the flag and the environment variable. No tool contains a machine path;
`tests/portability.test.mjs` proves the package runs from a foreign directory.

Some Linux/arm64 container images need a `libXdamage` stub for headless Chromium; when that is
the case, prefix the commands with `LD_LIBRARY_PATH=<stublib>`. That is an environment detail,
not a package requirement, and no tool encodes it.

Additional executable gates added for D-1:

```
node tools/measure_live_room_addendum.mjs            # now includes rule 13, the banner content oracle
node tests/banner_geometry_oracle_selftest.mjs       # 3 seeded defects must drive the gate non-zero
node tests/portability.test.mjs                      # package must run from a foreign path
```

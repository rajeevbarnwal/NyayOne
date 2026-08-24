# NYAY-7 tests-first RED baseline

- Recorded: 2026-08-24
- Production build: `VITE_API_BASE_URL=http://127.0.0.1:4174 npm run build`
- Browser gate: `NYAY7_BASE_URL=http://127.0.0.1:4174 NYAY7_EVIDENCE_PATH=/private/tmp/nyay7-red-evidence/results.json npm run qa:nyay7:ui-foundation`
- Evidence SHA-256: `01abef3b511efc58dc62b7d0171b5ef40ef299d9a9d246be93a9154def251540`

The fail-closed inventory was valid: 120/120 assertions executed, with no missing, duplicate, unknown, malformed, skipped, or unexecuted rows. The pre-implementation result was 79 passed and 41 failed:

| Contract | Passed | Failed | RED reason |
| --- | ---: | ---: | --- |
| Mount | 15 | 0 | Existing routes mount correctly. |
| Axe serious/critical | 15 | 0 | Existing screens already have no serious/critical violations. Moderate landmark findings remain visible in diagnostics and are not suppressed. |
| Horizontal overflow | 15 | 0 | No current overflow at the required viewports. |
| Mobile 44px targets | 13 | 2 | S-03 `privacy notice` is 82.13×17px at both mobile viewports. |
| Layout shift | 15 | 0 | Current cumulative layout shift is within 0.1. |
| Revision L token use | 0 | 15 | Existing screens still use the legacy palette and typography. |
| Selector/context contract | 6 | 9 | S-03 lacks the final controls; S-08/S-09 lack carried Student/English context. S-04/S-05 correctly expose no selector authority. |
| Approved visual baseline | 0 | 15 | Existing UI does not match the sealed Revision L captures under the 1% ceiling. |

No GREEN UI component or production screen change was made before this evidence was captured.

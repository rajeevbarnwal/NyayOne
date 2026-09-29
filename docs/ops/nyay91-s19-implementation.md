# S-19 implementation work in progress

S-19 is the next screen after the S-18 merge. This draft begins its state and
projection boundaries; it is **not** a completed screen, measured conformance
result, enforcement promotion, or independent QA handoff. The new state module
is not connected to the production route in this first slice.

## Frozen authority

- Design: v3.2.1.08, `S-19` in `source/continuation-states.json` inside
  `frontend/test-baselines/nyay66/v3.2.1.08/NYAYONE_S01_S35_v3.2.1.08.zip`.
- Canonical ZIP SHA-256:
  `0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`.
- 26 states × mobile390/desktop = 52 source-only S-19 rows. None is claimed as
  measured by this draft. Optional manual-save mode is not the shipped default.
- Backend: `backend/app/api/v1/student_settings.py`,
  `backend/app/services/otp_flow_service.py` and existing frontend typed adapters.

## Initial tests-first slice

`privacySettingsState` defines S-19-only rules for:

- Exact canonical consent inventory; pending drafts separate from confirmed
  values; a newer server version and matching saved consent required before
  announcing success; rollback after failure and reload-gated version conflict.
- Current-visit export references and the five actual server statuses:
  pending, processing, complete, failed and cancelled. A replayed POST can
  return the original request's current status. `complete` does not promise
  an email or a download; `cancelled` does not invent a cancellation endpoint.
- Exact typed DELETE plus a current recovery-purpose verified projection and
  no failed authority read/in-flight submit. The server remains the authority
  and consumes proof at deletion. Its verified projection has a null client
  expiry budget; the UI must not invent one.

The new focused suite was authored before the module (RED: missing module),
then all 59 cases passed. Full frontend matrix: 166 files / 2,600 tests passed;
TypeScript and ESLint passed. These are local unit checks, not live-backend QA
or a visual-gate result.

## Remaining work and approval boundaries

1. Connect the controller and Revision L shell/presentation to `/s-19` with
   focused deletion substates replacing the overview (not appended below it).
   Preserve shared auth transitions and server-authoritative deletion adapter.
   Recovery start → verify → privacy/delete; never recovery/complete.
2. Narrow S-19 browser expectation/census/legacy-negative-control and inventory
   alignment needs owner approval before changing sealed expectations.
3. S-19 hosted PNG calibration requires a narrow extension to the existing
   owner-only manual calibration path. Prepare only after owner approval;
   owner integrity approval, merge and dispatch precede verified import.
4. Disposition transient session/deletion-accepted and optional-manual rows
   explicitly. Do not manufacture delays or mark absent coverage as passing.
5. Hosted measurement, geometry/accessibility corrections, scoped exact-image
   owner exceptions if necessary, independent Claude QA and the six-file
   evidence pack (including `preview.svg`) precede Testing handoff.

Existing evaluator, references, exception approvals, tolerances, and the 74
blocking light rows remain unchanged. S-18's measured/report-only rows retain
their merged disposition. This draft changes no backend or other screen.

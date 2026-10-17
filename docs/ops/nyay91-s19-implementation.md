# S-19 implementation work in progress

S-19 is the next screen after the S-18 merge. This draft begins its state and
projection boundaries; it is **not** a completed screen, measured conformance
result, enforcement promotion, or independent QA handoff. The state module is
now connected to the S-19 route through its own controller and Revision L view.

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

1. Implemented focused deletion substates replacing the overview (not appended
   below it), confirmed consent cache/rollback/conflict reload, and truthful
   export request/status handling. Shared auth transitions and the deletion
   adapter remain unchanged. Recovery start → verify → privacy/delete; never
   recovery/complete. Failed recovery-authority reads still hide confirmation
   and prevent Send/deletion until a fresh valid read.
2. Owner approved narrow S-19 browser/census/inventory alignment on 2026-10-17.
   Legacy negative control moved to unchanged S-20; security assertions stay
   intact. Source-based authority tests follow the extracted controller.
3. Owner approved a separate capture-only calibration prerequisite. It adds
   `s19-v32108` to the existing owner-dispatched path. Owner integrity approval,
   Terminal merge and dispatch precede hash-verified import; no dispatch by Codex.
4. Disposition transient session/deletion-accepted and optional-manual rows
   explicitly. Do not manufacture delays or mark absent coverage as passing.
5. Hosted measurement, geometry/accessibility corrections, scoped exact-image
   owner exceptions if necessary, independent Claude QA and the six-file
   evidence pack (including `preview.svg`) precede Testing handoff.

Existing evaluator, references, exception approvals, tolerances, and the 74
blocking light rows remain unchanged. S-18's measured/report-only rows retain
their merged disposition. This draft changes no backend or other screen.

## 2026-10-17 local validation (not hosted conformance)

- Presentation regression RED before the new view; census RED before S-19 was
  classified Revision L; recovery-authority regression RED before correction.
- Frontend: 167 test files, 2,621 passed, one existing skipped test. Typecheck
  and lint pass. Namespace scan PASS including 17/17 negative controls.
- Real Chromium / synthetic API: 12/12 S-19 tests; independent census fixture:
  22/22. Includes duplicate toggles, version/conflict/reload, malformed 2xx,
  same-component query/hash settlement, export truth, recovery-proof failure
  and focused deletion, focus restoration, 320/390/1440 overflow, 48px targets,
  and zero serious/critical axe on overview/mobile-entry states.
- These do not certify all S-19 states, live backend behavior, physical mobile,
  screen-reader output, hosted pixel parity, or independent Claude QA.

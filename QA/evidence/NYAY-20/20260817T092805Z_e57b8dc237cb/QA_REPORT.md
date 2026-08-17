# NYAY-20 Local Engineering Report

## Verdict

LOCAL ENGINEERING GATES PASS for source commit
`e57b8dc237cb562a3c4de224997c06d9cf226f4b`.

This is not an independent QA verdict, a remote-head result, a security closure
for NYAY-6, or approval for production/external users. NYAY-20 remains In
Progress until the branch is pushed, all required CI succeeds on the exact PR
head, and Claude Code independently verifies the exact remote head.

## Implemented boundary

- Canonical NyayOne application, GitHub, Jira project/board, cookie, storage,
  logger and integration identities.
- Isolated Compose project, database, volume, 1130-1144 host-port plane,
  21500-21549 TURN relay range and 172.29.31.0/24 video subnet.
- Exact GitHub/Jira HTTPS-origin validation, including malformed and non-443
  ports, without echoing supplied credentials.
- NyayOne CI PostgreSQL service identities in all required DB workflows.
- Fail-closed parsed policy and planted oracle tests for identity removal,
  drift, Compose credentials, database-prefix bypasses and added legacy
  services/ports/resources.
- Fresh empty NyayOne database assumption documented for calendar namespaces.
- Historical migrations unchanged; the public-organisation namespace remains a
  documented compatibility exception owned by NYAY-16.

## Results

- Complete backend: 1205 passed, 4 skipped, 0 failed.
- Frontend: 75 test files passed; 706 tests passed and 1 was explicitly
  skipped; typecheck, lint and build passed.
- Runtime policy and 5 seeded policy tests passed.
- Workflow policy: 7 workflows passed.
- Existing evidence manifests: 4 manifests / 302 files passed.
- Rendered root and video Compose contracts passed.
- Runtime dependency lock: 40 applicable pins matched; 2 marker-inapplicable
  packages were explicitly skipped.
- `git diff --check`: passed.

Terminal colour/control sequences, carriage returns and trailing horizontal
whitespace were mechanically removed from `frontend-native.log` before sealing;
the command output text, counts and exit code were retained.

## Explicitly pending

- Push and PR exact-head equality.
- Required GitHub CI on the exact PR head.
- Independent Claude Code PostgreSQL/Chromium/config/privacy rerun.
- Final independent evidence archive and Jira attachment upload.

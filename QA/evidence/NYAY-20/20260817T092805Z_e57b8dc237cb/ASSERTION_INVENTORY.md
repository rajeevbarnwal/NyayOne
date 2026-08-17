# NYAY-20 Assertion Inventory

| Acceptance claim | Executed evidence |
|---|---|
| Default runtime cannot identify as or connect to LegalSaathi | `policy.log`, `backend-full.log`, `compose-isolation.log` |
| Parsed configuration and planted negative canaries fail closed | `policy.log`; backend `test_config.py`; `test_nyayone_runtime_isolation.py` |
| Compose project, host ports, DB, volume and video subnet are isolated | `compose-isolation.log` |
| Health, log, storage, OTP and integration metadata use NyayOne | backend complete suite and runtime policy in `backend-full.log`, `policy.log` |
| No inherited migration file changed | `changed-files.txt`, `PROVENANCE.json` |
| Native backend regression | `backend-full.log` |
| Native frontend regression | `frontend-native.log` |
| Workflow and existing evidence-manifest policies remain valid | `policy.log` |
| Source diff has no whitespace errors | `policy.log` |
| Exact remote-head required CI | PENDING; cannot be claimed by this package |
| Independent exact-head QA | PENDING; cannot be claimed by this package |

All test invocations are non-chunked. Skips are reported rather than counted as
passes. PostgreSQL target-runtime checks remain the responsibility of required
remote CI and independent exact-head QA before Testing.

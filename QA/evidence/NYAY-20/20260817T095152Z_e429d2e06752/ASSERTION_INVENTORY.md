# NYAY-20 CI Remediation Assertion Inventory

| Claim | Evidence |
|---|---|
| Failed CI cause is isolated to the unit-test subprocess environment | `QA_REPORT.md`, `PROVENANCE.json` |
| PostgreSQL stages retain the caller environment and URL | `changed-files.txt`, `ci-remediation.log` |
| Regression oracle pins the explicit test boundary | `changed-files.txt`, targeted 38-test result in `ci-remediation.log` |
| Complete backend remains green | `ci-remediation.log` |
| Runtime/workflow/manifest policies remain green | `ci-remediation.log` |
| No migration changed | `changed-files.txt`, `PROVENANCE.json` |
| New exact-head remote CI | PENDING |
| Independent exact-head QA | PENDING |

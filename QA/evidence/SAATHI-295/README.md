# SAATHI-295 Evidence Skeleton

This directory is a repository-owned location contract. At creation time it
contains **no PASS evidence**. Executors must create raw artifacts under the
paths below for one exact commit and generate `SHA256SUMS.txt` only after all
artifacts are final.

```text
QA/evidence/SAATHI-295/
  provenance/
  api/
  postgres/
  ics/
  privacy/
  playwright/
    s90/
    s91/
    s92/
    s93/
  screenshots/
  regression/
  scope/
  FINAL_QA_REPORT.md
  SHA256SUMS.txt
```

Do not commit secrets or a raw public-feed capability. Token-bearing paths must
be redacted before sealing. Synthetic fixtures are required for screenshots,
traces and raw logs.

## Evidence integrity rules

1. Every artifact names the exact tested commit and runtime.
2. Raw command output includes exit code and stdout/stderr.
3. A blocked tool/runtime is `BLOCKED`, not PASS or N/A.
4. SQLite is supplementary and never substitutes for PostgreSQL constraints or
   concurrency.
5. A deterministic calendar/ICS unit adapter does not substitute for HTTP,
   browser and independent parser proof.
6. Expected counts are never copied into actual-result columns.
7. `SHA256SUMS.txt` is generated after the report and raw evidence are final and
   is verified from the repository root.
8. The template remains a template; the executor copies it to
   `FINAL_QA_REPORT.md` and replaces every placeholder with observed evidence.

## Jira lifecycle

- Development starts: owned child ticket may be In Progress.
- Engineering may transition an owned child In Progress -> Testing only after
  all implementable owned gates pass on the exact pushed commit and raw
  evidence plus remote equality/CI are attached in Jira.
- Independent QA owns Testing -> In Review.
- Any reproduced product, security, privacy, schema or test failure returns the
  affected child to In Progress with the failing test input, expected result,
  actual result, artifact path and commit.
- SAATHI-285 and SAATHI-290 dependencies must be reconciled before SAATHI-295
  can be promoted as a complete vertical slice.
- A target-runtime or access block does not justify promotion.
- PO owns In Review -> Done.

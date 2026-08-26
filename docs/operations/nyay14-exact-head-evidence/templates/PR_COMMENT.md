## Independent QA evidence — exact head

- Reviewed head: `FULL_40_CHARACTER_HEAD_SHA`
- Evidence archive: `JIRA_OR_DURABLE_EVIDENCE_LOCATION`
- Archive SHA-256: `FULL_64_CHARACTER_SHA256`
- Manifest SHA-256: `FULL_64_CHARACTER_SHA256`
- Validated package SHA-256: `FULL_64_CHARACTER_SHA256`
- Limitations: `none` or an explicit semicolon-separated list
- Verdict: **PASS | FAIL | BLOCKED | HEAD_CHANGED | handoff-only**

The verdict was produced by `scripts/ci/nyay14_evidence_gate.py`. A PASS is
merge-eligible only after an independent authoritative remote-head read-back
still matches the reviewed head.

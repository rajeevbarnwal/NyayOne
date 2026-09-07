## Jira

- Ticket: NYAY-

## Summary


## Testing


## Notes

## Exact-head QA evidence

- Reviewed head (full SHA):
- Base SHA:
- Prospective merge SHA:
- Independent reviewer / separate execution identity / run ID:
- Verdict (PASS / FAIL / BLOCKED / HEAD_CHANGED / handoff-only):
- Manifest SHA-256 and raw-artifact inventory:
- Contact sheet + rendered-text sidecar digests / Jira attachment IDs:
- Required check URLs (exact reviewed head; seven existing contexts):
- Known risks / limitations / skipped or missing assertions:
- NYAY-40 seeded failure-digest coverage and privacy read-back:

NYAY-13 observation is not independent approval or merge authorization. Until
separate owner-approved promotion, retain manual independent QA. Head changes
invalidate the attestation; never relabel historical evidence as a new run.
Before merge, read back the exact head and closed review state; use the guarded
merge rail without bypass. After merge, record the exact merge SHA, ancestry,
main-push run/check URLs and protected-checkout verification in the closure.


# Sprint 4 evidence hardening

Scope: NYAY-24, NYAY-25, NYAY-31, NYAY-35, NYAY-36 and authorization-header hygiene.
This changes QA infrastructure only. Historical packages and risk-disposition
records remain immutable; new evidence records the remediated behavior.

## Enforced boundaries

- NYAY-24: C0/C1 controls (including DEL) in file/directory/ZIP member paths,
  including percent-decoded variants, produce opaque diagnostics.
- NYAY-25: percent-decoded query values are re-parsed for nested fields. Both
  decoding and nested-field traversal are bounded at eight passes/levels;
  exceeding either bound denies acceptance. Sensitive values are not echoed.
- NYAY-31: `wave2_aggregate_privacy_contract.json` defines a closed-world A6.4
  aggregate projection, bound to the SHA-256 of `wave2_postgres_gate.py`.
  `scan_evidence.project_wave2_aggregate(raw_bytes)` extracts exactly one
  `reviews_for_session` strict nonnegative integer and records the raw source
  digest. It drops runtime actor, session, PID and worker payloads. The raw
  source is retained privately; its hash is recorded, never silently rewritten.
  Duplicate JSON keys, unknown fields, mismatched producer/row, non-integers,
  strings, PII and credentials cannot be accepted as the projection. A boolean
  is not a count. This permits the projection, **not** the full raw Wave-2 report,
  and does not independently attest producer PASS. Original assertion inventory
  and producer gates are unchanged. Unrelated/uncontracted evidence continues
  through the ordinary scanner. Future inclusion of the corrected projection
  in NYAY-9 evidence still requires independent verification.
- NYAY-35: pre-validation CLI refusal results use authoritative v2 schema,
  `declaredSchemaVersion: null` when no declaration was safely read, FAIL and
  `mergeAuthorized: false`. Full validation retains actual declarations solely
  as diagnostics and preserves historical v1 authorization rules.
- NYAY-36: the downgrade-refusal negative test asserts absence of the exact
  requested `archive.tar.gz`, alongside report, manifest and package-record
  paths. The forged-scanner subcase already used matching paths and is retained.
  A planted-output probe proves that the corrected oracle catches a file at the
  requested path; it does not imply the real gate creates unauthorized outputs.
- Header hygiene: accepted RED assertions remain enforced after GREEN; their
  header now reflects that state. The header oracle scans tracked working files
  before commit and CI's checked-out files after commit. An explicit immutable
  ref override remains available to reproduce the original stale-header RED.

## Validation

`test_sprint4_hardening_red.py`: 17 baseline methods (14 formerly failing, 3
preservation checks). `test_sprint4_hardening_adversarial.py`: closed-schema,
control-path, nested-field, exact projection, CI-wiring and seeded mutant probes.
Both are mandatory policy-workflow commands. Removing either fails verification.
Seeded A06/C18 fix-removal probes recreate the original gaps; these are fresh
regression proofs, not edits to historical waived matrices or a claim of having
rerun every historical Phase 1 mutant.

Run both files with Python 3.12 and `PYTHONDONTWRITEBYTECODE=1`, followed by the
NYAY-14 security/historical, evidence/privacy and full policy suites. Publication
requires a new exact-head evidence package and rendered contact sheet with
downloaded attachment hash verification. Merge remains owner-executed through
the guarded rail; NYAY-21 remains HOLD/NO-GO.

## Legitimate reseals

| Source | Previous SHA-256 | Updated SHA-256 | Reason |
| --- | --- | --- | --- |
| NYAY-14 gate | 00311af5cf3a3a7d1bdf840e468ca3259e27f712d0c73d35935a8248a88208ff | 50975750724f0e80e6fb5f9e642df14d004f0ce750c2b7f1989169409097b218 | Refusal-schema diagnostics only |
| NYAY-14 security tests | 6a1a61f45013bfe98518ad246d67079f1d4be49b57916a7329acfbda8befe5f3 | ff5453339d848797b75c2a575807ca56d6c06b7b3c0bcc6e88507324ff2b9ca5 | Exact requested output-path oracle |
| Privacy scanner | 4798a1357a386deb4b6b3ef9c08b85e1b3a4598de35b0d0789e4c318817bea92 | 4af6f5924601e86e56ca2a3f5c03ec37d697bbfaba3f57c2445d48151e84fdd4 | Control paths, nested fields, strict aggregate projection |
| Policy job semantic hash | 096febd2f1fc8ae43aa5688dc01c29d4f1c1049c3ef6ec2905d19e899463366e | 6b87b79d8b4ec9e3ae5dee6b38a4dd268fdc61f76d6ef4a171c087c56d547c00 | Two required hardening test commands |

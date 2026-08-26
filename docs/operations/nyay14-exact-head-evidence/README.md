# NYAY-14 exact-head QA evidence gate

This package defines the reusable, fail-closed evidence contract for an
independent QA review. It binds every verdict to one exact remote head and keeps
the protected Desktop checkout outside the execution boundary.

## Verdicts

The only valid classifications are `PASS`, `FAIL`, `BLOCKED`, `HEAD_CHANGED`,
and `handoff-only`. Their precedence is:

1. `HEAD_CHANGED`
2. `FAIL`
3. `BLOCKED`
4. `handoff-only`
5. `PASS`

`PASS` is impossible when a required raw-log category or assertion group is
missing, when any executed count is zero, when a metric lacks raw-artifact
lineage, when privacy scanning fails, or when the manifest/archive inventory is
not exact.

## Required evidence

- Provenance: repository, base, reviewed remote head, prospective merge, capture
  time, and runtime/tool versions.
- Raw logs: backend, PostgreSQL migration, PostgreSQL concurrency, frontend
  native, and Chromium.
- Visual matrix: screen, state, viewport, approved reference, exact tested head,
  baseline/live/comparison artifact identifiers, and executed metric.
- Quality results: accessibility, privacy/PII, credentials, and seeded-oracle
  execution.
- Independent read-backs for the exact remote head and exact merge commit.
- An independently supplied repository, base, prospective merge, approved visual
  matrix, and protected-checkout root; package-supplied copies are not authority.
- Explicit limitations, including `none` when there are no limitations.

Use the JSON and Markdown files under `templates/` to assemble the package. Raw
evidence and generated archives must remain outside `QA/evidence/**`; that tree
has an independent frozen inventory.

The validated canonical package is written as `VALIDATED_PACKAGE.json` inside
the evidence root before sealing. Its SHA-256 is recorded in the validation
report, manifest, and archive, so provenance and result claims cannot be
detached from their raw artifacts. Package, approved-matrix, report, and archive
paths must be distinct and outside the declared protected checkout. Existing
output files are never replaced.

Every sealing entry point performs the privacy scan itself and verifies that
the source tree is byte-for-byte stable before and after manifest/archive
creation. Archives must contain one gzip stream, cannot contain another archive
under either a known suffix or a recognized archive structure, and must embed
the exact manifest and validated-package digests reported by the gate. JSON is
strict RFC-compatible JSON; `NaN` and infinities are rejected.

## Commands

Run the contract oracle:

```bash
python scripts/ci/test_nyay14_evidence_gate.py
python scripts/ci/test_nyay14_evidence_gate_security.py
```

Validate an evidence package against the authoritative remote head:

```bash
python scripts/ci/nyay14_evidence_gate.py validate \
  --package /absolute/run/package.json \
  --evidence-root /absolute/run/evidence \
  --authoritative-repository owner/private-repository \
  --authoritative-base 0000000000000000000000000000000000000000 \
  --authoritative-remote-head 0123456789abcdef0123456789abcdef01234567 \
  --authoritative-prospective-merge 2222222222222222222222222222222222222222 \
  --approved-visual-matrix /absolute/input/approved-visual-matrix.json \
  --protected-root /absolute/protected/checkout \
  --execution-root /absolute/isolated/worktree \
  --report /absolute/run/VALIDATION_REPORT.json \
  --archive /absolute/run/evidence.tar.gz
```

Exit codes are `0` for `PASS`, `1` for `FAIL`, `2` for `BLOCKED`, `3` for
`HEAD_CHANGED`, and `4` for `handoff-only`. A non-PASS validation never creates
the report, manifest, archive, or merge authorization.

The manifest and archive operations can also be executed independently:

```bash
python scripts/ci/nyay14_evidence_gate.py manifest \
  --evidence-root /absolute/evidence --protected-root /absolute/protected/checkout
python scripts/ci/nyay14_evidence_gate.py verify-manifest --evidence-root /absolute/evidence
python scripts/ci/nyay14_evidence_gate.py build-archive \
  --evidence-root /absolute/evidence --archive /absolute/evidence.tar.gz \
  --protected-root /absolute/protected/checkout
python scripts/ci/nyay14_evidence_gate.py verify-archive --archive /absolute/evidence.tar.gz
```

Protected-checkout operation evidence is deliberately narrow. The accepted
direct, read-only commands are `git status --porcelain=v1 -z`, `git rev-parse
HEAD`, and `git rev-parse --show-toplevel`. Shell wrappers, Git configuration
overrides, output options, and all other command shapes fail closed.

Never use a package-supplied head as the authoritative value. Read the remote PR
head independently immediately before validation. If it differs, preserve the
evidence and return `HEAD_CHANGED`; do not regenerate it under the new head.
The same rule applies to repository identity, base, prospective merge, and the
approved visual matrix: obtain each outside the package and provide it through
the dedicated command-line argument.

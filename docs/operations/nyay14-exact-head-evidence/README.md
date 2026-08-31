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
  --authoritative-evidence-schema-version nyay14-evidence/v2 \
  --authoritative-source-archive-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --authoritative-ticket-type non-ui \
  --authoritative-contact-sheet-panel-role classification-matrix \
  --authoritative-contact-sheet-panel-role guarded-merge-checklist \
  --authoritative-contact-sheet-panel-role pr-comment-template \
  --protected-root /absolute/protected/checkout \
  --execution-root /absolute/isolated/worktree \
  --report /absolute/run/VALIDATION_REPORT.json \
  --archive /absolute/run/evidence.tar.gz
```

Version 2 requires a combined contact sheet. UI tickets use the ordered
`approved-baseline:left` / `live-implementation:right` design-parity pair.
Non-UI tickets use `rendered-evidence` with the independently approved panel
roles supplied on the command line. The sheet binds the reviewed head and an
already sealed source-archive digest; the final evidence envelope then binds
the source archive, sheet, and privacy-clean rendered-text sidecar. This
two-stage construction avoids a self-referential final-archive digest.

The PNG container is closed-world: it may contain only one `IHDR`, contiguous
`IDAT` data, and one terminal `IEND`, with no metadata or ancillary chunks and
no trailing bytes. The rendered-text sidecar is therefore the only textual
representation of the pixels. It must be manifest-bound, name the repository
privacy scanner and its version, and repeat the exact sheet digest, source
archive digest, reviewed head, panel count, and ordered panel roles in both its
structured `contentBindings` and its scanned text. Every panel also names a
manifested raw-log or evidence-artifact source. A missing, empty, mismatched,
or privacy-positive sidecar fails closed with redacted diagnostic codes only.
The scanned text uses exact binding lines:

```text
sheetSha256=<64-lowercase-hex>
sourceArchiveSha256=<64-lowercase-hex>
reviewedHead=<40-lowercase-git-sha>
panelCount=<positive-integer>
panelRoles=<ordered,comma-separated,roles>
```

The command line defaults to v2. A package cannot select v1 or backdate its own
timestamp to avoid the contact-sheet boundary. Re-validating an immutable v1
record requires both explicit `--authoritative-evidence-schema-version
nyay14-evidence/v1` and the exact external file seal through
`--historical-v1-package-sha256`; a mismatch fails with
`HISTORICAL_SEAL_MISMATCH`.

The v2 contract also records the exact primary seals for the six immutable
pre-enforcement evidence records (NYAY-7, NYAY-9, NYAY-14, NYAY-21, NYAY-28,
and NYAY-29). Only NYAY-9 contains a literal NYAY-14 v1
`VALIDATED_PACKAGE.json`; the other five are earlier sealed evidence records
whose archive or contact-sheet seal is preserved without relabelling their
historical format. None is regenerated or made subject to the v2 sheet rule.

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

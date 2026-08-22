# NYAY-19 reconstruction provenance

`scripts/provenance/nyay19_replay_audit.py` is the durable reconstruction
auditor. Its v1 oracle is
`scripts/provenance/specs/nyay19-reconstruction-v1.json`.

The auditor accepts seven local ledgers by stable alias. Paths are runtime
bindings and never enter source control or the report. For the patch-apply
source-mutation channel, it streams JSONL, globally de-duplicates successful
`patch_apply_end` records by call ID before the strict time/root filter,
rejects conflicting duplicates, sorts by timestamp/call ID, and replays every
unified diff with
`git apply --unidiff-zero --whitespace=nowarn` before applying any move.
Additions are converted from the recorded patch content into an equivalent Git
patch. Final snapshots are neither accepted nor used.

That is a complete claim only for successful patch-apply events in the exact
seven SHA-256-pinned ledger files, strict timestamp window, and recorded source
root. It is not a blanket claim that every possible filesystem mutation is a
patch-apply event.

Independent QA supplies its own local paths:

```bash
python scripts/provenance/nyay19_replay_audit.py \
  --ledger canonical-1=/local/path/to/canonical-1.jsonl \
  --ledger canonical-2=/local/path/to/canonical-2.jsonl \
  --ledger canonical-3=/local/path/to/canonical-3.jsonl \
  --ledger postgres-gate=/local/path/to/postgres-gate.jsonl \
  --ledger head-compat=/local/path/to/head-compat.jsonl \
  --ledger browser=/local/path/to/browser.jsonl \
  --ledger ci-policy=/local/path/to/ci-policy.jsonl \
  --audit-non-apply-mutators \
  --replay-repo /local/path/to/NyayOne \
  --output test-results/nyay19-provenance/summary.json
```

`--replay-repo` is read only. The exact parent is fetched into a newly created
temporary Git repository; the supplied checkout, its index, and its refs are
never modified. Before replay, the auditor also requires the spec's
`reconstructed_commit` to exist in that repository and verifies that it has
exactly one parent, that the parent is the specified NYAY-19 parent, that its
tree is the specified reconstructed tree, and that its subject is exactly
`[NYAY-19] Enforce authentication retention lifecycle`.

Reports contain aliases, hashes, counts, tree/stat results and the claim
boundary only—never ledger paths, command bodies, diffs, messages, exception
strings, credentials, or source-thread identifiers.

## Separate non-apply mutator audit

`--audit-non-apply-mutators` performs a second, aggregate audit over the same
seven pinned ledgers and strict window. It globally de-duplicates every
dispatched `custom_tool_call` for the command wrapper before filtering when
the record has a valid call ID and input. Outcome is deliberately not an
inclusion condition: completed, failed, errored, aborted, cancelled,
in-progress, missing-status, and unknown-status dispatches are all retained
because a process may mutate before failing or being aborted.

The pinned corpus reconciles 1,194 command-capable envelopes, containing 1,184
nested `exec_command` and 76 nested `write_stdin` invocations, and binds their
inputs and statuses to command-stream SHA-256
`9917c4547b6f757300544db61013a46e8bde77bab576c6ebfce44089955ccbe3`.
Envelope and nested-invocation counts are different units: one wrapper
envelope can dispatch multiple commands, while a polling envelope can contain
`write_stdin` without `exec_command`, so 1,184 + 76 is not expected to equal
1,194. All 1,194 records in this pinned corpus have outer status `completed`;
the other seven status categories are exactly zero. Nested command exit codes
do not redefine the recorded outer-tool status. The report exposes only
aggregate counts and the digest.

The fresh review found two explicit repository-state envelopes (`git add` and
the recorded commit), seven explicit file-mutator envelopes limited to
disposable SQLite files under the temporary workspace, and zero non-apply
source-tree content mutators. This classification is a review attestation over
the exact pinned command stream, not a claim that static marker matching can
prove the semantics of arbitrary shell or program execution. Any ledger hash,
command-stream digest, source split, or marker count drift fails closed and
requires a new review.

The v1 oracle requires 362 events, 402 changes, 63 paths, 16 additions, 386
updates, no deletes/moves/conflicts, reconstructed tree
`e2b56d285ff6bad437bafaa2a25736fbf43bcf9c`, and exact 63-file
`+17655/-204` Git statistics. Synthetic engine tests are:

```bash
python -m unittest scripts.provenance.test_nyay19_replay_audit
```

The historical transcript proves only original prefix `d374619`, exact parent,
subject, statistics/modes, and the complete patch-apply ledger within the scope
above. The locally reconstructed commit object is separately verified as
`d3746191a5ea7da575cc0139779d6dc506bc2e7d` with tree
`e2b56d285ff6bad437bafaa2a25736fbf43bcf9c`; that does not convert it into proof
of the unknown original object. Original full commit SHA, original tree SHA,
and original author/committer metadata were never recorded and remain
`UNKNOWN_NOT_CLAIMED`.

# NYAY-40 — privacy-safe producer failure diagnostics

Scope: the shared attestation exporter adds diagnostics for a complete failed
Wave-1 browser inventory. Wave-3 and NYAY-5 exports remain unchanged. Neither the
producer's assertion inventory nor any acceptance threshold changes.

## Projection and privacy boundary

The exporter reads the same stable, bounded JSON snapshot already used for its
aggregate attestation. A failed Wave-1 inventory must match all 1,467 reviewed
assertion identities. Missing, duplicate, or substituted identities cannot be
published as trustworthy diagnostic IDs. Failed rows must contain both expected
and actual fields. No raw values, screenshots, filenames, or free-form details
are copied into the attestation.

Each diagnostic row contains the repository-owned assertion ID, its screen ID
(or `not-screen-specific` for runtime-wide assertions), and expected/actual
HMAC-SHA256 digests. The key is generated independently for each export and
discarded, never sealed or uploaded. This deliberately prevents dictionary
recovery of low-entropy private values and cross-run linkage. Digests support
within-export equality/difference, **not reconstruction or independent replay of
raw values**. They must not be represented as plain SHA-256 hashes of content.

Failed diagnostic exports declare `nyayone-evidence-attestation-v2`; existing
aggregate-only and historical v1 exports retain their original interpretation.
The new v2 schema requires the exact diagnostic row count, bounded IDs, derived
screen IDs, and two 64-hex digests. The existing manifest seal, privacy scan,
inventory re-verification, schema check, and conditional upload all remain
mandatory. A valid failed export continues to fail `--require-pass`.

## Tests and historical Linux disposition

The tests seed a failure, substituted ID, missing comparison field, malformed
read-back digest, and private comparison value. They verify non-linkability,
privacy scanning, and the existing failure-upload conditions. One existing
failed-result fixture now supplies expected/actual fields; its FAIL assertion
is preserved.

The historical producer baseline is
`1432a747573d64fda56e5001298f79554a5a03c4`. This change is a diagnostic overlay,
not a retrospective claim that the old run contained these diagnostics. The
Linux producer observation must bind its overlay head separately and verify
that frontend, backend, and the Wave-1 producer/workflow are byte-identical to
that baseline. No blind rerun is authorized. A green observation supports only
`single-occurrence / variance-consistent`, not proof of the unknown original
assertion. A failing observation requires classification and separate authority
before correction. That first observation failed `functional_runtime` and did
not establish historical variance. The owner subsequently authorized the
following enrichment and bounded classification tree.

## Runtime enrichment

The Wave-1 collector retains no message body, exception message, query string,
raw asset name, request identifier or host. It projects events immediately to a
closed diagnostic vocabulary: console, page, request-failed, HTTP, unmatched-API;
canonical route templates; bounded HTTP status/method; and a fixed network-error
code vocabulary with an `OTHER` fallback. This vocabulary does **not** exempt any
error: every event remains in the original array and the original zero-error
assertion is byte-for-byte unchanged. Unknown routes become `unclassified-route`.

On `functional_runtime` failure, export all five categories with counts and
grouped template rows. Strict type/schema checks reject extra fields, raw routes,
boolean counts and inconsistent totals. A separate ephemeral HMAC binds the
projection, using the same discarded per-export key as expected/actual hashes.
Historical v2 rows without enrichment remain readable; this is not retroactive
evidence enrichment. The producer collector is now intentionally changed, while
product code remains historical-main content.

The first enriched Linux run determines next steps: harness/fixture/preview
defects permit a narrow tests-first correction; product defects require a stop
and separate authorization; no recurrence requires exactly one additional run
at the settled head and remains an environment-conditional open risk if silent.
No runtime error allowlisting, blind retry, or quarantine change is permitted.

## Policy seal

Adding the diagnostic contract command is the only policy-job semantic delta.
The corresponding semantic seal changes from
`6b87b79d8b4ec9e3ae5dee6b38a4dd268fdc61f76d6ef4a171c087c56d547c00` to
`a71b647eca26aaba7923a029979a1bbe57b7ff24ff720e7615dbea1d2b0c4da5`.
No scanner seal, threshold, required check, or quarantine posture changes.

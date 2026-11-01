# SSH remote recognition in publication scans

The evidence scanner distinguishes conventional Git SSH service identities from
personal email addresses without skipping the rest of a document or remote.
It recognizes a conservative subset of complete, unencoded remotes:

- `git@github.com:sample/repository.git` (SCP-like syntax).
- `ssh://git@github.com/sample/repository.git` (SSH URL syntax).
- Other canonical DNS hosts with the literal service username `git`, optional
  valid SSH URL ports, and at least two safe repository path segments.

Only the matching `git@host` span avoids the generic email finding. All credential
patterns still run over the original bytes. Host and repository path must also
pass the existing sensitive-path checks. Paths with encoding, traversal,
queries/fragments or unsupported characters do not qualify. Unsupported syntax
can still produce a conservative false positive; this is not a Git URL parser.

The bare text `git@github.com` is ambiguous and remains an email finding. The
documented form `SSH remote git@github.com` (including a colon or quoted identity)
is recognized only with that explicit SSH-remote context on the same line.
Only spaces or tabs may separate the label from the optional opening quote and
identity. A strict end anchor prevents a label on the previous line from
qualifying; a line ending after the identity remains valid. This does not exempt
other GitHub emails or other bare identities. Email, credential and other
sensitive structured fields remain checked even if their value resembles a
remote. Filesystem and ZIP member paths never receive SSH exemptions.

Percent-decoded URL/form values do not gain an SSH exemption. Explicit `ssh://`
URLs join HTTP URLs in the existing bounded percent-decoding checks so encoded
identities and embedded leaks cannot hide behind the new recognition rule.
ZIP content/comments and declared base64 payloads continue through the same
scanner; adjacent PII or credentials still fail, with opaque diagnostic labels.
Visual formats, unknown binaries, archives, input limits, synthetic-domain rules,
redaction rules and all other fail-closed checks are unchanged.

## Verification

`python3 scripts/ci/test_evidence_policy.py SshRemotePrivacyTests` covers canonical
remotes, the contextual identity, personal-email and host/userinfo lookalikes,
encoded/malformed remotes, sensitive fields/paths, mixed leaks, containers and
CLI status/output. The original scanner, policy, evidence-gate and hardening
suites also remain required. The scanner source seal is updated mechanically;
source-drift rejection stays active. No visual gate bundle, reference, tolerance,
exception or product code changes are part of this fix.

Historical scan results and evidence remain immutable. A historical SSH false
positive is not retroactively relabelled as a clean scan. Independent QA must
compare base and head using new synthetic evidence and record its own verdict.

The contextual lookup uses a bounded search on the original byte buffer, rather
than slicing it. This preserves the word boundary before `SSH` even at the
80-byte window edge: a prefixed word such as `XSSH` cannot become valid context
through truncation. Distant context still does not qualify.

Email candidates are located around literal `@` bytes before the unchanged
`EMAIL` expression checks them against the original buffer. This avoids repeated
suffix searches through long slash-separated paths without changing email
syntax, match boundaries, synthetic-domain handling or other privacy rules.
Regression coverage compares exact matches with the frozen expression and scans
a megabyte of long remotes, both clean and with appended email/OTP canaries.

"""Independent QA policy core and non-authorizing signed-review observation CLI.

validate_review consumes facts from a trusted adapter, NOT package JSON. The
standalone CLI cannot authorize or execute a merge, even on a valid signature.
Promotion requires separately administered trust and publication, not a flag.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

REPOSITORY = "rajeevbarnwal/NyayOne"
ISSUER = "trusted-independent-publisher"
RAW = {"backend", "postgresql-migration", "postgresql-concurrency", "frontend-native", "chromium"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _match(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _object(value):
    return value if type(value) is dict else {}


def _inventory(value):
    return (type(value) is list and bool(value) and
            all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", v)
                and all(part not in (".", "..") for part in v.split("/")) for v in value)
            and len(set(value)) == len(value))


def validate_review(evidence, facts):
    """Policy decision over independently authenticated/acquired adapter facts.

    Callers must not expose this function as a JSON-in/approval-out endpoint.
    CLI observation is deliberately non-authorizing regardless of this result.
    """
    e, f = _object(evidence), _object(facts)
    codes = []

    def require(ok, code):
        if not ok:
            codes.append(code)

    require(bool(e) and bool(f), "INPUT_MISSING")
    require(e.get("repository") == f.get("repository") == REPOSITORY, "REPOSITORY_MISMATCH")
    require(f.get("visibility") == "PRIVATE", "REPOSITORY_NOT_PRIVATE")
    require(f.get("acquisitionTrusted") is True, "UNTRUSTED_READBACK")
    for key, remote, code in (("reviewedHead", "remoteHead", "HEAD_CHANGED"),
                              ("base", "base", "BASE_CHANGED"),
                              ("prospectiveMerge", "prospectiveMerge", "PROSPECTIVE_MERGE_CHANGED")):
        require(_match(SHA, e.get(key)) and e.get(key) == f.get(remote), code)
    trust = _object(f.get("trust"))
    require(trust.get("issuer") == ISSUER, "UNTRUSTED_ISSUER")
    for key in ("reviewer", "implementer"):
        require(_match(IDENTITY, e.get(key)) and e.get(key) == trust.get(key), "IDENTITY_MISMATCH")
    require(e.get("reviewer") != e.get("implementer"), "SELF_CERTIFICATION")
    for key in ("signatureVerified", "signedPayloadMatches", "separateExecutionIdentity"):
        require(trust.get(key) is True, "TRUST_" + key.upper())
    for key in ("revoked", "expired", "implementationCanWriteTrust"):
        require(trust.get(key) is False, "TRUST_" + key.upper())
    require(_match(IDENTITY, e.get("runId")), "RUN_ID_INVALID")
    require(e.get("verdict") == "PASS", "QA_NOT_PASS")
    require(type(e.get("limitations")) is list and
            all(_match(IDENTITY, item) for item in e["limitations"]), "LIMITATIONS_INVALID")
    raw = e.get("rawCategories")
    require(type(raw) is list and all(isinstance(v, str) for v in raw)
            and len(raw) == len(RAW) and set(raw) == RAW, "RAW_INVENTORY_INVALID")
    counts = _object(e.get("assertions"))
    keys = {"expected", "executed", "passed", "failed", "missing", "skipped", "selectors"}
    integers = set(counts) == keys and all(type(v) is int and v >= 0 for v in counts.values())
    require(integers, "ASSERTION_TYPES_INVALID")
    if integers:
        require(counts["expected"] == counts["executed"] == counts["passed"] > 0
                and counts["selectors"] > 0 and
                counts["failed"] == counts["missing"] == counts["skipped"] == 0, "ASSERTION_COVERAGE_FAILED")
    artifacts = _object(f.get("artifactReadBack"))
    require(_inventory(e.get("inventory")) and _inventory(artifacts.get("inventory"))
            and sorted(e["inventory"]) == sorted(artifacts["inventory"]), "ARTIFACT_INVENTORY_MISMATCH")
    for key, readback in (("manifestSha256", "manifestSha256"), ("contactSheetSha256", "sheetSha256")):
        require(_match(DIGEST, e.get(key)) and e.get(key) == artifacts.get(readback), "ARTIFACT_DIGEST_MISMATCH")
    for key in ("hashesVerified", "privacyPassed", "archiveClean", "rawMetricsVerified",
                "contactSidecarVerified", "nonzeroAttachments"):
        require(artifacts.get(key) is True, "ARTIFACT_" + key.upper())
    checks = _object(f.get("checkReadBack"))
    require(checks.get("exactHead") == e.get("reviewedHead") and _match(SHA, checks.get("exactHead")), "CHECK_HEAD_MISMATCH")
    for key in ("allRequiredSuccess", "urlsVerified", "publisherTrusted", "uniqueContext"):
        require(checks.get(key) is True, "CHECK_" + key.upper())
    review = _object(f.get("reviewState"))
    for key in ("unresolved", "requests", "changesRequested"):
        require(type(review.get(key)) is int and review[key] == 0, "REVIEW_STATE_OPEN")
    require(review.get("paginationComplete") is True, "REVIEW_PAGINATION_INCOMPLETE")
    coverage = _object(e.get("failureDigestCoverage"))
    require(coverage.get("contract") == "nyay40", "FAILURE_DIGEST_CONTRACT_MISSING")
    for key in ("seededFailureExecuted", "privacyScanned", "manifested", "uploadedReadBack"):
        require(coverage.get(key) is True, "FAILURE_DIGEST_" + key.upper())
    codes = sorted(set(codes))
    classification = "HEAD_CHANGED" if "HEAD_CHANGED" in codes else "FAIL" if codes else "PASS"
    return {"schema": "nyay13-independent-qa/v1", "classification": classification,
            "mergeAuthorized": not codes, "codes": codes}


def render_pr_comment(evidence, facts):
    result = validate_review(evidence, facts)
    if result["classification"] != "PASS":
        return "NYAY13_QA_REFUSED: " + ",".join(result["codes"])
    return (f"Independent QA: PASS\nReviewed head: {evidence['reviewedHead']}\n"
            f"Base: {evidence['base']}\nManifest SHA-256: {evidence['manifestSha256']}\n"
            f"Contact sheet SHA-256: {evidence['contactSheetSha256']}\n"
            f"Limitations: {', '.join(evidence['limitations']) or 'none declared'}\n")


def render_merge_command(evidence, facts):
    if not validate_review(evidence, facts)["mergeAuthorized"]:
        return None
    # Deliberately does not execute. Trusted caller must also select the PR.
    return f"gh pr merge --repo {REPOSITORY} --merge --match-head-commit {evidence['reviewedHead']}"


def approval_policy(configuration):
    separate = _object(configuration).get("trustedSeparateReviewerAvailable") is True
    return {"requiredApprovals": int(separate), "requireLastPushApproval": separate,
            "independentEvidenceRequired": True, "bypassAllowed": False}


def validate_closure(head, merge, readback):
    r = _object(readback)
    ok = (_match(SHA, head) and _match(SHA, merge) and r.get("merge") == merge
          and r.get("reviewedHead") == head and r.get("mainPushHead") == merge
          and all(r.get(k) is True for k in ("headIsAncestor", "mergeIsAncestor",
                    "allMainGatesSuccess", "runUrlsVerified", "checkUrlsVerified")))
    return {"classification": "PASS" if ok else "BLOCKED", "closureAuthorized": bool(ok),
            "codes": [] if ok else ["EXACT_MERGE_READBACK_INCOMPLETE"]}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def observe_signed_review(envelope, signature, public_key, policy, live_head, *, now=None):
    """Verify a bounded RSA/SHA-256 independent receipt; NEVER authorize merge.

    Policy and public key are supplied by a separately administered verifier,
    outside implementer control. Live head is acquired separately, not signed
    package input. A signature authenticates claims, not their factual truth;
    independent producer/artifact acquisition remains a promotion prerequisite.
    """
    refused = {"classification": "BLOCKED", "mergeAuthorized": False,
               "mode": "observe-only", "codes": ["SIGNED_REVIEW_INVALID"]}
    try:
        p = _object(policy)
        timestamp = time.time() if now is None else now
        if not (type(envelope) is dict and set(envelope) == {"evidence", "facts", "issuedAt", "expiresAt"}
                and type(envelope["evidence"]) is dict and type(envelope["facts"]) is dict
                and type(envelope["issuedAt"]) is int and type(envelope["expiresAt"]) is int
                and envelope["issuedAt"] <= timestamp < envelope["expiresAt"]
                and 0 < envelope["expiresAt"] - envelope["issuedAt"] <= 3600
                and type(public_key) is bytes and 0 < len(public_key) <= 16384
                and type(signature) is bytes and 0 < len(signature) <= 8192
                and p.get("publicKeySha256") == hashlib.sha256(public_key).hexdigest()
                and p.get("revoked") is False and p.get("issuer") == ISSUER
                and _match(IDENTITY, p.get("reviewer")) and _match(IDENTITY, p.get("implementer"))
                and p["reviewer"] != p["implementer"] and _match(SHA, live_head)):
            return refused
        payload = canonical(envelope)
        if len(payload) > 1048576:
            return refused
        with tempfile.TemporaryDirectory(prefix="nyay13-verify-") as directory:
            root = Path(directory)
            (root / "key.pem").write_bytes(public_key)
            (root / "signature.bin").write_bytes(signature)
            (root / "payload.json").write_bytes(payload)
            result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(root / "key.pem"),
                "-signature", str(root / "signature.bin"), str(root / "payload.json")],
                capture_output=True, timeout=10, check=False)
        if result.returncode != 0:
            return refused
        facts = json.loads(json.dumps(envelope["facts"]))
        trust = _object(facts.get("trust"))
        if any(trust.get(k) != p[k] for k in ("reviewer", "implementer", "issuer")):
            return refused
        facts["remoteHead"] = live_head
        # Derive signature facts; do not accept these two package assertions.
        trust.update(signatureVerified=True, signedPayloadMatches=True)
        result = validate_review(envelope["evidence"], facts)
        return {**result, "policyVerdict": result["classification"], "mergeAuthorized": False,
                "mode": "observe-only", "promotion": "INDEPENDENT_PUBLISHER_NOT_ENABLED"}
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        return refused


def _read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_FIELD")
            result[key] = value
        return result
    data = Path(path).read_bytes()
    if len(data) > 1048576:
        raise ValueError("INPUT_TOO_LARGE")
    return json.loads(data, object_pairs_hook=unique)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--trust-policy", required=True)
    parser.add_argument("--pr", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.pr <= 0:
            raise ValueError("PR_INVALID")
        live = subprocess.run(["gh", "pr", "view", str(args.pr), "--repo", REPOSITORY,
            "--json", "headRefOid,state,baseRefName"], capture_output=True, text=True, timeout=30, check=True)
        readback = _object(json.loads(live.stdout))
        if readback.get("state") != "OPEN" or readback.get("baseRefName") != "main":
            raise ValueError("PR_INVALID")
        result = observe_signed_review(_read_json(args.envelope), Path(args.signature).read_bytes(),
            Path(args.public_key).read_bytes(), _read_json(args.trust_policy), readback["headRefOid"])
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        result = {"classification": "BLOCKED", "mergeAuthorized": False,
                  "mode": "observe-only", "codes": ["OBSERVATION_INPUT_OR_READBACK_FAILED"]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["classification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

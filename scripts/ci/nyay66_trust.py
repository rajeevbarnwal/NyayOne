"""Trusted-base NYAY-66 approval reader. Never imports or executes candidate code.

Run this file from the event's base commit, not the candidate checkout. The
initial installation uses a reviewed immutable bootstrap commit in the workflow.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.request

POLICY = "frontend/scripts/nyay66-policy.json"
SOURCE_CONTRACT = "contracts/unicode-legal-name-v1.json"
TOLERANCES = {"pixelRatio": 0.001, "mean": 0.25, "geometry": 1}
OWNER = "rajeevbarnwal"
REPOSITORY = "rajeevbarnwal/NyayOne"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def comparison_base(event_name, event, parent):
    if event_name in {"pull_request", "pull_request_target"}:
        base = event.get("pull_request", {}).get("base", {}).get("sha")
    elif event_name == "push":
        base = event.get("before")
    elif event_name == "workflow_dispatch":
        base = parent
    else:
        base = None
    if not isinstance(base, str) or not re.fullmatch(r"[a-f0-9]{40}", base) or base == "0" * 40:
        raise ValueError("COMPARISON_BASE_REQUIRED")
    return base


def protected(path):
    return (
        path == ".github/workflows/nyay66-conformance.yml"
        or path in {"scripts/ci/nyay66_trust.py", "scripts/ci/test_nyay66_review_regressions.py", "frontend/package.json", "frontend/package-lock.json"}
        or path.startswith(("frontend/scripts/nyay66-", "frontend/scripts/lib/nyay66-", "frontend/test-baselines/nyay66/", "frontend/public/fonts/", "docs/design/nyayone-option-3.2.1/"))
    ) and path != POLICY


def inventory(repo, revision):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("INVALID_REVISION")
    files = {}
    for record in git(repo, "ls-tree", "-rz", "--full-tree", revision).split(b"\0"):
        if not record:
            continue
        meta, encoded_path = record.split(b"\t", 1)
        path = encoded_path.decode("utf-8")
        if protected(path):
            mode, kind, blob = meta.decode().split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("UNSAFE_GATE_FILE")
            files[path] = sha(git(repo, "cat-file", "blob", blob))
    return files


def config_at(repo, revision):
    exists = git(repo, "ls-tree", revision, "--", POLICY).strip()
    return json.loads(git(repo, "show", f"{revision}:{POLICY}")) if exists else None


def settings(config):
    return {k: v for k, v in (config or {}).items() if k not in {"integrityApproval", "enforced", "exceptions"}}


def bundle_digest(files, config_settings):
    return sha(canonical({"files": files, "settings": config_settings}).encode())


def progression(before, after):
    allowed = {f"S-{i:02}" for i in range(1, 18)} | {"S-07-popup"}
    if not isinstance(before, list) or not isinstance(after, list) or any(not isinstance(x, str) for x in before + after) or len(set(after)) != len(after) or not set(before) <= set(after) or not set(after) <= allowed:
        raise ValueError("ENFORCEMENT_REGRESSION")


def validate_tolerances(config):
    if canonical(config.get("tolerances")) != canonical(TOLERANCES) or config.get("ownerToleranceApproval") != "NYAY-66:15382":
        raise ValueError("TOLERANCE_APPROVAL_MISMATCH")
    return True


def valid_reference(approval):
    return isinstance(approval, dict) and all(type(approval.get(key)) is int and approval[key] > 0 for key in ("pr", "commentId")) and isinstance(approval.get("bundleSha256"), str) and re.fullmatch(r"[a-f0-9]{64}", approval["bundleSha256"])


def approve_change(old, new, old_settings, new_settings, approval, comments):
    digest = bundle_digest(new, new_settings)
    if not valid_reference(approval) or approval["bundleSha256"] != digest:
        raise ValueError("INTEGRITY_APPROVAL_REQUIRED")
    # Even unchanged bundles read back their recorded approval; metadata alone
    # never grants authority. Deleting or editing the owner comment fails closed.
    if not any(c.get("id") == approval["commentId"] and c.get("approvalPr") == approval["pr"] and c.get("user", {}).get("login") == OWNER and c.get("body", "").strip() == f"NYAY66-INTEGRITY {digest}" for c in comments):
        raise ValueError("INTEGRITY_APPROVAL_REQUIRED")
    return True


def read_comments(config):
    references = [config.get("integrityApproval", {}).get("pr")]
    references += [entry.get("approvalPr") for entry in config.get("exceptions", [])]
    if any(type(pr) is not int or pr <= 0 for pr in references):
        raise ValueError("INVALID_APPROVAL_PR")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("APPROVAL_READBACK_UNAVAILABLE")
    comments = []
    for pr in sorted(set(references)):
        page = 1
        while True:
            request = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/issues/{pr}/comments?per_page=100&page={page}", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            if not isinstance(data, list):
                raise ValueError("INVALID_COMMENT_READBACK")
            for item in data:
                if item.get("user", {}).get("login") == OWNER and item.get("body", "").strip().startswith(("NYAY66-INTEGRITY ", "NYAY66-EXCEPTION ")):
                    comments.append({"id": item["id"], "approvalPr": pr, "user": {"login": OWNER}, "body": item["body"].strip()})
            if len(data) < 100:
                break
            page += 1
    return comments


def validate(repo, base, head, comments):
    previous, config = config_at(repo, base), config_at(repo, head)
    if not isinstance(config, dict):
        raise ValueError("CONFIG_REQUIRED")
    validate_tolerances(config)
    progression((previous or {}).get("enforced", []), config.get("enforced"))
    old, new = inventory(repo, base), inventory(repo, head)
    approve_change(old, new, settings(previous), settings(config), config.get("integrityApproval"), comments)
    return {"head": head, "base": base, "bundleSha256": bundle_digest(new, settings(config)), "comments": comments}


def export_bundle(repo, head, destination):
    """Materialize approved Git blobs only, without archive attributes/hooks."""
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for path in [*inventory(repo, head), POLICY]:
        output = destination / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(git(repo, "show", f"{head}:{path}"))


def export_source_contract(repo, head, destination):
    """Copy the authorized candidate's blob into a fresh trusted-scratch file.

    The contract is product input, not part of the approved evaluator bundle.
    Inspect checkout metadata only: never open a candidate-controlled path for
    content, including a symlink target or a FIFO that could block the reader.
    """
    if not re.fullmatch(r"[a-f0-9]{40}", head):
        raise ValueError("INVALID_REVISION")
    records = git(repo, "ls-tree", "-z", "--full-tree", head, "--", SOURCE_CONTRACT).split(b"\0")
    if len(records) != 2 or records[1]:
        raise ValueError("UNSAFE_SOURCE_CONTRACT_GIT_ENTRY")
    metadata, path = records[0].split(b"\t", 1)
    mode, kind, blob = metadata.decode("ascii").split()
    if path != SOURCE_CONTRACT.encode() or kind != "blob" or mode not in {"100644", "100755"}:
        raise ValueError("UNSAFE_SOURCE_CONTRACT_GIT_ENTRY")
    checkout = Path(repo)
    try:
        for directory in (checkout, checkout / "contracts"):
            if not stat.S_ISDIR(directory.lstat().st_mode):
                raise ValueError("UNSAFE_SOURCE_CONTRACT_PATH")
        if not stat.S_ISREG((checkout / SOURCE_CONTRACT).lstat().st_mode):
            raise ValueError("UNSAFE_SOURCE_CONTRACT_PATH")
    except OSError as error:
        raise ValueError("UNSAFE_SOURCE_CONTRACT_PATH") from error
    content = git(repo, "cat-file", "blob", blob)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--read-approvals", action="store_true")
    parser.add_argument("--authorization")
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--export")
    parser.add_argument("--export-source-contract")
    args = parser.parse_args()
    if args.describe:
        config = config_at(args.repo, args.head)
        print(bundle_digest(inventory(args.repo, args.head), settings(config)))
        return
    if args.read_approvals:
        comments = read_comments(config_at(args.repo, args.head))
    else:
        authorization = json.loads(Path(args.authorization).read_text())
        if authorization.get("head") != args.head or authorization.get("base") != args.base:
            raise ValueError("AUTHORIZATION_HEAD_MISMATCH")
        comments = authorization["comments"]
    result = validate(args.repo, args.base, args.head, comments)
    if not args.read_approvals and result != authorization:
        raise ValueError("AUTHORIZATION_BUNDLE_MISMATCH")
    if args.export:
        export_bundle(args.repo, args.head, args.export)
    if args.export_source_contract:
        export_source_contract(args.repo, args.head, args.export_source_contract)
    encoded = canonical(result)
    if args.read_approvals:
        # The only cross-job output is verified public approval data; no token.
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"authorization={encoded}\n")
    print(f"NYAY66_INTEGRITY_OK {result['bundleSha256']}")


if __name__ == "__main__":
    main()

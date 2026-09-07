"""Observe-first campaign planning; no dispatch, skip, merge or promotion authority.

The selector deliberately proposes narrowing only for an exact small set of root
documentation files. All real producers still execute. Measurement is arithmetic
over externally acquired complete job records, NOT proof of acquisition or billed
usage. Promotion requires independently verified completeness and scope parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

PRODUCERS = ("registration", "wave1", "wave2", "wave3", "wave4", "wave5", "nyay5", "nyay18")
REQUIRED_CONTEXTS = tuple("nyayone-" + p + "-required" for p in
                          ("registration", "wave1", "wave2", "wave3", "wave4", "wave5", "policy"))
DOCUMENT_ONLY = frozenset({"README.md", "LICENSE", "LICENSE.md", "CONTRIBUTING.md"})
SHA = re.compile(r"[0-9a-f]{40}\Z")
SAFE_PATH = re.compile(r"[A-Za-z0-9_. /-]+\Z")
WEEK = 604800


def require(ok):
    if not ok:
        raise ValueError("NYAY42_INPUT_INVALID")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def valid_head(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def select_campaign(paths, *, base, head, event, history_complete):
    require(valid_head(base) and valid_head(head))
    require(type(history_complete) is bool and type(paths) is list)
    require(event in {"pull_request", "push", "schedule", "workflow_dispatch"})
    require(all(type(p) is str and SAFE_PATH.fullmatch(p) and not p.startswith("/")
                and all(x not in {"", ".", ".."} for x in p.split("/")) for p in paths))
    normalized = sorted(set(paths))
    narrow = (event == "pull_request" and history_complete and bool(normalized)
              and set(normalized) <= DOCUMENT_ONLY)
    record = {
        "schemaVersion": "nyay42-campaign-observation/v1", "mode": "observe-only",
        "repository": "rajeevbarnwal/NyayOne", "base": base, "reviewedHead": head,
        "event": event, "historyComplete": history_complete,
        "diffSha256": digest(normalized), "changedPathCount": len(normalized),
        "selectorSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reason": "ROOT_DOCUMENT_ONLY" if narrow else "FULL_CLOSURE",
        "candidateProducers": [] if narrow else list(PRODUCERS),
        "executeProducers": list(PRODUCERS),
        "alwaysRun": ["policy", "namespace", "independent-qa-observe"],
        "requiredContexts": list(REQUIRED_CONTEXTS), "mergeAuthorized": False,
        "selectionActivated": False, "quarantineChanged": False,
    }
    record["selectionSha256"] = digest(record)
    return record


def fallback_plan(*, offline_seconds, already_dispatched, reviewed_head, remote_head):
    """Plan only: ordinary rerun cannot change runs-on; trusted dispatch is needed."""
    require(type(offline_seconds) is int and offline_seconds >= 0)
    require(type(already_dispatched) is bool and valid_head(reviewed_head) and valid_head(remote_head))
    action = "WAIT"
    if reviewed_head != remote_head:
        action = "HEAD_CHANGED"
    elif offline_seconds > 600 and not already_dispatched:
        action = "HOSTED_DISPATCH_REQUIRED"
    return {"action": action, "execute": False, "reviewedHead": reviewed_head,
            "maxHostedAttempts": 1, "latePilotResultAccepted": False}


def measure(rows, *, migration_at, observed_until, baseline_week_minutes, baseline_campaign_minutes):
    """Estimate job-rounded usage, including failed/cancelled/retried/unmerged work.

    Rows must come from a separately validated complete all-attempt inventory.
    Campaign keys must be independently assigned from real merge records and
    include main/nightly allocation. This pure calculator cannot certify those
    facts, comparable throughput, assertion parity, or a completed NYAY-42 gate.
    """
    if migration_at is None:
        return {"verdict": "NOT_STARTED", "programVerified": False}
    require(type(migration_at) is int and type(observed_until) is int
            and observed_until >= migration_at)
    require(all(type(v) in (int, float) and math.isfinite(v) and v > 0
                for v in (baseline_week_minutes, baseline_campaign_minutes)))
    require(type(rows) is list and bool(rows))
    identities, weeks, campaigns = set(), [0, 0], {}
    local_minutes = 0
    fields = {"jobId", "attempt", "startedAt", "seconds", "hosted", "campaign", "conclusion"}
    for row in rows:
        require(type(row) is dict and set(row) == fields)
        require(type(row["jobId"]) is str and re.fullmatch(r"[0-9]+", row["jobId"]) is not None)
        require(type(row["campaign"]) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row["campaign"]) is not None)
        require(type(row["attempt"]) is int and row["attempt"] > 0)
        require(type(row["hosted"]) is bool and type(row["seconds"]) is int and row["seconds"] >= 0)
        require(type(row["startedAt"]) is int and migration_at <= row["startedAt"] < observed_until)
        require(row["conclusion"] in {"success", "failure", "cancelled", "timed_out", "action_required", "neutral", "skipped"})
        identity = (row["jobId"], row["attempt"])
        require(identity not in identities)
        identities.add(identity)
        # Explicit non-execution has zero charge only when duration is zero.
        require(row["conclusion"] != "skipped" or row["seconds"] == 0)
        index = (row["startedAt"] - migration_at) // WEEK
        require(index < 2)
        minutes = math.ceil(row["seconds"] / 60)
        # Zero hosted minutes is still a real externally verified campaign;
        # its identity must not disappear from the merged-PR denominator.
        campaigns.setdefault(row["campaign"], 0)
        if row["hosted"]:
            weeks[index] += minutes
            campaigns[row["campaign"]] = campaigns.get(row["campaign"], 0) + minutes
        else:
            local_minutes += minutes
    # Unmerged overhead counts against totals, not as another successful merge.
    merged = [v for k, v in campaigns.items() if k != "unmerged"]
    require(bool(merged))
    average = sum(campaigns.values()) / len(merged)
    week_reduction = [1 - v / baseline_week_minutes for v in weeks]
    campaign_reduction = 1 - average / baseline_campaign_minutes
    verdict = "IN_PROGRESS" if observed_until - migration_at < 2 * WEEK else (
        "TARGET_MET" if min(week_reduction) >= .70 and campaign_reduction >= .70 else "NOT_MET")
    return {"verdict": verdict, "hostedMinutes": sum(weeks), "weeklyHostedMinutes": weeks,
            "localMinutes": local_minutes, "meanCampaignMinutes": average,
            "weeklyReduction": week_reduction, "campaignReduction": campaign_reduction,
            "billedUsage": "UNVERIFIED", "programVerified": False,
            "completenessAndWorkloadParity": "EXTERNAL_VERIFICATION_REQUIRED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    try:
        require(valid_head(args.base) and valid_head(args.head))
        complete = True
        try:
            raw = subprocess.check_output(["git", "diff", "--name-only", "-z", "--no-renames",
                                           args.base, args.head, "--"], stderr=subprocess.DEVNULL)
            paths = [p.decode("utf-8", errors="strict") for p in raw.split(b"\0") if p]
        except (subprocess.CalledProcessError, UnicodeError):
            paths, complete = [], False
        print(json.dumps(select_campaign(paths, base=args.base, head=args.head,
                                         event=args.event, history_complete=complete), sort_keys=True))
    except (ValueError, OSError):
        print('{"code":"NYAY42_INPUT_INVALID","selectionActivated":false}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

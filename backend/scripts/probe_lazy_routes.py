"""Does FastAPI 0.141's LAZY route materialisation race when N threads hit a
COLD app simultaneously? Barrier-synchronised so all threads reach routing at
the same instant. No DB in the path, so any non-2xx is routing-level.
"""
from __future__ import annotations

import sys
import threading
from collections import Counter

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.api.v1.router import api_router

N = 8


def one_round(target: str, method: str) -> list[int]:
    app_ = FastAPI()
    app_.include_router(api_router, prefix="/api/v1")
    client = TestClient(app_)  # cold: no request yet -> routes not materialised
    barrier = threading.Barrier(N)
    codes: list[int] = [0] * N

    def worker(i: int) -> None:
        barrier.wait()
        r = client.request(method, target)
        codes[i] = r.status_code

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return codes


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    cases = [
        ("/api/v1/health", "GET", {200}),
        # unauth PUT on the flaky path shape: expect a stable auth/validation code,
        # never a routing-level 404/405
        ("/api/v1/student/law-schools/00000000-0000-0000-0000-000000000001/follow", "PUT", None),
        ("/api/v1/student/law-schools/00000000-0000-0000-0000-000000000001/saved", "PUT", None),
    ]
    bad = 0
    for target, method, expected in cases:
        tally: Counter[int] = Counter()
        for _ in range(rounds):
            codes = one_round(target, method)
            tally.update(codes)
        # a routing-level failure shows up as an EXTRA code appearing only sometimes
        routing_codes = {c for c in tally if c in (404, 405)}
        print(f"{method} {target}\n   codes={dict(tally)} distinct={len(tally)}", flush=True)
        if len(tally) > 1 or routing_codes:
            bad += 1
            print("   ^^ NON-DETERMINISTIC or routing-level code present", flush=True)
    print(f"rounds_per_case={rounds} suspicious_cases={bad}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

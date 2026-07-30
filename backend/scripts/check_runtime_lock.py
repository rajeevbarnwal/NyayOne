#!/usr/bin/env python
"""F2 — prove THIS interpreter matches ``backend/requirements.lock``, or refuse.

Both runners (``backend/scripts/full_suite.sh`` and
``scripts/wave2_tutoring_browser_gate.sh``) call this BEFORE they start a
service, a migration or a test process, so a run can never get far enough to
produce evidence against an interpreter nobody declared.

It answers exactly two questions about every distribution pinned in the lock:

* is it installed at all?  -> ``MISSING``
* is the installed version the pinned one? -> ``MISMATCH``

and prints the resolved version of each pin either way, so the raw log of every
gate carries the executable and the versions the evidence was produced with.

Usage:
    python backend/scripts/check_runtime_lock.py            # verify, print, exit
    python backend/scripts/check_runtime_lock.py --header   # one-line summary too
    python backend/scripts/check_runtime_lock.py --only fastapi,SQLAlchemy

Exit codes: 0 = every pin satisfied, 3 = at least one MISSING/MISMATCH,
4 = the lock file itself could not be read.
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "requirements.lock"

#: PEP 503 name normalisation: ``SQLAlchemy``, ``sqlalchemy`` and
#: ``typing_extensions`` must all match the distribution actually installed.
_NORMALISE = re.compile(r"[-_.]+")


def normalise(name: str) -> str:
    return _NORMALISE.sub("-", name).lower()


def read_pins(lock_path: Path) -> list[tuple[str, str]]:
    """``[(distribution, exact version), ...]`` in lock-file order."""
    pins: list[tuple[str, str]] = []
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if "==" not in line:
            raise SystemExit(
                f"{lock_path}: '{line}' is not an EXACT pin; a lock file may "
                f"only contain 'name==version' lines"
            )
        name, _, version = line.partition("==")
        pins.append((name.strip(), version.strip().split(" ")[0]))
    return pins


def installed_versions() -> dict[str, str]:
    found: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        found[normalise(name)] = dist.version
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument(
        "--only",
        default="",
        help="comma list: verify/print only these pinned distributions",
    )
    parser.add_argument(
        "--header",
        action="store_true",
        help="also print a single-line 'python=... lock=...' summary first",
    )
    args = parser.parse_args(argv)

    lock_path = Path(args.lock)
    if not lock_path.is_file():
        print(f"RUNTIME LOCK MISSING: {lock_path} does not exist", file=sys.stderr)
        return 4
    pins = read_pins(lock_path)
    wanted = {normalise(n) for n in args.only.split(",") if n.strip()}
    if wanted:
        pins = [p for p in pins if normalise(p[0]) in wanted]
        unknown = wanted - {normalise(p[0]) for p in pins}
        if unknown:
            print(
                f"RUNTIME LOCK ERROR: {sorted(unknown)} are not pinned in {lock_path}",
                file=sys.stderr,
            )
            return 4

    found = installed_versions()
    problems: list[str] = []
    if args.header:
        print(
            f"python={sys.executable} version={sys.version.split()[0]} "
            f"lock={lock_path}"
        )
    width = max((len(name) for name, _ in pins), default=10)
    for name, pinned in pins:
        actual = found.get(normalise(name))
        if actual is None:
            state, problems = "MISSING", problems + [
                f"      {name}=={pinned}  -> NOT INSTALLED"
            ]
            actual = "-"
        elif actual != pinned:
            state = "MISMATCH"
            problems.append(f"      {name}=={pinned}  -> found {actual}")
        else:
            state = "ok"
        print(f"  {name:<{width}}  pinned={pinned:<12} installed={actual:<12} {state}")

    if problems:
        print(
            "\nPREREQUISITE NOT MET: this interpreter does not match the "
            "repository runtime lock, so anything it produced would be evidence "
            "about a different dependency set.\n"
            f"\n  interpreter : {sys.executable}\n"
            f"  lock file   : {lock_path}\n"
            "\n  OUT OF PIN:\n" + "\n".join(problems) + "\n"
            "\n  Fix by rebuilding the project virtualenv from the lock:\n"
            f"      python3 -m venv backend/.venv\n"
            f"      backend/.venv/bin/python -m pip install -r {lock_path}\n",
            file=sys.stderr,
        )
        return 3
    print(f"runtime lock: {len(pins)} pinned distribution(s) satisfied exactly")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

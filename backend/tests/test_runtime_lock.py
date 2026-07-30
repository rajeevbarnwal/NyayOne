"""F2 — the repository owns its runtime versions, and the runners enforce it.

These are regression guards, not unit tests of pip: they fail the moment the
lock stops being exact, stops covering a core runtime package, or a runner
grows back an undeclared interpreter fallback (a bare ``python3``, or an
interpreter under ``/tmp``) — which is exactly how a gate ends up producing
evidence about a dependency set nobody chose.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from scripts.check_runtime_lock import main, normalise, read_pins

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
LOCK = BACKEND / "requirements.lock"
REQUIREMENTS = BACKEND / "requirements.txt"
FULL_SUITE = BACKEND / "scripts" / "full_suite.sh"
BROWSER_GATE = REPO / "scripts" / "wave2_tutoring_browser_gate.sh"

#: The packages the manifest requires to be pinned, by their PEP 503 name.
CORE = {
    "fastapi",
    "starlette",
    "pydantic",
    "httpx",
    "sqlalchemy",
    "alembic",
    "psycopg",  # the DB driver
    "psycopg-binary",
    "pgvector",
}


def test_lock_exists_and_is_exact():
    pins = read_pins(LOCK)
    assert pins, "the runtime lock is empty"
    assert len({normalise(name) for name, _ in pins}) == len(pins), "duplicate pin"
    for name, version in pins:
        assert version and not version.startswith(("<", ">", "~", "!")), (name, version)


def test_lock_covers_every_core_runtime_package():
    pinned = {normalise(name) for name, _ in read_pins(LOCK)}
    assert CORE <= pinned, f"unpinned core runtime package(s): {sorted(CORE - pinned)}"


def test_requirements_txt_is_constrained_by_the_lock_and_does_not_float():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "-c requirements.lock" in text, "requirements.txt must apply the lock"
    pinned = {normalise(name) for name, _ in read_pins(LOCK)}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        assert "==" in line, f"{line!r} floats; requirements.txt must not"
        distribution = line.partition("==")[0].split("[")[0].strip()
        assert normalise(distribution) in pinned, f"{distribution} is not in the lock"


def test_this_interpreter_satisfies_the_lock(capsys):
    """The suite is running on a declared, in-pin interpreter — or it says so."""
    assert main(["--lock", str(LOCK)]) == 0, capsys.readouterr().out


@pytest.mark.parametrize("runner", [FULL_SUITE, BROWSER_GATE], ids=["suite", "gate"])
def test_runners_select_only_declared_interpreters(runner: Path):
    source = runner.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    # The CANDIDATE LIST is the thing under test: prose in a help message may
    # legitimately mention python3, an interpreter search must not offer it.
    candidates = re.search(r"VENV_CANDIDATES=\((.*?)\n\s*\)", body, re.S)
    assert candidates, f"{runner.name} has no explicit VENV_CANDIDATES list"
    listed = candidates.group(1)
    assert "/tmp/" not in listed, f"{runner.name} defaults to a /tmp interpreter"
    assert not re.search(r"(^|[\s\"])python3?([\s\"]|$)", listed), (
        f"{runner.name} still offers a bare python/python3 fallback: {listed!r}"
    )
    assert not re.search(r"for cand in[^\n]*\bpython3\b", body), (
        f"{runner.name} still has a bare python3 fallback loop"
    )
    # An explicit PYTHON= is honoured, a project virtualenv is the only default,
    # and the lock is enforced before anything else runs.
    assert 'if [[ -n "${PYTHON:-}" ]]' in body
    assert "/backend/.venv/bin/python" in body or "/.venv/bin/python" in body
    assert "check_runtime_lock.py" in body


def test_lock_check_reports_a_mismatch_rather_than_passing(tmp_path, capsys):
    bad = tmp_path / "bad.lock"
    bad.write_text("fastapi==0.0.1\n", encoding="utf-8")
    assert main(["--lock", str(bad)]) == 3
    out = capsys.readouterr()
    assert "MISMATCH" in out.out
    assert "PREREQUISITE NOT MET" in out.err


def test_lock_check_reports_a_missing_distribution(tmp_path, capsys):
    bad = tmp_path / "missing.lock"
    bad.write_text("definitely-not-installed-legalsaathi==1.0.0\n", encoding="utf-8")
    assert main(["--lock", str(bad)]) == 3
    out = capsys.readouterr()
    assert "MISSING" in out.out
    assert "NOT INSTALLED" in out.err


def test_lock_check_reports_an_unreadable_lock(tmp_path):
    assert main(["--lock", str(tmp_path / "nope.lock")]) == 4


def test_project_venv_is_gitignored():
    """``backend/.venv`` must never be committable."""
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() in {".venv/", ".venv"} for line in ignore), (
        "add '.venv/' to .gitignore — the project virtualenv must stay untracked"
    )


def test_running_interpreter_is_not_the_undeclared_tmp_venv():
    """A soft guard: the suite should be running from a project virtualenv."""
    if "/tmp/" in sys.executable:
        pytest.skip(f"explicitly-selected interpreter {sys.executable}")
    assert Path(sys.executable).exists()

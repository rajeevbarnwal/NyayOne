"""F2 — PEP 508 MARKERS in the runtime lock are parsed, evaluated and obeyed.

The defect these guards exist for
---------------------------------
``backend/scripts/check_runtime_lock.py`` used to read a lock line with
``line.partition("==")`` and ``version.strip().split(" ")[0]``. That is string
surgery, not requirement parsing, and it SILENTLY DISCARDED the marker: a line
that says "only below Python 3.11" was read as an unconditional pin. Two of the
lock's entries — ``exceptiongroup`` and ``tomli`` — are stdlib backports that a
3.11+ interpreter must NOT have installed, so on the CI runner (CPython 3.12)
the checker demanded them, reported MISSING, and refused to start the suite.
The gate failed on its own parser, not on the code under test.

Why the environment is INJECTED
-------------------------------
This repository's virtualenv is CPython 3.10.12 and there is no 3.11 or 3.12
interpreter on this machine, so "what does a 3.12 run do" cannot be answered by
running one. It is answered the same way the F5 platform guards answer "what
does a macOS host do": the environment is DATA. ``marker_environment`` takes an
explicit, standards-shaped PEP 508 environment, so the 3.10 and the 3.12
verdicts below are properties of the evaluator and are identical on every
machine that runs this suite.

An injected marker environment is NOT a substitute for executing the suite on a
bare-metal 3.12 interpreter — it proves what the EVALUATOR concludes, not what
that interpreter would have installed. It is exactly the layer the defect lived
in.
"""
import os
import re
from pathlib import Path

import pytest

from scripts import check_runtime_lock as runtime_lock
from scripts.check_runtime_lock import (
    EXIT_LOCK_UNREADABLE,
    EXIT_LOCK_VIOLATION,
    InstalledIndex,
    LockFileError,
    marker_environment,
    normalise,
    read_lock,
    read_pins,
)

BACKEND = Path(__file__).resolve().parents[1]
LOCK = BACKEND / "requirements.lock"
CHECKER = BACKEND / "scripts" / "check_runtime_lock.py"

#: The stdlib backports that are only needed below 3.11 — the exact pair that
#: failed CI. Their pins are asserted, not just their names: "fix the marker"
#: must never quietly become "unpin it" or "delete it".
BACKPORTS = {"exceptiongroup": "1.3.1", "tomli": "2.4.1"}
BACKPORT_MARKER = 'python_version < "3.11"'


def _environment(**overrides: str) -> dict[str, str]:
    """A COMPLETE PEP 508 environment, so nothing leaks in from this machine.

    Every variable the standard defines is given a value here. A partial dict
    would inherit the rest from whoever is running pytest, and a marker with a
    platform clause would then mean something different on a Mac than in CI —
    which is the class of defect this file exists to stop.
    """
    environment = {
        "implementation_name": "cpython",
        "implementation_version": "3.10.12",
        "os_name": "posix",
        "platform_machine": "aarch64",
        "platform_python_implementation": "CPython",
        "platform_release": "6.1.0",
        "platform_system": "Linux",
        "platform_version": "#1 SMP",
        "python_full_version": "3.10.12",
        "python_version": "3.10",
        "sys_platform": "linux",
    }
    environment.update(overrides)
    return environment


#: The interpreter this repo's venv actually is (and the one CI used to be).
PY310 = _environment()
#: The interpreter CI now runs: the one the old parser could not survive.
PY312 = _environment(
    python_version="3.12", python_full_version="3.12.4", implementation_version="3.12.4"
)
#: A third, to prove the boundary is the MARKER and not a hardcoded "3.12".
PY311 = _environment(
    python_version="3.11", python_full_version="3.11.9", implementation_version="3.11.9"
)
#: 3.12 on a different operating system, for the platform clauses below.
PY312_WINDOWS = _environment(
    python_version="3.12",
    python_full_version="3.12.4",
    implementation_version="3.12.4",
    os_name="nt",
    platform_system="Windows",
    platform_machine="AMD64",
    sys_platform="win32",
)


def _entries(lock_path: Path, environment: dict[str, str]) -> dict:
    return {e.key: e for e in read_lock(lock_path, environment=environment)}


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _executable_source(text: str) -> str:
    """The checker's CODE, with docstrings and comment lines removed.

    The module's own prose quotes the discarded-marker idioms in order to
    explain the defect, so a naive substring scan of the whole file would fail
    on its documentation. Only what actually runs is judged.
    """
    kept: list[str] = []
    fence = ""
    for line in text.splitlines():
        stripped = line.strip()
        if fence:
            if fence in stripped:
                fence = ""
            continue
        if stripped.startswith(('"""', "'''")):
            opener = stripped[:3]
            if opener not in stripped[3:]:
                fence = opener
            continue
        if stripped.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# The parser: `packaging`, not string surgery.
# ---------------------------------------------------------------------------


def test_the_checker_parses_requirements_with_packaging_and_no_marker_regex():
    """A structural guard on HOW the lock is read, not only on the answer.

    The bug was a parsing STRATEGY, and a strategy can be reintroduced while
    every behavioural test still passes (by special-casing two package names,
    say). So the source itself is asserted: requirements come from
    ``packaging.requirements.Requirement`` and the discarded-marker idioms are
    gone.
    """
    code = _executable_source(CHECKER.read_text(encoding="utf-8"))
    assert re.search(
        r"^from packaging\.requirements import .*\bRequirement\b", code, re.M
    ), "lock entries must be parsed by packaging.requirements.Requirement"
    assert re.search(r"^from packaging\.markers import .*default_environment", code, re.M)
    assert "Requirement(line)" in code, "the raw lock line goes to packaging, whole"
    # The exact idioms that threw the marker away.
    assert 'partition("==")' not in code, "a marker cannot survive partition('==')"
    assert 'split(" ")[0]' not in code, "a marker cannot survive split(' ')[0]"
    # No hand-rolled marker handling of any kind: the only ';' that splits a
    # requirement from its marker is inside packaging.
    assert 'split(";")' not in code and "split(';')" not in code
    assert '";"' not in code and "';'" not in code
    # And no package is special-cased by name to paper over the parse.
    for name in BACKPORTS:
        assert name not in code, f"{name} must not be hardcoded in the checker"


def test_the_real_lock_keeps_both_backports_pinned_and_markered():
    """The fix is a MARKER, not a deletion and not an unpinning."""
    entries = _entries(LOCK, PY310)
    for name, version in BACKPORTS.items():
        entry = entries[normalise(name)]
        assert entry.version == version, f"{name} lost or changed its pin"
        assert entry.marker == BACKPORT_MARKER, f"{name} lost its marker"
        # The marker did NOT bleed into the version, which is what the old
        # `split(" ")[0]` hack would have produced from this same line.
        assert ";" not in entry.version and " " not in entry.version


def test_read_pins_is_still_the_whole_file_view():
    """``read_pins`` answers a question about the FILE, so nothing is dropped.

    The approved ``test_runtime_lock.py`` uses it to assert the lock covers the
    core runtime packages and that ``requirements.txt`` cannot float, and those
    are file-level facts: they must not change depending on which interpreter
    is reading them.
    """
    pins = dict(read_pins(LOCK))
    for name, version in BACKPORTS.items():
        assert pins[name] == version
    assert len(pins) == len(read_lock(LOCK))


# ---------------------------------------------------------------------------
# Applicability: 3.10 vs 3.12, stated as data.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "environment,applicable",
    [
        pytest.param(PY310, True, id="python-3.10-needs-the-backports"),
        pytest.param(PY311, False, id="python-3.11-does-not"),
        pytest.param(PY312, False, id="python-3.12-does-not"),
    ],
)
def test_backport_applicability_follows_the_marker(environment, applicable):
    entries = _entries(LOCK, environment)
    for name in BACKPORTS:
        assert entries[normalise(name)].applicable is applicable, name


def test_absent_backports_FAIL_on_310_and_PASS_on_312(tmp_path, capsys, monkeypatch):
    """The CI failure and its fix, in one test, from one lock file.

    Nothing is installed at all (the metadata table is empty), so the ONLY
    thing separating the two verdicts is whether the marker applies.
    """
    monkeypatch.setattr(runtime_lock, "installed_versions", dict)
    lock = _write(
        tmp_path,
        "backports.lock",
        'exceptiongroup==1.3.1 ; python_version < "3.11"\n'
        'tomli==2.4.1 ; python_version < "3.11"\n',
    )

    assert runtime_lock.main(["--lock", str(lock)], environment=PY310) == (
        EXIT_LOCK_VIOLATION
    )
    on_310 = capsys.readouterr()
    assert on_310.out.count("MISSING") == 2
    assert "exceptiongroup==1.3.1 ; python_version < \"3.11\"  -> NOT INSTALLED" in (
        on_310.err
    )

    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == 0
    on_312 = capsys.readouterr()
    assert "MISSING" not in on_312.out and "MISMATCH" not in on_312.out
    # One line per skipped entry, plus the run summary.
    assert on_312.out.count("SKIPPED / NOT APPLICABLE") == 3
    assert (
        'SKIPPED / NOT APPLICABLE (marker `python_version < "3.11"` is false '
        "for this environment)"
    ) in on_312.out
    assert "2 SKIPPED / NOT APPLICABLE to this environment" in on_312.out


def test_the_real_lock_is_satisfied_under_an_injected_312_environment(capsys):
    """The whole real lock, judged as a 3.12 run would judge it.

    This is the evaluator's verdict on the real file, not a bare-metal 3.12
    run: the installed distributions are still this venv's 3.10 set. It proves
    exactly the thing that broke — that the two backports stop being demanded —
    and nothing about what a 3.12 machine would have installed.
    """
    rc = runtime_lock.main(["--lock", str(LOCK)], environment=PY312)
    out = capsys.readouterr().out
    if os.getenv("CI") and rc != 0:
        pytest.fail(f"Interpreter lock mismatch in CI: {out}")
    for name in BACKPORTS:
        assert re.search(rf"^  {name}\s+pinned=\S+\s+installed=\(not queried\)", out, re.M)
    if rc == 0:
        assert out.count("SKIPPED / NOT APPLICABLE") == len(BACKPORTS) + 1  # +1 summary
    # ...while every applicable pin was still checked against real metadata.
    assert "  fastapi" in out and " ok" in out


def test_a_complex_marker_is_evaluated_whole(tmp_path):
    """`and`, `or`, parentheses and a platform clause — all of it, or none.

    A parser that "handles markers" by looking for one comparison would get
    this wrong in a way no single-clause fixture can catch.
    """
    marker = (
        '(python_version < "3.11" or python_version >= "3.13") '
        'and sys_platform == "linux"'
    )
    lock = _write(tmp_path, "complex.lock", f"sample-dist==1.0.0 ; {marker}\n")

    def applicable(environment: dict[str, str]) -> bool:
        (entry,) = read_lock(lock, environment=environment)
        assert entry.marker == marker, "the COMPLETE marker must survive parsing"
        return entry.applicable

    assert applicable(PY310) is True  # left of the `or`, and linux
    assert applicable(PY311) is False  # neither side of the `or`
    assert applicable(PY312) is False  # neither side of the `or`
    assert applicable(_environment(python_version="3.13")) is True  # right of the `or`
    # Same 3.13, wrong platform: the `and` decides.
    assert applicable(
        _environment(python_version="3.13", sys_platform="win32", os_name="nt")
    ) is False
    assert applicable(PY312_WINDOWS) is False


def test_extras_and_the_normalised_name_both_survive(tmp_path):
    """A pin with extras keeps them, and is still matched on its PEP 503 name."""
    lock = _write(
        tmp_path, "extras.lock", 'psycopg[binary,pool]==3.3.4 ; python_version >= "3.9"\n'
    )
    (entry,) = read_lock(lock, environment=PY312)
    assert entry.extras == ("binary", "pool")
    assert entry.display == "psycopg[binary,pool]"
    assert entry.key == "psycopg"  # extras are not part of the distribution name
    assert entry.version == "3.3.4"
    assert entry.applicable is True
    assert entry.requirement_line() == (
        'psycopg[binary,pool]==3.3.4 ; python_version >= "3.9"'
    )


# ---------------------------------------------------------------------------
# An APPLICABLE requirement is still enforced exactly as before.
# ---------------------------------------------------------------------------


def test_applicable_pin_with_the_wrong_version_installed_is_a_mismatch(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        runtime_lock, "installed_versions", lambda: {"fastapi": "0.141.1"}
    )
    lock = _write(tmp_path, "mismatch.lock", 'fastapi==0.0.1 ; python_version >= "3.0"\n')
    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == (
        EXIT_LOCK_VIOLATION
    )
    captured = capsys.readouterr()
    assert "MISMATCH" in captured.out
    assert "SKIPPED" not in captured.out
    assert "found 0.141.1" in captured.err
    assert "PREREQUISITE NOT MET" in captured.err


def test_applicable_pin_that_is_not_installed_is_missing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runtime_lock, "installed_versions", dict)
    lock = _write(
        tmp_path, "missing.lock", 'legalsaathi-nope==1.0.0 ; python_version >= "3.0"\n'
    )
    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == (
        EXIT_LOCK_VIOLATION
    )
    captured = capsys.readouterr()
    assert "MISSING" in captured.out
    assert "NOT INSTALLED" in captured.err


# ---------------------------------------------------------------------------
# Everything the parser cannot vouch for FAILS CLOSED (exit 4).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("this is not a requirement", id="prose"),
        pytest.param("fastapi==", id="empty-version"),
        pytest.param('fastapi==1.0.0 ; python_version <<< "3.11"', id="bad-marker"),
        pytest.param('fastapi==1.0.0 ; nonsense_variable == "x"', id="unknown-variable"),
        pytest.param("fastapi==1.0.0 ;", id="dangling-semicolon"),
    ],
)
def test_an_unparseable_line_fails_closed(tmp_path, capsys, line):
    """Never skipped, never half-understood: exit 4, the lock is unreadable."""
    lock = _write(tmp_path, "invalid.lock", line + "\n")
    with pytest.raises(LockFileError):
        read_lock(lock, environment=PY312)
    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == (
        EXIT_LOCK_UNREADABLE
    )
    assert "RUNTIME LOCK ERROR" in capsys.readouterr().err


@pytest.mark.parametrize(
    "line,label",
    [
        pytest.param('fastapi>=0.141.1 ; python_version >= "3.0"', "applicable >=", id="ge"),
        pytest.param('fastapi~=0.141.0 ; python_version >= "3.0"', "applicable ~=", id="compatible"),
        pytest.param('fastapi>=0.1,<2 ; python_version >= "3.0"', "applicable range", id="range"),
        pytest.param('fastapi==0.141.* ; python_version >= "3.0"', "applicable wildcard", id="wildcard"),
        pytest.param("fastapi @ https://example.invalid/f.whl", "direct reference", id="url"),
        pytest.param("fastapi", "no specifier at all", id="bare"),
        # A false marker does not buy a line out of being exact: a lock file
        # states WHICH version was executed, on every interpreter it names.
        pytest.param('fastapi>=0.141.1 ; python_version < "3.11"', "non-applicable >=", id="ge-skipped"),
    ],
)
def test_a_requirement_that_is_not_an_exact_pin_fails_closed(tmp_path, capsys, line, label):
    lock = _write(tmp_path, "loose.lock", line + "\n")
    with pytest.raises(LockFileError):
        read_lock(lock, environment=PY312)
    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == (
        EXIT_LOCK_UNREADABLE
    ), label
    err = capsys.readouterr().err
    assert "RUNTIME LOCK ERROR" in err
    assert "EXACT pin" in err or "exact" in err.lower()


def test_the_exit_codes_are_unchanged():
    """0 / 3 / 4 / 5 keep their meanings; SKIPPED introduces no new status."""
    assert runtime_lock.EXIT_LOCK_VIOLATION == 3
    assert runtime_lock.EXIT_LOCK_UNREADABLE == 4
    assert runtime_lock.EXIT_PLATFORM_MISMATCH == 5


# ---------------------------------------------------------------------------
# The landmine: a false-marker requirement is never asked about.
# ---------------------------------------------------------------------------


def test_a_false_marker_requirement_is_never_queried_from_metadata(
    tmp_path, capsys, monkeypatch
):
    """Not "it happens to pass" — the metadata is never touched at all.

    Reporting a not-applicable requirement as MISSING is only half the bug; the
    other half is that its installed state is not evidence about anything, so
    it must not be consulted. ``installed_versions`` is replaced by a landmine
    that raises the moment anything asks.
    """

    def _landmine():  # pragma: no cover - it must never be called
        raise AssertionError(
            "installed metadata was queried for a requirement whose marker is "
            "false; a not-applicable pin says nothing about this interpreter"
        )

    monkeypatch.setattr(runtime_lock, "installed_versions", _landmine)
    lock = _write(
        tmp_path,
        "skipped-only.lock",
        'exceptiongroup==1.3.1 ; python_version < "3.11"\n'
        'tomli==2.4.1 ; python_version < "3.11"\n',
    )
    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == 0
    assert capsys.readouterr().out.count("SKIPPED / NOT APPLICABLE") == 3  # 2 + summary


def test_only_the_applicable_names_are_looked_up(tmp_path, capsys, monkeypatch):
    """The metadata IS loaded for the applicable pin — and still not asked
    about the skipped one. A per-name landmine, so "we never load metadata at
    all" cannot be mistaken for "we never ask about that name"."""

    class Landmine(dict):
        def get(self, key, default=None):  # type: ignore[override]
            if key in {"exceptiongroup", "tomli"}:  # pragma: no cover
                raise AssertionError(f"metadata was queried for {key!r}")
            return super().get(key, default)

    monkeypatch.setattr(
        runtime_lock, "installed_versions", lambda: Landmine({"fastapi": "0.141.1"})
    )
    lock = _write(
        tmp_path,
        "mixed.lock",
        "fastapi==0.141.1\n"
        'exceptiongroup==1.3.1 ; python_version < "3.11"\n'
        'tomli==2.4.1 ; python_version < "3.11"\n',
    )
    assert runtime_lock.main(["--lock", str(lock)], environment=PY312) == 0
    out = capsys.readouterr().out
    assert re.search(r"^  fastapi\s+pinned=0\.141\.1\s+installed=0\.141\.1\s+ok$", out, re.M)
    assert out.count("SKIPPED / NOT APPLICABLE") == 3  # 2 + summary


def test_installed_index_reads_metadata_once_and_only_on_demand(monkeypatch):
    calls: list[int] = []

    def _counting() -> dict[str, str]:
        calls.append(1)
        return {"fastapi": "0.141.1"}

    monkeypatch.setattr(runtime_lock, "installed_versions", _counting)
    index = InstalledIndex()
    assert index.loaded is False and calls == []
    assert index.version("fastapi") == "0.141.1"
    assert index.version("pgvector") is None
    assert index.loaded is True and calls == [1]


# ---------------------------------------------------------------------------
# The injection seam itself.
# ---------------------------------------------------------------------------


def test_marker_environment_defaults_to_this_interpreter_and_accepts_overrides():
    import sys

    default = marker_environment()
    assert default["python_version"] == f"{sys.version_info[0]}.{sys.version_info[1]}"
    injected = marker_environment({"python_version": "3.12"})
    assert injected["python_version"] == "3.12"
    # Overriding one variable must not blank out the rest of the environment.
    assert set(injected) == set(default)
    assert marker_environment() == default, "the seam must not mutate global state"

"""F2 — the repository owns its runtime versions, and the runners enforce it.

These are regression guards, not unit tests of pip: they fail the moment the
lock stops being exact, stops covering a core runtime package, or a runner
grows back an undeclared interpreter fallback (a bare ``python3``, or an
interpreter under ``/tmp``) — which is exactly how a gate ends up producing
evidence about a dependency set nobody chose.
"""
from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

import pytest

from scripts import check_runtime_lock as runtime_lock
from scripts.check_runtime_lock import (
    EXIT_LOCK_UNREADABLE,
    EXIT_LOCK_VIOLATION,
    EXIT_PLATFORM_MISMATCH,
    HostFacts,
    current_host,
    extension_abi,
    main,
    normalise,
    platform_report,
    read_pins,
)

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


# ---------------------------------------------------------------------------
# F5 — the CROSS-PLATFORM venv trap.
#
# `backend/.venv` is ONE path shared by every machine that checks this repo
# out, and a virtualenv is not portable. The incident these guards exist for:
# a venv built on Linux/aarch64 (pyvenv.cfg `home = /usr/bin`, version 3.10.12,
# site-packages full of `*.cpython-310-aarch64-linux-gnu.so` ELF objects) was
# read from macOS. The version-only lock check PASSED on the Linux side and the
# macOS side got "MISSING alembic/psycopg/pgvector" — a completely wrong
# diagnosis of "wrong operating system", and one that sends somebody off to
# reinstall packages into a directory that can never work on their machine.
# ---------------------------------------------------------------------------


def _write_venv(root: Path, *, home: str, version: str, abi: str, libdir: str) -> Path:
    """Synthesise a virtualenv-shaped directory. The REAL venv is never touched."""
    site = root / "lib" / libdir / "site-packages"
    (site / "pkg").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text(
        f"home = {home}\ninclude-system-site-packages = false\nversion = {version}\n",
        encoding="utf-8",
    )
    (site / f"_cffi_backend.cpython-{abi}.so").write_bytes(b"\x7fELF-not-a-real-object")
    (site / "pkg" / f"_speedups.cpython-{abi}.so").write_bytes(b"not-a-real-object")
    # Untagged and stable-ABI files must be SKIPPED, not guessed at.
    (site / "pkg" / "_plain.so").write_bytes(b"")
    (site / "pkg" / "_rust.abi3.so").write_bytes(b"")
    return root


# -- SIMULATED hosts and SIMULATED venvs, always used in matched PAIRS -------
#
# A venv fixture is only "foreign" RELATIVE TO A HOST. A fixture hardcoded to
# one platform is therefore native on the machines of that platform, and a test
# that asserts refusal from such a fixture alone asserts something that is only
# true off that platform — the portability guard would itself not be portable,
# and would fail on exactly the operating system it exists to protect.
#
# So every refusal below names BOTH sides explicitly. `HostFacts` is data, the
# checker takes it as an argument, and nothing here reads `sys.platform`,
# `platform.system()` or `sysconfig` — the answers are identical on every
# machine that runs this suite.

#: The machine that built this repo's `backend/.venv` (see its pyvenv.cfg).
HOST_LINUX_AARCH64 = HostFacts(
    executable="/repo/backend/.venv/bin/python",
    version=(3, 10, 12),
    system="Linux",
    machine="aarch64",
    sysconfig_platform="linux-aarch64",
    ext_tag="cpython-310-aarch64-linux-gnu",
    ext_platform="aarch64-linux-gnu",
)
#: The machine the incident was REPORTED from: the same checkout, on macOS.
HOST_MACOS_ARM64 = HostFacts(
    executable="/Users/dev/repo/backend/.venv/bin/python",
    version=(3, 9, 6),
    system="Darwin",
    machine="arm64",
    sysconfig_platform="macosx-14.0-arm64",
    ext_tag="cpython-39-darwin",
    ext_platform="darwin",
)
#: A macOS machine that is NATIVE to ``VENV_DARWIN`` below — the host on which
#: that fixture proves nothing at all.
HOST_MACOS_ARM64_PY312 = HostFacts(
    executable="/Users/dev/.pyenv/versions/3.12.4/bin/python",
    version=(3, 12, 4),
    system="Darwin",
    machine="arm64",
    sysconfig_platform="macosx-14.0-arm64",
    ext_tag="cpython-312-darwin",
    ext_platform="darwin",
)

#: A venv built on macOS/arm64 by CPython 3.12: foreign to any Linux host.
VENV_DARWIN = {
    "version": "3.12.4",
    "abi": "312-darwin",
    "libdir": "python3.12",
    "home": ("Users", "nobody", ".pyenv", "versions", "3.12.4", "bin"),
}
#: What `backend/.venv` is in this repository: Linux/aarch64, CPython 3.10,
#: site-packages full of ELF objects. Foreign to any macOS host.
VENV_LINUX = {
    "version": "3.10.12",
    "abi": "310-aarch64-linux-gnu",
    "libdir": "python3.10",
    "home": ("usr", "bin"),
}


def _write_venv_spec(tmp_path: Path, name: str, spec: dict) -> Path:
    """Materialise one of the venv specs above under ``tmp_path``.

    ``home`` is rooted in a directory that is never created, so "the builder
    interpreter is not on this machine" is a property of the FIXTURE and not a
    guess about which paths happen to exist on whoever's laptop.
    """
    return _write_venv(
        tmp_path / name,
        home=str(tmp_path / "absent-builder" / Path(*spec["home"])),
        version=spec["version"],
        abi=spec["abi"],
        libdir=spec["libdir"],
    )


def _short(spec: dict) -> str:
    return ".".join(spec["version"].split(".")[:2])


#: (host, venv) pairs that MUST be refused, in both directions. Each row states
#: the whole claim: which host, which venv, which tag each side carries.
FOREIGN_PAIRS = [
    pytest.param(
        HOST_LINUX_AARCH64, VENV_DARWIN, "darwin", "aarch64-linux-gnu",
        id="linux-host-refuses-darwin-venv",
    ),
    pytest.param(
        HOST_MACOS_ARM64, VENV_LINUX, "aarch64-linux-gnu", "darwin",
        id="darwin-host-refuses-linux-venv",
    ),
]


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("_cffi_backend.cpython-310-aarch64-linux-gnu.so", ("310", "aarch64-linux-gnu")),
        ("_speedups.cpython-312-darwin.so", ("312", "darwin")),
        ("resultproxy.cpython-311-x86_64-linux-gnu.so", ("311", "x86_64-linux-gnu")),
        ("_rust.cp310-win_amd64.pyd", ("310", "win_amd64")),
        # No judgeable tag: an absent tag is not evidence, so it is skipped.
        ("_rust.abi3.so", None),
        ("_plain.so", None),
        ("notanextension.py", None),
    ],
)
def test_extension_abi_tag_parsing(filename, expected):
    assert extension_abi(filename) == expected


def test_platform_check_passes_for_the_venv_running_this_suite(capsys):
    """The venv the suite is IN belongs to the machine the suite is ON."""
    assert main(["--platform-only"]) == 0
    out = capsys.readouterr().out
    assert "platform-check=OK" in out
    report = platform_report()
    assert report.ok, report.problems
    assert report.host.system and report.host.machine


def test_platform_check_fails_for_a_foreign_platform_venv(tmp_path, capsys):
    """A venv built elsewhere is REFUSED, with its own exit status and wording.

    "Elsewhere" is stated, not assumed: a macOS venv judged by the Linux host
    that this repo's own `backend/.venv` was built by. Both sides of the
    comparison are fixture data, so the exit status and every word of the
    refusal are the same on Linux, on macOS and anywhere else.
    """
    fake = _write_venv_spec(tmp_path, "foreign", VENV_DARWIN)
    rc = main(["--platform-only", "--venv", str(fake)], host=HOST_LINUX_AARCH64)
    assert rc == EXIT_PLATFORM_MISMATCH
    captured = capsys.readouterr()
    assert "platform-check=MISMATCH" in captured.out
    err = captured.err
    assert "PLATFORM MISMATCH (exit 5)" in err
    # Every independent signal fired, not just the easiest one.
    assert "compiled extension(s) are tagged for platform 'darwin'" in err
    assert "pyvenv.cfg declares version 3.12.4" in err
    assert "does not exist on this machine" in err
    assert "lib/python3.12" in err


def test_the_exact_incident_is_detected_a_linux_venv_read_from_macos(tmp_path):
    """The REAL trap: this repo's Linux venv, opened by a macOS interpreter.

    The venv is byte-for-byte what `backend/.venv` looks like here (``home =
    /usr/bin``, ``version = 3.10.12``, aarch64 ELF extensions); only the HOST
    is simulated, because the test cannot be run from macOS.
    """
    linux_venv = _write_venv(
        tmp_path / "dotvenv",
        home="/usr/bin",
        version="3.10.12",
        abi="310-aarch64-linux-gnu",
        libdir="python3.10",
    )
    macos_host = HOST_MACOS_ARM64
    report = platform_report(linux_venv, host=macos_host)
    assert not report.ok
    joined = "\n".join(report.problems)
    assert "tagged for platform 'aarch64-linux-gnu'" in joined
    assert "can only load 'darwin'" in joined
    assert "pyvenv.cfg declares version 3.10.12" in joined
    assert "lib/python3.10" in joined
    assert report.venv_platform == "aarch64-linux-gnu"
    # And the SAME directory is healthy for the Linux host that built it.
    linux_host = HOST_LINUX_AARCH64
    # `home = /usr/bin` really does hold python3.10 on the Linux host; on a
    # machine where it does not, that alone is the finding — which is the point.
    same = platform_report(linux_venv, host=linux_host)
    assert not [p for p in same.problems if "tagged for platform" in p]
    assert not [p for p in same.problems if "declares version" in p]


# ---------------------------------------------------------------------------
# The refusal must be the SAME on both operating systems — including the
# operating system the suite is currently running on, whichever that is.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host,venv_spec,venv_tag,host_tag", FOREIGN_PAIRS)
def test_a_foreign_venv_is_refused_in_both_directions(
    host, venv_spec, venv_tag, host_tag, tmp_path, capsys
):
    """Linux host + macOS venv, and macOS host + Linux venv — same verdict.

    Both rows run on every machine and neither row's expectations are derived
    from the machine: the host is fixture data, the venv is fixture data, and
    the four signals asserted below are properties of that PAIR.
    """
    fake = _write_venv_spec(tmp_path, "foreign", venv_spec)
    rc = main(["--platform-only", "--venv", str(fake)], host=host)
    assert rc == EXIT_PLATFORM_MISMATCH
    captured = capsys.readouterr()
    assert "platform-check=MISMATCH" in captured.out
    err = captured.err
    assert "PLATFORM MISMATCH (exit 5)" in err
    assert f"compiled extension(s) are tagged for platform '{venv_tag}'" in err
    assert f"can only load '{host_tag}'" in err
    assert f"pyvenv.cfg declares version {venv_spec['version']}" in err
    assert "does not exist on this machine" in err
    assert f"lib/python{_short(venv_spec)}" in err
    assert f"host-platform={host.system}/{host.machine}" in captured.out


def _signals(report) -> set[str]:
    """The KINDS of problem found, independent of the platform names in them."""
    kinds = set()
    for problem in report.problems:
        if "tagged for platform" in problem:
            kinds.add("compiled-extension-platform")
        elif "declares version" in problem:
            kinds.add("declared-version")
        elif "does not exist on this machine" in problem:
            kinds.add("builder-interpreter-absent")
        elif "never imports from" in problem:
            kinds.add("incompatible-lib-tree")
        else:  # pragma: no cover - a new signal must be named here on purpose
            kinds.add(f"unclassified: {problem}")
    return kinds


def test_both_directions_produce_the_same_verdict_on_any_machine(tmp_path, monkeypatch):
    """The two directions agree, and NEITHER measures the local machine.

    ``current_host`` is replaced by a landmine: if any part of the refusal
    reached for the platform of whoever is running pytest, this test would blow
    up instead of quietly reporting a different answer on macOS than on Linux.
    That is the defect this file is guarding against — a portability guard that
    was itself not portable.
    """

    def _landmine():  # pragma: no cover - it must never be called
        raise AssertionError(
            "the platform refusal consulted the machine running pytest; its "
            "verdict must come only from the HostFacts it was given"
        )

    monkeypatch.setattr(runtime_lock, "current_host", _landmine)

    verdicts = {}
    for host, spec, name in (
        (HOST_LINUX_AARCH64, VENV_DARWIN, "linux-host-darwin-venv"),
        (HOST_MACOS_ARM64, VENV_LINUX, "darwin-host-linux-venv"),
    ):
        fake = _write_venv_spec(tmp_path, name, spec)
        report = platform_report(fake, host=host)
        verdicts[name] = (report.ok, _signals(report))
        assert main(["--platform-only", "--venv", str(fake)], host=host) == (
            EXIT_PLATFORM_MISMATCH
        )

    expected = {
        "compiled-extension-platform",
        "declared-version",
        "builder-interpreter-absent",
        "incompatible-lib-tree",
    }
    assert verdicts["linux-host-darwin-venv"] == (False, expected)
    assert verdicts["darwin-host-linux-venv"] == (False, expected)
    # Same verdict, opposite platforms: the answer is a fact about the pair.
    assert verdicts["linux-host-darwin-venv"] == verdicts["darwin-host-linux-venv"]


def test_a_venv_native_to_its_host_raises_no_platform_signal(tmp_path):
    """Why a hardcoded fixture cannot prove the refusal on its own platform.

    The macOS venv fixture above, read by a macOS host, is not foreign at all:
    the compiled extensions load, the declared version matches, the lib tree is
    the right one. Asserting those three signals from that fixture alone is an
    assertion that only holds off macOS — which is precisely how this suite
    passed on Linux and failed on the Mac it was written to protect.
    """
    native = _write_venv_spec(tmp_path, "native", VENV_DARWIN)
    report = platform_report(native, host=HOST_MACOS_ARM64_PY312)
    assert _signals(report) == {"builder-interpreter-absent"}, report.problems
    # The one surviving problem is about a missing directory, not about a
    # platform, so it can never distinguish the two operating systems.
    assert "darwin" not in "\n".join(report.problems)


def test_the_real_shared_venv_is_refused_by_the_other_operating_system():
    """The production incident, against the REAL `backend/.venv`.

    `backend/.venv` is ONE path shared by every machine that checks this repo
    out, and it can only ever have been built by one of them. Whichever that
    was, the OTHER operating system must refuse it — and which one is "the
    other" is read out of the venv's own binaries, never out of the machine
    running pytest.
    """
    shared = BACKEND / ".venv"
    if not shared.is_dir():  # no venv checked out here; nothing to judge
        return
    built_for = platform_report(shared, host=HOST_LINUX_AARCH64).venv_platform
    # Pick the host that CANNOT be the builder, from the venv's binaries alone.
    other = HOST_MACOS_ARM64 if "linux" in built_for else HOST_LINUX_AARCH64
    report = platform_report(shared, host=other)
    assert not report.ok, (
        f"the shared venv (built for {built_for}) was accepted by "
        f"{other.describe()} — the cross-platform trap is no longer detected"
    )
    assert any("tagged for platform" in p for p in report.problems), report.problems
    assert f"can only load '{other.ext_platform}'" in "\n".join(report.problems)


def test_platform_mismatch_is_not_confusable_with_a_missing_package(tmp_path, capsys):
    """Distinct exit status AND distinct wording from ``MISSING``/``MISMATCH``."""
    fake = _write_venv_spec(tmp_path, "foreign", VENV_DARWIN)
    assert EXIT_PLATFORM_MISMATCH not in (EXIT_LOCK_VIOLATION, EXIT_LOCK_UNREADABLE)
    # The platform question is answered BEFORE the lock is even opened, so a
    # foreign venv cannot be reported as "you are missing alembic". The host is
    # named so the venv is foreign on every machine, not only off macOS.
    rc = main(
        ["--venv", str(fake), "--lock", str(tmp_path / "does-not-exist.lock")],
        host=HOST_LINUX_AARCH64,
    )
    assert rc == EXIT_PLATFORM_MISMATCH, "the lock error won the race"
    err = capsys.readouterr().err
    assert "NOT INSTALLED" not in err
    assert "MISSING" not in err
    assert "This is NOT a missing package" in err


def test_platform_failure_names_the_exact_rebuild_command(tmp_path, capsys):
    fake = _write_venv(
        tmp_path / "proj" / ".venv",
        home="/nowhere/at/all/bin",
        version="3.12.4",
        abi="312-darwin",
        libdir="python3.12",
    )
    assert main(["--platform-only", "--venv", str(fake)]) == EXIT_PLATFORM_MISMATCH
    err = capsys.readouterr().err
    host = current_host()
    scoped = f".venv-{host.system}-{host.machine}"
    assert scoped == host.venv_dir_name
    assert f"python3 -m venv {tmp_path / 'proj' / scoped}" in err
    assert f"{tmp_path / 'proj' / scoped}/bin/python -m pip install -r " in err
    assert ".venv-$(uname -s)-$(uname -m)" in err


def test_pyvenv_cfg_home_without_any_interpreter_is_detected(tmp_path):
    empty_home = tmp_path / "emptyhome"
    empty_home.mkdir()
    host = current_host()
    venv = _write_venv(
        tmp_path / "v",
        home=str(empty_home),
        version=".".join(str(p) for p in host.version),
        abi=host.ext_tag.replace("cpython-", ""),
        libdir=f"python{host.short_version}",
    )
    report = platform_report(venv, host=host)
    assert any("contains no interpreter" in p for p in report.problems), report.problems


def test_pyvenv_cfg_home_interpreter_of_the_wrong_version_is_detected(tmp_path):
    """`home` exists and holds a python — but not the one that built the venv."""
    home = tmp_path / "wronghome"
    home.mkdir()
    shim = home / "python3"
    shim.write_text("#!/bin/sh\necho '3 7 17'\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    host = current_host()
    venv = _write_venv(
        tmp_path / "v",
        home=str(home),
        version=".".join(str(p) for p in host.version),
        abi=host.ext_tag.replace("cpython-", ""),
        libdir=f"python{host.short_version}",
    )
    report = platform_report(venv, host=host)
    assert any(
        "which is Python 3.7.17" in p and "not the" in p for p in report.problems
    ), report.problems


def test_a_venv_with_no_pyvenv_cfg_is_refused(tmp_path):
    bare = tmp_path / "bare"
    (bare / "lib").mkdir(parents=True)
    report = platform_report(bare)
    assert not report.ok
    assert any("pyvenv.cfg" in p for p in report.problems), report.problems


@pytest.mark.parametrize("runner", [FULL_SUITE, BROWSER_GATE], ids=["suite", "gate"])
def test_runners_prefer_a_platform_scoped_venv_before_the_shared_one(runner: Path):
    source = runner.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert 'PLATFORM_VENV=".venv-$(uname -s)-$(uname -m)"' in body, (
        f"{runner.name} does not derive a platform-scoped virtualenv name"
    )
    candidates = re.search(r"VENV_CANDIDATES=\((.*?)\n\s*\)", body, re.S)
    assert candidates, f"{runner.name} has no explicit VENV_CANDIDATES list"
    listed = [c.strip() for c in candidates.group(1).splitlines() if c.strip()]
    scoped = [i for i, c in enumerate(listed) if "$PLATFORM_VENV" in c]
    shared = [i for i, c in enumerate(listed) if re.search(r"/\.venv/bin/python", c)]
    assert scoped, f"{runner.name} never offers the platform-scoped virtualenv"
    assert shared, f"{runner.name} dropped the shared .venv fallback entirely"
    assert min(scoped) < min(shared), (
        f"{runner.name} must try the platform-scoped venv BEFORE the shared "
        f"one; got {listed}"
    )
    # And the shared one is only ACCEPTED if it proves it belongs here.
    assert "--platform-only" in body, (
        f"{runner.name} selects a virtualenv without running the platform check"
    )
    assert re.search(r"check_runtime_lock\.py\"? --platform-only", body), (
        f"{runner.name} does not gate candidate selection on the platform check"
    )


@pytest.mark.parametrize("runner", [FULL_SUITE, BROWSER_GATE], ids=["suite", "gate"])
def test_runners_still_refuse_a_bare_python3_after_the_platform_change(runner: Path):
    """The F2 rule survives F5: no bare python3, no /tmp interpreter, ever."""
    source = runner.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    candidates = re.search(r"VENV_CANDIDATES=\((.*?)\n\s*\)", body, re.S)
    assert candidates
    listed = candidates.group(1)
    assert "/tmp/" not in listed
    assert not re.search(r"(^|[\s\"])python3?([\s\"]|$)", listed), listed
    assert not re.search(r"for cand in[^\n]*\bpython3\b", body)
    # A candidate that fails the platform check must be SKIPPED, never used
    # with a warning: the loop body has no `else PYTHON=` escape hatch.
    assert not re.search(r"PYTHON=\"?\$\{?cand\}?\"?\s*;?\s*#?\s*fallback", body)
    # `PYTHON=` set explicitly still wins verbatim.
    assert 'if [[ -n "${PYTHON:-}" ]]' in body


def test_platform_scoped_venv_directories_are_gitignored():
    ignore = [
        line.strip()
        for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    ]
    assert any(line in {".venv/", ".venv"} for line in ignore)
    assert ".venv-*/" in ignore, (
        "add '.venv-*/' to .gitignore — the platform-scoped virtualenvs "
        "(.venv-Linux-aarch64, .venv-Darwin-arm64, ...) must stay untracked"
    )
    assert "venv-*/" in ignore


def test_the_platform_and_venv_platform_reach_the_gate_log_header(capsys):
    """F5.4: every gate log's runtime header names BOTH platforms."""
    assert main(["--header", "--only", "fastapi", "--lock", str(LOCK)]) == 0
    out = capsys.readouterr().out
    header = out.splitlines()
    assert header[0].startswith("python=")
    assert header[1].startswith("host-platform="), header[:2]
    assert "venv-platform=" in header[1]
    host = current_host()
    assert f"{host.system}/{host.machine}" in header[1]
    # And both runners really do put that report into the file they append to.
    for runner, needle in (
        (FULL_SUITE, "RUNTIME_HEADER"),
        (BROWSER_GATE, "RUNTIME_HEADER"),
    ):
        body = runner.read_text(encoding="utf-8")
        assert needle in body
        assert "host platform:" in body, f"{runner.name} header omits the host platform"
        assert '"$LOCK_REPORT"' in body, (
            f"{runner.name} does not stamp the platform-bearing lock report into "
            "its raw log"
        )


def test_platform_check_is_bounded_and_does_not_follow_the_real_venv(tmp_path):
    """The scan is a walk of a synthesised tree; the real venv is never written."""
    before = os.stat(BACKEND / ".venv").st_mtime if (BACKEND / ".venv").exists() else None
    fake = _write_venv(
        tmp_path / "v",
        home="/nowhere/bin",
        version="9.9.9",
        abi="999-plan9-fake",
        libdir="python9.9",
    )
    assert platform_report(fake).ok is False
    if before is not None:
        assert os.stat(BACKEND / ".venv").st_mtime == before

#!/usr/bin/env python
"""F2 — prove THIS interpreter matches ``backend/requirements.lock``, or refuse.

Both runners (``backend/scripts/full_suite.sh`` and
``scripts/wave2_tutoring_browser_gate.sh``) call this BEFORE they start a
service, a migration or a test process, so a run can never get far enough to
produce evidence against an interpreter nobody declared.

It answers four questions, in this order, and the ORDER is the point:

0. does this virtualenv even BELONG to the operating system and CPU now running
   it?  -> ``PLATFORM MISMATCH`` (exit 5)
1. does each pinned requirement APPLY to this environment at all? A PEP 508
   marker (``exceptiongroup==1.3.1 ; python_version < "3.11"``) says a
   stdlib-backport is needed only below 3.11, so on 3.11+ it must NOT be
   installed -> ``SKIPPED / NOT APPLICABLE`` (not a failure, and never queried
   from installed metadata)
2. is every APPLICABLE pinned distribution installed at all? -> ``MISSING``
   (exit 3)
3. is the installed version the pinned one? -> ``MISMATCH`` (exit 3)

Why question 1 exists
---------------------
The first version of this checker read a lock line with
``line.partition("==")`` and ``version.split(" ")[0]``, which parsed
``exceptiongroup==1.3.1 ; python_version < "3.11"`` as an UNCONDITIONAL pin: the
marker was silently thrown away. On CPython 3.12 that made the checker demand
two stdlib backports (``exceptiongroup``, ``tomli``) that 3.12 must not have,
report them MISSING, and refuse to start the suite — a gate failing because of
its own parser. Lock lines are therefore parsed by
:class:`packaging.requirements.Requirement` and their markers evaluated against
a real PEP 508 environment. There is no string surgery and no regex anywhere
near a marker.

and prints the resolved version of each pin either way, so the raw log of every
gate carries the executable and the versions the evidence was produced with.

Why question 0 exists, and why it runs FIRST
--------------------------------------------
``backend/.venv`` is ONE path shared by every machine that checks the repo out.
A virtualenv is not portable: its ``pyvenv.cfg`` names a ``home`` interpreter on
the machine that built it, and its site-packages hold compiled extensions tagged
for one ABI (``_cffi_backend.cpython-310-aarch64-linux-gnu.so`` is a Linux/arm64
ELF object and cannot be loaded by anything else). Build it on Linux, read it on
macOS, and the SAME directory is simultaneously healthy and unusable — and the
lock check, asked only questions 1 and 2, reported PASS on the Linux side while
the macOS side got ``MISSING`` for alembic/psycopg/pgvector. "Missing package"
is a completely wrong diagnosis of "wrong operating system", and it is the
diagnosis that sends somebody off to reinstall packages into a venv that can
never work. So the platform question is asked BEFORE any pin is looked at, and
it fails with its OWN exit status and its OWN wording.

Usage:
    python backend/scripts/check_runtime_lock.py            # verify, print, exit
    python backend/scripts/check_runtime_lock.py --header   # one-line summary too
    python backend/scripts/check_runtime_lock.py --only fastapi,SQLAlchemy
    python backend/scripts/check_runtime_lock.py --platform-only   # question 0
    python backend/scripts/check_runtime_lock.py --platform-only --venv DIR

Exit codes: 0 = every check satisfied, 3 = at least one MISSING/MISMATCH,
4 = the lock file itself could not be read (absent, unparseable, or carrying a
requirement that is not an exact ``==`` pin), 5 = PLATFORM MISMATCH (this
virtualenv was built for a different OS/CPU than the interpreter running it).
"""
from __future__ import annotations

import argparse
import os
import platform as _platform
import re
import subprocess
import sys
import sysconfig
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement

DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "requirements.lock"

#: Distinct from 3 (`MISSING`/`MISMATCH`) and 4 (unreadable lock) on purpose:
#: a caller — human or shell — must be able to tell "wrong machine" apart from
#: "wrong versions" without parsing prose.
EXIT_PLATFORM_MISMATCH = 5
EXIT_LOCK_VIOLATION = 3
EXIT_LOCK_UNREADABLE = 4

#: PEP 503 name normalisation: ``SQLAlchemy``, ``sqlalchemy`` and
#: ``typing_extensions`` must all match the distribution actually installed.
_NORMALISE = re.compile(r"[-_.]+")


def normalise(name: str) -> str:
    return _NORMALISE.sub("-", name).lower()


class LockFileError(Exception):
    """The lock file itself cannot be trusted — reported as exit 4.

    Raised for a line that is not a valid PEP 508 requirement at all, and for a
    line that is a valid requirement but not an EXACT ``==`` pin. Both are
    "the lock is unreadable", not "the environment is wrong": nothing was
    measured, so nothing can be concluded about the interpreter.
    """


def marker_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """The PEP 508 marker environment to evaluate lock markers against.

    Defaults to :func:`packaging.markers.default_environment` — the interpreter
    that is DOING the checking, described in the standard's own variable names
    (``python_version``, ``sys_platform``, ``platform_machine``, ...).

    ``overrides`` is the injection seam, and it is deliberately the same shape
    as the ``HostFacts`` seam :func:`platform_report` and :func:`main` already
    take: a test states "given a Python 3.12 environment" as DATA and gets the
    same verdict on every machine, instead of needing a 3.12 interpreter to be
    installed before the 3.12 behaviour can be asserted at all.
    """
    environment = dict(default_environment())
    if overrides:
        environment.update({str(k): str(v) for k, v in overrides.items()})
    return environment


@dataclass(frozen=True)
class LockEntry:
    """One lock line, parsed by ``packaging`` — never by string surgery.

    The old parser did ``line.partition("==")`` and then
    ``version.strip().split(" ")[0]``, which SILENTLY DISCARDED any PEP 508
    marker: ``exceptiongroup==1.3.1 ; python_version < "3.11"`` was read as an
    unconditional pin, so a Python 3.12 interpreter — which must not have that
    stdlib backport installed — was reported MISSING and the gate refused to
    run. A marker is part of the requirement, so it is parsed and EVALUATED,
    and every field of the requirement survives into this record: the name as
    written, its PEP 503 normalisation, the exact pin, the extras and the
    complete marker expression.
    """

    name: str  # exactly as written in the lock file
    key: str  # PEP 503 normalised, the form metadata is matched on
    version: str  # the exact `==` pin
    extras: tuple[str, ...] = ()
    marker: str = ""  # the COMPLETE marker expression, "" when there is none
    applicable: bool = True  # marker absent, or marker true for the environment

    @property
    def display(self) -> str:
        """``psycopg[binary]`` — the name plus its extras, as pinned."""
        if not self.extras:
            return self.name
        return f"{self.name}[{','.join(self.extras)}]"

    def requirement_line(self) -> str:
        """The requirement this entry came from, rebuilt in canonical form."""
        line = f"{self.display}=={self.version}"
        return f"{line} ; {self.marker}" if self.marker else line


def parse_requirement(line: str, *, lock_path: Path | None = None) -> Requirement:
    """One lock line -> :class:`packaging.requirements.Requirement`.

    Fails CLOSED: an unparseable line is a :class:`LockFileError`, never a line
    that is skipped or half-understood.
    """
    try:
        return Requirement(line)
    except InvalidRequirement as exc:
        where = f"{lock_path}: " if lock_path is not None else ""
        raise LockFileError(
            f"{where}{line!r} is not a valid PEP 508 requirement: {exc}"
        ) from exc


def exact_version(requirement: Requirement, *, lock_path: Path | None = None) -> str:
    """The single ``==`` version a lock entry must carry, or refuse.

    A lock file states WHICH version was executed. ``>=``, ``~=``, a range, a
    wildcard ``==1.2.*`` or a direct URL reference all mean "some version", so
    they are refused rather than resolved to whatever happens to be installed.
    """
    where = f"{lock_path}: " if lock_path is not None else ""
    if requirement.url:
        raise LockFileError(
            f"{where}'{requirement}' is a direct reference, not an EXACT pin; a "
            f"lock file may only contain 'name==version' requirements"
        )
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==" or (
        specifiers[0].version.endswith(".*")
    ):
        raise LockFileError(
            f"{where}'{requirement}' is not an EXACT pin; a lock file may only "
            f"contain 'name==version' requirements"
        )
    return specifiers[0].version


def read_lock(
    lock_path: Path, *, environment: Mapping[str, str] | None = None
) -> list[LockEntry]:
    """Every lock entry, parsed and marker-EVALUATED, in lock-file order.

    ``environment`` is passed through to :func:`marker_environment`; ``None``
    means "this interpreter". Entries whose marker is false are returned with
    ``applicable=False`` rather than dropped, so the report can SAY they were
    skipped instead of quietly shrinking.
    """
    env = marker_environment(environment)
    entries: list[LockEntry] = []
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement = parse_requirement(line, lock_path=lock_path)
        version = exact_version(requirement, lock_path=lock_path)
        marker = requirement.marker
        entries.append(
            LockEntry(
                name=requirement.name,
                key=normalise(requirement.name),
                version=version,
                extras=tuple(sorted(requirement.extras)),
                marker=str(marker) if marker is not None else "",
                applicable=True if marker is None else bool(marker.evaluate(env)),
            )
        )
    return entries


def read_pins(lock_path: Path) -> list[tuple[str, str]]:
    """``[(distribution, exact version), ...]`` in lock-file order.

    The FILE-level view: every entry, applicable or not, because "what does the
    lock pin" is a question about the file and not about any one interpreter.
    Applicability lives on :class:`LockEntry` (see :func:`read_lock`).
    """
    return [(entry.name, entry.version) for entry in read_lock(lock_path)]


def installed_versions() -> dict[str, str]:
    found: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        found[normalise(name)] = dist.version
    return found


class InstalledIndex:
    """Installed-distribution metadata, read LAZILY and asked per name.

    Laziness is a correctness property here, not a micro-optimisation: a
    requirement whose marker is false describes a dependency this interpreter
    must NOT have, so asking the metadata about it — and reporting whatever
    comes back — is exactly the bug. Nothing installed is inspected until an
    APPLICABLE entry needs an answer, and a test proves it by replacing
    :func:`installed_versions` with a landmine that raises when called.
    """

    def __init__(self) -> None:
        self._table: dict[str, str] | None = None

    @property
    def loaded(self) -> bool:
        return self._table is not None

    def version(self, key: str) -> str | None:
        if self._table is None:
            # Resolved through the module global on purpose: that is the seam a
            # test replaces.
            self._table = installed_versions()
        return self._table.get(key)


# ---------------------------------------------------------------------------
# Question 0: does this virtualenv belong to the machine that is running it?
# ---------------------------------------------------------------------------

#: Compiled-extension file suffixes, longest first so ``.abi3.so`` still ends
#: at ``.so``.
_EXT_SUFFIXES = (".so", ".pyd", ".dylib")

#: ``cpython-310-aarch64-linux-gnu`` / ``cpython-312-darwin`` — PEP 3149.
_LONG_IMPL = {"cpython", "pypy", "graalpy", "jython"}
#: ``cp310-win_amd64`` / ``pp39-pypy39_pp73-darwin`` — the short wheel form.
_SHORT_IMPL = re.compile(r"^(?:cp|pp|gp|jy)(\d+)$", re.I)

#: Where a virtualenv keeps its packages, on every platform this repo runs on.
_SITE_GLOBS = ("lib/python*/site-packages", "lib64/python*/site-packages",
               "Lib/site-packages")

#: Never walk an unbounded tree: a healthy venv answers in the first few
#: thousand entries, and a pathological one must not hang a gate.
_SCAN_BUDGET = 40000


def extension_abi(filename: str) -> tuple[str, str] | None:
    """``('310', 'aarch64-linux-gnu')`` from a PEP 3149 extension file name.

    Returns ``None`` for anything whose name carries no judgeable platform tag
    — a bare ``_speedups.so`` or a stable-ABI ``_rust.abi3.so``. Those are
    silently skipped rather than guessed at: an absent tag is not evidence.
    """
    stem = None
    for suffix in _EXT_SUFFIXES:
        if filename.endswith(suffix):
            stem = filename[: -len(suffix)]
            break
    if stem is None or "." not in stem:
        return None
    tag = stem.rsplit(".", 1)[1]
    if not tag or tag == "abi3":
        return None
    parts = tag.split("-")
    if parts[0].lower() in _LONG_IMPL and len(parts) >= 3 and parts[1].isdigit():
        return parts[1], "-".join(parts[2:])
    short = _SHORT_IMPL.match(parts[0])
    if short and len(parts) >= 2:
        return short.group(1), "-".join(parts[1:])
    return None


@dataclass(frozen=True)
class HostFacts:
    """What the interpreter DOING the checking is, in the terms that matter."""

    executable: str
    version: tuple[int, int, int]
    system: str  # exactly `uname -s`
    machine: str  # exactly `uname -m`
    sysconfig_platform: str
    ext_tag: str  # e.g. 'cpython-310-aarch64-linux-gnu'
    ext_platform: str  # e.g. 'aarch64-linux-gnu'

    @property
    def short_version(self) -> str:
        return f"{self.version[0]}.{self.version[1]}"

    @property
    def venv_dir_name(self) -> str:
        """The platform-scoped virtualenv directory name for THIS host."""
        return f".venv-{self.system}-{self.machine}"

    def describe(self) -> str:
        return (
            f"{self.system}/{self.machine} "
            f"(sysconfig {self.sysconfig_platform}, ext tag {self.ext_tag or 'unknown'})"
        )


def current_host() -> HostFacts:
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ""
    parsed = extension_abi(suffix) if suffix else None
    tag = suffix
    for candidate in _EXT_SUFFIXES:
        if tag.endswith(candidate):
            tag = tag[: -len(candidate)]
            break
    return HostFacts(
        executable=sys.executable,
        version=tuple(sys.version_info[:3]),  # type: ignore[arg-type]
        system=_platform.system(),
        machine=_platform.machine(),
        sysconfig_platform=sysconfig.get_platform(),
        ext_tag=tag.lstrip("."),
        ext_platform=parsed[1] if parsed else "",
    )


def read_pyvenv_cfg(venv_root: Path) -> dict[str, str]:
    """``pyvenv.cfg`` as a dict. Missing file -> ``{}`` (the caller decides)."""
    cfg_path = venv_root / "pyvenv.cfg"
    values: dict[str, str] = {}
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        values[key.strip().lower()] = value.strip()
    return values


def scan_venv_abis(venv_root: Path) -> tuple[dict[str, int], dict[str, str]]:
    """``({platform_tag: count}, {platform_tag: first file seen})``.

    Every site-packages tree inside the venv is scanned, not only the one the
    RUNNING interpreter would import from — the whole point is to notice a
    ``lib/python3.10`` tree that a 3.9 interpreter cannot even see.
    """
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}
    seen = 0
    roots: list[Path] = []
    for pattern in _SITE_GLOBS:
        roots.extend(sorted(venv_root.glob(pattern)))
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                seen += 1
                if seen > _SCAN_BUDGET:
                    return counts, samples
                parsed = extension_abi(name)
                if parsed is None:
                    continue
                tag = parsed[1]
                counts[tag] = counts.get(tag, 0) + 1
                samples.setdefault(tag, str(Path(dirpath, name)))
    return counts, samples


def _home_interpreter(home: Path, want_short: str) -> tuple[Path | None, list[Path]]:
    """The interpreter ``pyvenv.cfg``'s ``home`` points at, and what was tried."""
    names = [f"python{want_short}", f"python{want_short}.exe", "python3",
             "python3.exe", "python", "python.exe"]
    tried = [home / n for n in names]
    for candidate in tried:
        if candidate.is_file() or candidate.is_symlink():
            return candidate, tried
    return None, tried


def _probe_version(exe: Path) -> tuple[int, int, int] | None:
    """Ask an interpreter its own version. Any failure -> ``None``, never a guess."""
    try:
        proc = subprocess.run(
            [str(exe), "-c", "import sys;print('%d %d %d' % sys.version_info[:3])"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        parts = proc.stdout.split()
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return None


@dataclass
class PlatformReport:
    host: HostFacts
    venv_root: Path | None
    is_venv: bool
    cfg: dict[str, str] = field(default_factory=dict)
    abi_counts: dict[str, int] = field(default_factory=dict)
    abi_samples: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def venv_platform(self) -> str:
        """The platform this venv's COMPILED CONTENT was built for."""
        if not self.abi_counts:
            return "unknown (no ABI-tagged compiled extension found)"
        return max(self.abi_counts.items(), key=lambda kv: kv[1])[0]

    def header_line(self) -> str:
        root = str(self.venv_root) if self.venv_root else "<none: not a virtualenv>"
        return (
            f"host-platform={self.host.describe()} "
            f"venv={root} venv-platform={self.venv_platform} "
            f"platform-check={'OK' if self.ok else 'MISMATCH'}"
        )


def platform_report(
    venv_root: Path | None = None, *, host: HostFacts | None = None
) -> PlatformReport:
    """Question 0, as data. ``venv_root=None`` means "the venv I am running in".

    Split out from :func:`main` so a test can point it at a SYNTHESISED foreign
    venv in a tmp dir and prove the refusal, without going anywhere near the
    real one.
    """
    facts = host or current_host()
    explicit = venv_root is not None
    root = Path(venv_root) if explicit else Path(sys.prefix)
    is_venv = explicit or (Path(sys.prefix) != Path(sys.base_prefix))
    report = PlatformReport(
        host=facts, venv_root=root if is_venv else None, is_venv=is_venv
    )
    if not is_venv:
        report.notes.append(
            f"{facts.executable} is not running inside a virtualenv "
            f"(sys.prefix == sys.base_prefix == {sys.prefix}); there is no "
            "pyvenv.cfg to judge, so only the interpreter's own tags are reported"
        )
        return report

    report.cfg = read_pyvenv_cfg(root)
    report.abi_counts, report.abi_samples = scan_venv_abis(root)

    # ---- (a) compiled extensions must be loadable by THIS interpreter -------
    foreign = {
        tag: n
        for tag, n in report.abi_counts.items()
        if facts.ext_platform and tag != facts.ext_platform
    }
    for tag, count in sorted(foreign.items(), key=lambda kv: -kv[1]):
        report.problems.append(
            f"{count} compiled extension(s) are tagged for platform '{tag}', "
            f"but this interpreter can only load '{facts.ext_platform}' "
            f"(e.g. {report.abi_samples.get(tag, '?')})"
        )
    if not report.abi_counts:
        report.notes.append(
            "no ABI-tagged compiled extension was found in this venv, so the "
            "extension evidence is absent (not a pass on its own)"
        )

    # ---- (b) pyvenv.cfg must exist and describe THIS interpreter ------------
    if not report.cfg:
        report.problems.append(
            f"{root / 'pyvenv.cfg'} is missing or unreadable, so this directory "
            "cannot prove it is a virtualenv built for any machine at all"
        )
        return report

    declared = report.cfg.get("version") or report.cfg.get("version_info") or ""
    declared_parts = [p for p in declared.split(".") if p.isdigit()]
    declared_short = ".".join(declared_parts[:2]) if len(declared_parts) >= 2 else ""
    if declared_short and declared_short != facts.short_version:
        report.problems.append(
            f"pyvenv.cfg declares version {declared} but the interpreter running "
            f"it is {'.'.join(str(p) for p in facts.version)} — this venv was "
            f"built by a different Python than the one now using it"
        )

    # ---- (c) the `home` interpreter must exist and match the venv's version -
    home_raw = report.cfg.get("home", "")
    if not home_raw:
        report.problems.append("pyvenv.cfg has no `home` key; it names no builder")
    else:
        home = Path(home_raw)
        if not home.is_dir():
            report.problems.append(
                f"pyvenv.cfg home = {home_raw} does not exist on this machine — "
                "the interpreter that built this venv is not here"
            )
        else:
            want = declared_short or facts.short_version
            exe, tried = _home_interpreter(home, want)
            if exe is None:
                report.problems.append(
                    f"pyvenv.cfg home = {home_raw} contains no interpreter "
                    f"(tried {', '.join(p.name for p in tried)})"
                )
            elif exe.name not in {f"python{want}", f"python{want}.exe"}:
                # The versioned name the venv claims is absent, so the only
                # honest way to learn what `home` really holds is to ask it.
                actual = _probe_version(exe)
                if actual is None:
                    report.problems.append(
                        f"pyvenv.cfg home = {home_raw} has no python{want} and "
                        f"{exe} could not be asked for its version"
                    )
                elif f"{actual[0]}.{actual[1]}" != want:
                    report.problems.append(
                        f"pyvenv.cfg home = {home_raw} resolves to {exe} which is "
                        f"Python {actual[0]}.{actual[1]}.{actual[2]}, not the "
                        f"{want} this venv was built with"
                    )

    # ---- (d) the venv's own package tree must be one this interpreter reads --
    lib_versions = sorted(
        {p.name.replace("python", "") for p in root.glob("lib/python*") if p.is_dir()}
    )
    if lib_versions and facts.short_version not in lib_versions:
        report.problems.append(
            f"this venv keeps its packages under lib/python{', lib/python'.join(lib_versions)}"
            f", which a Python {facts.short_version} interpreter never imports from"
        )
    return report


def format_platform_failure(report: PlatformReport, *, lock_path: Path) -> str:
    facts = report.host
    venv_name = facts.venv_dir_name
    root = report.venv_root
    where = ""
    if root is not None:
        try:
            parent = root.parent
            where = f"{parent}/{venv_name}"
        except (OSError, ValueError):  # pragma: no cover - defensive
            where = f"backend/{venv_name}"
    else:  # pragma: no cover - defensive
        where = f"backend/{venv_name}"
    return (
        "\nPLATFORM MISMATCH (exit 5): this virtualenv was NOT built for the "
        "operating system / CPU that is now running it.\n"
        "\n  This is NOT a missing package and reinstalling packages will not "
        "fix it. A virtualenv is machine-bound: its pyvenv.cfg names a builder "
        "interpreter and its compiled extensions are ABI-tagged binaries. One "
        "shared .venv path read from two operating systems is healthy on one "
        "and unusable on the other, and only this check can tell you which.\n"
        f"\n  interpreter    : {facts.executable}\n"
        f"  interpreter is : Python {'.'.join(str(p) for p in facts.version)} "
        f"on {facts.describe()}\n"
        f"  virtualenv     : {root}\n"
        f"  venv built for : {report.venv_platform}\n"
        f"  pyvenv.cfg     : home={report.cfg.get('home', '<none>')} "
        f"version={report.cfg.get('version', '<none>')}\n"
        "\n  MISMATCHED:\n"
        + "\n".join(f"      - {p}" for p in report.problems)
        + "\n"
        "\n  Fix by building a PLATFORM-SCOPED virtualenv for THIS host — the "
        "runners prefer it over the shared one, so the two operating systems "
        "stop overwriting each other:\n"
        f"      python3 -m venv {where}\n"
        f"      {where}/bin/python -m pip install -r {lock_path}\n"
        f"\n  (the directory name is exactly `.venv-$(uname -s)-$(uname -m)` = "
        f"`{venv_name}`)\n"
    )


def main(
    argv: list[str] | None = None,
    *,
    host: HostFacts | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    """``host`` is the SAME seam :func:`platform_report` already exposes.

    A real invocation never passes it (and then this is byte-for-byte the old
    behaviour: the host is measured with :func:`current_host`). A test passes
    it so it can state "given a Darwin host and a Linux venv" and get the same
    exit status, stdout and stderr on every machine — the platform-refusal
    evidence is about the host under test, not about whoever ran pytest.

    ``environment`` is the same idea for PEP 508 markers: ``None`` measures
    this interpreter with :func:`packaging.markers.default_environment`, and a
    test injects ``{"python_version": "3.12", ...}`` to assert what a 3.12 run
    does without a 3.12 interpreter having to exist on the machine.
    """
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
    parser.add_argument(
        "--platform-only",
        action="store_true",
        help="run ONLY the platform check (question 0) and exit 0 or 5",
    )
    parser.add_argument(
        "--venv",
        default="",
        help="platform-check this virtualenv directory instead of sys.prefix",
    )
    args = parser.parse_args(argv)

    lock_path = Path(args.lock)

    # ---- question 0 FIRST, always ------------------------------------------
    # Ahead of the lock file even being opened: on a platform-mismatched venv
    # every pin looks MISSING, and answering "you are missing alembic" to "you
    # are on the wrong operating system" is the exact wrong answer that made
    # this check necessary.
    plat = platform_report(Path(args.venv) if args.venv else None, host=host)
    if args.header:
        print(
            f"python={sys.executable} version={sys.version.split()[0]} "
            f"lock={lock_path}"
        )
    if args.header or args.platform_only:
        print(plat.header_line())
    if not plat.ok:
        print(
            format_platform_failure(plat, lock_path=lock_path.resolve()),
            file=sys.stderr,
        )
        return EXIT_PLATFORM_MISMATCH
    if args.platform_only:
        for note in plat.notes:
            print(f"  note: {note}")
        print(
            f"platform check: this virtualenv belongs to {plat.host.describe()}"
            if plat.is_venv
            else f"platform check: {plat.host.executable} is a non-virtualenv "
            f"interpreter on {plat.host.describe()}"
        )
        return 0

    if not lock_path.is_file():
        print(f"RUNTIME LOCK MISSING: {lock_path} does not exist", file=sys.stderr)
        return EXIT_LOCK_UNREADABLE
    try:
        entries = read_lock(lock_path, environment=environment)
    except LockFileError as exc:
        print(f"RUNTIME LOCK ERROR: {exc}", file=sys.stderr)
        return EXIT_LOCK_UNREADABLE
    wanted = {normalise(n) for n in args.only.split(",") if n.strip()}
    if wanted:
        entries = [e for e in entries if e.key in wanted]
        unknown = wanted - {e.key for e in entries}
        if unknown:
            print(
                f"RUNTIME LOCK ERROR: {sorted(unknown)} are not pinned in {lock_path}",
                file=sys.stderr,
            )
            return EXIT_LOCK_UNREADABLE

    installed = InstalledIndex()
    problems: list[str] = []
    skipped: list[LockEntry] = []
    width = max((len(e.display) for e in entries), default=10)
    for entry in entries:
        if not entry.applicable:
            # NOT queried from installed metadata, on purpose: this requirement
            # does not apply to this environment, so what is or is not installed
            # under that name is not evidence about anything.
            skipped.append(entry)
            print(
                f"  {entry.display:<{width}}  pinned={entry.version:<12} "
                f"installed={'(not queried)':<12} SKIPPED / NOT APPLICABLE "
                f"(marker `{entry.marker}` is false for this environment)"
            )
            continue
        actual = installed.version(entry.key)
        if actual is None:
            state, problems = "MISSING", problems + [
                f"      {entry.requirement_line()}  -> NOT INSTALLED"
            ]
            actual = "-"
        elif actual != entry.version:
            state = "MISMATCH"
            problems.append(f"      {entry.requirement_line()}  -> found {actual}")
        else:
            state = "ok"
        print(
            f"  {entry.display:<{width}}  pinned={entry.version:<12} "
            f"installed={actual:<12} {state}"
        )

    if problems:
        print(
            "\nPREREQUISITE NOT MET: this interpreter does not match the "
            "repository runtime lock, so anything it produced would be evidence "
            "about a different dependency set.\n"
            f"\n  interpreter : {sys.executable}\n"
            f"  lock file   : {lock_path}\n"
            "\n  OUT OF PIN:\n" + "\n".join(problems) + "\n"
            "\n  Fix by rebuilding the project virtualenv from the lock. Use the\n"
            "  PLATFORM-SCOPED directory so two operating systems sharing this\n"
            "  checkout stop overwriting each other's binaries:\n"
            f"      python3 -m venv backend/{plat.host.venv_dir_name}\n"
            f"      backend/{plat.host.venv_dir_name}/bin/python -m pip install "
            f"-r {lock_path}\n",
            file=sys.stderr,
        )
        return EXIT_LOCK_VIOLATION
    tail = (
        f" ({len(skipped)} SKIPPED / NOT APPLICABLE to this environment: "
        f"{', '.join(e.display for e in skipped)})"
        if skipped
        else ""
    )
    print(
        f"runtime lock: {len(entries) - len(skipped)} pinned distribution(s) "
        f"satisfied exactly{tail}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

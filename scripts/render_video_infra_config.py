#!/usr/bin/env python3
"""Render the Wave 2 video-plane service configs from the environment.

SAATHI-451 / frozen matrix row H1.

WHY A RENDERER EXISTS AT ALL. Neither livekit-server nor coturn expands
environment variables inside its config file, and both need at least one secret
(the LiveKit API secret; the TURN shared secret). The only ways to reconcile
"config must come from the environment" with "no secret value is committed" are
(a) commit a config file with a real secret in it — never, or (b) commit a
TEMPLATE and render it at deploy time. This is (b).

WHAT IT GUARANTEES, and therefore what an operator does not have to remember:

* every placeholder in the template is resolved, or nothing is written at all
  (a half-rendered config is a server that boots with a literal ``${...}`` in it);
* no rendered secret is a known placeholder / development default — the same
  frozen set ``backend/app/core/config.py`` fails closed on, so the infra cannot
  be brought up in a state the application would then refuse to run against;
* ``forced-turn`` (the default) cannot be talked into advertising a
  browser-reachable SFU address, because that value is not templated;
* ``direct`` refuses to render without ``LIVEKIT_ADVERTISE_IP``;
* the file holding the LiveKit API secret is written 0600; the coturn file, which
  holds no secret and must be readable by the container's ``nobody`` user, 0644;
* NOTHING this script prints is a secret VALUE. It prints setting NAMES, the
  mode, and output paths. Same privacy contract as ``ConfigurationError``.

Usage::

    python3 scripts/render_video_infra_config.py                    # forced-turn
    python3 scripts/render_video_infra_config.py --env-file .env
    python3 scripts/render_video_infra_config.py --mode direct --env-file .env
    python3 scripts/render_video_infra_config.py --check            # no write

Exit status: 0 rendered/valid, 2 configuration problem, 3 usage problem.
"""
from __future__ import annotations

import argparse
import os
import re
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA_DIR = REPO_ROOT / "infra" / "video"
DEFAULT_OUT_DIR = INFRA_DIR / "rendered"

MODES = ("forced-turn", "direct")

#: Mirrors ``backend/app/core/config.py::_PLACEHOLDER_SECRETS``. Duplicated
#: rather than imported because this script must run with a bare ``python3`` on a
#: deployment host, with no backend virtualenv and no ``app`` package on the
#: path. ``backend/tests/test_wave2_video_infra.py`` asserts this set is a
#: SUPERSET of the one config.py enforces, so the two cannot drift apart in the
#: dangerous direction.
PLACEHOLDER_SECRETS = frozenset(
    {
        "", "changeme", "change-me", "change_me", "placeholder", "todo", "tbd",
        "none", "null", "test", "testing", "secret", "dev", "devkey", "devsecret",
        "dev-secret", "example", "xxx", "xxxx", "your-key", "your-key-id",
        "your-secret", "razorpay", "livekit", "rzp_test_key", "key", "api_key",
        "coturn", "turn", "changeit", "password", "sample",
    }
)

#: Values checked against ``PLACEHOLDER_SECRETS``, and never echoed.
SECRET_VARS = ("LIVEKIT_API_SECRET", "TURN_STATIC_AUTH_SECRET")

#: Required for every mode.
COMMON_VARS = (
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "TURN_PUBLIC_HOST",
    "TURN_REALM",
    "TURN_EXTERNAL_IP",
    "TURN_STATIC_AUTH_SECRET",
    "TURN_CREDENTIAL_TTL_SECONDS",
    "VIDEO_WEBHOOK_URL",
)
#: Required in addition, per mode.
MODE_VARS = {"forced-turn": (), "direct": ("LIVEKIT_ADVERTISE_IP",)}

#: The webhook path the committed E2 route is mounted at
#: (backend/app/api/v1/tutoring.py::video_webhook under the /api/v1 prefix).
WEBHOOK_PATH = "/api/v1/video/webhook"

TEMPLATES = {
    "livekit": ("livekit.{mode}.yaml.tmpl", "livekit.yaml", 0o600),
    "coturn": ("turnserver.conf.tmpl", "turnserver.conf", 0o644),
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class RenderError(RuntimeError):
    """A configuration problem. The message names settings, never values."""


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` env file. Comments, blanks and ``export`` tolerated.

    Values are taken literally: no shell expansion, no ``$(...)``. Surrounding
    single/double quotes are stripped because ``.env`` files in the wild have
    them and a quoted secret that silently keeps its quotes is a 401 nobody can
    explain.
    """
    if not path.is_file():
        raise RenderError(f"env file not found: {path}")
    values: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise RenderError(f"{path}:{lineno}: not a KEY=VALUE line")
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def resolve(env_file: Path | None, mode: str) -> dict[str, str]:
    """Merge sources, then validate. Real environment WINS over the file.

    That order is deliberate: an operator overriding one value for a single
    command (``TURN_EXTERNAL_IP=... python3 scripts/render...``) must not have it
    silently reverted by the checked-in-shaped file they are also passing.
    """
    merged: dict[str, str] = {}
    if env_file is not None:
        merged.update(load_env_file(env_file))
    for name in COMMON_VARS + MODE_VARS[mode]:
        from_process = os.environ.get(name)
        if from_process is not None and from_process != "":
            merged[name] = from_process

    problems: list[str] = []
    required = COMMON_VARS + MODE_VARS[mode]
    for name in required:
        if not (merged.get(name) or "").strip():
            problems.append(f"{name} is required for mode '{mode}'")

    for name in SECRET_VARS:
        value = (merged.get(name) or "").strip()
        if value and value.lower() in PLACEHOLDER_SECRETS:
            # NAME only. The value is a placeholder, but printing it would still
            # teach the habit of interpolating secrets into messages.
            problems.append(
                f"{name} is a known placeholder / development default; "
                "generate a real one (openssl rand -hex 32)"
            )
    secret = (merged.get("LIVEKIT_API_SECRET") or "").strip()
    if secret and len(secret) < 16:
        # Matches LiveKitCommunityAdapter's own refusal, so the infra cannot be
        # rendered into a state the adapter would reject at import time.
        problems.append(
            "LIVEKIT_API_SECRET is shorter than 16 characters, which "
            "LiveKitCommunityAdapter refuses as too short to sign grants safely"
        )

    api_key = (merged.get("LIVEKIT_API_KEY") or "").strip()
    if api_key and not _IDENTIFIER_RE.match(api_key):
        # It becomes a YAML mapping KEY in `keys:`; a colon or space there would
        # produce a file that parses into something else entirely.
        problems.append(
            "LIVEKIT_API_KEY must match [A-Za-z0-9_.-]+ (it is used as a YAML key)"
        )

    url = (merged.get("VIDEO_WEBHOOK_URL") or "").strip()
    if url and not url.rstrip("/").endswith(WEBHOOK_PATH):
        problems.append(
            f"VIDEO_WEBHOOK_URL must end with {WEBHOOK_PATH} — that is the route "
            "the committed video webhook handler is mounted at"
        )
    if url and not (url.startswith("http://") or url.startswith("https://")):
        problems.append("VIDEO_WEBHOOK_URL must be an http:// or https:// URL")

    ttl = (merged.get("TURN_CREDENTIAL_TTL_SECONDS") or "").strip()
    if ttl and (not ttl.isdigit() or int(ttl) <= 0):
        problems.append("TURN_CREDENTIAL_TTL_SECONDS must be a positive integer")

    if problems:
        raise RenderError("; ".join(problems))
    return merged


def render_one(template: Path, values: dict[str, str], mode: str) -> str:
    body = template.read_text(encoding="utf-8")
    try:
        rendered = string.Template(body).substitute(values)
    except KeyError as exc:  # placeholder the template needs but nobody declared
        raise RenderError(
            f"{template.name} references undeclared placeholder {exc.args[0]}; "
            "add it to infra/video/.env.example and to COMMON_VARS/MODE_VARS"
        ) from exc
    except ValueError as exc:
        raise RenderError(f"{template.name}: malformed placeholder ({exc})") from exc
    if "${" in rendered:  # pragma: no cover - substitute() would have raised
        raise RenderError(f"{template.name}: unresolved placeholder after render")
    header = (
        f"# GENERATED by scripts/render_video_infra_config.py — DO NOT EDIT.\n"
        f"# source: infra/video/{template.name}\n"
        f"# LEGALSAATHI-VIDEO-MODE: {mode}\n"
        f"# Re-render after any change to the template or the environment.\n"
    )
    return header + rendered


def render(mode: str, values: dict[str, str]) -> dict[str, tuple[str, str, int]]:
    out: dict[str, tuple[str, str, int]] = {}
    for service, (tmpl_name, out_name, file_mode) in TEMPLATES.items():
        template = INFRA_DIR / tmpl_name.format(mode=mode)
        if not template.is_file():
            raise RenderError(f"template missing: {template}")
        out[service] = (out_name, render_one(template, values, mode), file_mode)
    return out


def write(out_dir: Path, rendered: dict[str, tuple[str, str, int]]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    written: list[Path] = []
    for _service, (name, body, file_mode) in sorted(rendered.items()):
        target = out_dir / name
        # Create with the restrictive mode FIRST, then write: a 0600 file that
        # spends a millisecond at 0644 with a secret in it is still a leak.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, file_mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(target, file_mode)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render infra/video service configs from the environment.",
    )
    parser.add_argument("--mode", choices=MODES, default="forced-turn")
    parser.add_argument(
        "--env-file", type=Path, default=None,
        help="KEY=VALUE file to read (the real environment takes precedence)",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--check", action="store_true",
        help="validate and render in memory; write nothing",
    )
    args = parser.parse_args(argv)

    try:
        values = resolve(args.env_file, args.mode)
        rendered = render(args.mode, values)
    except RenderError as exc:
        print(f"video infra config is invalid; refusing to render: {exc}", file=sys.stderr)
        return 2

    if args.check:
        print(f"OK mode={args.mode} templates={len(rendered)} (nothing written)")
        return 0
    try:
        written = write(args.out_dir, rendered)
    except OSError as exc:
        print(f"could not write rendered config: {exc}", file=sys.stderr)
        return 2
    print(f"mode={args.mode}")
    for path in written:
        try:
            shown: Path | str = path.relative_to(REPO_ROOT)
        except ValueError:  # --out-dir outside the repo (tests, staging hosts)
            shown = path
        print(f"wrote {shown} mode={oct(path.stat().st_mode & 0o777)}")
    print(
        "next: docker compose -f docker-compose.yml "
        "-f infra/video/docker-compose.video.yml --profile video up -d coturn livekit"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())

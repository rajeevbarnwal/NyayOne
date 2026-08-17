#!/usr/bin/env python3
"""Fail closed when uploadable CI evidence contains secrets or raw PII.

Only textual evidence can pass this dependency-free phase-one policy. Visual
formats, PDFs, opaque containers and unknown binary payloads are rejected:
without a pinned pixel/OCR inspector, accepting them would be a false privacy
claim. ZIP files are the sole supported container and every member, path and
comment is dispatched through the same policy.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import io
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_to_bytes
import zipfile


PATTERNS = {
    "authorization credential": re.compile(
        rb"authorization[\"']?\s*[:=]\s*[\"']?\s*"
        rb"(?:bearer|basic|token|api[-_ ]?key)\s+"
        rb"(?P<value>[^\s,\"']{4,4096})",
        re.I,
    ),
    "raw auth field": re.compile(
        rb'"(?:access_token|auth_token|feed_token|id_token|join_token|'
        rb'onboarding_capability|participant_token|payment_token|refresh_token|'
        rb'session_token)"\s*:\s*"(?P<value>[^"\r\n]{1,4096})"',
        re.I,
    ),
    "raw credential assignment": re.compile(
        rb"(?:^|[\s;&?])(?:[A-Z0-9_]*(?:SESSION|AUTH|TOKEN|SECRET|PASSWORD)"
        rb"[A-Z0-9_]*|api[-_]?key)\s*[:=]\s*[\"']?"
        rb"(?P<value>[A-Za-z0-9+/=._~<>{}\[\]*#-]{8,4096})",
        re.I | re.M,
    ),
    "form credential field": re.compile(
        rb'"(?:name|key)"\s*:\s*"[^"\r\n]*'
        rb'(?:token|secret|password|otp|authorization)[^"\r\n]*"\s*,\s*'
        rb'"value"\s*:\s*"(?P<value>[^"\r\n]{1,4096})"',
        re.I,
    ),
    "credential cookie": re.compile(
        rb"(?:set-cookie|cookie)[\"']?\s*[:=]\s*[\"']?[^\r\n]{0,2048}"
        rb"(?:session|auth|token)[^=;\s]*="
        rb"(?P<value>[^;\s,\"']{4,4096})",
        re.I,
    ),
    "jwt-like credential": re.compile(
        rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        rb"[A-Za-z0-9_-]{10,}\b"
    ),
    "raw otp field": re.compile(
        rb"(?:\"(?:otp|one_time_code|verification_code|recovery_code|passcode)\""
        rb"|\b(?:otp|verification|recovery)\s+code\b)\s*[:=]\s*[\"']?"
        rb"(?P<value>\d{4,8})\b",
        re.I,
    ),
    "raw mobile field": re.compile(
        rb'"(?:mobile|mobile_number|phone|phone_number|destination)"\s*:\s*"?'
        rb"(?P<value>(?:\+?91[- ]?)?[6-9]\d{9})\"?",
        re.I,
    ),
    "raw date of birth field": re.compile(
        rb'"(?:dob|date_of_birth|birth_date)"\s*:\s*"'
        rb'(?P<value>\d{4}-\d{2}-\d{2})"',
        re.I,
    ),
    "raw personal name field": re.compile(
        rb'"(?:first_name|middle_name|last_name|full_name|guardian_name)"\s*:\s*"'
        rb'(?P<value>[^"\r\n]{1,4096})"',
        re.I,
    ),
    "web storage credential": re.compile(
        rb'"(?:localStorage|sessionStorage|local|session)"\s*:\s*\{'
        rb'[^{}]{0,4096}"[^"\r\n]*(?:token|secret|password|otp|authorization|bearer)'
        rb'[^"\r\n]*"\s*:\s*"(?P<value>[^"\r\n]{1,4096})"',
        re.I,
    ),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(
        rb"\b(?:gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "application capability": re.compile(
        rb"\b(?:feed|join|participant|payment|tok)_[A-Za-z0-9_-]{16,4096}\b",
        re.I,
    ),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}

EMAIL = re.compile(
    rb"\b[A-Z0-9.!#$%&'*+/=?^_{|}~-]+@([A-Z0-9.-]+\.[A-Z]{2,63})\b",
    re.I,
)
SYNTHETIC_EMAIL_DOMAINS = {
    b"example.com",
    b"example.net",
    b"example.org",
    b"example.test",
}

URL_TOKEN = re.compile(rb"https?://[^\s\"'<>]{1,8192}", re.I)

QUERY_FIELD = re.compile(
    rb"(?:^|[?&#;\s])(?P<key>[A-Za-z0-9_.%+-]{1,384})="
    rb"(?P<value>[^&#;\s\r\n]{0,8192})",
    re.M,
)
LINE_FIELD = re.compile(
    rb"(?:^|[,{}][ \t]*)(?:[ \t]*-[ \t]*)?[ \t]*[\"']?"
    rb"(?P<key>[A-Za-z0-9_.-]{1,128})[\"']?[ \t]*[:=][ \t]*"
    rb"[\"']?(?P<value>[^\r\n#,'\"}]{0,8192})",
    re.M,
)
MULTIPART_FIELD = re.compile(
    rb'content-disposition\s*:\s*form-data\s*;[^\r\n]{0,1024}'
    rb'name\s*=\s*"(?P<key>[^"\r\n]{1,128})"[^\r\n]*\r?\n'
    rb"(?:[^\r\n]*\r?\n)*\r?\n(?P<value>[^\r\n]{0,8192})",
    re.I,
)
DATA_URL_BASE64 = re.compile(
    rb"data:[A-Za-z0-9.+/-]{1,128}(?:;[A-Za-z0-9.+_=-]{1,128})*"
    rb";base64,(?P<body>[A-Za-z0-9+/=]+)",
    re.I,
)
BASE64_BODY_FIRST = re.compile(
    rb'"(?:body|content|data|text|value)"\s*:\s*"'
    rb"(?P<body>[A-Za-z0-9+/=\\r\\n]+)\"\s*,\s*"
    rb'"(?:encoding|content_encoding|transfer_encoding)"\s*:\s*"base64"',
    re.I,
)
BASE64_ENCODING_FIRST = re.compile(
    rb'"(?:encoding|content_encoding|transfer_encoding)"\s*:\s*"base64"\s*,\s*'
    rb'"(?:body|content|data|text|value)"\s*:\s*"'
    rb"(?P<body>[A-Za-z0-9+/=\\r\\n]+)\"",
    re.I,
)
BASE64_TRANSFER_BODY = re.compile(
    rb"content-transfer-encoding\s*:\s*base64[^\r\n]*\r?\n\r?\n"
    rb"(?P<body>[A-Za-z0-9+/=\r\n]+)",
    re.I,
)

VISUAL_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
PDF_EXTENSIONS = {".pdf"}
ZIP_EXTENSIONS = {".zip"}
OPAQUE_CONTAINER_EXTENSIONS = {
    ".7z",
    ".bz2",
    ".gz",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
}

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILES = 5_000
MAX_TOTAL_FILE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5_000
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 256 * 1024 * 1024
MAX_BASE64_ENCODED_BYTES = 8 * 1024 * 1024
MAX_BASE64_DECODED_BYTES = 6 * 1024 * 1024
MAX_CONTENT_DEPTH = 3
MAX_PERCENT_DECODE_PASSES = 8

_REDACTED_WORDS = {
    b"",
    b"false",
    b"masked",
    b"none",
    b"notcaptured",
    b"notrecorded",
    b"notstored",
    b"null",
    b"omitted",
    b"redacted",
    b"removed",
    b"synthetic",
    b"true",
    b"unavailable",
}
_CREDENTIAL_FIELDS = {
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "bearer",
    "feed_token",
    "id_token",
    "join_token",
    "onboarding_capability",
    "participant_token",
    "password",
    "payment_token",
    "refresh_token",
    "secret",
    "session_token",
    "token",
}
_OTP_FIELDS = {
    "one_time_code",
    "otp",
    "otp_code",
    "passcode",
    "recovery_code",
    "verification_code",
}
_MOBILE_FIELDS = {"destination", "mobile", "mobile_number", "phone", "phone_number"}
_EMAIL_FIELDS = {"email", "email_address", "institutional_email"}
_DOB_FIELDS = {"birth_date", "date_of_birth", "dob"}
_NAME_FIELDS = {"first_name", "full_name", "guardian_name", "last_name", "middle_name"}


@dataclass(frozen=True)
class ScanReport:
    files_discovered: int
    bytes_scanned: int
    findings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def failures(self) -> list[str]:
        return [*self.errors, *self.findings]


def _opaque_label(kind: str, identity: bytes | str) -> str:
    raw = identity if isinstance(identity, bytes) else identity.encode("utf-8", "surrogatepass")
    return f"{kind}#{hashlib.sha256(raw).hexdigest()[:12]}"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_redacted(value: bytes) -> bool:
    stripped = value.strip().strip(b"\"'")
    lowered = stripped.lower()
    for prefix in (b"bearer ", b"basic ", b"token ", b"api-key ", b"apikey "):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix) :].strip()
            break
    normalized = re.sub(rb"[\s_.-]+", b"", lowered)
    normalized = normalized.strip(b"<>[]{}()*#")
    if normalized in _REDACTED_WORDS:
        return True
    return bool(re.fullmatch(rb"(?:[*xX#]){3,}\d{0,4}", stripped))


def _email_is_synthetic(value: bytes) -> bool:
    matches = list(EMAIL.finditer(value))
    return bool(matches) and all(
        match.group(1).lower().rstrip(b".") in SYNTHETIC_EMAIL_DOMAINS
        for match in matches
    )


def _field_category(key: str) -> str | None:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    normalized = re.sub(r"[^a-z0-9]+", "_", snake.lower()).strip("_")
    if normalized in _CREDENTIAL_FIELDS or any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("access_token", "auth_token", "password", "secret", "session_token")
    ) or normalized.endswith("_session"):
        return "raw auth field"
    if normalized in _OTP_FIELDS or any(
        normalized.endswith(f"_{suffix}") for suffix in ("otp_code", "verification_code")
    ):
        return "raw otp field"
    if normalized in _MOBILE_FIELDS:
        return "raw mobile field"
    if normalized in _EMAIL_FIELDS:
        return "raw email address"
    if normalized in _DOB_FIELDS:
        return "raw date of birth field"
    if normalized in _NAME_FIELDS:
        return "raw personal name field"
    return None


def _field_finding(label: str, key: str, value: bytes) -> list[str]:
    category = _field_category(key)
    if category is None or _is_redacted(value):
        return []
    if category == "raw email address" and _email_is_synthetic(value):
        return []
    if category == "raw mobile field" and re.fullmatch(
        rb"(?:[+() -]*[*xX#]){3,}[0-9() +*-]{0,8}", value.strip()
    ):
        return []
    return [f"{label}: {category}"]


def _findings(label: str, data: bytes) -> list[str]:
    findings: list[str] = []
    for finding_label, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            value = match.groupdict().get("value")
            if value is not None and _is_redacted(value):
                continue
            findings.append(f"{label}: {finding_label}")
            break
    for match in EMAIL.finditer(data):
        domain = match.group(1).lower().rstrip(b".")
        if domain not in SYNTHETIC_EMAIL_DOMAINS:
            findings.append(f"{label}: raw email address")
            break
    if b'\\"' in data:
        normalized = data.replace(b'\\"', b'"')
        if normalized != data:
            for finding in _findings(label, normalized):
                if finding not in findings:
                    findings.append(finding)
    return findings


def _percent_decode_variants(raw: bytes) -> tuple[list[bytes], bool]:
    variants = [raw]
    decoded = raw
    for _ in range(MAX_PERCENT_DECODE_PASSES):
        try:
            candidate = unquote_to_bytes(decoded)
        except Exception:
            return variants, True
        if candidate == decoded:
            return variants, False
        variants.append(candidate)
        decoded = candidate
    try:
        still_encoded = unquote_to_bytes(decoded) != decoded
    except Exception:
        still_encoded = True
    return variants, still_encoded


def _path_findings(label: str, path_name: str) -> list[str]:
    raw = path_name.encode("utf-8", "surrogatepass")
    variants_list, exceeded = _percent_decode_variants(raw)
    variants = tuple(dict.fromkeys(variants_list))
    findings: list[str] = []
    if exceeded:
        findings.append(f"{label} path: percent encoding exceeds the scan limit")
    for data in variants:
        for finding in _findings(f"{label} path", data):
            if finding not in findings:
                findings.append(finding)
    explicit_patterns = (
        (rb"(?:^|[/_.-])(?:otp|code)[_.=-]+(?P<value>\d{4,8})(?:$|[/_.-])", "raw otp field"),
        (
            rb"(?<!\d)(?P<value>(?:\+?91[-_. ]?)?[6-9]\d{9})(?!\d)",
            "raw mobile field",
        ),
        (
            rb"(?:^|[/_.-])(?:dob|birth)[_.=-]+(?P<value>\d{4}-\d{2}-\d{2})",
            "raw date of birth field",
        ),
        (
            rb"(?:^|[/_.-])(?:token|secret|password|authorization)[_.=-]+"
            rb"(?P<value>[A-Za-z0-9+/=~]{4,})",
            "raw auth field",
        ),
    )
    for data in variants:
        lowered = data.lower()
        for pattern, category in explicit_patterns:
            match = re.search(pattern, lowered, re.I)
            finding = f"{label} path: {category}"
            if (
                match
                and not _is_redacted(match.group("value"))
                and finding not in findings
            ):
                findings.append(finding)
    return findings


def _discover(root: Path) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        return [], ["evidence root: path does not exist"]
    except OSError as exc:
        return [], [f"evidence root: cannot be inspected ({exc.__class__.__name__})"]

    if stat.S_ISLNK(root_stat.st_mode):
        return [], ["evidence root: must not be a symlink"]
    if not stat.S_ISDIR(root_stat.st_mode):
        return [], ["evidence root: must be a directory"]

    files: list[Path] = []
    def walk_error(exc: OSError) -> None:
        errors.append(
            f"evidence root: directory cannot be traversed ({exc.__class__.__name__})"
        )

    for current, directories, names in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        current_path = Path(current)
        retained_directories: list[str] = []
        for name in sorted(directories):
            candidate = current_path / name
            relative = _relative(candidate, root)
            label = _opaque_label("directory", relative)
            if name.startswith("."):
                errors.append(f"{label}: hidden evidence path is not allowed")
                continue
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                errors.append(f"{label}: cannot be inspected ({exc.__class__.__name__})")
                continue
            if stat.S_ISLNK(mode):
                errors.append(f"{label}: symlink is not allowed")
                continue
            if not stat.S_ISDIR(mode):
                errors.append(f"{label}: unsupported directory node")
                continue
            retained_directories.append(name)
        directories[:] = retained_directories

        for name in sorted(names):
            candidate = current_path / name
            relative = _relative(candidate, root)
            label = _opaque_label("file", relative)
            if name.startswith("."):
                errors.append(f"{label}: hidden evidence path is not allowed")
                continue
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                errors.append(f"{label}: cannot be inspected ({exc.__class__.__name__})")
                continue
            if stat.S_ISLNK(mode):
                errors.append(f"{label}: symlink is not allowed")
            elif not stat.S_ISREG(mode):
                errors.append(f"{label}: unsupported non-regular node")
            else:
                files.append(candidate)
    return files, errors


def _visual_magic(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "WebP"
    if data.startswith(b"BM"):
        return "BMP"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        if brand in {b"avif", b"avis", b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return "ISO-BMFF image"
    prefix = data[:4096]
    if re.match(
        rb"^(?:\xef\xbb\xbf)?\s*(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*<svg\b",
        prefix,
        re.I | re.S,
    ):
        return "SVG"
    return None


def _zip_magic(data: bytes) -> bool:
    return data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _opaque_container_magic(data: bytes) -> str | None:
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if data.startswith(b"\x1f\x8b"):
        return "gzip"
    if data.startswith(b"BZh"):
        return "bzip2"
    if data.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if data.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return "RAR"
    if len(data) > 262 and data[257:262] == b"ustar":
        return "tar"
    return None


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _json_field_findings(label: str, value: object) -> list[str]:
    findings: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            form_name = node.get("name", node.get("key"))
            if isinstance(form_name, str) and "value" in node:
                raw_value = node["value"]
                if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                    findings.extend(
                        _field_finding(
                            label,
                            form_name,
                            str(raw_value if raw_value is not None else "null").encode("utf-8"),
                        )
                    )
            for key, child in node.items():
                if isinstance(key, str) and (
                    isinstance(child, (str, int, float, bool)) or child is None
                ):
                    findings.extend(
                        _field_finding(
                            label,
                            key,
                            str(child if child is not None else "null").encode("utf-8"),
                        )
                    )
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str) and len(node) <= MAX_BASE64_DECODED_BYTES:
            stripped = node.strip()
            if stripped.startswith(("{", "[")):
                try:
                    nested = json.loads(stripped)
                except json.JSONDecodeError:
                    return
                if nested != node:
                    walk(nested)

    walk(value)
    return findings


def _declared_json_base64(value: object) -> list[bytes]:
    bodies: list[bytes] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            encoding = next(
                (
                    item
                    for key, item in node.items()
                    if isinstance(key, str)
                    and re.sub(r"[^a-z]", "", key.lower())
                    in {"encoding", "contentencoding", "transferencoding"}
                ),
                None,
            )
            if isinstance(encoding, str) and encoding.lower() == "base64":
                body = next(
                    (
                        item
                        for key, item in node.items()
                        if isinstance(key, str)
                        and key.lower() in {"body", "content", "data", "text", "value"}
                        and isinstance(item, str)
                    ),
                    None,
                )
                if body is not None:
                    bodies.append(body.encode("ascii", "backslashreplace"))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return bodies


def _decode_base64(label: str, encoded: bytes) -> tuple[bytes | None, list[str]]:
    compact = re.sub(rb"\s+", b"", encoded)
    if not compact:
        return None, [f"{label}: declared base64 body is empty"]
    if len(compact) > MAX_BASE64_ENCODED_BYTES:
        return None, [f"{label}: declared base64 body exceeds the scan limit"]
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error):
        return None, [f"{label}: declared base64 body is malformed"]
    if not decoded:
        return None, [f"{label}: declared base64 body decodes to empty content"]
    if len(decoded) > MAX_BASE64_DECODED_BYTES:
        return None, [f"{label}: decoded base64 body exceeds the scan limit"]
    return decoded, []


def _text_semantics(
    label: str,
    data: bytes,
    *,
    depth: int,
    archive_depth: int,
) -> tuple[int, list[str], list[str]]:
    findings = _findings(label, data)
    errors: list[str] = []
    scanned = 0

    for match in URL_TOKEN.finditer(data):
        variants, exceeded = _percent_decode_variants(match.group(0))
        if exceeded:
            errors.append(f"{label}: URL percent encoding exceeds the scan limit")
            continue
        for variant in variants:
            findings.extend(_findings(label, variant))

    for match in QUERY_FIELD.finditer(data):
        encoded_key = match.group("key").replace(b"+", b" ")
        try:
            key_variants, key_exceeded = _percent_decode_variants(encoded_key)
            value_variants, value_exceeded = _percent_decode_variants(
                match.group("value").replace(b"+", b" ")
            )
            if key_exceeded or value_exceeded:
                errors.append(f"{label}: URL/form percent encoding exceeds the scan limit")
                continue
            key = key_variants[-1].decode("utf-8", "replace")
            value = value_variants[-1]
        except Exception:
            errors.append(f"{label}: URL/form field cannot be decoded")
            continue
        findings.extend(_field_finding(label, key, value))

    for match in LINE_FIELD.finditer(data):
        key = match.group("key").decode("ascii", "ignore")
        findings.extend(_field_finding(label, key, match.group("value").strip()))

    for match in MULTIPART_FIELD.finditer(data):
        key = match.group("key").decode("utf-8", "replace")
        findings.extend(_field_finding(label, key, match.group("value")))

    parsed_json: object | None = None
    try:
        parsed_json = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    if parsed_json is not None:
        findings.extend(_json_field_findings(label, parsed_json))

    declared: list[bytes] = []
    if parsed_json is not None:
        declared.extend(_declared_json_base64(parsed_json))
    for pattern in (
        DATA_URL_BASE64,
        BASE64_BODY_FIRST,
        BASE64_ENCODING_FIRST,
        BASE64_TRANSFER_BODY,
    ):
        declared.extend(match.group("body") for match in pattern.finditer(data))

    seen: set[str] = set()
    for encoded in declared:
        digest = hashlib.sha256(encoded).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        body_label = _opaque_label("base64-body", digest)
        decoded, decode_errors = _decode_base64(body_label, encoded)
        errors.extend(decode_errors)
        if decoded is None:
            continue
        body_scanned, body_findings, body_errors = _dispatch_payload(
            body_label,
            "declared-body.bin",
            decoded,
            depth=depth + 1,
            archive_depth=archive_depth,
        )
        scanned += body_scanned
        findings.extend(body_findings)
        errors.extend(body_errors)
    return scanned, findings, errors


def _unsafe_zip_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or "\x00" in name
        or "\n" in name
        or "\r" in name
        or any(part.startswith(".") for part in path.parts if part not in {"", "."})
    )


def _scan_zip(
    label: str,
    data: bytes,
    *,
    depth: int,
    archive_depth: int,
) -> tuple[int, list[str], list[str]]:
    findings: list[str] = []
    errors: list[str] = []
    scanned = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return 0, [], [f"{label}: ZIP evidence is malformed"]

    with archive:
        if archive.comment:
            comment_label = _opaque_label("zip-comment", archive.comment)
            comment_scanned, comment_findings, comment_errors = _dispatch_payload(
                comment_label,
                "archive-comment.txt",
                archive.comment,
                depth=depth + 1,
                archive_depth=archive_depth + 1,
            )
            scanned += comment_scanned
            findings.extend(comment_findings)
            errors.extend(comment_errors)

        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            return scanned, findings, [*errors, f"{label}: ZIP has too many members"]
        file_members = [member for member in members if not member.is_dir()]
        if not file_members:
            errors.append(f"{label}: ZIP contains zero regular members")
        declared_total = sum(member.file_size for member in file_members)
        if declared_total > MAX_ARCHIVE_TOTAL_BYTES:
            return scanned, findings, [*errors, f"{label}: ZIP expands beyond the scan limit"]

        seen_paths: set[str] = set()
        for member in members:
            member_label = _opaque_label("zip-member", f"{label}/{member.filename}")
            findings.extend(_path_findings(member_label, member.filename))
            normalized_name = member.filename.casefold()
            if normalized_name in seen_paths:
                errors.append(f"{member_label}: duplicate ZIP member path")
                continue
            seen_paths.add(normalized_name)
            if _unsafe_zip_path(member.filename):
                errors.append(f"{member_label}: unsafe ZIP member path")
                continue
            member_mode = member.external_attr >> 16
            if member_mode and stat.S_ISLNK(member_mode):
                errors.append(f"{member_label}: ZIP symlink is not allowed")
                continue
            if member.flag_bits & 0x1:
                errors.append(f"{member_label}: encrypted ZIP member is not scan-safe")
                continue
            if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                errors.append(f"{member_label}: ZIP member exceeds the scan limit")
                continue

            if member.comment:
                comment_label = _opaque_label("zip-member-comment", member.comment)
                comment_scanned, comment_findings, comment_errors = _dispatch_payload(
                    comment_label,
                    "member-comment.txt",
                    member.comment,
                    depth=depth + 1,
                    archive_depth=archive_depth + 1,
                )
                scanned += comment_scanned
                findings.extend(comment_findings)
                errors.extend(comment_errors)
            if member.extra:
                errors.append(f"{member_label}: opaque ZIP extra metadata is not scan-safe")

            if member.is_dir():
                continue
            if member.file_size == 0:
                errors.append(f"{member_label}: ZIP member is empty")
                continue
            try:
                member_data = archive.read(member)
            except (
                OSError,
                RuntimeError,
                NotImplementedError,
                zipfile.BadZipFile,
            ) as exc:
                errors.append(
                    f"{member_label}: ZIP member cannot be read ({exc.__class__.__name__})"
                )
                continue
            if len(member_data) != member.file_size:
                errors.append(f"{member_label}: ZIP member length mismatch")
                continue
            member_scanned, member_findings, member_errors = _dispatch_payload(
                member_label,
                member.filename,
                member_data,
                depth=depth + 1,
                archive_depth=archive_depth + 1,
            )
            scanned += member_scanned
            findings.extend(member_findings)
            errors.extend(member_errors)
    return scanned, findings, errors


def _dispatch_payload(
    label: str,
    declared_name: str,
    data: bytes,
    *,
    depth: int,
    archive_depth: int,
) -> tuple[int, list[str], list[str]]:
    if depth > MAX_CONTENT_DEPTH:
        return len(data), [], [f"{label}: nested encoded content exceeds the scan depth"]
    if not data:
        return 0, [], [f"{label}: evidence payload is empty"]
    if len(data) > MAX_FILE_BYTES and archive_depth == 0:
        return len(data), [], [f"{label}: evidence file exceeds the scan limit"]

    suffix = Path(declared_name).suffix.lower()
    visual_kind = _visual_magic(data)
    pdf_magic = b"%PDF-" in data[:1024]
    zip_kind = _zip_magic(data)
    opaque_kind = _opaque_container_magic(data)

    if visual_kind is not None:
        return (
            len(data),
            [],
            [
                f"{label}: {visual_kind} evidence requires pixel privacy inspection "
                "and is not uploadable under the phase-one policy"
            ],
        )
    if suffix in VISUAL_EXTENSIONS:
        findings: list[str] = []
        errors = [f"{label}: visual extension does not match a supported image signature"]
        extra_scanned = 0
        if _is_text(data):
            extra_scanned, findings, text_errors = _text_semantics(
                label,
                data,
                depth=depth,
                archive_depth=archive_depth,
            )
            errors.extend(text_errors)
        return len(data) + extra_scanned, findings, errors

    if pdf_magic or suffix in PDF_EXTENSIONS:
        return len(data), [], [f"{label}: PDF evidence is not scan-safe in phase one"]

    if (zip_kind or suffix in ZIP_EXTENSIONS) and archive_depth:
        return len(data), [], [f"{label}: nested archive/container is not scan-safe"]

    if suffix in ZIP_EXTENSIONS and not zip_kind:
        return len(data), [], [
            f"{label}: ZIP evidence is malformed: ZIP signature must begin at byte zero "
            "and match its extension"
        ]

    if zip_kind:
        archive_scanned, findings, errors = _scan_zip(
            label,
            data,
            depth=depth,
            archive_depth=archive_depth,
        )
        return len(data) + archive_scanned, findings, errors

    if opaque_kind is not None or suffix in OPAQUE_CONTAINER_EXTENSIONS:
        kind = opaque_kind or "opaque"
        return len(data), [], [f"{label}: {kind} archive/container is not scan-safe"]

    if not _is_text(data):
        return len(data), [], [f"{label}: unknown binary evidence is not scan-safe"]

    extra_scanned, findings, errors = _text_semantics(
        label,
        data,
        depth=depth,
        archive_depth=archive_depth,
    )
    return len(data) + extra_scanned, findings, errors


def scan_report(root: Path) -> ScanReport:
    root = root.expanduser()
    files, errors = _discover(root)
    findings: list[str] = []
    bytes_scanned = 0

    if not files and not any("does not exist" in error for error in errors):
        errors.append("evidence root: directory contains zero regular files")
    if len(files) > MAX_FILES:
        errors.append("evidence root: contains too many files")

    total_file_bytes = 0

    for path in files:
        relative = _relative(path, root)
        label = _opaque_label("file", relative)
        findings.extend(_path_findings(label, relative))
        try:
            size = path.stat().st_size
        except OSError as exc:
            errors.append(f"{label}: file cannot be inspected ({exc.__class__.__name__})")
            continue
        total_file_bytes += size
        if size > MAX_FILE_BYTES:
            errors.append(f"{label}: evidence file exceeds the scan limit")
            continue
        if total_file_bytes > MAX_TOTAL_FILE_BYTES:
            errors.append("evidence root: aggregate payload exceeds the scan limit")
            break
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(f"{label}: file cannot be read ({exc.__class__.__name__})")
            continue
        scanned, payload_findings, payload_errors = _dispatch_payload(
            label,
            path.name,
            data,
            depth=0,
            archive_depth=0,
        )
        bytes_scanned += scanned
        findings.extend(payload_findings)
        errors.extend(payload_errors)

    return ScanReport(
        files_discovered=len(files),
        bytes_scanned=bytes_scanned,
        findings=tuple(sorted(set(findings))),
        errors=tuple(sorted(set(errors))),
    )


def scan(root: Path) -> list[str]:
    """Compatibility wrapper used by the seeded policy tests."""

    return scan_report(root).failures


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: scan_evidence.py EVIDENCE_DIR", file=sys.stderr)
        return 2
    report = scan_report(Path(sys.argv[1]))
    print(
        "Evidence privacy scan: "
        f"files={report.files_discovered} bytes={report.bytes_scanned} "
        f"findings={len(report.findings)} errors={len(report.errors)}"
    )
    if report.failures:
        print("Evidence privacy scan failed:", file=sys.stderr)
        print("\n".join(report.failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

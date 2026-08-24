#!/usr/bin/env python3
"""Fail-closed NYAY-18 policy for shipped frontend identity and namespaces.

The policy deliberately scans only browser/mobile inputs that can ship.  Test,
QA and historical documentation trees are outside this boundary, so their
deterministic negative canaries are not turned into a repository-wide word ban.
Every production compatibility literal is instead bound to one exact source
path, occurrence count and SHA-256 in ``nyay18_namespace_contract.json``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("nyay18_namespace_contract.json")

REQUIRED_METADATA_PATHS = (
    "frontend/index.html",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/capacitor.config.ts",
    "frontend/vite.config.ts",
)
SHIPPED_TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".mjs",
    ".scss",
    ".svg",
    ".ts",
    ".tsx",
    ".txt",
    ".webmanifest",
}
MAX_SOURCE_BYTES = 4 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LEGACY_BRAND = re.compile(
    r"legal(?:[\s._-]+|['\"`]\s*\+\s*['\"`]|</?[A-Za-z][^>\r\n]{0,80}>){0,4}saathi",
    re.IGNORECASE,
)
JS_STRING = re.compile(
    r"(?P<quote>['\"`])(?P<body>(?:\\.|(?!(?P=quote)).)*)(?P=quote)",
    re.DOTALL,
)
LEGACY_NAMESPACE = re.compile(r"^ls-[A-Za-z0-9_.:${}-]+$")
CURRENT_RUNTIME_NAMESPACE = re.compile(
    r"(?<![A-Za-z0-9_])(?:__nyayone[A-Za-z0-9_.:${}-]*|"
    r"nyayone(?:[.:-][A-Za-z0-9_.:${}-]+))",
    re.IGNORECASE,
)
CURRENT_DISPLAY_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9])NYAY-[A-Z][A-Z0-9]*-",
    re.IGNORECASE,
)
JS_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
JS_STRING_ATOM = r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`)"
SIMPLE_STRING_CONST = re.compile(
    rf"\bconst\s+(?P<name>{JS_IDENTIFIER})\s*=\s*(?P<value>{JS_STRING_ATOM})\s*;"
)
SIMPLE_IDENTIFIER_INITIALIZER = re.compile(
    rf"\b(?:const|let)\s+(?P<name>{JS_IDENTIFIER})\s*=\s*"
    r"(?P<value>[^;\r\n]+)\s*;"
)
CONCAT_EXPRESSION = re.compile(
    rf"(?P<expression>(?:{JS_STRING_ATOM}|{JS_IDENTIFIER})"
    rf"(?:\s*\+\s*(?:{JS_STRING_ATOM}|{JS_IDENTIFIER}))+)",
)
CONCAT_ATOM = re.compile(rf"{JS_STRING_ATOM}|{JS_IDENTIFIER}")
ARRAY_JOIN_EXPRESSION = re.compile(
    rf"\[(?P<items>\s*{JS_STRING_ATOM}(?:\s*,\s*{JS_STRING_ATOM})*\s*)\]"
    rf"\.join\(\s*(?P<separator>{JS_STRING_ATOM})\s*\)"
)
METHOD_CONCAT_EXPRESSION = re.compile(
    rf"(?P<receiver>{JS_STRING_ATOM}|{JS_IDENTIFIER})\.concat\("
    rf"(?P<items>\s*(?:{JS_STRING_ATOM}|{JS_IDENTIFIER})"
    rf"(?:\s*,\s*(?:{JS_STRING_ATOM}|{JS_IDENTIFIER}))*\s*)\)"
)
FROM_FIXED_CODE_EXPRESSION = re.compile(
    r"String\.from(?P<method>CharCode|CodePoint)\(\s*(?P<codes>"
    r"(?:0[xX][0-9A-Fa-f]+|[0-9]+)"
    r"(?:\s*,\s*(?:0[xX][0-9A-Fa-f]+|[0-9]+))*)\s*\)"
)
PRESENTATION_STYLE_SUFFIXES = {".css", ".scss"}
PRESENTATION_MARKUP_SUFFIXES = {".html", ".jsx", ".svg", ".tsx"}
JSX_PRESENTATION_ATTRIBUTE = re.compile(
    r"\b(?P<name>className|class|data-nyayone-[A-Za-z0-9_-]+)\s*="
)
DATA_HOOK_OBJECT_KEY = re.compile(r"^data-nyayone-[A-Za-z0-9_-]+$")
DATA_HOOK_TOKEN = re.compile(r"\bdata-nyayone-[A-Za-z0-9_-]+\b")
CONST_DECLARATION = re.compile(
    rf"\bconst\s+(?P<name>{JS_IDENTIFIER})\s*="
)
JSX_SPREAD_IDENTIFIER = re.compile(
    rf"\{{\s*\.\.\.\s*(?P<name>{JS_IDENTIFIER})\s*\}}"
)
ASSIGNMENT_OPERATOR = re.compile(
    r"(?<![=!<>])(?:\*\*|&&|\|\||\?\?|[+\-*/%&|^])?=(?!=|>)"
)
DOM_SELECTOR_CALL = re.compile(
    r"\.(?:querySelector(?:All)?|matches|closest|getElementById|"
    r"getElementsByClassName)(?:\s*<[^>\r\n]+>)?\s*\(\s*$"
)
BROWSER_AUTHORITY_CALL = re.compile(
    r"(?:\b(?:localStorage|sessionStorage)\s*\.\s*"
    r"(?:getItem|setItem|removeItem)|"
    r"\b(?:(?:window|self|globalThis)\s*\.\s*)?caches\s*\.\s*"
    r"(?:open|delete|has|match)|"
    r"\bcookieStore\s*\.\s*(?:get|getAll|set|delete)|"
    r"\bnew\s+(?:CustomEvent|Event|MessageEvent|StorageEvent|BroadcastChannel)|"
    r"\.\s*(?:addEventListener|removeEventListener))\s*\("
)
DOCUMENT_COOKIE_ASSIGNMENT = re.compile(r"\bdocument\s*\.\s*cookie\s*=")
DOM_DERIVED_AUTHORITY_KEY = re.compile(
    r"(?:\?\.|\.)\s*(?:className|classList|dataset|attributes)\b|"
    r"(?:\?\.|\.)\s*getAttribute\s*\(|"
    r"(?:\?\.|\.)\s*(?:currentTarget|target)\s*"
    r"(?:\?\.|\.)\s*(?:id|name|value)\b|"
    r"\[\s*['\"](?:className|classList|dataset|attributes|getAttribute)['\"]\s*\]"
)
DOM_PRESENTATION_DESTRUCTURE = re.compile(
    r"\b(?:const|let)\s*\{[^}\r\n]*\b"
    r"(?:className|classList|dataset|attributes)\b[^}\r\n]*\}\s*=\s*"
    r"[^;\r\n]*\b(?:currentTarget|target)\b"
)
PERSISTENT_BROWSER_AUTHORITY_USE = re.compile(
    r"\b(?:localStorage|sessionStorage)\s*(?:(?:\?\.|\.)\s*"
    r"(?:getItem|setItem|removeItem)|\[\s*['\"]"
    r"(?:getItem|setItem|removeItem)['\"]\s*\])|"
    r"\b(?:indexedDB|caches|cookieStore)\s*(?:(?:\?\.|\.)\s*"
    r"(?:open|delete|deleteDatabase|has|match|get|getAll|set)|\[\s*['\"]"
    r"(?:open|delete|deleteDatabase|has|match|get|getAll|set)['\"]\s*\])|"
    r"\b(?:const|let)\s+" + JS_IDENTIFIER + r"\s*=\s*"
    r"(?:(?:window|self|globalThis)\s*(?:\?\.|\.)\s*)?"
    r"(?:localStorage|sessionStorage|indexedDB|caches|cookieStore)\s*;|"
    r"\b(?:const|let)\s*\{[^}\r\n]*\b"
    r"(?:getItem|setItem|removeItem|open|delete|deleteDatabase|has|match|get|getAll|set)"
    r"\b[^}\r\n]*\}\s*=\s*"
    r"(?:(?:window|self|globalThis)\s*(?:\?\.|\.)\s*)?"
    r"(?:localStorage|sessionStorage|indexedDB|caches|cookieStore)\s*;|"
    r"[\(\[,?:=]\s*(?:(?:window|self|globalThis)\s*(?:\?\.|\.)\s*)?"
    r"(?:localStorage|sessionStorage|indexedDB|caches|cookieStore)\s*"
    r"(?=[,\)\]\}:;])|"
    r"\bnew\s+(?:(?:window|self|globalThis)\s*(?:\?\.|\.)\s*)?"
    r"(?:BroadcastChannel|CustomEvent|MessageEvent|StorageEvent)\b|"
    r"\bdocument\s*(?:(?:\?\.|\.)\s*cookie|"
    r"\[\s*['\"]cookie['\"]\s*\])\s*="
)
PLANTED_MUTANT_NAMES = (
    "legacy-brand-direct",
    "legacy-brand-spaced",
    "legacy-namespace",
    "legacy-storage-key",
    "metadata-drift",
    "source-inventory-drift",
    "compatibility-hash-drift",
    "unsafe-source-node",
    "uncontracted-current-namespace",
    "constructed-brand-array-join",
    "constructed-brand-const-propagation",
    "constructed-brand-template-interpolation",
    "constructed-brand-multi-fragment",
    "constructed-brand-literal-concat-method",
    "constructed-brand-literal-character-codes",
    "constructed-brand-literal-code-points",
    "constructed-current-literal-code-points",
)
PLANTED_BRAND_CANARY = "LegalSaathi NYAY18 PLANTED BRAND CANARY"
PLANTED_NAMESPACE_CANARY = "ls-planted-private-v1"


@dataclass(frozen=True, order=True)
class Failure:
    code: str
    path: str


@dataclass(frozen=True)
class AuditReport:
    failures: tuple[Failure, ...]
    scanned_files: int
    source_inventory_count: int
    source_inventory_sha256: str
    namespace_contract_sha256: str
    compatibility_source_count: int
    compatibility_literal_count: int
    self_test_passed: bool
    self_test_mutants: int
    self_test_mutants_killed: int

    def evidence(self) -> dict[str, object]:
        status = "PASS" if not self.failures and self.self_test_passed else "FAIL"
        return {
            "gate": "nyay18_frontend_namespace_static_v1",
            "status": status,
            "executed": True,
            "sourceInventory": {
                "count": self.source_inventory_count,
                "sha256": self.source_inventory_sha256,
                "exact": not any(item.code == "source-inventory" for item in self.failures),
            },
            "namespaceContract": {
                "sha256": self.namespace_contract_sha256,
            },
            "compatibilityBoundary": {
                "sourceCount": self.compatibility_source_count,
                "literalCount": self.compatibility_literal_count,
                "hashesExact": not any(
                    item.code.startswith("compatibility-") for item in self.failures
                ),
            },
            "selfTest": {
                "passed": self.self_test_passed,
                "mutants": self.self_test_mutants,
                "mutantsKilled": self.self_test_mutants_killed,
                "named": len(PLANTED_MUTANT_NAMES),
                "inventorySha256": hashlib.sha256(
                    ("\n".join(PLANTED_MUTANT_NAMES) + "\n").encode("utf-8")
                ).hexdigest(),
            },
            "privacy": {
                "rawSourceIncluded": False,
                "findingContentIncluded": False,
            },
            "failureCount": len(self.failures),
            "failureCodes": sorted({item.code for item in self.failures}),
        }


@dataclass(frozen=True)
class SelfTestResult:
    passed: bool
    mutants: int
    mutants_killed: int

    def evidence(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "mutants": self.mutants,
            "mutantsKilled": self.mutants_killed,
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_test_source(relative: Path) -> bool:
    name = relative.name.casefold()
    return (
        any(token in name for token in (".test.", ".spec.", ".stories."))
        or name.endswith(".d.ts")
        or any(part.casefold() in {"test", "tests", "__tests__"} for part in relative.parts)
    )


def shipped_source_inventory(root: Path) -> tuple[str, ...]:
    """Return every production input covered by the static shipped-surface gate."""

    paths: set[str] = {
        relative for relative in REQUIRED_METADATA_PATHS if (root / relative).exists()
    }
    for subtree in (root / "frontend/src", root / "frontend/public"):
        if not subtree.exists():
            continue
        for path in subtree.rglob("*"):
            if not (path.is_file() or path.is_symlink()):
                continue
            relative = path.relative_to(root)
            if subtree.name == "src" and _is_test_source(relative):
                continue
            paths.add(relative.as_posix())
    return tuple(sorted(paths))


def source_inventory_sha256(paths: Iterable[str]) -> str:
    rows = tuple(sorted(paths))
    payload = ("\n".join(rows) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _failure(code: str, path: str = "policy") -> Failure:
    return Failure(code=code, path=path)


def _load_json(path: Path) -> tuple[dict[str, object] | None, list[Failure]]:
    if not path.is_file() or path.is_symlink():
        return None, [_failure("contract-unreadable", path.as_posix())]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, [_failure("contract-unreadable", path.as_posix())]
    if not isinstance(value, dict):
        return None, [_failure("contract-schema", path.as_posix())]
    return value, []


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    value, failures = _load_json(path)
    if failures or value is None:
        raise ValueError("NYAY-18 namespace contract is missing or malformed")
    return value


def _contract_parts(
    contract: dict[str, object],
) -> tuple[dict[str, str], dict[str, int], dict[str, dict[str, object]], list[Failure]]:
    failures: list[Failure] = []
    if set(contract) != {
        "schema_version",
        "source_inventory_sha256",
        "metadata",
        "required_runtime_namespaces",
        "compatibility_sources",
    } or contract.get("schema_version") != 1:
        failures.append(_failure("contract-schema"))

    inventory_digest = contract.get("source_inventory_sha256")
    if not isinstance(inventory_digest, str) or not SHA256.fullmatch(inventory_digest):
        failures.append(_failure("contract-schema"))

    raw_metadata = contract.get("metadata")
    expected_metadata_keys = {
        "package_name",
        "capacitor_app_id",
        "capacitor_android_scheme",
        "capacitor_web_dir",
        "app_name",
        "service_worker_cache",
    }
    if (
        not isinstance(raw_metadata, dict)
        or set(raw_metadata) != expected_metadata_keys
        or not all(isinstance(value, str) and value for value in raw_metadata.values())
    ):
        failures.append(_failure("contract-schema"))
        metadata: dict[str, str] = {}
    else:
        metadata = {str(key): str(value) for key, value in raw_metadata.items()}

    raw_required = contract.get("required_runtime_namespaces")
    if (
        not isinstance(raw_required, dict)
        or not raw_required
        or list(raw_required) != sorted(raw_required)
        or not all(
            isinstance(namespace, str)
            and namespace
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
            for namespace, count in raw_required.items()
        )
    ):
        failures.append(_failure("contract-schema"))
        required: dict[str, int] = {}
    else:
        required = dict(raw_required)

    raw_sources = contract.get("compatibility_sources")
    compatibility: dict[str, dict[str, object]] = {}
    if not isinstance(raw_sources, dict):
        failures.append(_failure("contract-schema"))
    else:
        for path, raw in raw_sources.items():
            safe_path = (
                isinstance(path, str)
                and Path(path).as_posix() == path
                and not Path(path).is_absolute()
                and ".." not in Path(path).parts
            )
            if (
                not safe_path
                or not isinstance(raw, dict)
                or set(raw) != {"sha256", "allowed_literals"}
            ):
                failures.append(_failure("contract-schema"))
                continue
            digest = raw.get("sha256")
            literals = raw.get("allowed_literals")
            if (
                not isinstance(digest, str)
                or not SHA256.fullmatch(digest)
                or not isinstance(literals, dict)
                or not literals
                or not all(
                    isinstance(literal, str)
                    and (LEGACY_BRAND.search(literal) is not None or literal.startswith("ls-"))
                    and isinstance(count, int)
                    and not isinstance(count, bool)
                    and count > 0
                    for literal, count in literals.items()
                )
            ):
                failures.append(_failure("contract-schema", str(path)))
                continue
            compatibility[str(path)] = {
                "sha256": digest,
                "allowed_literals": dict(literals),
            }
    return metadata, required, compatibility, failures


def _read_inventory(
    root: Path, inventory: tuple[str, ...]
) -> tuple[dict[str, str], list[Failure]]:
    texts: dict[str, str] = {}
    failures: list[Failure] = []
    for relative in inventory:
        path = root / relative
        try:
            mode = path.lstat().st_mode
        except OSError:
            failures.append(_failure("unsafe-source", relative))
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            failures.append(_failure("unsafe-source", relative))
            continue
        size = path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            failures.append(_failure("unsafe-source", relative))
            continue
        if path.suffix.casefold() not in SHIPPED_TEXT_SUFFIXES:
            allowed_unscanned = (
                path.name == ".gitkeep"
                or relative == "frontend/src/features/student/schools/lawschoolFormat.d.mts"
                or (
                    relative.startswith("frontend/public/fonts/")
                    and path.suffix.casefold() == ".woff2"
                )
            )
            if not allowed_unscanned:
                failures.append(_failure("unsupported-source-format", relative))
            continue
        try:
            texts[relative] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            failures.append(_failure("unsafe-source", relative))
    return texts, failures


def _mask_spans(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _mask_nonruntime_comments(text: str, suffix: str) -> str:
    """Mask comments without erasing string/template literal contents."""

    if suffix in {".html", ".svg"}:
        return re.sub(
            r"<!--[\s\S]*?-->",
            lambda match: "".join(
                character if character in "\r\n" else " "
                for character in match.group(0)
            ),
            text,
        )
    if suffix not in {".css", ".js", ".jsx", ".mjs", ".scss", ".ts", ".tsx"}:
        return text

    chars = list(text)
    index = 0
    quote: str | None = None
    while index < len(chars):
        character = chars[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            continue
        if character == "/" and index + 1 < len(chars) and chars[index + 1] == "/":
            end = index + 2
            while end < len(chars) and chars[end] not in "\r\n":
                end += 1
            for offset in range(index, end):
                chars[offset] = " "
            index = end
            continue
        if character == "/" and index + 1 < len(chars) and chars[index + 1] == "*":
            end = index + 2
            while end + 1 < len(chars) and not (
                chars[end] == "*" and chars[end + 1] == "/"
            ):
                end += 1
            end = min(len(chars), end + 2)
            for offset in range(index, end):
                if chars[offset] not in "\r\n":
                    chars[offset] = " "
            index = end
            continue
        index += 1
    return "".join(chars)


def _allowed_spans(
    relative: str,
    text: str,
    compatibility: dict[str, dict[str, object]],
) -> tuple[list[tuple[int, int]], int, list[Failure]]:
    source = compatibility.get(relative)
    if source is None:
        return [], 0, []
    allowed = source["allowed_literals"]
    assert isinstance(allowed, dict)
    matches: dict[str, list[tuple[int, int]]] = {literal: [] for literal in allowed}
    for match in JS_STRING.finditer(text):
        body = match.group("body")
        if body in matches:
            matches[body].append(match.span())
    failures: list[Failure] = []
    spans: list[tuple[int, int]] = []
    total = 0
    for literal, expected in sorted(allowed.items()):
        actual = len(matches[literal])
        total += int(expected)
        if actual != expected:
            failures.append(_failure("compatibility-literal-count", relative))
        else:
            spans.extend(matches[literal])
    return spans, total, failures


def _is_markup_token(text: str, start: int) -> bool:
    prefix = text[max(0, start - 100):start]
    return re.search(
        r"(?:className|class|id|htmlFor|data-[A-Za-z0-9_-]+)\s*=\s*\{?\s*$",
        prefix,
    ) is not None


def _balanced_brace_end(text: str, start: int) -> int:
    """Return the end of one JSX braced value without interpreting its code."""

    if start >= len(text) or text[start] != "{":
        return start
    depth = 0
    quote: str | None = None
    index = start
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    # An ambiguous or malformed expression must not mask the remainder of the
    # source. Returning the opening brace keeps the projection fail-closed.
    return start


def _is_open_markup_attribute(text: str, start: int) -> bool:
    """Return whether ``start`` is inside a plausible, currently open tag."""

    opening = text.rfind("<", 0, start)
    closing = text.rfind(">", 0, start)
    if opening <= closing:
        return False
    tag_prefix = text[opening + 1:start]
    tag = re.match(r"[A-Za-z][A-Za-z0-9:._-]*(?:\s|$)", tag_prefix)
    if tag is None:
        return False

    depth = 0
    quote: str | None = None
    index = tag.end()
    while index < len(tag_prefix):
        character = tag_prefix[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
        elif character in {"'", '"', "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            if depth == 0:
                return False
            depth -= 1
        index += 1
    return quote is None and depth == 0


def _contains_assignment_outside_literals(text: str) -> bool:
    literal_spans = [match.span() for match in JS_STRING.finditer(text)]
    return ASSIGNMENT_OPERATOR.search(_mask_spans(text, literal_spans)) is not None


def _literal_has_presentation_only_nesting(text: str, stop: int) -> bool:
    """Accept only direct JSX-expression or array-member string literals."""

    stack: list[tuple[str, bool]] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    index = 0
    while index < stop:
        literal = JS_STRING.match(text, index)
        if literal is not None:
            index = literal.end()
            continue
        character = text[index]
        if character in pairs:
            previous = text[:index].rstrip()
            array_literal = character == "[" and (
                not previous or previous[-1] in "([{,:;=!?+-*/%&|^~<>"
            )
            stack.append((pairs[character], array_literal))
        elif character in pairs.values():
            if not stack or character != stack[-1][0]:
                return False
            stack.pop()
        index += 1
    # Array members are a common, presentation-only class-list form. Strings
    # inside calls, grouping parentheses, objects or blocks remain observable.
    return all(expected == "]" and is_array for expected, is_array in stack)


def _presentation_expression_literal_spans(
    text: str,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Select literal class/data tokens without masking executable JSX code."""

    if end <= start + 1 or text[start] != "{" or text[end - 1] != "}":
        return []
    expression = text[start + 1:end - 1]
    if _contains_assignment_outside_literals(expression):
        return []
    spans: list[tuple[int, int]] = []
    for literal in JS_STRING.finditer(expression):
        if not _literal_has_presentation_only_nesting(expression, literal.start()):
            continue
        if literal.group("quote") == "`" and "${" in literal.group("body"):
            for literal_start, literal_end in _presentation_template_literal_spans(
                expression, literal
            ):
                spans.append(
                    (start + 1 + literal_start, start + 1 + literal_end)
                )
            break
        spans.append((start + 1 + literal.start(), start + 1 + literal.end()))
    return spans


def _presentation_template_literal_spans(
    text: str,
    match: re.Match[str],
) -> list[tuple[int, int]]:
    """Mask template static text and safe literals, never interpolation code."""

    spans: list[tuple[int, int]] = []
    body_start = match.start("body")
    body_end = match.end("body")
    cursor = body_start
    while cursor < body_end:
        marker = text.find("${", cursor, body_end)
        if marker < 0:
            if cursor < body_end:
                spans.append((cursor, body_end))
            break
        if cursor < marker:
            spans.append((cursor, marker))
        brace_start = marker + 1
        brace_end = _balanced_brace_end(text, brace_start)
        if brace_end <= brace_start or brace_end > body_end:
            break
        spans.extend(
            _presentation_expression_literal_spans(text, brace_start, brace_end)
        )
        cursor = brace_end
    return spans


def _spread_only_data_hook_declaration_ranges(text: str) -> list[tuple[int, int]]:
    """Prove data-hook objects are consumed only by exact JSX spreads."""

    declarations: dict[str, list[re.Match[str]]] = {}
    spreads: dict[str, list[re.Match[str]]] = {}
    for match in CONST_DECLARATION.finditer(text):
        declarations.setdefault(match.group("name"), []).append(match)
    for match in JSX_SPREAD_IDENTIFIER.finditer(text):
        spreads.setdefault(match.group("name"), []).append(match)

    ranges: list[tuple[int, int]] = []
    for name, name_spreads in spreads.items():
        name_declarations = declarations.get(name, [])
        if len(name_declarations) != 1:
            continue
        identifier = re.compile(
            rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])"
        )
        uses = [match.span() for match in identifier.finditer(text)]
        allowed_uses = [name_declarations[0].span("name")]
        allowed_uses.extend(match.span("name") for match in name_spreads)
        if sorted(uses) != sorted(allowed_uses):
            continue
        declaration_end = text.find(";", name_declarations[0].end())
        if declaration_end >= 0:
            ranges.append((name_declarations[0].start(), declaration_end + 1))
    return ranges


def _jsx_presentation_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in JSX_PRESENTATION_ATTRIBUTE.finditer(text):
        if not _is_open_markup_attribute(text, match.start()):
            continue
        if match.group("name").startswith("data-nyayone-"):
            spans.append(match.span("name"))
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] in {"'", '"', "`"}:
            literal = JS_STRING.match(text, index)
            if literal is not None:
                spans.append(literal.span())
        elif index < len(text) and text[index] == "{":
            end = _balanced_brace_end(text, index)
            spans.extend(_presentation_expression_literal_spans(text, index, end))
        else:
            end = index
            while end < len(text) and not text[end].isspace() and text[end] not in ">/":
                end += 1
            if end > index:
                spans.append((index, end))

    # A valueless JSX data hook has no assignment for the attribute parser to
    # anchor on. Mask only its exact attribute-name token.
    spans.extend(
        match.span()
        for match in DATA_HOOK_TOKEN.finditer(text)
        if _is_open_markup_attribute(text, match.start())
        and re.match(r"\s*=", text[match.end():]) is None
    )
    return spans


def _is_css_import_literal(text: str, match: re.Match[str]) -> bool:
    body = _decoded_runtime_projection(match.group("body"))
    if not re.search(r"\.(?:css|scss)(?:[?#].*)?$", body, re.IGNORECASE):
        return False
    line_prefix = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
    return re.search(r"\b(?:import|export)\b[^'\"`]*$", line_prefix) is not None


def _is_dom_selector_literal(text: str, match: re.Match[str]) -> bool:
    prefix = text[max(0, match.start() - 240):match.start()]
    return DOM_SELECTOR_CALL.search(prefix) is not None


def _presentation_namespace_projection(text: str, suffix: str) -> str:
    """Mask syntax-bound presentation identifiers, never namespace prefixes.

    CSS/SCSS cannot create browser authority state. In executable sources only
    exact JSX presentation attributes, CSS imports, DOM-selector literals and
    React data-hook object keys are masked. Browser authority calls are audited
    separately from the unmasked source so a side effect nested in JSX cannot
    hide behind this presentation projection.
    """

    if suffix in PRESENTATION_STYLE_SUFFIXES:
        return "".join(
            character if character in "\r\n" else " " for character in text
        )

    spans: list[tuple[int, int]] = []
    if suffix in PRESENTATION_MARKUP_SUFFIXES:
        spans.extend(_jsx_presentation_spans(text))
    data_hook_ranges = _spread_only_data_hook_declaration_ranges(text)
    for match in JS_STRING.finditer(text):
        if _is_css_import_literal(text, match) or _is_dom_selector_literal(text, match):
            spans.append(match.span())
            continue
        tail = text[match.end():match.end() + 20]
        if DATA_HOOK_OBJECT_KEY.fullmatch(match.group("body")) and re.match(
            r"\s*:", tail
        ) and any(start <= match.start() and match.end() <= end for start, end in data_hook_ranges):
            spans.append(match.span())
    return _mask_spans(text, spans)


def _decoded_runtime_projection(text: str) -> str:
    decoded = html.unescape(text)

    def replace_escape(match: re.Match[str]) -> str:
        try:
            value = int(match.group(1), 16)
            return chr(value) if value <= 0x10FFFF else match.group(0)
        except (ValueError, OverflowError):
            return match.group(0)

    decoded = re.sub(r"\\u\{([0-9A-Fa-f]{1,6})\}", replace_escape, decoded)
    decoded = re.sub(r"\\u([0-9A-Fa-f]{4})", replace_escape, decoded)
    return re.sub(r"\\x([0-9A-Fa-f]{2})", replace_escape, decoded)


def _contract_document_sha256(contract: dict[str, object]) -> str:
    payload = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _literal_atom_value(atom: str) -> str:
    if len(atom) < 2 or atom[0] not in {"'", '"', "`"} or atom[-1] != atom[0]:
        return ""
    return _decoded_runtime_projection(atom[1:-1])


def _simple_string_constants(text: str) -> dict[str, str]:
    return {
        match.group("name"): _literal_atom_value(match.group("value"))
        for match in SIMPLE_STRING_CONST.finditer(text)
    }


def _resolve_template(body: str, constants: dict[str, str]) -> tuple[str, bool]:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        expression = match.group(1).strip()
        if not expression:
            return ""
        if expression in constants:
            return constants[expression]
        if (
            len(expression) >= 2
            and expression[0] in {"'", '"', "`"}
            and expression[-1] == expression[0]
        ):
            return _literal_atom_value(expression)
        unresolved = True
        return "{dynamic}"

    return re.sub(r"\$\{([^{}]*)\}", replace, body), unresolved


def _string_expression_projections(text: str) -> tuple[tuple[str, bool], ...]:
    """Resolve a deliberately bounded set of browser-visible string expressions.

    The policy understands literal arrays joined by a literal separator,
    template substitutions containing literals/simple string constants,
    ``+`` and ``.concat`` expressions made from literals/simple string
    constants, and fixed numeric ``String.fromCharCode``/``fromCodePoint``
    calls. Unknown atoms remain marked dynamic so risky legacy-brand fragments
    fail closed.
    """

    constants = _simple_string_constants(text)
    projections: list[tuple[str, bool]] = []
    for match in JS_STRING.finditer(text):
        body = _decoded_runtime_projection(match.group("body"))
        if match.group("quote") == "`" and "${" in body:
            projections.append(_resolve_template(body, constants))
        else:
            projections.append((body, False))

    for match in CONCAT_EXPRESSION.finditer(text):
        values: list[str] = []
        unresolved = False
        for atom_match in CONCAT_ATOM.finditer(match.group("expression")):
            atom = atom_match.group(0)
            if atom[0] in {"'", '"', "`"}:
                body = _literal_atom_value(atom)
                if atom[0] == "`" and "${" in body:
                    body, dynamic = _resolve_template(body, constants)
                    unresolved = unresolved or dynamic
                values.append(body)
            elif atom in constants:
                values.append(constants[atom])
            else:
                unresolved = True
                values.append("{dynamic}")
        projections.append(("".join(values), unresolved))

    for match in ARRAY_JOIN_EXPRESSION.finditer(text):
        values = [
            _literal_atom_value(atom.group(0))
            for atom in re.finditer(JS_STRING_ATOM, match.group("items"))
        ]
        separator = _literal_atom_value(match.group("separator"))
        projections.append((separator.join(values), False))

    for match in METHOD_CONCAT_EXPRESSION.finditer(text):
        atoms = [match.group("receiver")]
        atoms.extend(
            atom.group(0)
            for atom in re.finditer(
                rf"{JS_STRING_ATOM}|{JS_IDENTIFIER}",
                match.group("items"),
            )
        )
        values: list[str] = []
        unresolved = False
        for atom in atoms:
            if atom[0] in {"'", '"', "`"}:
                values.append(_literal_atom_value(atom))
            elif atom in constants:
                values.append(constants[atom])
            else:
                unresolved = True
                values.append("{dynamic}")
        projections.append(("".join(values), unresolved))

    for match in FROM_FIXED_CODE_EXPRESSION.finditer(text):
        try:
            values = [
                int(value.strip(), 0)
                for value in match.group("codes").split(",")
            ]
            if match.group("method") == "CharCode":
                values = [value & 0xFFFF for value in values]
            elif any(value > 0x10FFFF for value in values):
                raise ValueError("invalid fixed code point")
            projections.append(("".join(chr(value) for value in values), False))
        except (OverflowError, ValueError):
            projections.append(("{dynamic}", True))
    return tuple(projections)


def _compact_ascii_letters_contains_legacy_brand(text: str) -> bool:
    positions: list[int] = []
    letters: list[str] = []
    for index, character in enumerate(text):
        if character.isascii() and character.isalpha():
            positions.append(index)
            letters.append(character.casefold())
    compact = "".join(letters)
    needle = "legalsaathi"
    offset = compact.find(needle)
    while offset >= 0:
        if positions[offset + len(needle) - 1] - positions[offset] <= 512:
            return True
        offset = compact.find(needle, offset + 1)
    return False


def _contains_constructed_legacy_brand(text: str) -> bool:
    if _compact_ascii_letters_contains_legacy_brand(text):
        return True
    for projection, unresolved in _string_expression_projections(text):
        compact = "".join(
            character.casefold()
            for character in projection
            if character.isascii() and character.isalpha()
        )
        if "legalsaathi" in compact:
            return True
        if unresolved:
            chunks = [
                "".join(
                    character.casefold()
                    for character in chunk
                    if character.isascii() and character.isalpha()
                )
                for chunk in projection.split("{dynamic}")
            ]
            needle = "legalsaathi"
            prefixes = tuple(needle[:length] for length in range(3, len(needle) + 1))
            suffixes = tuple(needle[-length:] for length in range(4, len(needle) + 1))
            if any(
                chunk.endswith(prefixes) or chunk.startswith(suffixes)
                for chunk in chunks
            ):
                return True
    return False


def _raw_runtime_namespace_candidates(text: str) -> set[str]:
    decoded = _decoded_runtime_projection(text)
    candidates = {
        match.group(0)
        for pattern in (CURRENT_RUNTIME_NAMESPACE, CURRENT_DISPLAY_REFERENCE)
        for match in pattern.finditer(decoded)
    }
    for projection, _ in _string_expression_projections(decoded):
        candidates.update(
            match.group(0)
            for pattern in (CURRENT_RUNTIME_NAMESPACE, CURRENT_DISPLAY_REFERENCE)
            for match in pattern.finditer(projection)
        )
    return candidates


def _first_argument_expression(text: str, start: int) -> str:
    """Extract one JavaScript call argument with bounded lexical balancing."""

    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    expression_start = index
    stack: list[str] = []
    quote: str | None = None
    pairs = {"(": ")", "[": "]", "{": "}"}
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character in pairs:
            stack.append(pairs[character])
        elif stack and character == stack[-1]:
            stack.pop()
        elif not stack and character in {",", ")"}:
            return text[expression_start:index]
        index += 1
    return text[expression_start:index]


def _cookie_assignment_expression(text: str, start: int) -> str:
    index = start
    expression_start = start
    quote: str | None = None
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character in {";", "\r", "\n"}:
            break
        index += 1
    return text[expression_start:index]


def _expression_with_referenced_constants(text: str, expression: str) -> str:
    declarations = {
        match.group("name"): match.group(0)
        for match in SIMPLE_STRING_CONST.finditer(text)
    }
    selected: dict[str, str] = {}
    pending = set(re.findall(rf"\b{JS_IDENTIFIER}\b", expression))
    while pending:
        name = pending.pop()
        declaration = declarations.get(name)
        if declaration is None or name in selected:
            continue
        selected[name] = declaration
        pending.update(re.findall(rf"\b{JS_IDENTIFIER}\b", declaration))
    return "\n".join((*selected.values(), expression))


def _expression_with_referenced_initializers(text: str, expression: str) -> str:
    """Expand unique simple identifier initializers for bounded taint checks."""

    matches: dict[str, list[str]] = {}
    for match in SIMPLE_IDENTIFIER_INITIALIZER.finditer(text):
        matches.setdefault(match.group("name"), []).append(match.group(0))
    declarations = {
        name: values[0] for name, values in matches.items() if len(values) == 1
    }
    selected: dict[str, str] = {}
    pending = set(re.findall(rf"\b{JS_IDENTIFIER}\b", expression))
    while pending:
        name = pending.pop()
        declaration = declarations.get(name)
        if declaration is None or name in selected:
            continue
        selected[name] = declaration
        pending.update(re.findall(rf"\b{JS_IDENTIFIER}\b", declaration))
    return "\n".join((*selected.values(), expression))


def _browser_authority_namespace_candidates(text: str) -> set[str]:
    """Project names used by browser state, cookie, event and channel APIs."""

    candidates: set[str] = set()
    for match in BROWSER_AUTHORITY_CALL.finditer(text):
        expression = _first_argument_expression(text, match.end())
        candidates.update(
            _raw_runtime_namespace_candidates(
                _expression_with_referenced_constants(text, expression)
            )
        )
    for match in DOCUMENT_COOKIE_ASSIGNMENT.finditer(text):
        expression = _cookie_assignment_expression(text, match.end())
        candidates.update(
            _raw_runtime_namespace_candidates(
                _expression_with_referenced_constants(text, expression)
            )
        )
    return candidates


def _browser_authority_uses_dom_derived_key(text: str) -> bool:
    """Reject DOM presentation state as browser-authority identifiers.

    Presentation strings may be excluded from the namespace census only while
    they remain presentation-only. Reading class/data/attribute state directly
    into storage, cache, cookie, event or channel identifiers crosses that
    boundary and must fail closed even when the argument has no string literal.
    """

    # Fail closed across bracket/optional calls and simple authority aliases.
    # A shipped module that combines DOM-derived presentation state with a
    # persistent/channel authority root needs explicit review rather than
    # relying on regex call-shape inference.
    if (
        (DOM_DERIVED_AUTHORITY_KEY.search(text) or DOM_PRESENTATION_DESTRUCTURE.search(text))
        and PERSISTENT_BROWSER_AUTHORITY_USE.search(text)
    ):
        return True

    for match in BROWSER_AUTHORITY_CALL.finditer(text):
        expression = _first_argument_expression(text, match.end())
        if DOM_DERIVED_AUTHORITY_KEY.search(
            _expression_with_referenced_initializers(text, expression)
        ):
            return True
    for match in DOCUMENT_COOKIE_ASSIGNMENT.finditer(text):
        expression = _cookie_assignment_expression(text, match.end())
        if DOM_DERIVED_AUTHORITY_KEY.search(
            _expression_with_referenced_initializers(text, expression)
        ):
            return True
    return False


def _runtime_namespace_candidates(text: str, suffix: str = "") -> set[str]:
    presentation_projection = _presentation_namespace_projection(text, suffix)
    candidates = _raw_runtime_namespace_candidates(presentation_projection)
    candidates.update(_browser_authority_namespace_candidates(text))
    return candidates


def _runtime_namespace_is_contracted(
    candidate: str,
    required_namespaces: dict[str, int],
) -> bool:
    if candidate in required_namespaces:
        return True
    if any(
        re.sub(r"\$\{[A-Za-z_$][A-Za-z0-9_$]*\}", "{dynamic}", namespace)
        == candidate
        for namespace in required_namespaces
    ):
        return True
    return any(
        namespace.endswith((".", "-")) and candidate.startswith(namespace)
        for namespace in required_namespaces
    )


def _is_legacy_browser_namespace(text: str, match: re.Match[str], suffix: str) -> bool:
    body = _decoded_runtime_projection(match.group("body"))
    if not LEGACY_NAMESPACE.fullmatch(body):
        return False
    if _is_markup_token(text, match.start()):
        return False
    if suffix in {".ts", ".js", ".mjs"}:
        return True
    window = text[max(0, match.start() - 240):min(len(text), match.end() + 240)]
    return re.search(
        r"(?:localStorage|sessionStorage|CacheStorage|caches\.|cookieStore|"
        r"document\.cookie|(?:storage|cache|namespace|key|prefix|event|channel|cookie)\b|"
        r"\.(?:get|set|remove|delete)\s*\()",
        window,
        re.IGNORECASE,
    ) is not None


def _metadata_failures(
    texts: dict[str, str], expected: dict[str, str]
) -> list[Failure]:
    if not expected:
        return [_failure("metadata-identity")]
    failures: list[Failure] = []

    try:
        package = json.loads(texts["frontend/package.json"])
    except (KeyError, json.JSONDecodeError):
        package = None
    if not isinstance(package, dict) or package.get("name") != expected["package_name"]:
        failures.append(_failure("metadata-identity", "frontend/package.json"))

    try:
        lock = json.loads(texts["frontend/package-lock.json"])
    except (KeyError, json.JSONDecodeError):
        lock = None
    lock_root = lock.get("packages", {}).get("") if isinstance(lock, dict) else None
    if (
        not isinstance(lock, dict)
        or lock.get("name") != expected["package_name"]
        or not isinstance(lock_root, dict)
        or lock_root.get("name") != expected["package_name"]
    ):
        failures.append(_failure("metadata-identity", "frontend/package-lock.json"))

    capacitor = texts.get("frontend/capacitor.config.ts", "")
    app_ids = re.findall(r"\bappId\s*:\s*['\"]([^'\"]+)['\"]", capacitor)
    app_names = re.findall(r"\bappName\s*:\s*['\"]([^'\"]+)['\"]", capacitor)
    web_dirs = re.findall(r"\bwebDir\s*:\s*['\"]([^'\"]+)['\"]", capacitor)
    android_schemes = re.findall(
        r"\bandroidScheme\s*:\s*['\"]([^'\"]+)['\"]", capacitor
    )
    if (
        app_ids != [expected["capacitor_app_id"]]
        or app_names != [expected["app_name"]]
        or web_dirs != [expected["capacitor_web_dir"]]
        or android_schemes != [expected["capacitor_android_scheme"]]
    ):
        failures.append(_failure("metadata-identity", "frontend/capacitor.config.ts"))

    index = texts.get("frontend/index.html", "")
    titles = re.findall(r"<title>\s*([^<]+?)\s*</title>", index, re.IGNORECASE)
    if titles != [expected["app_name"]]:
        failures.append(_failure("metadata-identity", "frontend/index.html"))
    module_entries: list[str] = []
    for attributes in re.findall(r"<script\s+([^>]*)>", index, re.IGNORECASE):
        script_type = re.findall(r"\btype=['\"]([^'\"]+)['\"]", attributes)
        script_src = re.findall(r"\bsrc=['\"]([^'\"]+)['\"]", attributes)
        if script_type == ["module"] and len(script_src) == 1:
            module_entries.extend(script_src)
    if module_entries != ["/src/main.tsx"]:
        failures.append(_failure("metadata-identity", "frontend/index.html"))

    service_worker = texts.get("frontend/public/sw.js", "")
    caches = re.findall(r"\bCACHE\s*=\s*['\"]([^'\"]+)['\"]", service_worker)
    if caches != [expected["service_worker_cache"]]:
        failures.append(_failure("metadata-identity", "frontend/public/sw.js"))

    for relative in (
        "frontend/src/i18n/locales/en.json",
        "frontend/src/i18n/locales/hi.json",
    ):
        try:
            locale = json.loads(texts[relative])
        except (KeyError, json.JSONDecodeError):
            locale = None
        if not isinstance(locale, dict) or locale.get("app.name") != expected["app_name"]:
            failures.append(_failure("metadata-identity", relative))
    return failures


def _deduplicate(failures: Iterable[Failure]) -> tuple[Failure, ...]:
    return tuple(sorted(set(failures)))


def _audit_tree(
    root: Path,
    contract: dict[str, object],
    *,
    self_test: SelfTestResult,
    namespace_contract_sha256: str | None = None,
) -> AuditReport:
    failures: list[Failure] = []
    try:
        root_mode = root.lstat().st_mode
    except OSError:
        root_mode = 0
    if not stat.S_ISDIR(root_mode) or stat.S_ISLNK(root_mode):
        failures.append(_failure("unsafe-root", root.as_posix()))

    metadata, required_namespaces, compatibility, contract_failures = _contract_parts(contract)
    failures.extend(contract_failures)
    inventory = shipped_source_inventory(root)
    inventory_digest = source_inventory_sha256(inventory)
    if inventory_digest != contract.get("source_inventory_sha256"):
        failures.append(_failure("source-inventory"))
    for relative in REQUIRED_METADATA_PATHS:
        if relative not in inventory:
            failures.append(_failure("required-source", relative))
    if "frontend/public/sw.js" not in inventory:
        failures.append(_failure("required-source", "frontend/public/sw.js"))

    texts, read_failures = _read_inventory(root, inventory)
    failures.extend(read_failures)
    failures.extend(_metadata_failures(texts, metadata))

    compatibility_literal_count = 0
    masked_texts: dict[str, str] = {}
    for relative, text in texts.items():
        runtime_text = _mask_nonruntime_comments(
            text, Path(relative).suffix.casefold()
        )
        spans, count, span_failures = _allowed_spans(
            relative, runtime_text, compatibility
        )
        compatibility_literal_count += count
        failures.extend(span_failures)
        masked_texts[relative] = _mask_spans(runtime_text, spans)

    for relative, source in compatibility.items():
        path = root / relative
        if relative not in inventory or not path.is_file() or path.is_symlink():
            failures.append(_failure("compatibility-source-missing", relative))
            continue
        try:
            actual = sha256_file(path)
        except OSError:
            failures.append(_failure("compatibility-source-hash", relative))
            continue
        if actual != source["sha256"]:
            failures.append(_failure("compatibility-source-hash", relative))

    combined = "\n".join(masked_texts.values())
    for namespace, expected_count in required_namespaces.items():
        if combined.count(namespace) != expected_count:
            failures.append(_failure("required-runtime-namespace"))

    for relative, text in masked_texts.items():
        decoded = _decoded_runtime_projection(text)
        if LEGACY_BRAND.search(decoded) or _contains_constructed_legacy_brand(decoded):
            failures.append(_failure("legacy-brand", relative))
        suffix = Path(relative).suffix.casefold()
        if _browser_authority_uses_dom_derived_key(text) or any(
            not _runtime_namespace_is_contracted(candidate, required_namespaces)
            for candidate in _runtime_namespace_candidates(text, suffix)
        ):
            failures.append(_failure("uncontracted-runtime-namespace", relative))
        presentation_text = _presentation_namespace_projection(text, suffix)
        for match in JS_STRING.finditer(presentation_text):
            if _is_legacy_browser_namespace(presentation_text, match, suffix):
                failures.append(_failure("legacy-browser-namespace", relative))
                break
        if re.search(
            r"(?:from|import\s*\()\s*['\"][^'\"]*(?:\.test\.|\.spec\.|/tests?/)",
            text,
        ):
            failures.append(_failure("excluded-source-import", relative))

    unique = _deduplicate(failures)
    return AuditReport(
        failures=unique,
        scanned_files=len(texts),
        source_inventory_count=len(inventory),
        source_inventory_sha256=inventory_digest,
        namespace_contract_sha256=(
            namespace_contract_sha256 or _contract_document_sha256(contract)
        ),
        compatibility_source_count=len(compatibility),
        compatibility_literal_count=compatibility_literal_count,
        self_test_passed=self_test.passed,
        self_test_mutants=self_test.mutants,
        self_test_mutants_killed=self_test.mutants_killed,
    )


def _self_test_fixture(root: Path) -> dict[str, object]:
    files = {
        "frontend/index.html": (
            "<!doctype html><title>NyayOne</title>"
            "<script type=\"module\" src=\"/src/main.tsx\"></script>\n"
        ),
        "frontend/package.json": '{"name":"nyayone-frontend"}\n',
        "frontend/package-lock.json": (
            '{"name":"nyayone-frontend","packages":{"":{"name":"nyayone-frontend"}}}\n'
        ),
        "frontend/capacitor.config.ts": (
            "export default { appId: 'com.nyayone.app', appName: 'NyayOne', "
            "webDir: 'dist', server: { androidScheme: 'https' } };\n"
        ),
        "frontend/vite.config.ts": "export default {};\n",
        "frontend/public/sw.js": "const CACHE = 'nyayone-shell-v1';\n",
        "frontend/src/main.ts": "export const EVENT = 'nyayone:self-test.v1';\n",
        "frontend/src/i18n/locales/en.json": '{"app.name":"NyayOne"}\n',
        "frontend/src/i18n/locales/hi.json": '{"app.name":"NyayOne"}\n',
        "frontend/src/compat.ts": (
            "export const RETIRED = 'legalsaathi.self-test.retired.v1';\n"
            "export const purge = (s: Storage) => s.removeItem(RETIRED);\n"
        ),
    }
    for relative, value in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    compatibility = root / "frontend/src/compat.ts"
    return {
        "schema_version": 1,
        "source_inventory_sha256": source_inventory_sha256(
            shipped_source_inventory(root)
        ),
        "metadata": {
            "package_name": "nyayone-frontend",
            "capacitor_app_id": "com.nyayone.app",
            "capacitor_android_scheme": "https",
            "capacitor_web_dir": "dist",
            "app_name": "NyayOne",
            "service_worker_cache": "nyayone-shell-v1",
        },
        "required_runtime_namespaces": {
            "nyayone-frontend": 3,
            "nyayone-shell-": 1,
            "nyayone-shell-v1": 1,
            "nyayone.app": 1,
            "nyayone:self-test.v1": 1,
        },
        "compatibility_sources": {
            "frontend/src/compat.ts": {
                "sha256": sha256_file(compatibility),
                "allowed_literals": {
                    "legalsaathi.self-test.retired.v1": 1,
                },
            }
        },
    }


def run_self_test() -> SelfTestResult:
    mutations = (
        (
            "legacy-brand-direct",
            "append",
            "frontend/src/main.ts",
            f"export const BRAND = '{PLANTED_BRAND_CANARY}';\n",
        ),
        (
            "legacy-brand-spaced",
            "append",
            "frontend/src/main.ts",
            "export const BRAND = 'Legal Saathi';\n",
        ),
        (
            "legacy-namespace",
            "append",
            "frontend/src/main.ts",
            "export const KEY = 'legalsaathi.planted.v1';\n",
        ),
        (
            "legacy-storage-key",
            "append",
            "frontend/src/main.ts",
            f"const STORAGE_KEY = '{PLANTED_NAMESPACE_CANARY}';\n"
            "localStorage.setItem(STORAGE_KEY, 'x');\n",
        ),
        (
            "metadata-drift",
            "append",
            "frontend/index.html",
            "<!doctype html><title>Other</title>\n",
        ),
        (
            "source-inventory-drift",
            "append",
            "frontend/src/added.ts",
            "export const brand = 'NyayOne';\n",
        ),
        (
            "compatibility-hash-drift",
            "compatibility-hash",
            "frontend/src/compat.ts",
            "",
        ),
        (
            "unsafe-source-node",
            "unsafe-source",
            "frontend/src/unsafe.ts",
            "",
        ),
        (
            "uncontracted-current-namespace",
            "append",
            "frontend/src/main.ts",
            "localStorage.setItem('nyayone.planted.private.v1', 'secret');\n",
        ),
        (
            "constructed-brand-array-join",
            "append",
            "frontend/src/main.ts",
            "export const brand = ['Legal', 'Saathi'].join('');\n",
        ),
        (
            "constructed-brand-const-propagation",
            "append",
            "frontend/src/main.ts",
            "const first = 'Legal'; const second = 'Saathi'; "
            "export const brand = first + second;\n",
        ),
        (
            "constructed-brand-template-interpolation",
            "append",
            "frontend/src/main.ts",
            "export const brand = `Legal${''}Saathi`;\n",
        ),
        (
            "constructed-brand-multi-fragment",
            "append",
            "frontend/src/main.ts",
            "export const brand = 'Leg' + 'al' + 'Saa' + 'thi';\n",
        ),
        (
            "constructed-brand-literal-concat-method",
            "append",
            "frontend/src/main.ts",
            "export const brand = 'Legal'.concat('Saathi');\n",
        ),
        (
            "constructed-brand-literal-character-codes",
            "append",
            "frontend/src/main.ts",
            "export const brand = String.fromCharCode("
            "76,101,103,97,108,83,97,97,116,104,105);\n",
        ),
        (
            "constructed-brand-literal-code-points",
            "append",
            "frontend/src/main.ts",
            "export const brand = String.fromCodePoint("
            "76,101,103,97,108,83,97,97,116,104,105);\n",
        ),
        (
            "constructed-current-literal-code-points",
            "append",
            "frontend/src/main.ts",
            "localStorage.setItem(String.fromCodePoint("
            "110,121,97,121,111,110,101,46,112,108,97,110,116,101,100,46,"
            "118,49), 'secret');\n",
        ),
    )
    if tuple(name for name, *_ in mutations) != PLANTED_MUTANT_NAMES:
        return SelfTestResult(False, len(PLANTED_MUTANT_NAMES), 0)
    killed = 0
    with tempfile.TemporaryDirectory(prefix="nyay18-static-selftest-") as directory:
        baseline_root = Path(directory) / "baseline"
        baseline_contract = _self_test_fixture(baseline_root)
        neutral = SelfTestResult(
            passed=True,
            mutants=len(mutations),
            mutants_killed=len(mutations),
        )
        clean = _audit_tree(baseline_root, baseline_contract, self_test=neutral)
        if clean.failures:
            return SelfTestResult(False, len(mutations), 0)

    for _, mutation, relative, replacement in mutations:
        with tempfile.TemporaryDirectory(prefix="nyay18-static-mutant-") as directory:
            root = Path(directory)
            contract = _self_test_fixture(root)
            path = root / relative
            if mutation == "compatibility-hash":
                path.write_text(
                    path.read_text(encoding="utf-8").replace("removeItem", "setItem"),
                    encoding="utf-8",
                )
            elif mutation == "unsafe-source":
                path.symlink_to(root / "frontend/src/main.ts")
            elif path.exists():
                path.write_text(path.read_text(encoding="utf-8") + replacement, encoding="utf-8")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(replacement, encoding="utf-8")
            report = _audit_tree(
                root,
                contract,
                self_test=SelfTestResult(True, len(mutations), len(mutations)),
            )
            if report.failures:
                killed += 1
    return SelfTestResult(killed == len(mutations), len(mutations), killed)


def audit(
    root: Path,
    contract: dict[str, object],
    *,
    namespace_contract_sha256: str | None = None,
) -> AuditReport:
    self_test = run_self_test()
    absolute_root = Path(os.path.abspath(root.expanduser()))
    return _audit_tree(
        absolute_root,
        contract,
        self_test=self_test,
        namespace_contract_sha256=namespace_contract_sha256,
    )


def _write_evidence(path: Path, report: AuditReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.evidence(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test-only", action="store_true")
    args = parser.parse_args()

    if args.self_test_only:
        result = run_self_test()
        if not result.passed:
            print(
                f"NYAY-18 planted-canary self-test failed: "
                f"killed={result.mutants_killed}/{result.mutants}",
                file=sys.stderr,
            )
            return 1
        print(
            f"NYAY-18 planted-canary self-test passed: "
            f"killed={result.mutants_killed}/{result.mutants}"
        )
        return 0

    contract, contract_failures = _load_json(args.contract)
    if contract is None:
        print("NYAY-18 namespace gate failed: contract is unavailable", file=sys.stderr)
        return 1
    try:
        contract_digest = sha256_file(args.contract)
    except OSError:
        contract_digest = _contract_document_sha256(contract)
    report = audit(
        args.root,
        contract,
        namespace_contract_sha256=contract_digest,
    )
    if contract_failures:
        report = AuditReport(
            failures=_deduplicate((*report.failures, *contract_failures)),
            scanned_files=report.scanned_files,
            source_inventory_count=report.source_inventory_count,
            source_inventory_sha256=report.source_inventory_sha256,
            namespace_contract_sha256=report.namespace_contract_sha256,
            compatibility_source_count=report.compatibility_source_count,
            compatibility_literal_count=report.compatibility_literal_count,
            self_test_passed=report.self_test_passed,
            self_test_mutants=report.self_test_mutants,
            self_test_mutants_killed=report.self_test_mutants_killed,
        )
    if args.output:
        _write_evidence(args.output, report)
    if report.failures or not report.self_test_passed:
        print("NYAY-18 namespace gate failed:", file=sys.stderr)
        for failure in report.failures:
            print(f"{failure.path}: {failure.code}", file=sys.stderr)
        if not report.self_test_passed:
            print(
                f"self-test: killed {report.self_test_mutants_killed}/"
                f"{report.self_test_mutants}",
                file=sys.stderr,
            )
        return 1
    print(
        "NYAY-18 namespace gate passed: "
        f"files={report.scanned_files} compatibility_literals="
        f"{report.compatibility_literal_count} self_test="
        f"{report.self_test_mutants_killed}/{report.self_test_mutants}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

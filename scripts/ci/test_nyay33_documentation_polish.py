#!/usr/bin/env python3
"""NYAY-33 tests-first contracts for the NYAY-29 design-document follow-up.

These tests intentionally describe the reconciled documentation state.  They
must remain RED until the separately authorized GREEN phase edits the four
NYAY-29 design artifacts.  No product implementation is in scope here.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESIGN_ROOT = ROOT / "docs/architecture/nyay29-tutor-lawyer-ceremony"
STRIDE_PATH = DESIGN_ROOT / "STRIDE_THREAT_MODEL.md"
TRUST_PATH = DESIGN_ROOT / "TRUST_BOUNDARIES_AND_DATA_FLOW.md"
SEQUENCE_PATH = DESIGN_ROOT / "CEREMONY_SEQUENCE_DIAGRAMS.md"
OPENAPI_PATH = DESIGN_ROOT / "CEREMONY_API_CONTRACT.openapi.json"


def _section(text: str, start: str, end: str) -> str:
    if start not in text or end not in text:
        raise AssertionError(f"NYAY33-SECTION-MISSING:{start}")
    return text.split(start, 1)[1].split(end, 1)[0]


def _stride_failure_codes(text: str) -> set[str]:
    inventory = _section(
        text,
        "The public typed failure inventory is closed and generic:",
        "Every response has",
    )
    return set(re.findall(r"\|\s*`\d{3}`\s*\|\s*`([A-Z][A-Z0-9_]+)`", inventory))


def _trust_failure_codes(text: str) -> set[str]:
    inventory = _section(
        text,
        "Failures use a closed public inventory:",
        "Every response uses",
    )
    return set(re.findall(r"`\d{3}\s+([A-Z][A-Z0-9_]+)`", inventory))


def _openapi_operation(document: dict[str, object], operation_id: str) -> dict[str, object]:
    for path_item in document["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                return operation
    raise AssertionError(f"NYAY33-OPERATION-MISSING:{operation_id}")


class Nyay33DocumentationPolishContracts(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.stride = STRIDE_PATH.read_text(encoding="utf-8")
        cls.trust = TRUST_PATH.read_text(encoding="utf-8")
        cls.sequence = SEQUENCE_PATH.read_text(encoding="utf-8")
        cls.openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    def test_f01_public_failure_codes_and_sequence_labels_are_one_closed_inventory(self) -> None:
        stride_codes = _stride_failure_codes(self.stride)
        trust_codes = _trust_failure_codes(self.trust)
        openapi_codes = set(
            self.openapi["components"]["schemas"]["MentorFailure"]["properties"]
            ["detail"]["properties"]["code"]["enum"]
        )
        sequence_codes = set(
            re.findall(
                r"\b(?:400|401|403|404|409|410|429|503)\s+([A-Z][A-Z0-9_]+)\b",
                self.sequence,
            )
        )

        findings: dict[str, object] = {}
        if stride_codes != openapi_codes:
            findings["stride"] = {
                "declared": len(stride_codes),
                "missing": sorted(openapi_codes - stride_codes),
                "extra": sorted(stride_codes - openapi_codes),
            }
        if trust_codes != openapi_codes:
            findings["trust"] = {
                "declared": len(trust_codes),
                "missing": sorted(openapi_codes - trust_codes),
                "extra": sorted(trust_codes - openapi_codes),
            }
        unknown_sequence_codes = sequence_codes - openapi_codes
        if unknown_sequence_codes:
            findings["sequenceUnknown"] = sorted(unknown_sequence_codes)

        self.assertEqual(
            findings,
            {},
            "F-01: STRIDE, trust-boundary, sequence, and OpenAPI public failure labels "
            "must be one exact closed inventory",
        )

    def test_f02_exchange_and_rotation_cookie_header_refs_match_their_effects(self) -> None:
        exchange = _openapi_operation(self.openapi, "exchangeTutorCeremony")
        rotate = _openapi_operation(self.openapi, "rotateTutorSession")
        actual = {
            "exchange:201": exchange["responses"]["201"]["headers"]["Set-Cookie"]["$ref"],
            "rotate:200": rotate["responses"]["200"]["headers"]["Set-Cookie"]["$ref"],
        }
        self.assertEqual(
            actual,
            {
                "exchange:201": "#/components/headers/MentorSessionCookieIssued",
                "rotate:200": "#/components/headers/MentorSessionCookieRotated",
            },
            "F-02: initial exchange must issue, while rotation must rotate, the mentor cookie",
        )

    def test_f03_recovery_revocation_has_one_authoritative_commit_point(self) -> None:
        stride_verify_row = next(
            row for row in self.stride.splitlines() if "`verifyTutorIdentity`" in row
        )
        stride_exchange_row = next(
            row for row in self.stride.splitlines() if "`exchangeTutorCeremony`" in row
        )
        stride_point = (
            "verify"
            if "revoke old generations" in stride_verify_row
            else "exchange"
            if "revoke old generations" in stride_exchange_row
            else "unknown"
        )

        trust_verify = _section(self.trust, "7. `verifyTutorIdentity`", "8. `exchangeTutorCeremony`")
        trust_exchange = _section(self.trust, "8. `exchangeTutorCeremony`", "9. Cookie issuance")
        trust_point = (
            "verify"
            if "revokes old actor/profile generations" in trust_verify
            else "exchange"
            if "revokes old actor/profile generations" in trust_exchange
            else "unknown"
        )

        recovery_sequence = _section(
            self.sequence,
            "Browser->>AuthAPI: POST /api/v1/auth/mentor/ceremony/recover",
            "Note over Browser,Audit: Authority deletion",
        )
        revoke_index = recovery_sequence.find("Revoke all prior actor/profile generations")
        exchange_index = recovery_sequence.find("POST exchange with recovery intent")
        sequence_point = (
            "verify"
            if 0 <= revoke_index < exchange_index
            else "exchange"
            if exchange_index >= 0 and revoke_index > exchange_index
            else "unknown"
        )

        verify_description = _openapi_operation(self.openapi, "verifyTutorIdentity")["description"]
        exchange_description = _openapi_operation(self.openapi, "exchangeTutorCeremony")["description"]
        recover_description = _openapi_operation(self.openapi, "recoverTutorCeremony")["description"]
        openapi_point = (
            "verify"
            if "revokes every prior" in verify_description
            else "exchange"
            if (
                "first revokes every prior" in exchange_description
                or "exchange must commit that revocation" in recover_description
            )
            else "unknown"
        )

        commit_points = {
            "STRIDE": stride_point,
            "trust": trust_point,
            "sequence": sequence_point,
            "OpenAPI": openapi_point,
        }
        self.assertNotIn("unknown", commit_points.values(), f"F-03: {commit_points}")
        self.assertEqual(
            len(set(commit_points.values())),
            1,
            "F-03: recovery revocation must have one documented atomic commit point; "
            f"found {commit_points}",
        )

    def test_f04_sensitive_403_denials_are_one_non_enumerating_public_code(self) -> None:
        stride_403 = set(
            re.findall(r"\|\s*`403`\s*\|\s*`([A-Z][A-Z0-9_]+)`", self.stride)
        )
        trust_403 = set(re.findall(r"`403\s+([A-Z][A-Z0-9_]+)`", self.trust))
        openapi_403 = set(self.openapi["x-nyayone-failure-status-map"]["403"])
        forbidden_codes = set(
            self.openapi["components"]["schemas"]["MentorForbiddenFailure"]["allOf"][1]
            ["properties"]["detail"]["properties"]["code"]["enum"]
        )
        forbidden_description = self.openapi["components"]["responses"]["Forbidden"][
            "description"
        ]

        self.assertEqual(stride_403, trust_403, "F-04: Markdown 403 inventories diverge")
        self.assertIn("intentionally collapses", forbidden_description)
        self.assertEqual(openapi_403, forbidden_codes)

        # STEP_UP_REQUIRED is an action-bound authentication condition, not a
        # sensitive role/profile/guardian/relation denial.  Every remaining
        # 403 reason must collapse to one non-enumerating public code.
        sensitive_denial_codes = openapi_403 - {"STEP_UP_REQUIRED"}
        self.assertEqual(
            len(sensitive_denial_codes),
            1,
            "F-04: OpenAPI claims sensitive denial collapse but exposes split codes "
            f"{sorted(sensitive_denial_codes)}; Markdown declares {sorted(stride_403)}",
        )


if __name__ == "__main__":
    unittest.main()

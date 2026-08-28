#!/usr/bin/env python3
"""Read-only structural gate for the NYAY-29 ceremony design package.

The gate validates design artifacts only.  It imports no application modules,
changes no repository state, and does not claim that any proposed control is
implemented.  During the RED phase it intentionally reports the absent future
artifacts with a stable, machine-readable inventory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "nyay29-ceremony-design/v1"
HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
DEFAULT_CONTRACT = HERE / "nyay29_ceremony_design_contract.json"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _finding(code: str, artifact: str, unit: str | None = None, detail: str | None = None) -> dict[str, str]:
    row = {"code": code, "artifact": artifact}
    if unit is not None:
        row["unit"] = unit
    if detail is not None:
        row["detail"] = detail
    return row


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("NYAY29_CONTRACT_SCHEMA_MISMATCH")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 4:
        raise ValueError("NYAY29_CONTRACT_ARTIFACT_INVENTORY_INVALID")
    if sum(len(item.get("units", [])) for item in artifacts) != 16:
        raise ValueError("NYAY29_CONTRACT_UNIT_INVENTORY_INVALID")
    return value


def _contains(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def _heading_body(text: str, heading: str) -> str | None:
    pattern = re.compile(
        rf"(?ms)^##{{1,5}}\s+{re.escape(heading)}\s*$\n(.*?)(?=^##{{1,5}}\s+|\Z)"
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _validate_markdown(artifact: dict[str, Any], text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    artifact_id = artifact["id"]
    for term in artifact.get("requiredTerms", []):
        if not _contains(text, term):
            findings.append(_finding("MISSING_ARTIFACT_TERM", artifact_id, detail=term))
    for unit in artifact["units"]:
        body = _heading_body(text, unit["heading"])
        if body is None:
            findings.append(_finding("MISSING_SECTION", artifact_id, unit["id"], unit["heading"]))
            continue
        for term in unit.get("requiredTerms", []):
            if not _contains(body, term):
                findings.append(_finding("MISSING_SECTION_TERM", artifact_id, unit["id"], term))
    return findings


def _openapi_operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for path_item in document.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if isinstance(operation, dict) and isinstance(operation.get("operationId"), str):
                operations[operation["operationId"]] = operation
    return operations


def _validate_openapi(artifact: dict[str, Any], text: str) -> list[dict[str, str]]:
    artifact_id = artifact["id"]
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return [_finding("INVALID_OPENAPI_JSON", artifact_id)]
    findings: list[dict[str, str]] = []
    if not str(document.get("openapi", "")).startswith("3."):
        findings.append(_finding("INVALID_OPENAPI_VERSION", artifact_id))
    schemas = document.get("components", {}).get("schemas", {})
    for schema in artifact.get("requiredSchemas", []):
        if schema not in schemas:
            findings.append(_finding("MISSING_API_SCHEMA", artifact_id, detail=schema))
    operations = _openapi_operations(document)
    required_failures = set(artifact.get("requiredFailureStatuses", []))
    for unit in artifact["units"]:
        unit_missing = False
        for operation_id in unit["operationIds"]:
            operation = operations.get(operation_id)
            if operation is None:
                findings.append(_finding("MISSING_API_OPERATION", artifact_id, unit["id"], operation_id))
                unit_missing = True
                continue
            if "security" not in operation:
                findings.append(_finding("MISSING_API_SECURITY", artifact_id, unit["id"], operation_id))
            responses = operation.get("responses", {})
            if not any(str(code).startswith("2") for code in responses):
                findings.append(_finding("MISSING_API_SUCCESS", artifact_id, unit["id"], operation_id))
            for code in sorted(required_failures - {str(code) for code in responses}):
                findings.append(_finding("MISSING_API_FAILURE", artifact_id, unit["id"], f"{operation_id}:{code}"))
            if operation_id != "getTutorSession" and "requestBody" not in operation:
                findings.append(_finding("MISSING_API_REQUEST", artifact_id, unit["id"], operation_id))
        if unit_missing:
            findings.append(_finding("MISSING_SECTION", artifact_id, unit["id"], "operation group incomplete"))
    return findings


def validate(root: Path, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    findings: list[dict[str, str]] = []
    missing_artifacts: list[str] = []
    missing_units: set[str] = set()
    package_text: list[str] = []
    present_artifacts = 0

    for artifact in contract["artifacts"]:
        artifact_id = artifact["id"]
        path = root / artifact["path"]
        if not path.is_file():
            missing_artifacts.append(artifact_id)
            findings.append(_finding("MISSING_ARTIFACT", artifact_id, detail=artifact["path"]))
            for unit in artifact["units"]:
                missing_units.add(unit["id"])
                findings.append(_finding("MISSING_SECTION", artifact_id, unit["id"], "artifact absent"))
            continue
        present_artifacts += 1
        text = path.read_text(encoding="utf-8")
        package_text.append(text)
        if artifact["format"] == "markdown":
            artifact_findings = _validate_markdown(artifact, text)
        elif artifact["format"] == "openapi-json":
            artifact_findings = _validate_openapi(artifact, text)
        else:
            artifact_findings = [_finding("UNKNOWN_ARTIFACT_FORMAT", artifact_id)]
        findings.extend(artifact_findings)
        missing_units.update(
            item["unit"] for item in artifact_findings if item["code"] == "MISSING_SECTION" and "unit" in item
        )

    combined = "\n".join(package_text)
    missing_cross_cutting: list[str] = []
    for requirement in contract.get("crossCuttingRequirements", []):
        if any(not _contains(combined, term) for term in requirement["terms"]):
            missing_cross_cutting.append(requirement["id"])
            findings.append(_finding("MISSING_CROSS_CUTTING_REQUIREMENT", "package", requirement["id"]))

    expected_artifacts = len(contract["artifacts"])
    expected_units = sum(len(item["units"]) for item in contract["artifacts"])
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "ticket": contract["ticket"],
        "classification": "GREEN" if not findings else "RED",
        "counts": {
            "expectedArtifacts": expected_artifacts,
            "presentArtifacts": present_artifacts,
            "missingArtifacts": len(missing_artifacts),
            "expectedUnits": expected_units,
            "missingUnits": len(missing_units),
            "expectedCrossCutting": len(contract.get("crossCuttingRequirements", [])),
            "missingCrossCutting": len(missing_cross_cutting),
        },
        "missingArtifacts": missing_artifacts,
        "missingUnits": sorted(missing_units),
        "missingCrossCutting": missing_cross_cutting,
        "findings": findings,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = validate(args.root.resolve(), load_contract(args.contract.resolve()))
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0 if result["classification"] == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())

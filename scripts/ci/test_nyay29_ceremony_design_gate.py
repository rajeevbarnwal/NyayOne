#!/usr/bin/env python3
"""NYAY-29 tests-first design-contract baseline.

The final test is intentionally RED until the separately authorized GREEN
phase supplies the four design artifacts.  Synthetic fixtures prove the gate
is satisfiable and is not hard-coded to reject every package.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUBJECT = HERE / "nyay29_ceremony_design_gate.py"
CONTRACT_PATH = HERE / "nyay29_ceremony_design_contract.json"


def load_gate():
    spec = importlib.util.spec_from_file_location("nyay29_ceremony_design_gate", SUBJECT)
    if spec is None or spec.loader is None:
        raise AssertionError("NYAY29-GATE-IMPORT: validator import unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _markdown_for(artifact: dict[str, object], cross_cutting: list[dict[str, object]]) -> str:
    lines = [f"# Synthetic {artifact['id']}", "", "Design fixture only.", ""]
    lines.extend(str(term) for term in artifact.get("requiredTerms", []))
    lines.append("")
    for unit in artifact["units"]:
        lines.extend([f"## {unit['heading']}", ""])
        lines.extend(str(term) for term in unit.get("requiredTerms", []))
        lines.append("")
    for requirement in cross_cutting:
        lines.extend(str(term) for term in requirement["terms"])
    return "\n".join(lines) + "\n"


def _openapi_for(artifact: dict[str, object], cross_cutting: list[dict[str, object]]) -> dict[str, object]:
    paths: dict[str, object] = {}
    for unit in artifact["units"]:
        for operation_id in unit["operationIds"]:
            operation = {
                "operationId": operation_id,
                "security": [{"mentorSession": []}],
                "responses": {
                    "200": {"description": "Synthetic success"},
                    **{
                        code: {"description": "Synthetic typed failure"}
                        for code in artifact["requiredFailureStatuses"]
                    },
                },
            }
            if operation_id != "getTutorSession":
                operation["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            paths[f"/synthetic/{operation_id}"] = {"post": operation}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Synthetic NYAY-29 contract",
            "version": "0.0.0",
            "description": " ".join(
                str(term) for requirement in cross_cutting for term in requirement["terms"]
            ),
        },
        "paths": paths,
        "components": {
            "securitySchemes": {"mentorSession": {"type": "apiKey", "in": "cookie", "name": "synthetic"}},
            "schemas": {name: {"type": "object"} for name in artifact["requiredSchemas"]},
        },
    }


def create_synthetic_package(root: Path, contract: dict[str, object]) -> None:
    cross_cutting = contract["crossCuttingRequirements"]
    for artifact in contract["artifacts"]:
        path = root / artifact["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if artifact["format"] == "markdown":
            path.write_text(_markdown_for(artifact, cross_cutting), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(_openapi_for(artifact, cross_cutting), sort_keys=True) + "\n",
                encoding="utf-8",
            )


class Nyay29CeremonyDesignGateTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate()
        cls.contract = cls.gate.load_contract(CONTRACT_PATH)

    def test_01_contract_inventory_is_closed_and_design_only(self) -> None:
        self.assertEqual(self.contract["schemaVersion"], "nyay29-ceremony-design/v1")
        self.assertEqual(self.contract["ticket"], "NYAY-29")
        self.assertEqual(self.contract["implementationTicket"], "NYAY-22")
        self.assertEqual(self.contract["scope"], "design-and-threat-model-only")
        self.assertEqual(len(self.contract["artifacts"]), 4)
        self.assertEqual(sum(len(row["units"]) for row in self.contract["artifacts"]), 16)
        self.assertEqual(
            [row["format"] for row in self.contract["artifacts"]],
            ["markdown", "markdown", "markdown", "openapi-json"],
        )

    def test_02_empty_tree_reports_exact_missing_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.gate.validate(Path(temp), self.contract)
        self.assertEqual(result["classification"], "RED")
        self.assertEqual(result["counts"]["missingArtifacts"], 4)
        self.assertEqual(result["counts"]["missingUnits"], 16)
        self.assertEqual(result["counts"]["missingCrossCutting"], 8)
        self.assertEqual(len(result["missingArtifacts"]), 4)

    def test_03_synthetic_complete_package_proves_gate_can_turn_green(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_synthetic_package(root, self.contract)
            result = self.gate.validate(root, self.contract)
        self.assertEqual(result["classification"], "GREEN", result["findings"])
        self.assertEqual(result["counts"]["missingArtifacts"], 0)
        self.assertEqual(result["counts"]["missingUnits"], 0)
        self.assertEqual(result["counts"]["missingCrossCutting"], 0)

    def test_04_incomplete_stride_and_api_contracts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_synthetic_package(root, self.contract)
            stride = root / self.contract["artifacts"][0]["path"]
            stride.write_text(
                stride.read_text(encoding="utf-8").replace("Elevation of privilege", ""),
                encoding="utf-8",
            )
            api_path = root / self.contract["artifacts"][3]["path"]
            api = json.loads(api_path.read_text(encoding="utf-8"))
            api["paths"].pop("/synthetic/verifyTutorIdentity")
            api_path.write_text(json.dumps(api, sort_keys=True) + "\n", encoding="utf-8")
            result = self.gate.validate(root, self.contract)
        codes = {row["code"] for row in result["findings"]}
        self.assertEqual(result["classification"], "RED")
        self.assertIn("MISSING_ARTIFACT_TERM", codes)
        self.assertIn("MISSING_API_OPERATION", codes)
        self.assertIn("MISSING_SECTION", codes)

    def test_05_repository_design_package_is_green(self) -> None:
        result = self.gate.validate(ROOT, self.contract)
        self.assertEqual(
            result["classification"],
            "GREEN",
            "NYAY-29 RED — design package is absent: "
            f"{result['counts']['missingArtifacts']}/4 artifacts, "
            f"{result['counts']['missingUnits']}/16 required units, and "
            f"{result['counts']['missingCrossCutting']}/8 cross-cutting contracts are missing",
        )


if __name__ == "__main__":
    unittest.main()

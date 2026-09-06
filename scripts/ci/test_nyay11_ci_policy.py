#!/usr/bin/env python3
"""NYAY-11 native authority gate cannot disappear behind a green CI result."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def policy_module():
    spec = importlib.util.spec_from_file_location("verify_nyayone_ci", HERE / "verify_nyayone_ci.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Nyay11CiPolicyTests(unittest.TestCase):
    def test_authority_policy_contract_is_discovered_exactly_once(self):
        policy = policy_module()
        command = "python scripts/ci/test_nyay11_ci_policy.py"
        key = ("nyayone-policy-gate.yml", "policy-contracts")
        self.assertEqual(getattr(policy, "EXPECTED_NYAY11_POLICY_COMMAND", None), command)
        self.assertIn(command, policy.REQUIRED_JOB_RUNS[key])
        workflow = policy.WORKFLOWS / key[0]
        source = workflow.read_text()
        self.assertEqual(source.count(command), 1)
        for mutant in (source.replace(command, "true"), source.replace(command, f"{command}\n          {command}")):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / workflow.name
                path.write_text(mutant)
                self.assertTrue(policy.check_workflow(path))

    def test_native_gate_is_unconditional_before_mentor_gate(self):
        policy = policy_module()
        self.assertEqual(policy.check_nyay11_db_gate_contract(), [])

    def test_native_gate_absence_duplication_and_bypasses_are_rejected(self):
        policy = policy_module()
        source = policy.DB_GATE.read_text()
        block = policy.EXPECTED_NYAY11_DB_GATE_BLOCK
        self.assertEqual(source.count(block), 1)
        for label, replacement in {
            "missing": "",
            "duplicate": block + block,
            "conditional": f"if false; then\n{block}fi\n",
            "ignored-error": block.rstrip() + " || true\n",
            "help-only": block.replace("--database-url", "--help --database-url"),
        }.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "db_gate.sh"
                path.write_text(source.replace(block, replacement))
                self.assertTrue(policy.check_nyay11_db_gate_contract(path))


if __name__ == "__main__":
    unittest.main()

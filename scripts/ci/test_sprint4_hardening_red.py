"""Enforced tests-first contracts for NYAY-24/25/31/35/36 and header hygiene."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Sprint4HardeningRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = load('scan_evidence')
        cls.gate = load('nyay14_evidence_gate')

    def test_merged_producer_and_contract_headers_have_no_stale_authorization(self):
        # Before PR #24 merges, exercise its exact reviewed candidate through
        # an explicit ref override. During implementation, scan the actual
        # tracked working files so uncommitted fixes are tested before push.
        root = HERE.parent.parent
        ref = os.environ.get('SPRINT4_HEADER_REVIEWED_REF')
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args])
        roots = ('frontend/scripts', 'backend/scripts', 'backend/tests', 'scripts/ci')
        commit = git('rev-parse', '--verify', ref + '^{commit}').decode().strip() if ref else None
        paths = (git('ls-tree', '-r', '--name-only', '-z', commit, *roots) if commit
                 else git('ls-files', '-z', *roots)).decode().split('\0')
        stale = re.compile(
            r'\b(?:not\s+(?:yet\s+)?authori[sz]ed|'
            r'no\b[^\n.!?]{0,100}\bauthori[sz]ed\s+yet|'
            r'must\s+remain\s+RED)\b', re.IGNORECASE)
        violations, examined = [], 0
        for path in paths:
            if Path(path).suffix not in {'.py', '.mjs', '.js', '.ts', '.sh'}:
                continue
            source = (git('show', commit + ':' + path).decode('utf-8') if commit
                      else (root / path).read_text(encoding='utf-8'))
            lines = source.splitlines()
            if lines and lines[0].startswith('#!'):
                lines = lines[1:]
            source = '\n'.join(lines).lstrip()
            header = ''
            if source.startswith(('"""', "'''")):
                delimiter = source[:3]
                header = source[3:].split(delimiter, 1)[0]
            elif source.startswith('/*'):
                header = source[2:].split('*/', 1)[0]
            elif source.startswith(('#', '//')):
                header_lines = []
                for line in source.splitlines():
                    if not line.lstrip().startswith(('#', '//')):
                        break
                    header_lines.append(line)
                header = '\n'.join(header_lines)
            examined += 1
            if stale.search(header):
                violations.append(path)
        self.assertGreater(examined, 0, 'HEADER_SOURCE_INVENTORY_EMPTY')
        self.assertEqual(violations, [], 'STALE_AUTHORIZATION_HEADER: ' + ', '.join(violations))

    def path_case(self, character, archive=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = f'clean{character}record.txt'
            if archive:
                with zipfile.ZipFile(root / 'bundle.zip', 'w') as z:
                    z.writestr(name, 'aggregate PASS\n')
            else:
                (root / name).write_text('aggregate PASS\n')
            findings = self.scan.scan(root)
            self.assertTrue(findings, 'NYAY24_CONTROL_PATH_ACCEPTED')
            self.assertNotIn(name, '\n'.join(findings))

    def test_nyay24_c0_filename(self): self.path_case('\n')
    def test_nyay24_c1_filename(self): self.path_case('\x85')
    def test_nyay24_c0_zip_member(self): self.path_case('\x07', True)
    def test_nyay24_c1_zip_member(self): self.path_case('\x85', True)
    def test_nyay24_nul_path_parser(self):
        self.assertTrue(self.scan._path_findings('opaque', 'clean\x00record.txt'))

    def nested_case(self, depth):
        from urllib.parse import quote
        nested = 'session_token=fixturevalue'
        for _ in range(depth): nested = quote(nested, safe='')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'query.txt').write_text('next=' + nested)
            findings = self.scan.scan(root)
            self.assertTrue(findings, 'NYAY25_NESTED_SENSITIVE_FIELD_ACCEPTED')
            self.assertNotIn('fixturevalue', '\n'.join(findings))

    def test_nyay25_double_encoded_nested_field(self): self.nested_case(2)
    def test_nyay25_nested_at_existing_decode_ceiling(self): self.nested_case(8)
    def test_nyay25_over_limit_still_denied(self): self.nested_case(10)

    def test_nyay31_contract_bound_wave2_summary_schema_is_defined(self):
        # Do not invent a broad key exception: GREEN must supply the sealed
        # aggregate projection contract, derived from producer A6.4, first.
        contract = HERE / 'wave2_aggregate_privacy_contract.json'
        self.assertTrue(contract.is_file(), 'NYAY31_SEALED_AGGREGATE_CONTRACT_MISSING')
        policy = json.loads(contract.read_text())
        self.assertEqual(policy['sourceRow'], 'A6.4')
        self.assertEqual(policy['field'], 'reviews_for_session')
        self.assertEqual(policy['valueType'], 'strict-integer')
        self.assertTrue(policy['producerSha256'])
        self.assertTrue(policy['exactInventory'])

    def test_nyay31_uncontracted_key_still_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'unknown.json').write_text(json.dumps({'reviews_for_session': 1}))
            self.assertTrue(self.scan.scan(root))

    def test_nyay31_planted_value_remains_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'unknown.json').write_text(json.dumps({'reviews_for_session': 'Bearer planted-secret'}))
            self.assertTrue(self.scan.scan(root))

    def refusal_case(self, code):
        result = self.gate._classified_failure(code)
        self.assertFalse(result['mergeAuthorized'])
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['schemaVersion'], self.gate.FUTURE_SCHEMA_VERSION)
        self.assertIn('declaredSchemaVersion', result)

    def test_nyay35_output_alias_schema(self): self.refusal_case('OUTPUT_PATH_ALIAS')
    def test_nyay35_unsafe_root_schema(self): self.refusal_case('UNSAFE_EXECUTION_ROOT')
    def test_nyay35_unreadable_schema(self): self.refusal_case('INPUT_UNREADABLE')
    def test_nyay35_historical_mismatch_schema(self): self.refusal_case('HISTORICAL_SEAL_MISMATCH')

    def test_nyay36_existing_oracle_detects_a_planted_requested_archive(self):
        security = load('test_nyay14_evidence_gate_security')
        case_type = security.Nyay14EvidenceGateSecurityTests
        case_type.setUpClass()
        original = case_type.validate
        planted = []
        def sabotage(instance, package, root, report, archive, **kwargs):
            result = original(instance, package, root, report, archive, **kwargs)
            if kwargs.get('authoritative_evidence_schema_version') == self.gate.FUTURE_SCHEMA_VERSION:
                archive.write_bytes(b'forbidden-output-canary')
                planted.append(True)
            return result
        case = case_type('test_package_validator_emits_each_nonpass_classification_truthfully')
        result = unittest.TestResult()
        with mock.patch.object(case_type, 'validate', sabotage): case.run(result)
        self.assertTrue(planted, 'NYAY36_MUTATION_NOT_EXERCISED')
        self.assertFalse(result.wasSuccessful(), 'NYAY36_REQUESTED_ARCHIVE_ORACLE_VACUOUS')


if __name__ == '__main__': unittest.main()

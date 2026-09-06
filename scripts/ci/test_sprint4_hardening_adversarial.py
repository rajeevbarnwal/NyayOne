"""Adversarial boundaries for the Sprint 4 evidence hardening batch."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('hardening_scan', HERE / 'scan_evidence.py')
scan = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scan
spec.loader.exec_module(scan)


class HardeningAdversarial(unittest.TestCase):
    def test_policy_requires_both_hardening_suites(self):
        spec = importlib.util.spec_from_file_location('hardening_policy', HERE/'verify_nyayone_ci.py')
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        path = HERE.parent.parent/'.github/workflows/nyayone-policy-gate.yml'
        original = path.read_text()
        for name in ('test_sprint4_hardening_red.py', 'test_sprint4_hardening_adversarial.py'):
            command = 'python scripts/ci/'+name
            self.assertIn(command, policy.REQUIRED_JOB_RUNS[('nyayone-policy-gate.yml','policy-contracts')])
            self.assertIn(command, original)
            with tempfile.TemporaryDirectory() as directory:
                candidate=Path(directory)/path.name
                candidate.write_text(original.replace(command, 'true'))
                self.assertTrue(any('required' in item.lower() for item in policy.check_workflow(candidate)))

    def test_seeded_A06_C18_fix_removal_restores_the_detected_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'clean\x85record.txt').write_text('PASS')
            self.assertTrue(scan.scan(root))
            with mock.patch.object(scan, '_path_findings', return_value=[]):
                self.assertEqual(scan.scan(root), [])
        from urllib.parse import quote
        raw=('next='+quote(quote('session_token=planted-sensitive', safe=''), safe='')).encode()
        self.assertTrue(self.findings(raw))
        with mock.patch.object(scan, '_nested_query_findings', return_value=[]):
            self.assertEqual(self.findings(raw), [])

    def findings(self, data):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'aggregate.json').write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
            return scan.scan(root)

    def projection(self):
        return {
            'schemaVersion': 'nyayone-wave2-aggregate/v1', 'sourceRow': 'A6.4',
            'producerSha256': hashlib.sha256((HERE.parent.parent / 'backend/scripts/wave2_postgres_gate.py').read_bytes()).hexdigest(),
            'sourceArtifactSha256': 'a' * 64, 'reviews_for_session': 1,
        }

    def test_exact_projection_passes(self):
        self.assertEqual(self.findings(self.projection()), [])

    def test_projection_materializes_only_exact_aggregate(self):
        raw = json.dumps({'gate': 'wave2_postgres', 'assertions': [
            {'id': 'A6.4', 'status': 'PASS', 'detail': {
                'reviews_for_session': 1, 'results': ['private-runtime-only']}}]}).encode()
        result = scan.project_wave2_aggregate(raw)
        self.assertEqual(result['sourceArtifactSha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['reviews_for_session'], 1)
        self.assertNotIn('private-runtime-only', json.dumps(result))
        self.assertEqual(self.findings(result), [])

    def test_projection_refuses_missing_duplicate_and_boolean_rows(self):
        for rows in ([], [{'id': 'A6.4', 'detail': {'reviews_for_session': True}}],
                     [{'id': 'A6.4', 'detail': {'reviews_for_session': 1}}]*2):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, '^WAVE2_AGGREGATE_INVALID$'):
                scan.project_wave2_aggregate(json.dumps({'gate': 'wave2_postgres', 'assertions': rows}).encode())

    def test_strict_projection_rejects_mutations(self):
        base = self.projection()
        mutations = [dict(base, reviews_for_session=value) for value in
                     [True, False, -1, 1.0, '1', None, {}, [], 'Bearer planted-secret',
                      'https://example.test', 'a'*64, '9876543210']]
        mutations += [dict(base, **{key: value}) for key, value in [
            ('sourceRow', 'A6.3'), ('producerSha256', 'b'*64),
            ('sourceArtifactSha256', 'invalid'), ('schemaVersion', 'foreign'),
            ('mobile', '9876543210'), ('unknown', 0), ('reviews_for_sessions', 1)]]
        mutations += [{k:v for k,v in base.items() if k != key} for key in base]
        for value in mutations:
            with self.subTest(value=value):
                self.assertTrue(self.findings(value), 'MALFORMED_AGGREGATE_ACCEPTED')

    def test_duplicate_projection_key_denied(self):
        raw = json.dumps(self.projection()).encode()
        raw = raw[:-1] + b', "reviews_for_session": 1}'
        self.assertTrue(self.findings(raw))

    def test_projection_contract_tampering_denied(self):
        original = Path.read_text
        def corrupt(path, *args, **kwargs):
            if path.name == 'wave2_aggregate_privacy_contract.json':
                return '{}'
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', corrupt):
            self.assertTrue(self.findings(self.projection()))

    def test_all_c0_c1_paths_and_encoded_variants(self):
        for code in [*range(32), *range(127,160)]:
            char = chr(code)
            encoded = ''.join('%%%02X' % b for b in char.encode())
            for name in ['clean'+char+'row', 'clean'+encoded+'row']:
                with self.subTest(code=code, encoded=name==encoded):
                    findings = scan._path_findings('opaque', name)
                    self.assertTrue(findings)
                    self.assertNotIn(name, '\n'.join(findings))

    def test_directory_and_zip_directory_controls_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bad\x85').mkdir()
            (root / 'bad\x85' / 'clean.txt').write_text('PASS')
            self.assertTrue(scan.scan(root))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root/'bundle.zip', 'w') as z:
                z.writestr('bad\x85/', '')
                z.writestr('clean.txt', 'PASS')
            self.assertTrue(scan.scan(root))

    def test_nested_sensitive_fields_redacted(self):
        from urllib.parse import quote
        for depth in (2, 8):
            for key in ('session_token', 'full_name', 'otp'):
                value = key+'=planted-sensitive'
                for _ in range(depth): value=quote(value, safe='')
                findings = self.findings(('next='+value).encode())
                self.assertTrue(findings)
                self.assertNotIn('planted-sensitive', '\n'.join(findings))


if __name__ == '__main__': unittest.main()

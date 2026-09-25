"""Approved storage maintenance; all cache APIs below are mocked, never live."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROUTINE = ["ci-flaky-nyay4-cookie-reload-symmetry.yml", "nyay18-frontend-namespace-gate.yml",
           "nyay5-profile-boundary-gate.yml", "wave1-foundation-gate.yml", "wave2-tutoring-db-gate.yml",
           "wave3-credential-trust-gate.yml", "wave4-private-reporting-gate.yml", "wave5-calendar-gate.yml"]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


class StorageRetentionTests(unittest.TestCase):
    def job(self):
        return workflow('nyay42-optimization-observe.yml')['jobs']['closed-pr-cache-cleanup']

    def test_routine_uploads_seven_days_and_visual_evidence_fourteen(self):
        total = 0
        for name, days in [(x, 7) for x in ROUTINE] + [(x, 14) for x in ['nyay66-conformance.yml', 'nyay66-calibration.yml']]:
            for job in workflow(name)['jobs'].values():
                for step in job.get('steps', []):
                    if step.get('uses', '').startswith('actions/upload-artifact@'):
                        self.assertEqual(step['with']['retention-days'], days, name)
                        total += name in ROUTINE
        self.assertEqual(total, 12)

    def test_owner_only_manual_main_and_no_candidate_code(self):
        job = self.job()
        self.assertEqual(job['if'].split(), "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && github.actor == github.repository_owner && github.triggering_actor == github.repository_owner".split())
        self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'write', 'pull-requests': 'read'})
        self.assertEqual(job['timeout-minutes'], 5)
        self.assertEqual(len(job['steps']), 1)
        step = job['steps'][0]
        self.assertNotIn('uses', step)
        self.assertEqual(step['env'], {'GH_TOKEN': '${{ github.token }}', 'REPOSITORY': '${{ github.repository }}'})
        self.assertNotIn('checkout', step['run'])
        self.assertNotIn('/artifacts', step['run'])

    def run_cleanup(self, scenario):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            # Test-only stand-ins isolate the approved shell from the real gh/date.
            (directory / 'date').write_text('#!/bin/sh\nprintf "100\\n"\n' if scenario == 'recent' else '#!/bin/sh\nif [ "$3" = "7 days ago" ]; then echo 100; else echo 50; fi\n')
            mock = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
mode = os.environ['SCENARIO']
ref = 'refs/heads/main' if mode == 'main' else 'refs/pull/42/head' if mode == 'head' else 'refs/pull/42/merge'
if '--method' in args:
    with open(os.environ['DELETES'], 'a') as f: f.write(json.dumps(args) + '\\n')
elif '--paginate' in args:
    print(('bad' if mode == 'invalid-id' else '73') + '\\t' + ref + '\\t2026-01-01T00:00:00Z')
elif '/pulls/' in args[1]:
    if mode == 'api-failure': sys.exit(1)
    print('open' if mode == 'open' else 'closed')
elif '?ref=' in args[1]:
    if mode == 'missing': sys.exit(0)
    if mode == 'refresh-failure': sys.exit(1)
    print(ref + '\\t' + ('2026-02-01T00:00:00Z' if mode == 'raced' else '2026-01-01T00:00:00Z'))
else: sys.exit(9)
'''
            (directory / 'gh').write_text(mock)
            for name in ['gh', 'date']:
                (directory / name).chmod(0o700)
            env = {**os.environ, 'PATH': f'{tmp}:' + os.environ['PATH'], 'REPOSITORY': 'example/repo',
                   'SCENARIO': scenario, 'DELETES': str(directory / 'deletes'), 'GITHUB_STEP_SUMMARY': str(directory / 'summary')}
            env.pop('GH_TOKEN', None)
            result = subprocess.run(['bash', '-c', self.job()['steps'][0]['run']], env=env, capture_output=True, text=True)
            deleted = (directory / 'deletes').read_text() if (directory / 'deletes').exists() else ''
            return result, deleted

    def test_only_old_unused_closed_pr_merge_cache_deleted(self):
        result, deleted = self.run_cleanup('eligible')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(deleted), ['api', '--method', 'DELETE', 'repos/example/repo/actions/caches/73'])

    def test_main_head_open_recent_missing_raced_and_failed_reads_not_deleted(self):
        for mode in ['main', 'head', 'open', 'recent', 'missing', 'raced', 'api-failure', 'refresh-failure', 'invalid-id']:
            with self.subTest(mode=mode):
                result, deleted = self.run_cleanup(mode)
                self.assertEqual(deleted, '', mode)
                if mode in ['refresh-failure', 'invalid-id']:
                    self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""NYAY-21 execution-time architecture contracts; synthetic, execution-free.

RED specification: add new interfaces alongside immutable historical validators.
No fixed production HEAD/count is an acceptance oracle. Observations are injected;
none of these contracts fetches, creates a backup, rewrites or pushes a repository.
Schema below is a proposed GREEN interface, not an execution approval record.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('nyay21_execution_subject', HERE / 'nyay21_history_purge.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def observation(head='a' * 40):
    return {'repository': gate.REPOSITORY, 'visibility': 'PRIVATE', 'defaultBranch': 'main',
            'head': head, 'refs': [{'name': 'refs/heads/main', 'oid': head},
                                 {'name': 'refs/tags/canary', 'oid': 'b' * 40}],
            'commits': [{'oid': head, 'signed': False}, {'oid': 'b' * 40, 'signed': True}],
            'targets': copy.deepcopy(list(gate.TARGETS)), 'exitCode': 0,
            'complete': True, 'rulesetGetSha256': 'c' * 64}


POLICY = {'schemaVersion': 'nyay21-execution/v2', 'repository': gate.REPOSITORY,
          'visibility': 'PRIVATE', 'defaultBranch': 'main',
          'targetManifest': copy.deepcopy(list(gate.TARGETS)),
          'filterRepoVersion': gate.FILTER_REPO_VERSION,
          'maxSnapshotAgeSeconds': 300}


def sealed_fixture():
    raw = observation()
    return {'schemaVersion': POLICY['schemaVersion'], 'repository': raw['repository'],
            'sourceHead': raw['head'], 'refs': raw['refs'],
            'refInventorySha256': digest(raw['refs']),
            'targetManifestSha256': digest(raw['targets']),
            'rulesetGetSha256': raw['rulesetGetSha256'], 'observationSha256': digest(raw),
            'capturedAt': 1000, 'expiresAt': 1300, 'policySha256': digest(POLICY)}


def approvals(seal):
    def record(kind, number):
        return {'id': f'00000000-0000-4000-8000-{number:012d}', 'action': kind,
                'approved': True, 'sealSha256': digest(seal), 'sourceHead': seal['sourceHead'],
                'approvedRefs': [x['name'] for x in seal['refs']],
                'owner': {'role': 'owner', 'identity': 'Rajeev Barnwal', 'verified': True},
                'security': {'role': 'technical-approver', 'identity': 'Claude Code', 'verified': True},
                'expiresAt': 1250, 'consumed': False}
    return {'rewrite': record('rewrite', 1), 'forceUpdate': record('force-update', 2)}


class ExecutionTimeArchitectureContracts(unittest.TestCase):
    def call(self, name, *args, **kwargs):
        function = getattr(gate, name, None)
        self.assertTrue(callable(function), 'NYAY21_EXECUTION_TIME_INTERFACE_MISSING: ' + name)
        return function(*args, **kwargs)

    def deny(self, result, code):
        self.assertIn(result['verdict'], ('FAIL', 'BLOCKED', 'HEAD_CHANGED'))
        self.assertIn(code, result['codes'])
        self.assertIs(result['executionAuthorized'], False)

    def capture(self, first=None, second=None):
        first = observation() if first is None else first
        reads = iter([first, copy.deepcopy(first) if second is None else second])
        return self.call('capture_execution_seal', lambda: copy.deepcopy(next(reads)),
                         policy=POLICY, now=1000)

    def auth(self, mutate=None, **kwargs):
        seal = sealed_fixture()
        records = approvals(seal)
        if mutate:
            mutate(records)
        return self.call('validate_execution_approvals', records, seal=seal,
                         current=kwargs.pop('current', seal), now=kwargs.pop('now', 1100), **kwargs)

    def test_01_capture_is_plan_only_without_execution_authority(self):
        result = self.capture()
        self.assertEqual(result['verdict'], 'PASS')
        self.assertIs(result['executionAuthorized'], False)
        self.assertEqual(result['seal']['sourceHead'], 'a' * 40)
        self.assertEqual(result['seal']['reachableCommitCount'], 2)
        self.assertEqual(result['seal']['signedCommitCount'], 1)

    def test_02_one_validator_accepts_two_fresh_heads_without_reseal_of_code(self):
        for head in ['d' * 40, 'e' * 40]:
            result = self.capture(observation(head))
            self.assertEqual(result['verdict'], 'PASS')
            self.assertEqual(result['seal']['sourceHead'], head)

    def test_03_canonical_seal_is_inventory_order_independent(self):
        a = self.capture()
        raw = observation()
        raw['refs'].reverse()
        raw['commits'].reverse()
        b = self.capture(raw)
        self.assertEqual(a['sealSha256'], b['sealSha256'])

    def test_04_head_change_during_capture_invalidates_snapshot(self):
        self.deny(self.capture(observation(), observation('d' * 40)), 'HEAD_CHANGED')

    def test_05_side_ref_change_also_invalidates_snapshot(self):
        raw = observation()
        raw['refs'][1]['oid'] = 'd' * 40
        self.deny(self.capture(observation(), raw), 'HEAD_CHANGED')

    def test_06_duplicate_refs_fail_closed(self):
        raw = observation()
        raw['refs'].append(raw['refs'][0])
        self.deny(self.capture(raw), 'REF_INVENTORY_INVALID')

    def test_07_empty_or_incomplete_inventory_cannot_be_sealed(self):
        raw = observation()
        raw['refs'] = []
        raw['complete'] = False
        self.deny(self.capture(raw), 'REF_INVENTORY_INVALID')

    def test_08_boolean_exit_code_is_not_integer_success(self):
        raw = observation()
        raw['exitCode'] = False
        self.deny(self.capture(raw), 'STRICT_INTEGER_REQUIRED')

    def test_09_target_identity_cannot_expand_with_live_head(self):
        raw = observation()
        raw['targets'][0]['blob'] = 'f' * 40
        self.deny(self.capture(raw), 'TARGET_MANIFEST_MISMATCH')

    def test_10_other_repo_or_public_visibility_is_denied(self):
        raw = observation()
        raw['repository'] = 'synthetic/foreign'
        raw['visibility'] = 'PUBLIC'
        self.deny(self.capture(raw), 'REPOSITORY_SCOPE_MISMATCH')

    def test_11_exact_seal_distinct_approvals_are_recognized_not_executed(self):
        result = self.auth()
        self.assertEqual(result['verdict'], 'PASS')
        self.assertIs(result['rewriteApproved'], True)
        self.assertIs(result['forceUpdateApproved'], True)
        self.assertIs(result['executionAuthorized'], False)

    def test_12_forged_approval_seal_digest_is_denied(self):
        self.deny(self.auth(lambda a: a['rewrite'].update(sealSha256='f' * 64)), 'APPROVAL_SEAL_MISMATCH')

    def test_13_rewrite_approval_cannot_substitute_for_force_approval(self):
        self.deny(self.auth(lambda a: a.update(forceUpdate=a['rewrite'])), 'DISTINCT_FORCE_APPROVAL_REQUIRED')

    def test_14_empty_approved_ref_scope_is_denied(self):
        self.deny(self.auth(lambda a: a['forceUpdate'].update(approvedRefs=[])), 'APPROVAL_REF_SCOPE_MISMATCH')

    def test_15_live_head_change_invalidates_old_approvals(self):
        current = sealed_fixture()
        current['sourceHead'] = 'e' * 40
        self.deny(self.auth(current=current), 'HEAD_CHANGED')

    def test_16_approval_consumption_and_expiry_cannot_be_replayed(self):
        self.deny(self.auth(lambda a: a['rewrite'].update(consumed=True), now=1400), 'APPROVAL_NOT_CURRENT')

    def lease(self, mutate=None):
        seal = sealed_fixture()
        rows = [{'ref': r['name'], 'expectedOldOid': r['oid'], 'newOid': 'd' * 40}
                for r in seal['refs']]
        if mutate:
            mutate(rows)
        return self.call('plan_execution_leases', rows, seal=seal, current=seal)

    def test_17_push_plan_has_atomic_dry_run_and_each_explicit_lease(self):
        result = self.lease()
        argv = result['dryRunArgv']
        self.assertIn('--atomic', argv)
        self.assertIn('--dry-run', argv)
        for ref in sealed_fixture()['refs']:
            self.assertIn('--force-with-lease=' + ref['name'] + ':' + ref['oid'], argv)
        self.assertNotIn('--force', argv)
        self.assertNotIn('--mirror', argv)
        self.assertIs(result['executionAuthorized'], False)

    def test_18_missing_lease_row_is_refused(self):
        self.deny(self.lease(lambda rows: rows.pop()), 'LEASE_INVENTORY_MISMATCH')

    def test_19_extra_lease_row_is_refused(self):
        self.deny(self.lease(lambda rows: rows.append({'ref': 'refs/heads/foreign',
                  'expectedOldOid': 'a' * 40, 'newOid': 'd' * 40})), 'LEASE_INVENTORY_MISMATCH')

    def test_20_wrong_old_oid_is_not_an_explicit_lease_proof(self):
        self.deny(self.lease(lambda rows: rows[0].update(expectedOldOid='f' * 40)), 'LEASE_INVENTORY_MISMATCH')

    def watchdog(self, mutate=None):
        seal = sealed_fixture()
        row = {'sourceHead': seal['sourceHead'], 'sealSha256': digest(seal),
               'rulesetGetSha256': seal['rulesetGetSha256'], 'restorePayloadSha256': 'd' * 64,
               'heartbeatAt': 1099, 'armed': True, 'getExitCode': 0,
               'independentProcess': True, 'boundedPutAttempts': 2,
               'persistentFailureEscalation': 'owner-break-glass'}
        if mutate:
            mutate(row)
        return self.call('validate_execution_watchdog', row, seal=seal,
                         restoration_payload_sha256='d' * 64, now=1100)

    def test_21_watchdog_binds_current_head_seal_and_restore_payload(self):
        result = self.watchdog()
        self.assertEqual(result['verdict'], 'PASS')
        self.assertIs(result['executionAuthorized'], False)

    def test_22_watchdog_stale_head_is_denied(self):
        self.deny(self.watchdog(lambda r: r.update(sourceHead='f' * 40)), 'WATCHDOG_BINDING_MISMATCH')

    def test_23_watchdog_restore_payload_swap_is_denied(self):
        self.deny(self.watchdog(lambda r: r.update(restorePayloadSha256='f' * 64)), 'WATCHDOG_BINDING_MISMATCH')

    def test_24_watchdog_failed_get_or_stale_heartbeat_cannot_arm(self):
        self.deny(self.watchdog(lambda r: r.update(getExitCode=1, heartbeatAt=1)), 'WATCHDOG_NOT_READY')

    def operator(self, mutate=None):
        seal = sealed_fixture()
        row = {'mode': 'single-operator', 'owner': 'Rajeev Barnwal',
               'sealSha256': digest(seal), 'riskAccepted': True,
               'independentTechnicalApproval': True, 'supportAndFreshClonePlan': True,
               'powerNetworkChecked': True, 'pausePoints': ['backup-drill', 'rewrite-push', 'ci-dispatch']}
        if mutate:
            mutate(row)
        return self.call('validate_execution_operator', row, seal=seal)

    def test_25_single_operator_attestation_is_explicit_not_fictional_second_person(self):
        self.assertEqual(self.operator()['verdict'], 'PASS')

    def test_26_single_operator_without_digest_bound_risk_acceptance_is_denied(self):
        self.deny(self.operator(lambda r: r.update(riskAccepted=False)), 'OPERATOR_ATTESTATION_REQUIRED')

    def scopes(self, decision=None, permissions=None):
        return self.call('validate_execution_scope_decision',
                         {'repository': gate.REPOSITORY, 'workflowsWriteDecision': decision,
                          'permissions': permissions or {'contents': 'write', 'workflows': 'write'},
                          'expiresAt': 14000}, seal=sealed_fixture(), now=1000,
                         rewritten_paths=['.github/workflows/synthetic.yml'])

    def test_27_workflows_write_requires_explicit_owner_decision(self):
        self.deny(self.scopes(), 'WORKFLOWS_SCOPE_DECISION_REQUIRED')

    def test_28_approved_scope_must_actually_be_present(self):
        self.deny(self.scopes(True, {'contents': 'write'}), 'WORKFLOWS_WRITE_REQUIRED')

    def test_29_explicit_narrow_workflows_scope_is_recognized_without_token_creation(self):
        result = self.scopes(True)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertIs(result['executionAuthorized'], False)

    def test_30_capture_never_spawns_execution_or_touches_protected_checkout(self):
        with patch('subprocess.run', side_effect=AssertionError('EXECUTION_FORBIDDEN')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('WRITE_FORBIDDEN')), \
             patch.object(Path, 'write_bytes', side_effect=AssertionError('WRITE_FORBIDDEN')):
            self.assertEqual(self.capture()['verdict'], 'PASS')

    def test_31_truthy_string_is_not_rewrite_approval(self):
        self.deny(self.auth(lambda a: a['rewrite'].update(approved='true')), 'APPROVAL_BOOLEAN_REQUIRED')

    def test_32_approval_scope_cannot_include_an_unsealed_ref(self):
        self.deny(self.auth(lambda a: a['forceUpdate']['approvedRefs'].append('refs/heads/foreign')),
                  'APPROVAL_REF_SCOPE_MISMATCH')

    def test_33_boolean_target_size_is_not_an_integer(self):
        raw = observation()
        raw['targets'][0]['size'] = True
        self.deny(self.capture(raw), 'STRICT_INTEGER_REQUIRED')

    def test_34_watchdog_false_exit_status_does_not_mean_zero(self):
        self.deny(self.watchdog(lambda r: r.update(getExitCode=False)), 'STRICT_INTEGER_REQUIRED')

    def test_35_negative_or_zero_watchdog_retry_budget_is_denied(self):
        self.deny(self.watchdog(lambda r: r.update(boundedPutAttempts=0)), 'WATCHDOG_NOT_READY')

    def test_36_scope_decision_cannot_grant_unrelated_privileges(self):
        self.deny(self.scopes(True, {'contents': 'write', 'workflows': 'write',
                                    'organization-administration': 'write'}), 'TOKEN_SCOPE_EXCESS')


if __name__ == '__main__':
    unittest.main(verbosity=2)

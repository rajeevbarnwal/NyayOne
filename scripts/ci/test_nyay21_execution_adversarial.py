"""Additional execution/v2 fail-closed contracts; no external effects."""
import copy
import unittest
from test_nyay21_execution_time_seal import gate, sealed_fixture, approvals, digest


class ExecutionAdversarial(unittest.TestCase):
    def test_push_binding_refuses_missing_scope_even_with_valid_approvals_and_leases(self):
        fn = getattr(gate, 'prepare_execution_push', None)
        self.assertTrue(callable(fn), 'PUSH_SCOPE_BINDING_MISSING')
        seal = sealed_fixture()
        rows = [{'ref':r['name'],'expectedOldOid':r['oid'],'newOid':'e'*40} for r in seal['refs']]
        result = fn(rows, seal=seal, current=seal, now=1100,
                    approvals=approvals(seal), scope_readback={}, scope_receipt_sha256='f'*64)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertNotIn('dryRunArgv',result)
        self.assertIs(result['executionAuthorized'],False)

    def test_push_binding_never_exposes_a_live_push_or_accepts_scope_drift(self):
        fn = getattr(gate, 'prepare_execution_push', None)
        self.assertTrue(callable(fn), 'PUSH_SCOPE_BINDING_MISSING')
        seal=sealed_fixture()
        rows = [{'ref':r['name'],'expectedOldOid':r['oid'],'newOid':'e'*40} for r in seal['refs']]
        receipt={'repository':gate.REPOSITORY, 'sourceHead':seal['sourceHead'],
               'sealSha256':digest(seal), 'readAt':1090, 'expiresAt':87500,
               'exitCode':0, 'ownerDecisionCommentId':'14996',
               'receiptKind':'independent-scope-readback/v1',
               'restorationWorkflow':'reviewed-ruleset-restoration/v1',
               'permissions':{'contents':'write','workflows':'write','metadata':'read',
                              'administration':'write','actions':'read'}}
        def check(value, auth=None):
            return fn(rows,seal=seal,current=seal,now=1100,
                      approvals=approvals(seal) if auth is None else auth,
                      scope_readback=value,scope_receipt_sha256=digest(value))
        result=check(receipt)
        self.assertEqual(result['verdict'],'PASS')
        self.assertIn('--dry-run',result['dryRunArgv'])
        self.assertNotIn('forceUpdateArgv',result)
        self.assertIs(result['executionAuthorized'],False)
        mutated=copy.deepcopy(receipt)
        mutated['permissions']['actions']='write'
        self.assertEqual(check(mutated)['verdict'],'FAIL')
        self.assertNotIn('dryRunArgv',check(mutated))
        self.assertNotIn('dryRunArgv',check(receipt,{}))

    def test_owner_dispatch_is_prepared_not_executed_with_actions_read(self):
        fn = getattr(gate, 'prepare_owner_ci_dispatch', None)
        self.assertTrue(callable(fn), 'OWNER_DISPATCH_BINDING_MISSING')
        seal = sealed_fixture()
        result = fn(seal=seal, post_push_head='e'*40, observed_main_head='e'*40,
                    permissions={'contents':'write','metadata':'read','workflows':'write',
                                 'administration':'write','actions':'read'})
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['step'], 12)
        self.assertEqual(result['operator'], 'owner')
        self.assertIs(result['executionAuthorized'], False)
        self.assertIs(result['dispatchExecuted'], False)
        self.assertEqual(len(result['ownerCommands']), 12)
        self.assertTrue(all('--ref main' in c for c in result['ownerCommands']))
        self.assertTrue(any('ci-flaky-nyay4-cookie-reload-symmetry.yml' in c
                            for c in result['ownerCommands']))
        self.assertIn('e'*40, result['ownerHeadGuard'])

    def test_owner_dispatch_rejects_head_drift_and_scope_expansion(self):
        fn = getattr(gate, 'prepare_owner_ci_dispatch', None)
        self.assertTrue(callable(fn), 'OWNER_DISPATCH_BINDING_MISSING')
        scopes = {'contents':'write','metadata':'read','workflows':'write',
                  'administration':'write','actions':'read'}
        for head, observed, permissions in [('e'*40,'f'*40,scopes),
                    ('not-a-head','not-a-head',scopes),
                    ('e'*40,'e'*40,{**scopes,'actions':'write'})]:
            result = fn(seal=sealed_fixture(), post_push_head=head,
                        observed_main_head=observed, permissions=permissions)
            self.assertIn(result['verdict'], ('FAIL','HEAD_CHANGED'))
            self.assertIs(result['executionAuthorized'], False)
            self.assertNotIn('ownerCommands', result)

    def test_owner_dispatch_readback_exact_inventory_and_strict_run_ids(self):
        fn = getattr(gate, 'validate_owner_ci_dispatch_readback', None)
        self.assertTrue(callable(fn), 'OWNER_DISPATCH_READBACK_MISSING')
        rows = [{'workflow':name, 'runId':index+1, 'headSha':'e'*40,
                 'event':'workflow_dispatch', 'repository':gate.REPOSITORY}
                for index,name in enumerate(gate.EXECUTION_CI_WORKFLOWS)]
        def check(value, head='e'*40):
            return fn(value, expected_head='e'*40, observed_main_head=head)
        result = check(rows)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertIs(result['executionAuthorized'], False)
        self.assertEqual(result['nextPause'], 'ci-dispatch')
        self.assertIs(result['campaignPassed'], False)
        for field,value in [('runId',True),('runId',0),('headSha','f'*40),
                            ('event','push'),('repository','foreign/repo')]:
            candidate = copy.deepcopy(rows)
            candidate[0][field] = value
            self.assertEqual(check(candidate)['verdict'], 'FAIL')
        for candidate in ([], rows[:-1], rows+[rows[0]], rows[1:]+[rows[1]]):
            self.assertEqual(check(candidate)['verdict'], 'FAIL')
        self.assertEqual(check(rows, 'f'*40)['verdict'], 'HEAD_CHANGED')

    def test_restoration_decision_requires_the_complete_owner_scope_set(self):
        seal = sealed_fixture()
        permissions = {'contents':'write', 'workflows':'write', 'metadata':'read',
                       'administration':'write', 'actions':'read'}
        row = {'repository':gate.REPOSITORY, 'workflowsWriteDecision':True,
               'restorationWorkflow':'reviewed-ruleset-restoration/v1',
               'permissions':permissions, 'expiresAt':87500}
        for missing in ('actions', 'metadata'):
            candidate = copy.deepcopy(row)
            candidate['permissions'].pop(missing)
            with self.subTest(missing=missing):
                result = gate.validate_execution_scope_decision(candidate, seal=seal, now=1100,
                                      rewritten_paths=['.github/workflows/example.yml'])
                self.assertEqual(result['verdict'], 'FAIL')
                self.assertIs(result['executionAuthorized'], False)

    def test_restoration_receipt_requires_exact_scopes_and_separate_digest(self):
        seal = sealed_fixture()
        row = {'repository':gate.REPOSITORY, 'sourceHead':seal['sourceHead'],
               'sealSha256':digest(seal), 'readAt':1090, 'expiresAt':87500,
               'exitCode':0, 'ownerDecisionCommentId':'14992',
               'receiptKind':'independent-scope-readback/v1',
               'restorationWorkflow':'reviewed-ruleset-restoration/v1',
               'permissions':{'contents':'write','workflows':'write','metadata':'read',
                              'administration':'write','actions':'read'}}
        def check(value, expected=None):
            return gate.validate_execution_scope_readback(value, seal=seal, now=1100,
                expected_receipt_sha256=digest(value) if expected is None else expected)
        self.assertEqual(check(row)['verdict'], 'PASS')
        self.assertIs(check(row)['executionAuthorized'], False)
        for permission in row['permissions']:
            candidate = copy.deepcopy(row)
            candidate['permissions'].pop(permission)
            with self.subTest(missing=permission):
                self.assertEqual(check(candidate)['verdict'], 'FAIL')
        for field, value in (('restorationWorkflow','unrestricted'),
                             ('repository','foreign/repository'), ('sourceHead','e'*40),
                             ('exitCode',False), ('readAt',0), ('sealSha256','e'*64)):
            self.assertEqual(check({**row,field:value})['verdict'], 'FAIL')
        candidate = copy.deepcopy(row)
        candidate['permissions']['actions'] = 'write'
        self.assertEqual(check(candidate)['verdict'], 'FAIL')
        self.assertEqual(check(row, 'e'*64)['verdict'], 'FAIL')

    def test_owner_authorized_restoration_scope_requires_path_binding(self):
        seal = sealed_fixture()
        row = {'repository':gate.REPOSITORY, 'workflowsWriteDecision':True,
               'restorationWorkflow': 'reviewed-ruleset-restoration/v1',
               'permissions': {'contents':'write','workflows':'write','metadata':'read',
                               'administration':'write','actions':'read'}, 'expiresAt':87500}
        call = lambda r: gate.validate_execution_scope_decision(r, seal=seal, now=1100,
                          rewritten_paths=['.github/workflows/example.yml'])
        self.assertEqual(call(row)['verdict'], 'PASS')
        self.assertEqual(call({**row,'restorationWorkflow':'unrestricted'})['verdict'], 'FAIL')
        row['permissions']['actions'] = 'write'
        self.assertEqual(call(row)['verdict'], 'FAIL')

    def test_fresh_same_authority_readback_does_not_invalidate_current_approval(self):
        seal = sealed_fixture()
        current = {**seal, 'capturedAt': 1090, 'expiresAt': 1390}
        result = gate.validate_execution_approvals(approvals(seal), seal=seal, current=current, now=1100)
        self.assertEqual(result['verdict'], 'PASS')
        # The old approval's lifetime does not extend with the new observation.
        expired = gate.validate_execution_approvals(approvals(seal), seal=seal, current=current, now=1350)
        self.assertEqual(expired['verdict'], 'FAIL')

    def test_malformed_approval_ids_are_canonical_refusals(self):
        seal = sealed_fixture()
        for value in ([], {}, None, True, 1):
            with self.subTest(kind=type(value).__name__):
                rows = approvals(seal)
                rows['rewrite']['id'] = value
                result = gate.validate_execution_approvals(rows, seal=seal, current=seal, now=1100)
                self.assertEqual(result['verdict'], 'FAIL')
                self.assertIs(result['executionAuthorized'], False)

    def test_malformed_lease_ref_cannot_raise_or_emit_argv(self):
        seal = sealed_fixture()
        for value in ([], {}, None, True):
            rows = [{'ref': r['name'], 'expectedOldOid': r['oid'], 'newOid': 'e'*40} for r in seal['refs']]
            rows[0]['ref'] = value
            result = gate.plan_execution_leases(rows, seal=seal, current=seal)
            self.assertEqual(result['verdict'], 'FAIL')
            self.assertNotIn('dryRunArgv', result)

    def test_self_reported_seal_counts_cannot_be_boolean(self):
        for key in ('reachableCommitCount', 'signedCommitCount'):
            seal = sealed_fixture()
            seal[key] = True
            self.assertFalse(gate._execution_seal_valid(seal))

    def test_push_scope_requires_independent_readback_not_decision_flag(self):
        fn = getattr(gate, 'validate_execution_scope_readback', None)
        self.assertTrue(callable(fn), 'SCOPE_READBACK_INTERFACE_MISSING')
        seal = sealed_fixture()
        result = fn({}, seal=seal, now=1100, expected_receipt_sha256='f'*64)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertIs(result['executionAuthorized'], False)

    def test_scope_readback_positive_and_tampering(self):
        seal = sealed_fixture()
        row = {'repository': gate.REPOSITORY, 'sourceHead': seal['sourceHead'],
               'sealSha256': digest(seal), 'permissions': {'contents': 'write', 'workflows': 'write', 'metadata': 'read'},
               'readAt': 1090, 'expiresAt': 87500, 'exitCode': 0,
               'ownerDecisionCommentId': '14954', 'receiptKind': 'independent-scope-readback/v1'}
        def check(value, expected=digest(row)):
            return gate.validate_execution_scope_readback(value, seal=seal, now=1100,
                                                         expected_receipt_sha256=expected)
        self.assertEqual(check(row)['verdict'], 'PASS')
        self.assertIs(check(row)['executionAuthorized'], False)
        mutations = [('repository', 'foreign/repository'), ('sourceHead', 'e'*40),
                     ('sealSha256', 'e'*64), ('readAt', 0), ('readAt', 1200),
                     ('readAt', True), ('expiresAt', False), ('exitCode', False),
                     ('exitCode', 1), ('expiresAt', 1100), ('expiresAt', 999999),
                     ('permissions', {'contents':'write'}), ('permissions', {'admin':'write'}),
                     ('ownerDecisionCommentId', ''), ('receiptKind', 'self-declared')]
        for key, value in mutations:
            with self.subTest(field=key, kind=type(value).__name__):
                candidate = {**row, key:value}
                # Even rebinding the expected hash cannot legalize bad scope/type/time.
                self.assertEqual(check(candidate, digest(candidate))['verdict'], 'FAIL')
        self.assertEqual(check(row, 'e'*64)['verdict'], 'FAIL')
        self.assertEqual(check({**row,'credential':'never-accepted'})['verdict'], 'FAIL')


if __name__ == '__main__':
    unittest.main()

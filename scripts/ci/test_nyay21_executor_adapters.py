"""Concrete adapter contracts. Network and destructive operations are mocked."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import nyay21_history_purge as gate

PATH=Path(__file__).with_name('nyay21_executor_adapters.py')


class ExecutorAdapterContracts(unittest.TestCase):
    def test_sealed_rewrite_does_not_fetch_new_or_server_managed_refs(self):
        a=self.module();ctx=Mock();executor=a.Executor(ctx)
        executor.step7()
        argv=ctx.command.call_args.args[0]
        self.assertIn('--no-fetch',argv)
        self.assertIn('--sensitive-data-removal',argv)
        self.assertNotIn('--force',argv)

    def module(self):
        self.assertTrue(PATH.is_file(), 'NYAY21_CONCRETE_EXECUTOR_ADAPTERS_REQUIRED')
        spec=importlib.util.spec_from_file_location('adapter_contract_target',PATH)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def ruleset(self):
        return {'id':20888530,'name':'main','target':'branch','source_type':'Repository',
                'source':gate.REPOSITORY,'enforcement':'active','conditions':{'ref_name':{'include':['refs/heads/main'],'exclude':[]}},
                'bypass_actors':[],'rules':[{'type':'pull_request','parameters':{'required_approving_review_count':0}},
                 {'type':'required_status_checks','parameters':{}},{'type':'non_fast_forward'}, {'type':'deletion'}],
                'updated_at':'2026-09-08T00:00:00Z','created_at':'2026-01-01T00:00:00Z',
                'node_id':'fixture','current_user_can_bypass':'never','_links':{}}

    def test_payload_pair_suspends_push_blockers_only_and_restores_exact_config(self):
        a=self.module();before=self.ruleset();pair=a.ruleset_pair(before,gate._canonical_json_sha256(before))
        self.assertEqual(pair['relaxation']['rules'],[{'type':'deletion'}])
        self.assertEqual(pair['restoration']['rules'],before['rules'])
        self.assertEqual(pair['restoration']['bypass_actors'],[])
        self.assertEqual(before,self.ruleset())

    def test_pair_refuses_wrong_full_get_digest(self):
        a=self.module()
        with self.assertRaisesRegex(a.Refusal,'RULESET_SNAPSHOT_MISMATCH'):
            a.ruleset_pair(self.ruleset(),'0'*64)

    def test_restoration_checks_full_get_except_server_managed_update_clock(self):
        a=self.module();before=self.ruleset();after=copy.deepcopy(before);after['updated_at']='2026-09-08T00:01:00Z'
        self.assertTrue(a.restored(before,after))
        for key,value in [('source','foreign/repo'),('rules',[]),('bypass_actors',[{'actor_id':1}]),('node_id','different')]:
            mutation=copy.deepcopy(after);mutation[key]=value
            with self.subTest(key=key):self.assertFalse(a.restored(before,mutation))

    def test_restore_get_failure_does_not_blind_put(self):
        a=self.module();api=Mock();api.get.side_effect=OSError('private diagnostic');events=[]
        pair=a.ruleset_pair(self.ruleset(),gate._canonical_json_sha256(self.ruleset()))
        with self.assertRaisesRegex(a.Refusal,'RESTORATION_READBACK_UNAVAILABLE'):
            a.restore(api,pair,events.append)
        api.put.assert_not_called();self.assertEqual(events,['RESTORATION_GET_FAILED'])

    def test_restore_foreign_edit_is_not_overwritten(self):
        a=self.module();api=Mock();before=self.ruleset();foreign=copy.deepcopy(before);foreign['name']='foreign';api.get.return_value=foreign
        pair=a.ruleset_pair(before,gate._canonical_json_sha256(before))
        with self.assertRaisesRegex(a.Refusal,'RULESET_CONCURRENT_CHANGE'):
            a.restore(api,pair,lambda _:None)
        api.put.assert_not_called()

    def test_restore_put_attempts_bounded_and_readback_proven(self):
        a=self.module();api=Mock();before=self.ruleset();pair=a.ruleset_pair(before,gate._canonical_json_sha256(before))
        relaxed={**before,**pair['relaxation']};api.get.return_value=relaxed;api.put.side_effect=OSError('private')
        with self.assertRaisesRegex(a.Refusal,'RESTORATION_OWNER_BREAK_GLASS'):
            a.restore(api,pair,lambda _:None)
        self.assertEqual(api.put.call_count,3)

    def test_custody_parent_mode_and_append_only_chain(self):
        a=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o755)
            with self.assertRaisesRegex(a.Refusal,'CUSTODY_PARENT_MODE'):
                a.Custody(root).append('STEP_6_ARMED',{'digest':'a'*64})
            root.chmod(0o700);log=a.Custody(root)
            first=log.append('STEP_6_ARMED',{'digest':'a'*64});second=log.append('STEP_9_RESTORED',{'digest':'b'*64})
            self.assertEqual(second['previous'],gate._canonical_json_sha256(first))
            self.assertEqual(len((root/'events.jsonl').read_text().splitlines()),2)
            with self.assertRaisesRegex(a.Refusal,'CUSTODY_FIELD_INVALID'):
                log.append('STEP_9_RESTORED',{'email':'sensitive'})

    def test_navigator_has_concrete_steps_6_through_15_and_pause_boundaries(self):
        a=self.module()
        self.assertEqual(set(a.STEPS),set(range(6,16)))
        for name in a.STEPS.values():self.assertTrue(callable(getattr(a.Executor,name,None)))
        self.assertEqual(a.PAUSES,{5:'backup-drill',11:'rewrite-push',13:'ci-dispatch'})

    def test_default_cli_has_no_effect_and_no_ambient_go(self):
        a=self.module();out=a.plan()
        self.assertIs(out['executionAuthorized'],False)
        self.assertEqual(out['mode'],'plan-only')
        self.assertEqual(out['steps'],a.STEPS)

    def test_step12_prepares_owner_dispatch_never_actions_write(self):
        a=self.module();executor=object.__new__(a.Executor)
        executor.context=Mock();executor.context.owner_dispatch_plan.return_value={'operator':'owner','dispatchExecuted':False}
        result=executor.step12()
        self.assertIs(result['dispatchExecuted'],False)
        executor.context.execute.assert_not_called()

    def test_push_always_restores_on_failure_and_checks_scope_before_dry_run(self):
        a=self.module();executor=object.__new__(a.Executor);ctx=Mock();executor.context=ctx
        ctx.validated_push_plan.return_value=['git','push','--atomic','--dry-run','--force-with-lease=refs/heads/main:'+('a'*40),'origin',('b'*40)+':refs/heads/main']
        ctx.command.side_effect=a.Refusal('PUSH_FAILED')
        with self.assertRaisesRegex(a.Refusal,'PUSH_FAILED'):executor.step8()
        ctx.restore.assert_called_once()
        self.assertEqual(ctx.mock_calls[0][0],'validated_push_plan')
        ctx.consume_force_approval.assert_not_called()

    def test_successful_push_uses_identical_explicit_leases_and_atomic_flag(self):
        a=self.module();executor=object.__new__(a.Executor);ctx=Mock();executor.context=ctx
        argv=['git','push','--atomic','--dry-run','--force-with-lease=refs/heads/main:'+('a'*40),'origin',('b'*40)+':refs/heads/main']
        ctx.validated_push_plan.return_value=argv;ctx.command.return_value={'exitCode':0}
        executor.step8()
        self.assertEqual(ctx.command.call_args_list[0].args[0],argv)
        self.assertEqual(ctx.command.call_args_list[1].args[0],[s for s in argv if s!='--dry-run'])
        ctx.consume_force_approval.assert_called_once();ctx.restore.assert_called_once()

    def test_rebinding_is_new_immutable_revision_and_requires_positive_campaign(self):
        a=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);old=root/'historical.json';old.write_text('historical')
            mapping=[{'old':'a'*40,'new':'b'*40}]
            with self.assertRaisesRegex(a.Refusal,'CAMPAIGN_NOT_PASS'):
                a.write_rebinding(root,'c'*64,mapping,{'passed':True,'assertions':0})
            path=a.write_rebinding(root,'c'*64,mapping,{'passed':True,'assertions':1})
            self.assertEqual(old.read_text(),'historical');self.assertTrue(path.is_file())
            with self.assertRaisesRegex(a.Refusal,'IMMUTABLE_REVISION_EXISTS'):
                a.write_rebinding(root,'c'*64,mapping,{'passed':True,'assertions':1})


if __name__=='__main__':unittest.main()

"""No-network adversarial runtime contracts; no production execution."""
import copy
import base64
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import nyay21_executor_runtime as runtime
import nyay21_executor_adapters as adapters
import nyay21_history_purge as gate
from test_nyay21_execution_time_seal import sealed_fixture


class RuntimeContracts(unittest.TestCase):
    def test_git_http_credentials_are_basic_and_never_command_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);(root/'mirror.git').mkdir()
            with patch.object(runtime.GitIO,'run',side_effect=[b'true\n',b'.\n',b'']):
                io=runtime.GitIO(root,'synthetic-only')
            expected='Authorization: Basic '+base64.b64encode(b'x-access-token:synthetic-only').decode()
            self.assertEqual(io.environment['GIT_CONFIG_VALUE_0'],expected)
            self.assertNotIn('GH_TOKEN',io.environment)

    def test_repository_read_is_scoped_and_does_not_mutate(self):
        api=runtime.GitHub('synthetic-credential')
        with patch.object(api,'request',return_value={'private':True}) as call:
            self.assertTrue(api.repository()['private']);call.assert_called_once_with('GET','')

    def test_api_refuses_foreign_or_nonruleset_mutations_before_network(self):
        api=runtime.GitHub('synthetic-credential')
        for method,path in [('DELETE',''),('POST','/actions/workflows/x/dispatches'),('PUT','/rulesets/1'),('GET','/../foreign'),('GET','https://foreign')]:
            with self.subTest(method=method,path=path),self.assertRaises(adapters.Refusal):api.request(method,path)

    def test_default_plan_has_no_io(self):
        with patch.object(runtime,'Runtime') as context,patch('sys.argv',['runtime']):
            with patch('builtins.print'):runtime.main()
            context.assert_not_called()

    def test_fresh_collector_uses_actual_ref_commit_signature_target_observations(self):
        self.assertTrue(callable(getattr(runtime,'collect_observation',None)),'RUNTIME_FRESH_COLLECTOR_REQUIRED')
        git=Mock();api=Mock();api.repository.return_value={'private':True,'full_name':gate.REPOSITORY,'default_branch':'main'}
        refs=[{'name':'refs/heads/main','oid':'a'*40}];git.remote_refs.return_value=refs;git.local_refs.return_value=refs
        git.run.side_effect=[(('a'*40)+'\n').encode(),b'tree '+b'b'*40+b'\ngpgsig synthetic\n\nmessage',b'32768\n',b'457352\n']
        api.get.return_value={'synthetic':'GET'}
        raw=runtime.collect_observation(git,api)
        self.assertEqual(raw['commits'],[{'oid':'a'*40,'signed':True}]);self.assertTrue(raw['complete'])
        self.assertEqual(raw['targets'],list(gate.TARGETS))

    def test_fresh_collector_ref_mismatch_fails_head_changed(self):
        self.assertTrue(callable(getattr(runtime,'collect_observation',None)),'RUNTIME_FRESH_COLLECTOR_REQUIRED')
        git=Mock();api=Mock();api.repository.return_value={'private':True,'full_name':gate.REPOSITORY,'default_branch':'main'}
        git.remote_refs.return_value=[{'name':'refs/heads/main','oid':'a'*40}];git.local_refs.return_value=[]
        with self.assertRaisesRegex(adapters.Refusal,'HEAD_CHANGED'):runtime.collect_observation(git,api)

    def test_watchdog_requires_strict_nonfuture_time(self):
        context=object.__new__(runtime.Runtime);context.root=Path('/synthetic');context.clock=lambda:1000
        pair={'value':'fixture'}
        for stamp in [True,'1000',1001,699]:
            row={'pairSha256':adapters.digest(pair),'pid':123,'armedAt':stamp}
            with self.subTest(stamp=stamp),patch.object(runtime,'read_json',return_value=row),patch.object(runtime.os,'kill'):
                with self.assertRaisesRegex(adapters.Refusal,'WATCHDOG_STALE'):context.verify_watchdog(pair)

    def test_predecessor_boolean_step_is_not_integer_one(self):
        context=object.__new__(runtime.Runtime);context.root=Path('/synthetic');context.seal=sealed_fixture()
        receipt={'step':True,'sealSha256':adapters.digest(context.seal),'completed':True}
        with patch.object(runtime,'read_json',return_value=receipt):
            with self.assertRaisesRegex(adapters.Refusal,'PREDECESSOR_RECEIPT_REQUIRED'):context.require_predecessor(2)

    def test_commit_map_must_cover_old_inventory_and_preserve_nontarget_trees(self):
        self.assertTrue(callable(getattr(runtime,'verify_tree_retention',None)),'NONTARGET_RETENTION_BINDING_REQUIRED')
        git=Mock();git.run.return_value=b'100644 blob '+b'c'*40+b'\tREADME.md\0'
        original={'a'*40:gate._canonical_json_sha256(['100644 blob '+('c'*40)+'\tREADME.md'])}
        mapping=[{'old':'a'*40,'new':'b'*40}]
        self.assertTrue(runtime.verify_tree_retention(git,original,mapping))
        git.run.return_value=b'100644 blob '+b'd'*40+b'\tREADME.md\0'
        with self.assertRaisesRegex(adapters.Refusal,'NONTARGET_RETENTION_CHANGED'):runtime.verify_tree_retention(git,original,mapping)

    def test_empty_or_foreign_map_cannot_pass_retention(self):
        self.assertTrue(callable(getattr(runtime,'verify_tree_retention',None)),'NONTARGET_RETENTION_BINDING_REQUIRED')
        for mapping in [[],[{'old':'c'*40,'new':'b'*40}]]:
            with self.subTest(mapping=mapping),self.assertRaises(adapters.Refusal):runtime.verify_tree_retention(Mock(),{'a'*40:'f'*64},mapping)

    def test_pause_cannot_advance_on_self_declared_proceed(self):
        context=object.__new__(runtime.Runtime);context.root=Path('/synthetic');context.seal=sealed_fixture();context.permit={}
        row={'owner':gate.OWNER_APPROVER,'pause':'rewrite-push','decision':'PROCEED','sealSha256':adapters.digest(context.seal)}
        with patch.object(runtime,'read_json',return_value=row),self.assertRaisesRegex(adapters.Refusal,'OWNER_PROCEED_REQUIRED'):
            context.require_proceed('rewrite-push')

    def test_unapproved_permit_is_refused_before_git_or_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);(root/'execution-permit.json').write_text('{}')
            with patch.object(runtime,'GitIO') as git,patch.object(runtime,'GitHub') as api:
                with self.assertRaisesRegex(adapters.Refusal,'OWNER_PERMIT_DIGEST_MISMATCH'):runtime.Runtime(root,'f'*64,'synthetic')
                git.assert_not_called();api.assert_not_called()

    def test_watchdog_missing_heartbeat_is_bounded_not_indefinite(self):
        self.assertTrue(callable(getattr(runtime,'watchdog_due',None)),'WATCHDOG_MISSING_HEARTBEAT_BOUND_REQUIRED')
        self.assertFalse(runtime.watchdog_due(alive=True,armed_at=1000,heartbeat=None,now=1029))
        self.assertTrue(runtime.watchdog_due(alive=True,armed_at=1000,heartbeat=None,now=1031))
        self.assertTrue(runtime.watchdog_due(alive=False,armed_at=1000,heartbeat=1029,now=1029))

    def test_real_disposable_git_filter_rewrite_preserves_nontarget_tree_and_map(self):
        # Synthetic local repository only; no origin, credentials, network or
        # production target content. This proves the concrete Git IO path.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);source=root/'source';source.mkdir()
            def run(*args):
                result=subprocess.run(['git',*args],cwd=source,capture_output=True)
                self.assertEqual(result.returncode,0,'SYNTHETIC_GIT_COMMAND_FAILED');return result.stdout
            run('init','-b','main');run('config','user.name','Synthetic QA');run('config','user.email','qa@example.test')
            (source/'README.md').write_text('retained canary\n');run('add','README.md');run('commit','-m','retained base')
            (source/'backend').mkdir();(source/gate.TARGETS[0]['path']).write_text('synthetic-only removed content\n')
            run('add','backend');run('commit','-m','synthetic target')
            (source/'CANARY.md').write_text('retained second canary\n');run('add','CANARY.md');run('commit','-m','retained tip')
            run('tag','canary-tag');run('clone','--mirror','--no-local',str(source),str(root/'mirror.git'))
            io=runtime.GitIO(root,'synthetic-only-not-a-real-credential')
            commits=io.run(['git','rev-list','--all']).decode().splitlines()
            original={oid:runtime.tree_digest(io,oid) for oid in commits}
            parents={}
            for line in io.run(['git','rev-list','--all','--parents']).decode().splitlines():
                parts=line.split();parents[parts[0]]=parts[1:]
            self.assertEqual(io.run(['git','filter-repo','--version']).decode().strip(),gate.FILTER_REPO_VERSION)
            io.run(['git','filter-repo','--invert-paths','--path',gate.TARGETS[0]['path'],
                    '--preserve-commit-hashes','--replace-refs','delete-no-add'])
            mapping=[dict(zip(['old','new'],line.split())) for line in (root/'mirror.git/filter-repo/commit-map').read_text().splitlines()[1:]]
            self.assertTrue(runtime.verify_tree_retention(io,original,mapping,parents))
            self.assertEqual({r['name'] for r in io.local_refs()},{'refs/heads/main','refs/tags/canary-tag'})
            live=io.run(['git','rev-list','--objects','--all']).decode()
            self.assertNotIn(gate.TARGETS[0]['path'],live)


if __name__=='__main__':unittest.main()

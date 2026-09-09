"""Owner-authorized F01-F05/CRLF/isolation contracts. No production effects."""
import os
import copy
import json
import subprocess
import hashlib
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nyay21_executor_runtime as runtime
import nyay21_executor_adapters as adapters
import nyay21_history_purge as gate
from test_nyay21_execution_time_seal import POLICY, observation
import test_nyay21_executor_adapters as inherited


def snapshot():
    return inherited.ExecutorAdapterContracts().ruleset()


class CorrectiveAuthorityContracts(unittest.TestCase):
    def test_credential_all_controls_rejected_before_io(self):
        for control in [chr(i) for i in range(32)]+[chr(127), chr(133), '\r\n']:
            with self.subTest(control=repr(control)):
                with self.assertRaisesRegex(adapters.Refusal, '^EXECUTION_CREDENTIAL_REQUIRED$'):
                    runtime.GitHub('synthetic'+control+'value')

    def test_valid_credential_unchanged(self):
        self.assertEqual(runtime.GitHub('synthetic-valid_123').credential, 'synthetic-valid_123')

    def test_git_credential_controls_rejected_before_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); root.chmod(0o700); (root/'mirror.git').mkdir()
            with patch.object(runtime.GitIO, 'run') as run:
                with self.assertRaisesRegex(adapters.Refusal, '^EXECUTION_CREDENTIAL_REQUIRED$'):
                    runtime.GitIO(root, 'synthetic\r\nInjected: value')
                run.assert_not_called()

    def test_protected_configuration_unset_refuses(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(adapters.Refusal, '^PROTECTED_ROOT_REQUIRED$'):
                runtime.configured_protected_roots()

    def test_protected_configuration_requires_real_repo(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'NYAY21_PROTECTED_ROOT':tmp}):
            with self.assertRaisesRegex(adapters.Refusal, '^PROTECTED_ROOT_INVALID$'):
                runtime.configured_protected_roots()

    def test_protected_original_and_runtime_source_retained(self):
        source=Path(runtime.__file__).resolve().parents[2]
        with patch.dict(os.environ, {'NYAY21_PROTECTED_ROOT':str(source)}):
            roots=runtime.configured_protected_roots()
            self.assertIn(Path('/Users/rajeevbarnwal/Desktop/Codes/NyayOne'), roots)
            self.assertIn(source, roots)

    def test_protected_owner_permit_mismatch_refuses(self):
        with self.assertRaisesRegex(adapters.Refusal, '^PROTECTED_ROOT_BINDING_MISMATCH$'):
            runtime.validate_protected_binding({'protectedRootSha256':'0'*64}, Path('/synthetic'))

    def test_protected_fake_git_marker_refuses(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'NYAY21_PROTECTED_ROOT':str(Path(tmp).resolve())}):
            (Path(tmp)/'.git').mkdir()
            with self.assertRaisesRegex(adapters.Refusal,'^PROTECTED_ROOT_INVALID$'):runtime.configured_protected_roots()

    def test_expired_resume_has_no_effects(self):
        ctx=object.__new__(runtime.Runtime)
        ctx.seal={'capturedAt':1000,'expiresAt':3700};ctx.now=lambda:3700;ctx.git=Mock();ctx.api=Mock()
        with self.assertRaisesRegex(adapters.Refusal,'^SEAL_EXPIRED$'):ctx.resume_rewrite_phase()
        self.assertEqual(ctx.git.mock_calls,[]);self.assertEqual(ctx.api.mock_calls,[])

    def test_watchdog_stdio_and_refusal_survive_parent_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);log=adapters.Custody(root)
            with self.assertRaisesRegex(adapters.Refusal,'RULESET_CONCURRENT_CHANGE'):
                with runtime.capture_watchdog_stdio(log):
                    print('synthetic-private-diagnostic')
                    raise adapters.Refusal('RULESET_CONCURRENT_CHANGE')
            rows=runtime.read_custody(root)
            self.assertEqual([r['event'] for r in rows],['WATCHDOG_STDOUT','WATCHDOG_STDOUT','RULESET_CONCURRENT_CHANGE','OWNER_ESCALATION_REQUIRED','WATCHDOG_STDERR','WATCHDOG_STDERR'])
            self.assertNotIn('synthetic-private-diagnostic',(root/'events.jsonl').read_text())

    def test_server_time_ignores_caller_timestamp(self):
        self.assertTrue(callable(getattr(runtime, 'AuthenticatedClock', None)), 'SERVER_TIME_AUTHORITY_REQUIRED')
        with self.assertRaises(TypeError):
            runtime.AuthenticatedClock(now=1000)

    def test_forty_five_minute_capture_policy(self):
        policy={**POLICY, 'maxSnapshotAgeSeconds':2700}
        result=gate.capture_execution_seal(observation, policy=policy, now=1000)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['seal']['expiresAt'], 3700)
        for invalid in [2701,True,2700.0]:
            with self.subTest(window=repr(invalid)):
                refused=gate.capture_execution_seal(observation,policy={**policy,'maxSnapshotAgeSeconds':invalid},now=1000)
                self.assertEqual(refused['verdict'],'FAIL')
                self.assertIs(refused['executionAuthorized'],False)
        oversized={**result['seal'],'expiresAt':3701}
        self.assertFalse(gate._execution_seal_valid(oversized))

    def test_registry_requires_authenticated_signed_snapshot(self):
        self.assertTrue(callable(getattr(runtime, 'ConsumptionRegistry', None)), 'AUTHENTICATED_REGISTRY_REQUIRED')

    def test_force_consumption_follows_verified_push(self):
        ctx=Mock(); order=[]
        ctx.validated_push_plan.return_value=['git','push','--atomic','--dry-run','--force-with-lease=refs/heads/main:'+('a'*40),'origin',('b'*40)+':refs/heads/main']
        ctx.command.side_effect=lambda argv: order.append('dry' if '--dry-run' in argv else 'push') or {'exitCode':0}
        ctx.verify_pushed_refs.side_effect=lambda: order.append('verified') or {'verified':True}
        ctx.consume_force_approval.side_effect=lambda: order.append('consumed')
        adapters.Executor(ctx).step8()
        self.assertEqual(order, ['dry','push','verified','consumed'])

    def test_get_retry_is_bounded_and_logged(self):
        before=snapshot(); pair=adapters.ruleset_pair(before,adapters.digest(before)); api=Mock(); events=[]
        api.get.side_effect=[OSError('synthetic'), before]
        self.assertTrue(adapters.restore(api,pair,events.append)['restored'])
        self.assertEqual(api.get.call_count,2); api.put.assert_not_called()
        self.assertIn('RESTORATION_GET_FAILED',events)

    def test_concurrent_edit_refusal_is_logged_and_rechecked(self):
        before=snapshot(); pair=adapters.ruleset_pair(before,adapters.digest(before)); api=Mock(); events=[]
        api.get.return_value={**before,'name':'foreign-edit'}
        with self.assertRaisesRegex(adapters.Refusal,'^RULESET_CONCURRENT_CHANGE$'):
            adapters.restore(api,pair,events.append)
        self.assertEqual(api.get.call_count,2); api.put.assert_not_called()
        self.assertIn('RULESET_CONCURRENT_CHANGE',events)
        self.assertIn('RESTORATION_OWNER_BREAK_GLASS',events)

    def test_watchdog_stdio_is_custody_bound(self):
        self.assertTrue(callable(getattr(runtime,'capture_watchdog_stdio',None)), 'WATCHDOG_STDIO_CUSTODY_REQUIRED')

    def test_reviewed_seal_capture_cli(self):
        self.assertTrue(callable(getattr(runtime,'capture_seal',None)), 'REVIEWED_CAPTURE_CLI_REQUIRED')

    def test_mirror_preparation_recipe_present(self):
        path=Path(runtime.__file__).resolve().parents[2]/'docs/operations/nyay21-history-purge/EXECUTION_V2_PREPARATION.md'
        self.assertTrue(path.is_file(), 'REVIEWED_MIRROR_PREPARATION_REQUIRED')

    def test_resume_checks_custody_and_window(self):
        self.assertTrue(callable(getattr(runtime.Runtime,'resume_rewrite_phase',None)), 'CUSTODY_WINDOW_RESUME_REQUIRED')

    def test_authenticated_clock_rejects_drift_and_transport_failure(self):
        api=Mock();api.server_time.return_value={'timestamp':1000,'requestId':'synthetic-request'}
        with patch.object(runtime.time,'time',return_value=1000),patch.object(runtime.time,'monotonic',return_value=10):
            clock=runtime.AuthenticatedClock(api)
            self.assertEqual(clock(),1000)
            api.server_time.return_value={'timestamp':1006,'requestId':'synthetic-request'}
            with self.assertRaisesRegex(adapters.Refusal,'SERVER_TIME_DRIFT'):clock()
            api.server_time.side_effect=OSError('private raw response')
            with self.assertRaisesRegex(adapters.Refusal,'^SERVER_TIME_UNAVAILABLE$'):clock()

    def test_signed_snapshot_identity_chain_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700)
            key=root/'synthetic-key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True,capture_output=True)
            public=' '.join(key.with_suffix('.pub').read_text().split()[:2])
            seal=gate.capture_execution_seal(observation,policy={**POLICY,'maxSnapshotAgeSeconds':2700},now=1000)['seal']
            permit={'registrySigners':{'owner':{'publicKey':public,'accountId':'synthetic-owner'}},
                    'registryAnchor':{'index':-1,'digest':'0'*64}}
            payload={'schemaVersion':'nyay21-registry-snapshot/v1','issue':'NYAY-21',
                     'repository':gate.REPOSITORY,'sealSha256':adapters.digest(seal),
                     'signer':'owner','accountId':'synthetic-owner','commentId':'12345',
                     'serverTimestamp':1001,'chainHead':'0'*64,'entries':[]}
            def signed(value):
                message=root/'message'
                message.write_bytes(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
                sig=Path(str(message)+'.sig')
                if sig.exists():sig.unlink()
                subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','nyay21-registry-v1',str(message)],check=True,capture_output=True)
                return {'payload':value,'signature':sig.read_text()}
            registry=runtime.ConsumptionRegistry(root,permit,seal,lambda:1002)
            good=signed(payload)
            self.assertEqual(registry.verify(good)['chainHead'],'0'*64)
            entry={'index':0,'previous':'0'*64,'sealSha256':adapters.digest(seal),
                   'approvalId':'00000000-0000-4000-8000-000000000001','action':'rewrite','event':'consumed',
                   'commentId':'12344','serverTimestamp':1001,'effectReceiptSha256':'d'*64}
            chain={**payload,'entries':[entry],'chainHead':adapters.digest(entry)}
            accepted=signed(chain)
            self.assertEqual(registry.verify(accepted)['entries'],[entry])
            for field,value in [('index',True),('index',1),('previous','f'*64),('event','approved'),
                                ('action',[]),('serverTimestamp',999),('effectReceiptSha256',False)]:
                changed={**entry,field:value}
                mutation={**chain,'entries':[changed],'chainHead':adapters.digest(changed)}
                with self.subTest(entry_field=field,value=repr(value)),self.assertRaises(adapters.Refusal):registry.verify(signed(mutation))
            (root/'registry-snapshot.json').write_text(json.dumps(accepted))
            registry.readback()
            (root/'registry-snapshot.json').write_text(json.dumps(good))
            with self.assertRaisesRegex(adapters.Refusal,'REGISTRY_ROLLBACK'):registry.readback()
            for field,value in [('chainHead','f'*64),('serverTimestamp',999),('commentId','bad'),('accountId','foreign'),('sealSha256','e'*64)]:
                with self.subTest(field=field),self.assertRaises(adapters.Refusal):registry.verify(signed({**payload,field:value}))
            tampered=copy.deepcopy(good);tampered['payload']['commentId']='99999'
            with self.assertRaisesRegex(adapters.Refusal,'REGISTRY_SIGNATURE_INVALID'):registry.verify(tampered)
            with patch.object(registry,'now',return_value=3700),self.assertRaisesRegex(adapters.Refusal,'SEAL_EXPIRED'):registry.verify(good)

    def test_restore_mixed_failures_never_exceed_two_gets(self):
        before=snapshot();pair=adapters.ruleset_pair(before,adapters.digest(before))
        for reads in [[OSError('private'),{**before,'name':'foreign'}],[{**before,'name':'foreign'},OSError('private')]]:
            api=Mock();api.get.side_effect=reads;events=[]
            with self.subTest(schedule=len(reads)),self.assertRaises(adapters.Refusal):adapters.restore(api,pair,events.append)
            self.assertEqual(api.get.call_count,2);api.put.assert_not_called()
            self.assertIn('RULESET_CONCURRENT_CHANGE',events)

    def test_failed_push_never_consumes_force_and_always_restores(self):
        ctx=Mock();ctx.validated_push_plan.return_value=['git','push','--atomic','--dry-run','--force-with-lease=refs/heads/main:'+('a'*40),'origin',('b'*40)+':refs/heads/main']
        ctx.command.side_effect=[{'exitCode':0},adapters.Refusal('GIT_COMMAND_FAILED')]
        with self.assertRaisesRegex(adapters.Refusal,'GIT_COMMAND_FAILED'):adapters.Executor(ctx).step8()
        ctx.consume_force_approval.assert_not_called();ctx.verify_pushed_refs.assert_not_called()
        ctx.restore.assert_called_once()

    def test_force_consumption_requires_exact_verified_effect_digest(self):
        ctx=object.__new__(runtime.Runtime);ctx.root=Path('/synthetic')
        ctx.seal=gate.capture_execution_seal(observation,policy={**POLICY,'maxSnapshotAgeSeconds':2700},now=1000)['seal']
        from test_nyay21_execution_time_seal import approvals
        ctx.approvals=approvals(ctx.seal);ctx.now=lambda:1001;ctx.registry=Mock()
        approval=ctx.approvals['forceUpdate']
        ctx.registry.readback.return_value={'entries':[{'approvalId':approval['id'],'action':approval['action'],
            'serverTimestamp':1001,'effectReceiptSha256':'f'*64}]}
        with patch.object(runtime,'read_json',return_value={'serverTimestamp':1001}),self.assertRaisesRegex(adapters.Refusal,'FORCE_CONSUMED_BEFORE_PUSH_VERIFICATION'):
            ctx.consume_force_approval()


class FinalF02Contracts(unittest.TestCase):
    def signed_fixture(self, purpose='execution', now=1002):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        top=Path(temporary.name).resolve();root=top/'custody';root.mkdir(mode=0o700)
        key=top/'synthetic-external-key'
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True,capture_output=True)
        public=' '.join(key.with_suffix('.pub').read_text().split()[:2])
        seal=gate.capture_execution_seal(observation,policy={**POLICY,'maxSnapshotAgeSeconds':2700},now=1000)['seal']
        identity={**self.identity(str(root)),'sealedPlanSha256':adapters.digest(seal)}
        identity['executionId']=runtime.execution_identity(identity)
        permit={'executionIdentity':identity,'registrySigners':{'owner':{'publicKey':public,'accountId':'synthetic-owner'}},
                'registryAnchor':{'index':-1,'digest':'0'*64}}
        restoration={'restored':True}
        proof={'executionId':identity['executionId'],'restorationProofSha256':adapters.digest(restoration)}
        for name,value in [('restoration-proof.json',restoration),('push-verified.json',proof)]:
            (root/name).write_text(json.dumps(value))
        row={'schemaVersion':'nyay21-registry-snapshot/v2','issue':'NYAY-21','repository':gate.REPOSITORY,
             'sealSha256':adapters.digest(seal),'signer':'owner','accountId':'synthetic-owner','commentId':'12345',
             'serverTimestamp':now,'expiresAt':now+2700,'entries':[],'registrations':[identity],
             'chainHead':'0'*64,'authority':purpose,'executionId':identity['executionId']}
        if purpose=='continuation':row.update(pushProofSha256=adapters.digest(proof),restorationProofSha256=adapters.digest(restoration))
        registry=runtime.ExecutionRegistry(root,permit,seal,lambda:now)
        def signed(value,domain=None):
            result=subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n',runtime.registry_namespace(domain or purpose)],
                input=json.dumps(value,sort_keys=True,separators=(',',':')).encode(),capture_output=True,check=True)
            return {'payload':value,'signature':result.stdout.decode()}
        return registry,row,signed

    def identity(self, root='/synthetic/custody'):
        return {'sealedPlanSha256':'a'*64,'approvalId':'00000000-0000-4000-8000-000000000001',
                'nonce':'b'*64,'custodyRootSha256':adapters.digest(root)}

    def test_execution_identity_binds_plan_approval_and_nonce(self):
        row=self.identity();expected=adapters.digest({k:row[k] for k in ['sealedPlanSha256','approvalId','nonce']})
        self.assertEqual(runtime.execution_identity(row),expected)
        for field,value in [('nonce',True),('nonce',''),('approvalId','arbitrary'),('sealedPlanSha256','a')]:
            with self.subTest(field=field),self.assertRaises(adapters.Refusal):runtime.execution_identity({**row,field:value})

    def test_custody_identity_rejects_copy_to_fresh_root(self):
        row=self.identity();row['executionId']=runtime.execution_identity(row)
        with self.assertRaisesRegex(adapters.Refusal,'CUSTODY_IDENTITY_MISMATCH'):
            runtime.validate_execution_identity(row,Path('/synthetic/other'),'a'*64,row['approvalId'])

    def test_registry_duplicate_approval_nonce_is_refused(self):
        first=self.identity();first['executionId']=runtime.execution_identity(first)
        second={**first,'nonce':'c'*64};second['executionId']=runtime.execution_identity(second)
        with self.assertRaisesRegex(adapters.Refusal,'APPROVAL_EXECUTION_ALREADY_REGISTERED'):
            runtime.register_execution([first],second)

    def test_registration_idempotent_only_exact_identity(self):
        row=self.identity();row['executionId']=runtime.execution_identity(row)
        self.assertEqual(runtime.register_execution([row],row),[row])
        with self.assertRaisesRegex(adapters.Refusal,'APPROVAL_EXECUTION_ALREADY_REGISTERED'):
            runtime.register_execution([row],{**row,'custodyRootSha256':'c'*64})

    def test_continuation_signature_domain_cannot_grant_execution(self):
        self.assertNotEqual(runtime.registry_namespace('execution'),runtime.registry_namespace('continuation'))
        with self.assertRaises(adapters.Refusal):runtime.registry_namespace('push')

    def test_restoration_precedes_verification_and_consumption(self):
        ctx=Mock();order=[]
        ctx.validated_push_plan.return_value=['git','push','--atomic','--dry-run','--force-with-lease=refs/heads/main:'+('a'*40),'origin',('b'*40)+':refs/heads/main']
        ctx.command.side_effect=lambda argv:order.append('dry' if '--dry-run' in argv else 'push') or {'exitCode':0}
        ctx.restore.side_effect=lambda:order.append('restored')
        ctx.verify_pushed_refs.side_effect=lambda:order.append('verified')
        ctx.consume_force_approval.side_effect=lambda:order.append('consumed')
        adapters.Executor(ctx).step8()
        self.assertLess(order.index('restored'),order.index('verified'))
        self.assertLess(order.index('verified'),order.index('consumed'))

    def test_real_signature_continuation_cannot_be_relabelled_as_execution(self):
        registry,row,signed=self.signed_fixture('continuation',now=4000)
        envelope=signed(row)
        self.assertEqual(registry.verify(envelope,purpose='continuation')['authority'],'continuation')
        with self.assertRaisesRegex(adapters.Refusal,'REGISTRY_AUTHORITY_INVALID'):registry.verify(envelope)
        forged={k:v for k,v in row.items() if k not in {'pushProofSha256','restorationProofSha256'}}
        forged['authority']='execution'
        with self.assertRaisesRegex(adapters.Refusal,'REGISTRY_SIGNATURE_INVALID'):
            registry.verify({'payload':forged,'signature':envelope['signature']})

    def test_expired_execution_receipt_fails_but_fresh_continuation_has_no_push_authority(self):
        registry,row,signed=self.signed_fixture('execution',now=4000)
        with self.assertRaisesRegex(adapters.Refusal,'SEAL_EXPIRED'):registry.verify(signed(row))
        registry,row,signed=self.signed_fixture('continuation',now=4000)
        self.assertEqual(registry.verify(signed(row),purpose='continuation')['serverTimestamp'],4000)
        with patch.object(registry,'now',return_value=6700),self.assertRaisesRegex(adapters.Refusal,'REGISTRY_SNAPSHOT_STALE'):
            registry.verify(signed(row),purpose='continuation')

    def test_signed_duplicate_uuid_with_new_nonce_refuses(self):
        registry,row,signed=self.signed_fixture()
        second={**row['registrations'][0],'nonce':'c'*64};second['executionId']=runtime.execution_identity(second)
        row['registrations'].append(second)
        with self.assertRaisesRegex(adapters.Refusal,'APPROVAL_EXECUTION_ALREADY_REGISTERED'):registry.verify(signed(row))

    def test_signed_continuation_requires_exact_restored_push_receipt(self):
        registry,row,signed=self.signed_fixture('continuation',now=4000)
        for field in ['pushProofSha256','restorationProofSha256']:
            with self.subTest(field=field),self.assertRaisesRegex(adapters.Refusal,'CONTINUATION_EFFECT_BINDING_MISMATCH'):
                registry.verify(signed({**row,field:'f'*64}),purpose='continuation')

    def test_snapshot_consumed_uuid_cannot_arm_new_execution(self):
        ctx=object.__new__(runtime.Runtime);ctx.root=Path('/synthetic');ctx.seal={'synthetic':'sealed'}
        ctx.approvals={'rewrite':{'id':'synthetic'}};ctx.registry=Mock();ctx.api=Mock();ctx.git=Mock()
        ctx.registry.readback.return_value={'entries':[{'approvalId':'synthetic'}]}
        receipt={'step':5,'sealSha256':adapters.digest(ctx.seal),'completed':True}
        ctx.permit={'backupDrillReceiptSha256':adapters.digest(receipt)}
        with patch.object(runtime,'read_json',return_value=receipt),self.assertRaisesRegex(adapters.Refusal,'REWRITE_APPROVAL_ALREADY_CONSUMED'):
            ctx.require_predecessor(6)
        self.assertEqual(ctx.git.mock_calls,[]);self.assertEqual(ctx.api.mock_calls,[])

    def test_clock_failure_cannot_prevent_post_push_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700)
            before=snapshot();pair=adapters.ruleset_pair(before,adapters.digest(before))
            (root/'ruleset-pair.json').write_text(json.dumps(pair))
            state={**before,**pair['relaxation']};ctx=object.__new__(runtime.Runtime)
            ctx.root=root;ctx.api=Mock();ctx.api.get.side_effect=lambda:copy.deepcopy(state)
            ctx.api.put.side_effect=lambda payload:state.update(copy.deepcopy(payload))
            ctx.emit=Mock();ctx.clock=Mock(side_effect=adapters.Refusal('SERVER_TIME_UNAVAILABLE'))
            with self.assertRaisesRegex(adapters.Refusal,'SERVER_TIME_UNAVAILABLE'):ctx.verify_pushed_refs()
            self.assertEqual(state,before)
            self.assertFalse((root/'push-verified.json').exists())


class CorrectiveE2EContracts(unittest.TestCase):
    def test_signed_registry_pause_resume_real_synthetic_git(self):
        """Real local Git effects, real signatures; GitHub/watchdog are offline fakes."""
        with tempfile.TemporaryDirectory() as tmp:
            top=Path(tmp).resolve();root=top/'custody';root.mkdir(mode=0o700)
            source=top/'source';source.mkdir();origin=top/'origin.git';key=top/'synthetic-external-key'
            def git(cwd,*args):
                result=subprocess.run(['git',*args],cwd=cwd,capture_output=True)
                self.assertEqual(result.returncode,0,'SYNTHETIC_GIT_FAILED')
                return result.stdout
            git(source,'init','-b','main');git(source,'config','user.name','Synthetic QA')
            git(source,'config','user.email','qa@example.test')
            (source/'README.md').write_text('retained\n');git(source,'add','.');git(source,'commit','-m','base')
            (source/'backend').mkdir()
            targets=[]
            for index,target in enumerate(gate.TARGETS):
                data=('synthetic target '+str(index)).encode();(source/target['path']).write_bytes(data)
                targets.append({**target,'blob':git(source,'hash-object',target['path']).decode().strip(),'size':len(data)})
            git(source,'add','.');git(source,'commit','-m','synthetic targets')
            (source/'CANARY.md').write_text('retained tip\n');git(source,'add','.');git(source,'commit','-m','tip')
            git(source,'tag','canary');git(source,'clone','--bare','--no-local',str(source),str(origin))
            git(source,'clone','--mirror','--no-local',str(origin),str(root/'mirror.git'))
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True,capture_output=True)
            public=' '.join(key.with_suffix('.pub').read_text().split()[:2])
            api=Mock();state=snapshot()
            api.repository.return_value={'private':True,'full_name':gate.REPOSITORY,'default_branch':'main'}
            api.get.side_effect=lambda:copy.deepcopy(state)
            api.put.side_effect=lambda payload:state.update(copy.deepcopy(payload))
            api.server_time.side_effect=lambda:{'timestamp':int(time.time()),'requestId':'synthetic-server-read'}
            credential='synthetic-only';api.credential=credential
            protected=Path(runtime.__file__).resolve().parents[2]
            with patch.object(gate,'TARGETS',tuple(targets)),patch.object(runtime,'REPO_URL',str(origin)),\
                 patch.object(runtime,'GitHub',return_value=api),patch.dict(os.environ,{'NYAY21_PROTECTED_ROOT':str(protected)}):
                receipt=runtime.capture_seal(root,credential);seal=runtime.read_json(root/'seal.json');now=int(time.time())
                def write(name,value):
                    (root/name).write_text(json.dumps(value,sort_keys=True,separators=(',',':')))
                def approval(action,index):
                    return {'id':f'00000000-0000-4000-8000-{index:012d}','action':action,'approved':True,
                            'sealSha256':adapters.digest(seal),'sourceHead':seal['sourceHead'],
                            'approvedRefs':[r['name'] for r in seal['refs']],
                            'owner':{'role':'owner','identity':gate.OWNER_APPROVER,'verified':True},
                            'security':{'role':'technical-approver','identity':gate.SECURITY_PRIVACY_APPROVER,'verified':True},
                            'expiresAt':seal['expiresAt'],'consumed':False}
                approvals={'rewrite':approval('rewrite',1),'forceUpdate':approval('force-update',2)}
                identities={}
                for kind,row in approvals.items():
                    identity={'sealedPlanSha256':adapters.digest(seal),'approvalId':row['id'],
                              'nonce':'b'*64,'custodyRootSha256':adapters.digest(str(root))}
                    identity['executionId']=runtime.execution_identity(identity);identities[kind]=identity
                scope={'repository':gate.REPOSITORY,'sourceHead':seal['sourceHead'],'sealSha256':adapters.digest(seal),
                       'permissions':runtime.PERMISSIONS,'readAt':now,'expiresAt':now+86400,'exitCode':0,
                       'ownerDecisionCommentId':'15047','receiptKind':'independent-scope-readback/v1',
                       'restorationWorkflow':'reviewed-ruleset-restoration/v1'}
                step5={'step':5,'sealSha256':adapters.digest(seal),'completed':True,'result':'synthetic-drill-receipt-only'}
                pair=adapters.ruleset_pair(state,adapters.digest(state))
                permit={'decision':'EXECUTION-GO','owner':gate.OWNER_APPROVER,'technicalApprover':gate.SECURITY_PRIVACY_APPROVER,
                        'repository':gate.REPOSITORY,'credentialSha256':hashlib.sha256(credential.encode()).hexdigest(),
                        'protectedRootSha256':adapters.digest(str(protected)),
                        'sealSha256':adapters.digest(seal),'approvalsSha256':adapters.digest(approvals),
                        'scopeReceiptSha256':adapters.digest(scope),'backupDrillReceiptSha256':adapters.digest(step5),
                        'reviewedCodeSha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                            [Path(runtime.__file__),Path(adapters.__file__),Path(gate.__file__)]},
                        'relaxationSha256':adapters.digest(pair['relaxation']),'restorationSha256':adapters.digest(pair['restoration']),
                        'notBefore':now-1,'expiresAt':seal['expiresAt'],
                        'registrySigners':{'owner':{'accountId':'synthetic-owner','publicKey':public}},
                        'executionIdentity':identities['rewrite'],
                        'registryAnchor':{'index':-1,'digest':'0'*64}}
                for name,value in [('approvals.json',approvals),('scope-readback.json',scope),('step-5.json',step5),('execution-permit.json',permit)]:write(name,value)
                entries=[]
                def publish(kind=None,effect=None):
                    purpose='continuation' if kind=='forceUpdate' else 'execution'
                    if kind:
                        row=approvals[kind]
                        entries.append({'index':len(entries),'previous':adapters.digest(entries[-1]) if entries else '0'*64,
                        'sealSha256':adapters.digest(seal),'approvalId':row['id'],'action':row['action'],'event':'consumed',
                        'executionId':identities[kind]['executionId'],
                        'commentId':str(20001+len(entries)),'serverTimestamp':int(time.time()),'effectReceiptSha256':adapters.digest(effect)})
                    payload={'schemaVersion':'nyay21-registry-snapshot/v2','issue':'NYAY-21','repository':gate.REPOSITORY,
                             'sealSha256':adapters.digest(seal),'signer':'owner','accountId':'synthetic-owner',
                             'commentId':str(20001+len(entries)),'serverTimestamp':int(time.time()),'expiresAt':int(time.time())+2700,
                             'chainHead':adapters.digest(entries[-1]) if entries else '0'*64,'entries':copy.deepcopy(entries),
                             'registrations':list(identities.values()),'authority':purpose,'executionId':identities['rewrite']['executionId']}
                    if purpose=='continuation':payload.update(pushProofSha256=adapters.digest(effect),
                        restorationProofSha256=adapters.digest(runtime.read_json(root/'restoration-proof.json')))
                    message=top/('message-'+str(len(entries)))
                    message.write_bytes(json.dumps(payload,sort_keys=True,separators=(',',':')).encode())
                    subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n',runtime.registry_namespace(purpose),str(message)],check=True,capture_output=True)
                    write('continuation-snapshot.json' if purpose=='continuation' else 'registry-snapshot.json',
                          {'payload':payload,'signature':Path(str(message)+'.sig').read_text()})
                publish()
                ctx=runtime.Runtime(root,adapters.digest(permit),credential)
                self.assertEqual(ctx.prepare_rewrite_claim()['authority'],'none')
                self.assertFalse((root/'watchdog-armed.json').exists())
                publish('rewrite',runtime.read_json(root/'rewrite-intent.json'))
                def arm(pair):
                    adapters.immutable_json(root,'watchdog-armed.json',{'pairSha256':adapters.digest(pair),'pid':os.getpid(),'armedAt':int(time.time())})
                with patch.object(ctx,'arm_watchdog',side_effect=arm):adapters.Executor(ctx).run(6)
                adapters.Executor(ctx).run(7)
                with self.assertRaisesRegex(adapters.Refusal,'REWRITE_APPROVAL_ALREADY_CONSUMED'):adapters.Executor(ctx).run(7)
                with self.assertRaisesRegex(adapters.Refusal,'SIGNED_CONSUMPTION_RECEIPT_REQUIRED'):
                    adapters.Executor(ctx).run(8)
                self.assertEqual(state,snapshot())
                self.assertTrue((root/'push-verified.json').is_file())
                self.assertFalse((root/'step-8.json').exists())
                after=git(origin,'show-ref')
                publish('forceUpdate',runtime.read_json(root/'push-verified.json'))
                resumed=ctx.resume_rewrite_phase()
                self.assertEqual(resumed['pause'],'rewrite-push')
                self.assertEqual(git(origin,'show-ref'),after)
                self.assertEqual(ctx.resume_rewrite_phase(),resumed)
                self.assertEqual(git(origin,'show-ref'),after)
                self.assertEqual(git(origin,'show','main:README.md'),b'retained\n')
                reachable=git(origin,'rev-list','--objects','--all').decode()
                for target in targets:self.assertNotIn(target['blob'],reachable)
                self.assertEqual(receipt['sealSha256'],adapters.digest(seal))


if __name__=='__main__': unittest.main()

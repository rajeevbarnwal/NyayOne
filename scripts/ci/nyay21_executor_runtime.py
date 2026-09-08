#!/usr/bin/env python3
"""Explicitly authorized I/O bindings for execution/v2; default is plan-only.

No token provisioning, backup creation, dispatch, freeze, or rewrite is performed
on import or without an explicit execution mode and an out-of-band owner permit digest.
Permit digests are supplied by the operator from the independent approval record,
never inferred from the files being validated. This is an operator trust boundary,
not a substitute for owner and independent technical approval.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode=True
import nyay21_history_purge as gate
from nyay21_executor_adapters import (
    Custody, Executor, Refusal, digest, immutable_json, plan, private_root,
    require, restore, restored, ruleset_pair, write_rebinding,
)

REPO_URL='https://github.com/'+gate.REPOSITORY+'.git'
PROTECTED=Path('/Users/rajeevbarnwal/Desktop/Codes/NyayOne')
PERMISSIONS={'contents':'write','workflows':'write','metadata':'read',
             'administration':'write','actions':'read'}


def read_json(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=16*1024*1024,'INPUT_FILE_INVALID')
    def pairs(rows):
        result={}
        for k,v in rows:
            require(k not in result,'INPUT_DUPLICATE_KEY');result[k]=v
        return result
    try:return json.loads(path.read_bytes(),object_pairs_hook=pairs)
    except (ValueError,OSError):raise Refusal('INPUT_JSON_INVALID') from None


class GitHub:
    """Fixed-host, fixed-repository HTTPS; no ambient gh credentials or redirects."""
    def __init__(self,credential):
        require(isinstance(credential,str) and credential and '\n' not in credential,'EXECUTION_CREDENTIAL_REQUIRED')
        self.credential=credential

    def request(self,method,path,payload=None):
        require(method in {'GET','PUT'} and isinstance(path,str) and (path=='' or path.startswith('/')) and
                '..' not in path and '://' not in path,'API_SCOPE_INVALID')
        require(method!='PUT' or path=='/rulesets/'+str(gate.RULESET_ID),'API_MUTATION_SCOPE_INVALID')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise Refusal('API_REDIRECT_REFUSED')
        headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',
                 'Authorization':'Bearer '+self.credential,'Content-Type':'application/json'}
        data=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request('https://api.github.com/repos/'+gate.REPOSITORY+path,data=data,headers=headers,method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
                require(response.status==200,'API_RESPONSE_INVALID');raw=response.read(16*1024*1024+1)
                require(len(raw)<=16*1024*1024,'API_RESPONSE_TOO_LARGE');return json.loads(raw)
        except (OSError,ValueError):raise Refusal('API_READ_OR_WRITE_FAILED') from None

    def repository(self):return self.request('GET','')
    def get(self):return self.request('GET','/rulesets/'+str(gate.RULESET_ID))
    def put(self,payload):return self.request('PUT','/rulesets/'+str(gate.RULESET_ID),payload)


class GitIO:
    """Only a bare mirror below a private scratch root; protected checkout excluded."""
    def __init__(self,root,credential):
        self.root=private_root(root);self.mirror=self.root/'mirror.git'
        require(self.mirror.is_dir() and not self.mirror.is_symlink() and self.mirror.resolve()==self.mirror
                and not self.mirror.is_relative_to(PROTECTED),'PROTECTED_OR_NONISOLATED_CHECKOUT')
        self.environment={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT'}}
        self.environment.update(PYTHONDONTWRITEBYTECODE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',
            GIT_TERMINAL_PROMPT='0',GIT_CONFIG_COUNT='2',GIT_CONFIG_KEY_0='http.extraHeader',
            GIT_CONFIG_VALUE_0='Authorization: Basic '+base64.b64encode(('x-access-token:'+credential).encode()).decode(),
            GIT_CONFIG_KEY_1='core.hooksPath',GIT_CONFIG_VALUE_1='/dev/null')
        require(self.run(['git','rev-parse','--is-bare-repository']).strip()==b'true','BARE_MIRROR_REQUIRED')
        common=self.run(['git','rev-parse','--git-common-dir']).decode().strip()
        require((self.mirror/common).resolve()==self.mirror,'EXTERNAL_GITDIR_REFUSED')
        # Local repositories may override an injected header or redirect origin.
        config=self.run(['git','config','--local','--list']).decode()
        require(not any(line.lower().startswith(('include.','includeif.','url.','http.','credential.','core.sshcommand')) for line in config.splitlines()),'LOCAL_GIT_CONFIG_REFUSED')

    def run(self,argv):
        require(isinstance(argv,list) and argv and argv[0]=='git' and all(isinstance(a,str) and '\0' not in a for a in argv),'COMMAND_INVALID')
        try:result=subprocess.run(argv,cwd=self.mirror,env=self.environment,capture_output=True,timeout=600)
        except (OSError,subprocess.TimeoutExpired):raise Refusal('GIT_COMMAND_UNAVAILABLE') from None
        require(type(result.returncode) is int and result.returncode==0,'GIT_COMMAND_FAILED')
        return result.stdout

    def remote_refs(self):
        raw=self.run(['git','ls-remote','--refs',REPO_URL,'refs/heads/*','refs/tags/*'])
        rows=[]
        for line in raw.decode('ascii').splitlines():
            try:oid,name=line.split('\t')
            except ValueError:raise Refusal('REMOTE_REF_INVENTORY_INVALID') from None
            rows.append({'name':name,'oid':oid})
        normalized=gate._execution_refs(rows);require(normalized is not None,'REMOTE_REF_INVENTORY_INVALID')
        return normalized

    def local_refs(self):
        raw=self.run(['git','for-each-ref','--format=%(objectname)%09%(refname)'])
        rows=[]
        for line in raw.decode('ascii').splitlines():
            oid,name=line.split('\t');rows.append({'name':name,'oid':oid})
        normalized=gate._execution_refs(rows);require(normalized is not None,'LOCAL_REF_INVENTORY_INVALID')
        return normalized


def collect_observation(git,api):
    """Read-only collector; derive counts from Git objects, never caller counts."""
    metadata=api.repository()
    require(metadata.get('private') is True and metadata.get('full_name')==gate.REPOSITORY
            and metadata.get('default_branch')=='main','REPOSITORY_SCOPE_CHANGED')
    refs=git.remote_refs();require(refs==git.local_refs(),'HEAD_CHANGED')
    heads=[r['oid'] for r in refs if r['name']=='refs/heads/main'];require(len(heads)==1,'MAIN_REF_REQUIRED')
    ids=git.run(['git','rev-list','--all']).decode('ascii').splitlines()
    require(bool(ids) and len(ids)==len(set(ids)) and all(gate._is_nonzero_hex40(x) for x in ids),'COMMIT_INVENTORY_INVALID')
    commits=[]
    for oid in ids:
        header=git.run(['git','cat-file','commit',oid]).split(b'\n\n',1)[0]
        commits.append({'oid':oid,'signed':any(line.startswith((b'gpgsig ',b'gpgsig-sha256 ')) for line in header.splitlines())})
    for target in gate.TARGETS:
        size=git.run(['git','cat-file','-s',target['blob']]).decode('ascii').strip()
        require(size==str(target['size']),'TARGET_OBJECT_SIZE_MISMATCH')
    return {'repository':gate.REPOSITORY,'visibility':'PRIVATE','defaultBranch':'main','head':heads[0],
            'refs':refs,'commits':commits,'targets':copy_targets(),'complete':True,'exitCode':0,
            'rulesetGetSha256':digest(api.get())}


def copy_targets():return [dict(t) for t in gate.TARGETS]


def tree_digest(git,oid):
    raw=git.run(['git','ls-tree','-rz','--full-tree',oid])
    rows=[]
    for entry in raw.split(b'\0'):
        if not entry:continue
        try:header,path=entry.split(b'\t',1)
        except ValueError:raise Refusal('TREE_INVENTORY_INVALID') from None
        if path not in {t['path'].encode() for t in gate.TARGETS}:
            rows.append((header+b'\t'+path).decode('utf8',errors='strict'))
    return digest(rows)


def verify_tree_retention(git,original,mapping,parents=None):
    require(isinstance(original,dict) and bool(original) and isinstance(mapping,list) and bool(mapping)
            and all(isinstance(r,dict) and set(r)=={'old','new'} and gate._is_nonzero_hex40(r['old'])
                    and gate._is_hex(r['new'],40) for r in mapping)
            and len({r['old'] for r in mapping})==len(mapping)
            and {r['old'] for r in mapping}==set(original),'RETENTION_MAP_INVENTORY_MISMATCH')
    # Zero mappings require separate prune proof; never treat them as passes.
    for row in mapping:
        if row['new']=='0'*40:
            old_parents=parents.get(row['old']) if isinstance(parents,dict) else None
            require(isinstance(old_parents,list) and len(old_parents)==1 and old_parents[0] in original
                    and original[row['old']]==original[old_parents[0]],'PRUNED_NONTARGET_TREE_CHANGED')
        else:require(tree_digest(git,row['new'])==original[row['old']],'NONTARGET_RETENTION_CHANGED')
    return True


def watchdog_due(*,alive,armed_at,heartbeat,now):
    require(type(alive) is bool and type(armed_at) is int and type(now) is int,'WATCHDOG_CLOCK_INVALID')
    stamp=armed_at if heartbeat is None else heartbeat
    require(type(stamp) is int,'WATCHDOG_CLOCK_INVALID')
    return not alive or not 0<=now-stamp<=30


class Runtime:
    """Production context. Construction validates files; methods are explicit effects.

    Backup/restore-drill and owner PROCEED receipts are independent runbook
    prerequisites. A missing step is a refusal, never a fabricated success.
    """
    def __init__(self,root,owner_permit_sha256,credential,*,clock=time.time):
        self.root=private_root(root);self.clock=clock;self.log=Custody(self.root)
        self.permit=read_json(self.root/'execution-permit.json')
        require(gate._is_hex(owner_permit_sha256,64) and digest(self.permit)==owner_permit_sha256,'OWNER_PERMIT_DIGEST_MISMATCH')
        require(self.permit.get('decision')=='EXECUTION-GO' and self.permit.get('owner')==gate.OWNER_APPROVER
                and self.permit.get('technicalApprover')==gate.SECURITY_PRIVACY_APPROVER
                and self.permit.get('repository')==gate.REPOSITORY,'FRESH_GO_REQUIRED')
        require(self.permit.get('credentialSha256')==hashlib.sha256(credential.encode()).hexdigest(),'SCOPE_CREDENTIAL_BINDING_MISMATCH')
        self.seal=read_json(self.root/'seal.json');self.approvals=read_json(self.root/'approvals.json')
        self.scope=read_json(self.root/'scope-readback.json')
        require(gate._execution_seal_valid(self.seal) and digest(self.seal)==self.permit.get('sealSha256')
                and digest(self.approvals)==self.permit.get('approvalsSha256')
                and digest(self.scope)==self.permit.get('scopeReceiptSha256'),'PERMIT_INPUT_BINDING_MISMATCH')
        require(self.scope.get('permissions')==PERMISSIONS,'RESTORATION_SCOPE_INVALID')
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                 [Path(__file__),Path(__file__).with_name('nyay21_executor_adapters.py'),Path(gate.__file__)]}
        require(sources==self.permit.get('reviewedCodeSha256'),'REVIEWED_EXECUTOR_CHANGED')
        self.api=GitHub(credential);self.git=GitIO(self.root,credential)
        self.watchdog=None;self.stop_heartbeat=threading.Event()

    def now(self):return int(self.clock())

    def emit(self,event):self.log.append(event,{'sealSha256':digest(self.seal)})

    def require_current_permit(self,step):
        now=self.now()
        require(all(type(self.permit.get(k)) is int for k in ['notBefore','expiresAt']) and
                self.permit['notBefore']<=now<self.permit['expiresAt'],'OWNER_PERMIT_NOT_CURRENT')
        require(step in range(6,16),'STEP_INVALID')
        remote=self.api.repository()
        require(remote.get('private') is True and remote.get('full_name')==gate.REPOSITORY and remote.get('default_branch')=='main','REPOSITORY_SCOPE_CHANGED')

    def require_predecessor(self,step):
        receipt=read_json(self.root/f'step-{step-1}.json')
        require(type(receipt.get('step')) is int and receipt['step']==step-1 and receipt.get('sealSha256')==digest(self.seal)
                and receipt.get('completed') is True,'PREDECESSOR_RECEIPT_REQUIRED')
        if step==6:
            require(digest(receipt)==self.permit.get('backupDrillReceiptSha256'),'BACKUP_DRILL_PAUSE_REQUIRED')

    def record_step(self,step,result):
        value={'step':step,'sealSha256':digest(self.seal),'completed':True,'result':result}
        immutable_json(self.root,f'step-{step}.json',value)
        self.log.append('STEP_COMPLETED',{'step':step,'digest':digest(value),'sealSha256':digest(self.seal)})

    def require_live_old_refs(self):
        require(self.git.remote_refs()==self.seal['refs'],'HEAD_CHANGED')

    def capture_ruleset_pair(self):
        self.require_live_old_refs()
        raw=collect_observation(self.git,self.api)
        raw['refs']=sorted(raw['refs'],key=lambda r:r['name']);raw['commits']=sorted(raw['commits'],key=lambda r:r['oid'])
        require(digest(raw)==self.seal['observationSha256'],'EXECUTION_OBSERVATION_CHANGED')
        trees={r['oid']:tree_digest(self.git,r['oid']) for r in raw['commits']}
        immutable_json(self.root,'original-trees.json',trees)
        parents={}
        for line in self.git.run(['git','rev-list','--all','--parents']).decode('ascii').splitlines():
            parts=line.split();parents[parts[0]]=parts[1:]
        require(set(parents)==set(trees),'PARENT_INVENTORY_MISMATCH')
        immutable_json(self.root,'original-parents.json',parents)
        pair=ruleset_pair(self.api.get(),self.seal['rulesetGetSha256'])
        require(digest(pair['relaxation'])==self.permit.get('relaxationSha256') and
                digest(pair['restoration'])==self.permit.get('restorationSha256'),'RULESET_PAIR_NOT_APPROVED')
        immutable_json(self.root,'ruleset-pair.json',pair);return pair

    def heartbeat(self):
        while not self.stop_heartbeat.wait(5):
            path=self.root/'heartbeat';fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(str(self.now()));stream.flush();os.fsync(stream.fileno())

    def arm_watchdog(self,pair):
        # Separate process survives executor SIGKILL. No production arming occurs
        # during tests. Credential stays in environment, never argv or receipts.
        fd=os.open(self.root/'heartbeat',os.O_CREAT|os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(str(self.now()));stream.flush();os.fsync(stream.fileno())
        self.heartbeat_thread=threading.Thread(target=self.heartbeat,daemon=True);self.heartbeat_thread.start()
        environment={k:v for k,v in os.environ.items() if k in {'PATH','LANG','TMPDIR'}}
        environment.update(PYTHONDONTWRITEBYTECODE='1',NYAY21_EXECUTION_CREDENTIAL=self.api.credential)
        self.watchdog=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--watchdog',str(self.root),
            '--pair-sha256',digest(pair),'--parent-pid',str(os.getpid())],env=environment,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        deadline=time.monotonic()+10
        while not (self.root/'watchdog-armed.json').exists():
            require(self.watchdog.poll() is None and time.monotonic()<deadline,'WATCHDOG_ARM_FAILED');time.sleep(.05)

    def verify_watchdog(self,pair):
        row=read_json(self.root/'watchdog-armed.json')
        require(row.get('pairSha256')==digest(pair) and type(row.get('pid')) is int,'WATCHDOG_BINDING_MISMATCH')
        try:os.kill(row['pid'],0)
        except OSError:raise Refusal('WATCHDOG_NOT_LIVE') from None
        require(type(row.get('armedAt')) is int and 0<=self.now()-row['armedAt']<=300,'WATCHDOG_STALE')
        return row

    def verify_filter_version(self,expected):
        require(self.git.run(['git','filter-repo','--version']).decode().strip()==expected,'FILTER_REPO_VERSION_MISMATCH')

    def consume(self,kind):
        result=gate.validate_execution_approvals(self.approvals,seal=self.seal,current=self.seal,now=self.now())
        require(result['verdict']=='PASS','APPROVAL_NOT_CURRENT')
        row=self.approvals[kind]
        immutable_json(self.root,'consumed-'+row['id']+'.json',{'id':row['id'],'sealSha256':digest(self.seal),'action':row['action']})

    def consume_rewrite_approval(self):self.consume('rewrite')
    def consume_force_approval(self):self.consume('forceUpdate')

    def command(self,argv):
        output=self.git.run(argv)
        return {'exitCode':0,'stdoutSha256':hashlib.sha256(output).hexdigest()}

    def verify_rewrite(self):
        refs=self.git.local_refs();require([r['name'] for r in refs]==[r['name'] for r in self.seal['refs']],'REWRITE_REF_SET_CHANGED')
        reachable=self.git.run(['git','rev-list','--objects','--all']).decode().splitlines()
        ids={line.split(' ',1)[0] for line in reachable}
        require(all(t['blob'] not in ids for t in gate.TARGETS),'TARGET_BLOB_REACHABLE')
        mapping=[]
        for line in (self.git.mirror/'filter-repo/commit-map').read_text().splitlines()[1:]:
            old,new=line.split();require(gate._is_hex(old,40) and gate._is_hex(new,40),'COMMIT_MAP_INVALID');mapping.append({'old':old,'new':new})
        require(bool(mapping),'COMMIT_MAP_EMPTY')
        parents=read_json(self.root/'original-parents.json')
        verify_tree_retention(self.git,read_json(self.root/'original-trees.json'),mapping,parents)
        replacements={r['old']:r['new'] for r in mapping}
        def surviving_parent(oid,seen=None):
            seen=set() if seen is None else seen
            require(oid in replacements and oid not in seen,'PARENT_MAP_INVALID');seen.add(oid)
            if replacements[oid]!='0'*40:return replacements[oid]
            require(len(parents[oid])==1,'PRUNED_MERGE_REFUSED')
            return surviving_parent(parents[oid][0],seen)
        for row in mapping:
            if row['new']=='0'*40:continue
            expected=list(dict.fromkeys(surviving_parent(p) for p in parents[row['old']]))
            actual=self.git.run(['git','rev-list','--parents','-n','1',row['new']]).decode('ascii').split()[1:]
            require(actual==expected,'REWRITTEN_PARENT_GRAPH_CHANGED')
        immutable_json(self.root,'rewrite-result.json',{'refs':refs,'mapping':mapping,'targetsUnreachable':True})
        return {'targetBlobsUnreachable':True,'refs':len(refs),'mappedCommits':len(mapping)}

    def validated_push_plan(self):
        self.require_current_permit(8);self.require_live_old_refs()
        rewrite=read_json(self.root/'rewrite-result.json')
        require(rewrite.get('targetsUnreachable') is True and self.git.local_refs()==rewrite['refs'],'REWRITE_OUTPUT_CHANGED')
        new={r['name']:r['oid'] for r in rewrite['refs']}
        rows=[{'ref':r['name'],'expectedOldOid':r['oid'],'newOid':new[r['name']]} for r in self.seal['refs']]
        value=gate.prepare_execution_push(rows,seal=self.seal,current=self.seal,now=self.now(),approvals=self.approvals,
            scope_readback=self.scope,scope_receipt_sha256=self.permit['scopeReceiptSha256'])
        require(value['verdict']=='PASS','PUSH_SCOPE_OR_APPROVAL_INVALID')
        self.verify_watchdog(read_json(self.root/'ruleset-pair.json'))
        # filter-repo removes origin. Explicit URL overrides no inherited remote.
        return [REPO_URL if a=='origin' else a for a in value['dryRunArgv']]

    def relax_ruleset(self):
        pair=read_json(self.root/'ruleset-pair.json');self.verify_watchdog(pair)
        require(restored(pair['before'],self.api.get()),'RULESET_CONCURRENT_CHANGE')
        self.api.put(pair['relaxation'])
        require(restored({**pair['before'],**pair['relaxation']},self.api.get()),'RELAXATION_READBACK_MISMATCH')

    def restore(self):
        proof=restore(self.api,read_json(self.root/'ruleset-pair.json'),self.emit)
        path=self.root/'restoration-proof.json'
        if not path.exists():immutable_json(self.root,path.name,proof)
        self.stop_heartbeat.set();return proof

    def restoration_proof(self):
        pair=read_json(self.root/'ruleset-pair.json')
        require(restored(pair['before'],self.api.get()),'RESTORATION_NOT_PROVEN')
        return read_json(self.root/'restoration-proof.json')

    def verify_post_push(self):
        expected=read_json(self.root/'rewrite-result.json')['refs']
        require(self.git.remote_refs()==expected,'POST_PUSH_REF_MISMATCH')
        require(self.api.repository().get('private') is True,'REPOSITORY_SCOPE_CHANGED')
        self.restoration_proof()
        return {'remoteRefsMatch':True,'private':True,'head':next(r['oid'] for r in expected if r['name']=='refs/heads/main')}

    def require_proceed(self,pause):
        row=read_json(self.root/('proceed-'+pause+'.json'))
        expected=self.permit.get('proceedReceiptSha256',{}).get(pause)
        require(gate._is_hex(expected,64) and digest(row)==expected and row.get('owner')==gate.OWNER_APPROVER
                and row.get('sealSha256')==digest(self.seal) and row.get('pause')==pause
                and row.get('decision')=='PROCEED','OWNER_PROCEED_REQUIRED')
        return {'pause':pause,'receiptSha256':digest(row)}

    def owner_dispatch_plan(self):
        head=self.verify_post_push()['head']
        value=gate.prepare_owner_ci_dispatch(seal=self.seal,post_push_head=head,observed_main_head=head,permissions=PERMISSIONS)
        require(value['verdict']=='PASS','OWNER_DISPATCH_PLAN_INVALID')
        return value

    def verify_dispatch_readback(self):
        receipt=read_json(self.root/'owner-dispatch-runs.json');head=self.verify_post_push()['head']
        rows=[]
        require(isinstance(receipt,list) and len(receipt)==len(gate.EXECUTION_CI_WORKFLOWS),'DISPATCH_INVENTORY_INVALID')
        for run_id in receipt:
            require(type(run_id) is int and run_id>0,'DISPATCH_RUN_ID_INVALID')
            raw=self.api.request('GET','/actions/runs/'+str(run_id))
            workflow=raw.get('path','').split('/')[-1]
            rows.append({'workflow':workflow,'runId':run_id,'headSha':raw.get('head_sha'),'event':raw.get('event'),'repository':raw.get('repository',{}).get('full_name')})
        value=gate.validate_owner_ci_dispatch_readback(rows,expected_head=head,observed_main_head=head)
        require(value['verdict']=='PASS','DISPATCH_READBACK_MISMATCH');return value

    def verify_completed_campaign(self):
        runs=self.verify_dispatch_readback()['runIds']
        for run_id in runs:
            raw=self.api.request('GET','/actions/runs/'+str(run_id))
            require(raw.get('status')=='completed' and raw.get('conclusion')=='success','CAMPAIGN_NOT_PASS')
        # Independent exact-head gate output is separately reviewed and bound.
        receipt=read_json(self.root/'campaign-evidence.json')
        require(digest(receipt)==self.permit.get('campaignEvidenceSha256') and receipt.get('head')==self.verify_post_push()['head']
                and receipt.get('runIds')==runs and receipt.get('passed') is True
                and type(receipt.get('assertions')) is int and receipt['assertions']>0,'CAMPAIGN_EVIDENCE_REQUIRED')
        return receipt

    def write_rebinding(self,campaign):
        result=read_json(self.root/'rewrite-result.json')
        path=write_rebinding(self.root,digest(self.seal),result['mapping'],campaign)
        return {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

    def verify_closure_signatures(self):
        receipt=read_json(self.root/'closure-signatures.json')
        require(digest(receipt)==self.permit.get('closureSignaturesSha256') and
                receipt.get('owner')==gate.OWNER_APPROVER and receipt.get('technicalApprover')==gate.SECURITY_PRIVACY_APPROVER
                and receipt.get('sealSha256')==digest(self.seal) and receipt.get('head')==self.verify_post_push()['head']
                and receipt.get('disposition')=='CLOSED','CLOSURE_SIGNATURES_REQUIRED')
        return {'closureReceiptSha256':digest(receipt)}


def watchdog(root,pair_sha256,parent_pid,credential):
    root=private_root(root);pair=read_json(root/'ruleset-pair.json')
    require(digest(pair)==pair_sha256,'WATCHDOG_PAIR_MISMATCH');api=GitHub(credential);log=Custody(root)
    require(restored(pair['before'],api.get()),'WATCHDOG_INITIAL_GET_MISMATCH')
    armed_at=int(time.time())
    immutable_json(root,'watchdog-armed.json',{'pairSha256':pair_sha256,'pid':os.getpid(),'armedAt':armed_at})
    while True:
        if (root/'restoration-proof.json').exists():
            require(restored(pair['before'],api.get()),'WATCHDOG_COMPLETION_MISMATCH');return
        try:os.kill(parent_pid,0);alive=True
        except OSError:alive=False
        try:heartbeat=int((root/'heartbeat').read_text())
        except (OSError,ValueError):heartbeat=None
        if watchdog_due(alive=alive,armed_at=armed_at,heartbeat=heartbeat,now=int(time.time())):
            result=restore(api,pair,lambda event:log.append(event,{'digest':pair_sha256}))
            if not (root/'restoration-proof.json').exists():immutable_json(root,'restoration-proof.json',result)
            return
        time.sleep(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-step',type=int,choices=range(11,16));parser.add_argument('--root',type=Path)
    parser.add_argument('--execute-rewrite-phase',action='store_true')
    parser.add_argument('--owner-permit-sha256');parser.add_argument('--watchdog',type=Path)
    parser.add_argument('--pair-sha256');parser.add_argument('--parent-pid',type=int)
    args=parser.parse_args()
    if args.execute_step is None and args.watchdog is None and not args.execute_rewrite_phase:print(json.dumps(plan(),sort_keys=True));return
    credential=os.environ.get('NYAY21_EXECUTION_CREDENTIAL','')
    if args.watchdog is not None:
        require(type(args.parent_pid) is int and args.parent_pid>1,'WATCHDOG_PARENT_REQUIRED')
        watchdog(args.watchdog,args.pair_sha256,args.parent_pid,credential);return
    require(args.root is not None and args.owner_permit_sha256 is not None,'OWNER_PERMIT_REQUIRED')
    context=Runtime(args.root,args.owner_permit_sha256,credential)
    # Keep the watchdog parent alive throughout the bounded rewrite segment.
    # Stop before pause B. Never carry automatic execution over a PROCEED pause.
    if args.execute_rewrite_phase:
        require(args.execute_step is None,'EXECUTION_MODE_CONFLICT')
        try:
            for step in range(6,11):Executor(context).run(step)
        finally:
            if (context.root/'ruleset-pair.json').exists():context.restore()
        print(json.dumps({'verdict':'PAUSED','pause':'rewrite-push','nextStep':11}));return
    print(json.dumps(Executor(context).run(args.execute_step),sort_keys=True))


if __name__=='__main__':
    try:main()
    except Refusal as error:
        print(json.dumps({'verdict':'BLOCKED','code':str(error),'executionAuthorized':False}));raise SystemExit(2)

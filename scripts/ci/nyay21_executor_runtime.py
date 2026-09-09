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
import contextlib
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from email.utils import parsedate_to_datetime

sys.dont_write_bytecode=True
import nyay21_history_purge as gate
from nyay21_executor_adapters import (
    Custody, Executor, Refusal, digest, immutable_json, plan, private_root,
    require, restore, restored, restoration_state, ruleset_pair, write_rebinding,
)

REPO_URL='https://github.com/'+gate.REPOSITORY+'.git'
PROTECTED=Path('/Users/rajeevbarnwal/Desktop/Codes/NyayOne')
PERMISSIONS={'contents':'write','workflows':'write','metadata':'read',
             'administration':'write','actions':'read'}


def scope_policy():
    return {'permissions':dict(PERMISSIONS),'repository':gate.REPOSITORY,
            'restorationWorkflow':'reviewed-ruleset-restoration/v1',
            'signatureDomain':'nyay21-step8-scope-v1','maxReceiptAgeSeconds':120}


class Step8Scope:
    """Independent signed JIT read-back, not executor-asserted permissions.

    One challenge admits one attempted live push. The same authenticated receipt
    may be checked before/after dry-run, but cannot be consumed twice. No signer
    private keys or Jira credentials are managed by this class.
    """
    def __init__(self,root,permit,seal,identity,now):
        self.root=private_root(root);self.permit=permit;self.seal=seal
        self.identity=identity;self.now=now;self.pending=None;self.accepted=None
        require(permit.get('scopePolicy')==scope_policy() and permit.get('sourceHead')==seal['sourceHead'],
                'SCOPE_POLICY_BINDING_MISMATCH')

    def challenge(self):
        now=self.now()
        require(type(now) is int and self.seal['capturedAt']<=now<self.seal['expiresAt'],'SEAL_EXPIRED')
        if self.pending is None:
            self.pending={'nonce':secrets.token_hex(32),'executionId':self.identity['executionId'],
                'sealSha256':digest(self.seal),'sourceHead':self.seal['sourceHead'],
                'scopePolicySha256':digest(scope_policy()),'issuedAt':now}
            immutable_json(self.root,'scope-challenge-'+self.pending['nonce']+'.json',self.pending)
            Custody(self.root).append('SCOPE_CHALLENGE_CREATED',{'digest':digest(self.pending)})
        return self.pending

    def verify(self,envelope):
        try:return self._verify(envelope)
        except Refusal:raise
        except (KeyError,TypeError,ValueError,AttributeError,OSError,UnicodeError,subprocess.TimeoutExpired):
            raise Refusal('SCOPE_RECEIPT_INVALID') from None

    def _verify(self,envelope):
        challenge=self.challenge();now=self.now();nonce=challenge['nonce']
        require(not (self.root/('scope-used-'+nonce+'.json')).exists(),'SCOPE_CHALLENGE_CONSUMED')
        require(isinstance(envelope,dict) and set(envelope)=={'payload','signature'},'SCOPE_RECEIPT_INVALID')
        row=envelope['payload'];signature=envelope['signature']
        fields={'schemaVersion','authority','repository','sealSha256','sourceHead','executionId',
                'challengeNonce','challengeSha256','scopePolicySha256','credentialSha256','permissions',
                'restorationWorkflow','readAt','expiresAt','tokenExpiresAt','exitCode','signer','accountId','commentId'}
        require(isinstance(row,dict) and set(row)==fields and row['schemaVersion']=='nyay21-step8-scope/v1'
                and row['authority']=='step8-scope','SCOPE_RECEIPT_INVALID')
        require(row['repository']==gate.REPOSITORY and row['sealSha256']==digest(self.seal)
                and row['sourceHead']==self.seal['sourceHead'] and row['executionId']==self.identity['executionId']
                and row['challengeNonce']==nonce and row['challengeSha256']==digest(challenge)
                and row['scopePolicySha256']==digest(scope_policy())
                and row['credentialSha256']==self.permit['credentialSha256']
                and row['permissions']==PERMISSIONS and row['restorationWorkflow']=='reviewed-ruleset-restoration/v1',
                'SCOPE_RECEIPT_BINDING_MISMATCH')
        require(all(type(row[k]) is int for k in ['readAt','expiresAt','tokenExpiresAt','exitCode'])
                and row['exitCode']==0 and challenge['issuedAt']<=row['readAt']<=now<row['expiresAt']
                and 0<row['expiresAt']-row['readAt']<=120
                and 600<=row['tokenExpiresAt']-now<=172800,'SCOPE_RECEIPT_STALE_OR_INVALID')
        require(row['signer'] in {'owner','claude'} and isinstance(row['commentId'],str)
                and re.fullmatch(r'[1-9][0-9]*',row['commentId']) is not None,'SCOPE_SIGNER_INVALID')
        signer=self.permit.get('registrySigners',{}).get(row['signer'])
        require(isinstance(signer,dict) and signer.get('accountId')==row['accountId']
                and isinstance(signer.get('publicKey'),str)
                and re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}',signer['publicKey']) is not None,
                'SCOPE_SIGNER_INVALID')
        require(isinstance(signature,str) and len(signature)<=8192,'SCOPE_SIGNATURE_INVALID')
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            allowed=Path(tmp)/'allowed';sig=Path(tmp)/'receipt.sig'
            allowed.write_text('scope-reader '+signer['publicKey']+'\n');sig.write_text(signature)
            result=subprocess.run(['ssh-keygen','-Y','verify','-f',str(allowed),'-I','scope-reader',
                '-n','nyay21-step8-scope-v1','-s',str(sig)],
                input=json.dumps(row,sort_keys=True,separators=(',',':')).encode(),capture_output=True,timeout=10)
        require(result.returncode==0,'SCOPE_SIGNATURE_INVALID')
        finished=self.now()
        require(row['readAt']<=finished<min(row['expiresAt'],self.seal['expiresAt']),
                'SCOPE_RECEIPT_STALE_OR_INVALID')
        if self.accepted is not None:require(self.accepted==envelope,'SCOPE_RECEIPT_CHANGED')
        self.accepted=envelope
        return row

    def consume(self):
        require(self.accepted is not None,'SCOPE_RECEIPT_REQUIRED')
        row=self.verify(self.accepted)
        immutable_json(self.root,'scope-used-'+self.pending['nonce']+'.json',{
            'receiptSha256':digest(row),'executionId':self.identity['executionId'],'serverTimestamp':self.now()})
        Custody(self.root).append('SCOPE_CHALLENGE_CONSUMED',{'digest':digest(row)})


def validate_credential(credential):
    """Reject controls before either REST or Git header construction; never echo."""
    require(isinstance(credential,str) and bool(credential) and
            not any(unicodedata.category(char).startswith('C') or char in '\u2028\u2029'
                    for char in credential),'EXECUTION_CREDENTIAL_REQUIRED')
    return credential


def configured_protected_roots():
    """Mandatory portable guard, additive to the original Mac and code checkout.

    Configuration is not authority: Runtime also requires its digest in the
    externally bound owner permit. No git imports or writes occur in these roots.
    """
    raw=os.environ.get('NYAY21_PROTECTED_ROOT')
    require(isinstance(raw,str) and bool(raw),'PROTECTED_ROOT_REQUIRED')
    root=Path(raw)
    require(root.is_absolute() and root.is_dir() and not root.is_symlink()
            and root.resolve()==root and (root/'.git').exists(), 'PROTECTED_ROOT_INVALID')
    environment={k:v for k,v in os.environ.items() if k in {'PATH','LANG','SYSTEMROOT'}}
    environment.update(GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null')
    try:
        result=subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'],
                              env=environment,capture_output=True,timeout=10)
        require(result.returncode==0 and Path(result.stdout.decode().strip()).resolve()==root,'PROTECTED_ROOT_INVALID')
    except (OSError,UnicodeError,subprocess.TimeoutExpired):raise Refusal('PROTECTED_ROOT_INVALID') from None
    return (root, PROTECTED, Path(__file__).resolve().parents[2])


def validate_protected_binding(permit,root):
    require(isinstance(permit,dict) and permit.get('protectedRootSha256')==digest(str(root)),
            'PROTECTED_ROOT_BINDING_MISMATCH')


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
        self.credential=validate_credential(credential)

    def request(self,method,path,payload=None,*,_clock=False):
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
                require(len(raw)<=16*1024*1024,'API_RESPONSE_TOO_LARGE')
                value=json.loads(raw)
                if _clock:
                    require(method=='GET' and path=='' and value.get('private') is True
                            and value.get('full_name')==gate.REPOSITORY,'SERVER_TIME_SCOPE_INVALID')
                    date=parsedate_to_datetime(response.headers.get('Date',''))
                    request_id=response.headers.get('X-GitHub-Request-Id','')
                    require(date.tzinfo is not None and bool(request_id),'SERVER_TIME_HEADER_INVALID')
                    return {'timestamp':int(date.timestamp()),'requestId':request_id}
                return value
        except (OSError,ValueError):raise Refusal('API_READ_OR_WRITE_FAILED') from None

    def repository(self):return self.request('GET','')
    def get(self):return self.request('GET','/rulesets/'+str(gate.RULESET_ID))
    def put(self,payload):return self.request('PUT','/rulesets/'+str(gate.RULESET_ID),payload)
    def server_time(self):return self.request('GET','',_clock=True)


class AuthenticatedClock:
    """Authenticated fixed-host Date read for each receipt; no caller clock API.

    Local wall time anchors the initial cross-check only. All subsequent checks
    use elapsed monotonic time, including request latency (bounded to five s).
    TLS/server time is transport evidence, not a signature by GitHub on receipts.
    """
    def __init__(self,api):
        self.api=api;self.wall=time.time();self.mono=time.monotonic();self.last=None

    def __call__(self):
        start=time.monotonic()
        try:row=self.api.server_time()
        except Exception:raise Refusal('SERVER_TIME_UNAVAILABLE') from None
        end=time.monotonic()
        require(isinstance(row,dict) and type(row.get('timestamp')) is int
                and row['timestamp']>=0 and isinstance(row.get('requestId'),str)
                and bool(row['requestId']),'SERVER_TIME_INVALID')
        expected=self.wall+(end-self.mono)
        require(0<=end-start<=5 and end>=self.mono and abs(row['timestamp']-expected)<=5,
                'SERVER_TIME_DRIFT')
        require(self.last is None or row['timestamp']>=self.last['timestamp'],'SERVER_TIME_ROLLBACK')
        self.last={'timestamp':row['timestamp'],'requestIdSha256':digest(row['requestId']),
                   'monotonicElapsedMs':int((end-self.mono)*1000)}
        return row['timestamp']


class ConsumptionRegistry:
    """Owner/Claude signed snapshot import; no Jira token or network client.

    The externally bound GO permit pins signer public keys, account identities
    and the chain anchor. SSH signatures use a dedicated domain namespace.
    A signed snapshot attests authenticated Jira read-back; it is not a Jira
    server signature. Private signing keys must not reside on the executor.
    """
    def __init__(self,root,permit,seal,now):
        self.root=private_root(root);self.permit=permit;self.seal=seal;self.now=now

    def verify(self,envelope):
        try:return self._verify(envelope)
        except Refusal:raise
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OSError):
            raise Refusal('REGISTRY_FORMAT_INVALID') from None

    def _verify(self,envelope):
        require(isinstance(envelope,dict) and set(envelope)=={'payload','signature'},'REGISTRY_FORMAT_INVALID')
        row=envelope['payload'];signature=envelope['signature']
        fields={'schemaVersion','issue','repository','sealSha256','signer','accountId','commentId',
                'serverTimestamp','chainHead','entries'}
        require(isinstance(row,dict) and set(row)==fields and row['schemaVersion']=='nyay21-registry-snapshot/v1'
                and row['issue']=='NYAY-21' and row['repository']==gate.REPOSITORY
                and row['sealSha256']==digest(self.seal),'REGISTRY_SCOPE_INVALID')
        require(row['signer'] in {'owner','claude'} and isinstance(signature,str) and len(signature)<=8192,
                'REGISTRY_SIGNATURE_INVALID')
        signers=self.permit.get('registrySigners',{})
        require(isinstance(signers,dict) and row['signer'] in signers,'REGISTRY_SIGNER_UNBOUND')
        signer=signers[row['signer']]
        require(isinstance(signer,dict) and set(signer)=={'publicKey','accountId'}
                and signer['accountId']==row['accountId'] and isinstance(row['accountId'],str)
                and bool(row['accountId']),'REGISTRY_IDENTITY_MISMATCH')
        key=signer['publicKey']
        require(isinstance(key,str) and re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}',key) is not None,
                'REGISTRY_KEY_INVALID')
        # Temporary verification files contain only public key, signature and
        # aggregate snapshot; subprocess never receives an untrusted executable.
        with tempfile.TemporaryDirectory(prefix='registry-verify-',dir=self.root) as tmp:
            directory=Path(tmp);allowed=directory/'allowed';sig=directory/'signature'
            allowed.write_text(row['signer']+' '+key+'\n');sig.write_text(signature)
            try:
                result=subprocess.run(['ssh-keygen','-Y','verify','-f',str(allowed),'-I',row['signer'],
                    '-n','nyay21-registry-v1','-s',str(sig)],
                    input=json.dumps(row,sort_keys=True,separators=(',',':')).encode(),
                    capture_output=True,timeout=10)
            except (OSError,subprocess.TimeoutExpired):raise Refusal('REGISTRY_VERIFIER_UNAVAILABLE') from None
            require(type(result.returncode) is int and result.returncode==0,'REGISTRY_SIGNATURE_INVALID')
        now=self.now()
        require(gate._execution_seal_valid(self.seal) and self.seal['capturedAt']<=now<self.seal['expiresAt'],'SEAL_EXPIRED')
        require(type(row['serverTimestamp']) is int and self.seal['capturedAt']<=row['serverTimestamp']<=now
                and now-row['serverTimestamp']<=2700,'REGISTRY_SNAPSHOT_STALE')
        require(isinstance(row['commentId'],str) and re.fullmatch(r'[1-9][0-9]*',row['commentId']) is not None,
                'REGISTRY_COMMENT_INVALID')
        anchor=self.permit.get('registryAnchor')
        require(isinstance(anchor,dict) and set(anchor)=={'index','digest'} and type(anchor['index']) is int
                and anchor['index']>=-1 and gate._is_hex(anchor['digest'],64),'REGISTRY_ANCHOR_INVALID')
        entries=row['entries'];require(isinstance(entries,list) and len(entries)<=10000,'REGISTRY_CHAIN_INVALID')
        previous=anchor['digest'];index=anchor['index']+1;seen=set();stamp=self.seal['capturedAt']
        for entry in entries:
            require(isinstance(entry,dict) and set(entry)=={'index','previous','sealSha256','approvalId','action',
                    'event','commentId','serverTimestamp','effectReceiptSha256'} and type(entry['index']) is int and entry['index']==index
                    and entry['previous']==previous and entry['sealSha256']==digest(self.seal)
                    and entry['action'] in {'rewrite','force-update'} and entry['event']=='consumed'
                    and isinstance(entry['approvalId'],str)
                    and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',entry['approvalId']) is not None
                    and entry['approvalId'] not in seen and type(entry['serverTimestamp']) is int
                    and gate._is_hex(entry['effectReceiptSha256'],64)
                    and stamp<=entry['serverTimestamp']<=row['serverTimestamp']
                    and isinstance(entry['commentId'],str) and re.fullmatch(r'[1-9][0-9]*',entry['commentId']) is not None,
                    'REGISTRY_CHAIN_INVALID')
            previous=digest(entry);index+=1;stamp=entry['serverTimestamp'];seen.add(entry['approvalId'])
        require(row['chainHead']==previous,'REGISTRY_CHAIN_HEAD_MISMATCH')
        return row

    def readback(self):
        row=self.verify(read_json(self.root/'registry-snapshot.json'))
        # Every accepted revision is immutable. A later snapshot may only extend
        # it, never truncate or replace previously consumed entries.
        for path in self.root.glob('registry-accepted-*.json'):
            old=read_json(path)
            require(old['entries']==row['entries'][:len(old['entries'])]
                    and old['serverTimestamp']<=row['serverTimestamp'],'REGISTRY_ROLLBACK')
        name='registry-accepted-'+digest(row)+'.json'
        if not (self.root/name).exists():immutable_json(self.root,name,row)
        return row


def execution_identity(row):
    require(isinstance(row,dict) and gate._is_hex(row.get('sealedPlanSha256'),64)
            and isinstance(row.get('approvalId'),str) and re.fullmatch(
                r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',row['approvalId']) is not None
            and gate._is_hex(row.get('nonce'),64),'EXECUTION_IDENTITY_INVALID')
    return digest({key:row[key] for key in ['sealedPlanSha256','approvalId','nonce']})


def validate_execution_identity(row,root,seal_sha,approval_id):
    require(isinstance(row,dict) and set(row)=={'sealedPlanSha256','approvalId','nonce','executionId','custodyRootSha256'}
            and row['executionId']==execution_identity(row) and row['sealedPlanSha256']==seal_sha
            and row['approvalId']==approval_id and row['custodyRootSha256']==digest(str(root)),
            'CUSTODY_IDENTITY_MISMATCH')
    return row


def register_execution(registrations,row):
    """Pure publisher-side uniqueness contract; does not post or sign anything."""
    require(isinstance(registrations,list) and len(registrations)<=10000,'REGISTRY_REGISTRATION_INVALID')
    require(isinstance(row,dict) and set(row)=={'sealedPlanSha256','approvalId','nonce','executionId','custodyRootSha256'}
            and row['executionId']==execution_identity(row) and gate._is_hex(row['custodyRootSha256'],64),
            'REGISTRY_REGISTRATION_INVALID')
    for previous in registrations:
        require(isinstance(previous,dict),'REGISTRY_REGISTRATION_INVALID')
        if previous.get('approvalId')==row['approvalId']:
            require(previous==row,'APPROVAL_EXECUTION_ALREADY_REGISTERED')
            return list(registrations)
    return [*registrations,dict(row)]


def registry_namespace(purpose):
    require(purpose in {'execution','continuation'},'REGISTRY_AUTHORITY_INVALID')
    return 'nyay21-registry-'+purpose+'-v2'


class ExecutionRegistry(ConsumptionRegistry):
    """v2 authority path. v1 remains a historical parser, never execution input.

    Signers serialize registration/consumption in the owner-operated registry.
    Full signed UUID history and a pinned custody identity prevent cross-root
    reuse. Continuation signatures have a different SSH domain and cannot pass
    execution verification, even if their JSON fields are copied or relabeled.
    """
    def verify(self,envelope,*,purpose='execution'):
        try:return self._verify_v2(envelope,purpose)
        except Refusal:raise
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OSError):
            raise Refusal('REGISTRY_FORMAT_INVALID') from None

    def _verify_v2(self,envelope,purpose):
        namespace=registry_namespace(purpose)
        require(isinstance(envelope,dict) and set(envelope)=={'payload','signature'},'REGISTRY_FORMAT_INVALID')
        row=envelope['payload'];signature=envelope['signature']
        fields={'schemaVersion','issue','repository','sealSha256','signer','accountId','commentId','serverTimestamp',
                'expiresAt','chainHead','entries','registrations','authority','executionId'}
        if purpose=='continuation':fields|={'pushProofSha256','restorationProofSha256'}
        require(isinstance(row,dict) and set(row)==fields and row['schemaVersion']=='nyay21-registry-snapshot/v2'
                and row['authority']==purpose and row['issue']=='NYAY-21' and row['repository']==gate.REPOSITORY
                and row['sealSha256']==digest(self.seal),'REGISTRY_AUTHORITY_INVALID')
        identity=self.permit.get('executionIdentity')
        validate_execution_identity(identity,self.root,digest(self.seal),identity.get('approvalId') if isinstance(identity,dict) else None)
        require(row['executionId']==identity['executionId'],'CUSTODY_IDENTITY_MISMATCH')
        signers=self.permit.get('registrySigners',{})
        require(row['signer'] in {'owner','claude'} and isinstance(signers,dict)
                and row['signer'] in signers and isinstance(signature,str) and len(signature)<=8192,'REGISTRY_SIGNER_UNBOUND')
        signer=signers[row['signer']]
        require(isinstance(signer,dict) and set(signer)=={'publicKey','accountId'} and signer['accountId']==row['accountId']
                and isinstance(row['accountId'],str) and bool(row['accountId']),'REGISTRY_IDENTITY_MISMATCH')
        key=signer['publicKey']
        require(isinstance(key,str) and re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}',key) is not None,'REGISTRY_KEY_INVALID')
        with tempfile.TemporaryDirectory(prefix='registry-v2-verify-',dir=self.root) as tmp:
            directory=Path(tmp);allowed=directory/'allowed';sig=directory/'signature'
            allowed.write_text(row['signer']+' '+key+'\n');sig.write_text(signature)
            try:
                result=subprocess.run(['ssh-keygen','-Y','verify','-f',str(allowed),'-I',row['signer'],'-n',namespace,'-s',str(sig)],
                    input=json.dumps(row,sort_keys=True,separators=(',',':')).encode(),capture_output=True,timeout=10)
            except (OSError,subprocess.TimeoutExpired):raise Refusal('REGISTRY_VERIFIER_UNAVAILABLE') from None
            require(type(result.returncode) is int and result.returncode==0,'REGISTRY_SIGNATURE_INVALID')
        now=self.now()
        require(type(row['serverTimestamp']) is int and type(row['expiresAt']) is int
                and self.seal['capturedAt']<=row['serverTimestamp']<=now<row['expiresAt']
                and 0<row['expiresAt']-row['serverTimestamp']<=2700,'REGISTRY_SNAPSHOT_STALE')
        if purpose=='execution':require(self.seal['capturedAt']<=now<self.seal['expiresAt'],'SEAL_EXPIRED')
        else:
            proof=read_json(self.root/'push-verified.json');restoration=read_json(self.root/'restoration-proof.json')
            require(row['pushProofSha256']==digest(proof) and row['restorationProofSha256']==digest(restoration)
                    and proof.get('executionId')==identity['executionId'] and proof.get('restorationProofSha256')==digest(restoration)
                    and restoration.get('restored') is True,'CONTINUATION_EFFECT_BINDING_MISMATCH')
        require(isinstance(row['commentId'],str) and re.fullmatch(r'[1-9][0-9]*',row['commentId']) is not None,'REGISTRY_COMMENT_INVALID')
        # No caller-selected truncated anchor can hide a previously used UUID.
        require(self.permit.get('registryAnchor')=={'index':-1,'digest':'0'*64},'REGISTRY_ANCHOR_INVALID')
        registrations=row['registrations'];require(isinstance(registrations,list),'REGISTRY_REGISTRATION_INVALID')
        accepted=[]
        for registration in registrations:
            updated=register_execution(accepted,registration)
            require(len(updated)==len(accepted)+1,'REGISTRY_DUPLICATE_REGISTRATION');accepted=updated
        require(identity in accepted,'EXECUTION_IDENTITY_UNREGISTERED')
        by_uuid={r['approvalId']:r for r in accepted}
        entries=row['entries'];require(isinstance(entries,list) and len(entries)<=10000,'REGISTRY_CHAIN_INVALID')
        previous='0'*64;seen=set();stamp=0
        for index,entry in enumerate(entries):
            require(isinstance(entry,dict) and set(entry)=={'index','previous','sealSha256','approvalId','action','event',
                    'commentId','serverTimestamp','effectReceiptSha256','executionId'} and type(entry['index']) is int
                    and entry['index']==index and entry['previous']==previous and entry['event']=='consumed'
                    and entry['action'] in {'rewrite','force-update'} and entry['approvalId'] in by_uuid
                    and entry['approvalId'] not in seen and entry['executionId']==by_uuid[entry['approvalId']]['executionId']
                    and entry['sealSha256']==by_uuid[entry['approvalId']]['sealedPlanSha256']
                    and gate._is_hex(entry['effectReceiptSha256'],64) and type(entry['serverTimestamp']) is int
                    and stamp<=entry['serverTimestamp']<=row['serverTimestamp'] and isinstance(entry['commentId'],str)
                    and re.fullmatch(r'[1-9][0-9]*',entry['commentId']) is not None,'REGISTRY_CHAIN_INVALID')
            previous=digest(entry);stamp=entry['serverTimestamp'];seen.add(entry['approvalId'])
        require(row['chainHead']==previous,'REGISTRY_CHAIN_HEAD_MISMATCH')
        return row

    def readback(self,*,purpose='execution'):
        filename='registry-snapshot.json' if purpose=='execution' else 'continuation-snapshot.json'
        envelope=read_json(self.root/filename)
        row=self.verify(envelope,purpose=purpose)
        for path in self.root.glob('registry-v2-accepted-*.json'):
            old=read_json(path)
            require(old['entries']==row['entries'][:len(old['entries'])]
                    and old['registrations']==row['registrations'][:len(old['registrations'])]
                    and old['serverTimestamp']<=row['serverTimestamp'],'REGISTRY_ROLLBACK')
        name='registry-v2-accepted-'+digest(row)+'.json'
        if not (self.root/name).exists():immutable_json(self.root,name,row)
        name='registry-v2-envelope-'+digest(row)+'.json'
        if not (self.root/name).exists():immutable_json(self.root,name,envelope)
        return row


class GitIO:
    """Only a bare mirror below a private scratch root; protected checkout excluded."""
    def __init__(self,root,credential):
        validate_credential(credential)
        protected_roots=configured_protected_roots()
        self.root=private_root(root);self.mirror=self.root/'mirror.git'
        require(self.mirror.is_dir() and not self.mirror.is_symlink() and self.mirror.resolve()==self.mirror
                and not any(self.root.is_relative_to(p) or p.is_relative_to(self.root)
                            for p in protected_roots),'PROTECTED_OR_NONISOLATED_CHECKOUT')
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
    def __init__(self,root,owner_permit_sha256,credential):
        self.root=private_root(root);self.log=Custody(self.root)
        self.permit=read_json(self.root/'execution-permit.json')
        require(gate._is_hex(owner_permit_sha256,64) and digest(self.permit)==owner_permit_sha256,'OWNER_PERMIT_DIGEST_MISMATCH')
        require(self.permit.get('decision')=='EXECUTION-GO' and self.permit.get('owner')==gate.OWNER_APPROVER
                and self.permit.get('technicalApprover')==gate.SECURITY_PRIVACY_APPROVER
                and self.permit.get('repository')==gate.REPOSITORY,'FRESH_GO_REQUIRED')
        validate_credential(credential)
        validate_protected_binding(self.permit,configured_protected_roots()[0])
        require(self.permit.get('credentialSha256')==hashlib.sha256(credential.encode()).hexdigest(),'SCOPE_CREDENTIAL_BINDING_MISMATCH')
        self.seal=read_json(self.root/'seal.json');self.approvals=read_json(self.root/'approvals.json')
        require(gate._execution_seal_valid(self.seal) and digest(self.seal)==self.permit.get('sealSha256')
                and digest(self.approvals)==self.permit.get('approvalsSha256'),'PERMIT_INPUT_BINDING_MISMATCH')
        require(self.permit.get('scopePolicy')==scope_policy()
                and self.permit.get('sourceHead')==self.seal['sourceHead'],'SCOPE_POLICY_BINDING_MISMATCH')
        self.identity=validate_execution_identity(self.permit.get('executionIdentity'),self.root,digest(self.seal),self.approvals['rewrite']['id'])
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                 [Path(__file__),Path(__file__).with_name('nyay21_executor_adapters.py'),Path(gate.__file__)]}
        require(sources==self.permit.get('reviewedCodeSha256'),'REVIEWED_EXECUTOR_CHANGED')
        self.api=GitHub(credential);self.git=GitIO(self.root,credential)
        self.clock=AuthenticatedClock(self.api)
        self.registry=ExecutionRegistry(self.root,self.permit,self.seal,self.now)
        self.step8_scope=Step8Scope(self.root,self.permit,self.seal,self.identity,self.now)
        self.watchdog=None;self.stop_heartbeat=threading.Event()

    def now(self):return int(self.clock())

    def emit(self,event):
        self.log.append(event,{'sealSha256':digest(self.seal)})
        if event in {'RESTORATION_GET_FAILED','RULESET_CONCURRENT_CHANGE'}:
            self.log.append('OWNER_ESCALATION_REQUIRED',{'sealSha256':digest(self.seal)})

    def require_current_permit(self,step):
        require(type(step) is int and step in range(6,16),'STEP_INVALID')
        if step==9:return  # Safety restoration never depends on window freshness.
        if step>=10:
            self.restoration_proof()
            self.registry.readback(purpose='continuation')
            return
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
            snapshot=self.registry.readback()
            self.validate_rewrite_claim(snapshot)

    def prepare_rewrite_claim(self):
        """GO-time staging, before watchdog arming. No rewrite/ruleset/push effect.

        Validate a fresh UNCONSUMED signed registration, seal the custody-bound
        intent, then let the independent publisher atomically consume the UUID
        against this intent before the uninterrupted steps 6–10 segment starts.
        """
        self.require_current_permit(6)
        receipt=read_json(self.root/'step-5.json')
        require(digest(receipt)==self.permit.get('backupDrillReceiptSha256'),'BACKUP_DRILL_PAUSE_REQUIRED')
        snapshot=self.registry.readback();approval=self.approvals['rewrite']
        require(not any(e['approvalId']==approval['id'] for e in snapshot['entries']),'REWRITE_APPROVAL_ALREADY_CONSUMED')
        path=self.root/'custody-identity.json'
        if path.exists():require(read_json(path)==self.identity,'CUSTODY_IDENTITY_MISMATCH')
        else:immutable_json(self.root,path.name,self.identity)
        value={'executionId':self.identity['executionId'],'custodyIdentitySha256':digest(self.identity),
               'unconsumedSnapshotSha256':digest(snapshot),'sealSha256':digest(self.seal),'approvalId':approval['id'],
               'backupDrillReceiptSha256':self.permit['backupDrillReceiptSha256'],'serverTimestamp':self.now()}
        path=self.root/'rewrite-intent.json'
        if path.exists():
            old=read_json(path)
            require(all(old.get(k)==value[k] for k in value if k!='serverTimestamp'),'REWRITE_INTENT_CHANGED')
            value=old
        else:immutable_json(self.root,path.name,value)
        return {'authority':'none','rewriteIntentSha256':digest(value),'next':'Independent publisher consumes R against this intent; import signed snapshot.'}

    def validate_rewrite_claim(self,snapshot):
        path=self.root/'rewrite-intent.json'
        require(path.exists(),'REWRITE_APPROVAL_ALREADY_CONSUMED' if any(
            e['approvalId']==self.approvals['rewrite']['id'] for e in snapshot['entries']) else 'REWRITE_CLAIM_REQUIRED')
        intent=read_json(path)
        require(intent.get('executionId')==self.identity['executionId'] and intent.get('custodyIdentitySha256')==digest(self.identity)
                and read_json(self.root/'custody-identity.json')==self.identity,'CUSTODY_IDENTITY_MISMATCH')
        original=self.registry.verify(read_json(self.root/('registry-v2-envelope-'+intent['unconsumedSnapshotSha256']+'.json')))
        require(digest(original)==intent['unconsumedSnapshotSha256'] and not any(
            e['approvalId']==self.approvals['rewrite']['id'] for e in original['entries']),'REWRITE_UNCONSUMED_PROOF_REQUIRED')
        entries=[e for e in snapshot['entries'] if e['approvalId']==self.approvals['rewrite']['id']]
        require(len(entries)==1 and entries[0]['action']=='rewrite' and entries[0]['effectReceiptSha256']==digest(intent),
                'SIGNED_CONSUMPTION_RECEIPT_REQUIRED')
        require(not (self.root/('consumed-'+self.approvals['rewrite']['id']+'.json')).exists(),
                'REWRITE_APPROVAL_ALREADY_CONSUMED')
        return intent

    def record_step(self,step,result):
        value={'step':step,'sealSha256':digest(self.seal),'completed':True,'result':result,
               'serverTimestamp':self.now(),'timeReceipt':self.clock.last}
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
        environment={k:v for k,v in os.environ.items() if k in {'PATH','LANG','TMPDIR','NYAY21_PROTECTED_ROOT'}}
        environment.update(PYTHONDONTWRITEBYTECODE='1',NYAY21_EXECUTION_CREDENTIAL=self.api.credential)
        self.watchdog=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--watchdog',str(self.root),
            '--pair-sha256',digest(pair),'--parent-pid',str(os.getpid())],env=environment,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        deadline=time.monotonic()+10
        while not (self.root/'watchdog-armed.json').exists():
            require(self.watchdog.poll() is None and time.monotonic()<deadline,'WATCHDOG_ARM_FAILED');time.sleep(.05)

    def verify_watchdog(self,pair,scope_receipt=None):
        row=read_json(self.root/'watchdog-armed.json')
        require(row.get('pairSha256')==digest(pair) and type(row.get('pid')) is int,'WATCHDOG_BINDING_MISMATCH')
        try:os.kill(row['pid'],0)
        except OSError:raise Refusal('WATCHDOG_NOT_LIVE') from None
        now=self.now()
        seal=getattr(self,'seal',{})
        require(type(row.get('armedAt')) is int and type(seal.get('capturedAt')) is int
                and type(seal.get('expiresAt')) is int and seal['capturedAt']<=row['armedAt']<=now<seal['expiresAt'],
                'WATCHDOG_STALE')
        if scope_receipt is not None:
            require(self.step8_scope.verify(self.step8_scope.accepted)==scope_receipt,'SCOPE_RECEIPT_CHANGED')
        return row

    def verify_filter_version(self,expected):
        require(self.git.run(['git','filter-repo','--version']).decode().strip()==expected,'FILTER_REPO_VERSION_MISMATCH')

    def consume(self,kind):
        row=self.approvals[kind]
        if kind=='rewrite':
            result=gate.validate_execution_approvals(self.approvals,seal=self.seal,current=self.seal,now=self.now())
            require(result['verdict']=='PASS','APPROVAL_NOT_CURRENT')
            require(read_json(self.root/'custody-identity.json')==self.identity,'CUSTODY_IDENTITY_MISMATCH')
        try:snapshot=self.registry.readback(purpose='execution' if kind=='rewrite' else 'continuation')
        except Refusal as error:
            if kind!='forceUpdate' or str(error)!='INPUT_FILE_INVALID':raise
            proof=read_json(self.root/'push-verified.json')
            name='consumption-request-'+row['id']+'.json'
            if not (self.root/name).exists():immutable_json(self.root,name,{'approvalId':row['id'],
                'action':row['action'],'sealSha256':digest(self.seal),'pushProofSha256':digest(proof),
                'authority':'continuation','instruction':'Import an independently signed continuation snapshot.'})
            self.emit('REGISTRY_CONSUMPTION_PAUSE')
            raise Refusal('SIGNED_CONSUMPTION_RECEIPT_REQUIRED') from None
        entries=[e for e in snapshot['entries'] if e['approvalId']==row['id'] and e['action']==row['action']]
        if kind=='rewrite' and not (self.root/'rewrite-intent.json').exists():
            require(not entries,'REWRITE_APPROVAL_ALREADY_CONSUMED')
            immutable_json(self.root,'rewrite-intent.json',{'executionId':self.identity['executionId'],
                'custodyIdentitySha256':digest(self.identity),'unconsumedSnapshotSha256':digest(snapshot),
                'sealSha256':digest(self.seal),'approvalId':row['id'],
                'backupDrillReceiptSha256':self.permit['backupDrillReceiptSha256'],'serverTimestamp':self.now()})
        if not entries:
            value={'approvalId':row['id'],'action':row['action'],'sealSha256':digest(self.seal),
                   'priorChainHead':snapshot['chainHead'],'serverTimestamp':self.now(),
                   'instruction':'Owner/Claude must post consumption to NYAY-21 and import a signed snapshot.'}
            name='consumption-request-'+row['id']+'.json'
            if not (self.root/name).exists():immutable_json(self.root,name,value)
            self.emit('REGISTRY_CONSUMPTION_PAUSE')
            raise Refusal('SIGNED_CONSUMPTION_RECEIPT_REQUIRED')
        if kind=='forceUpdate':
            proof=read_json(self.root/'push-verified.json')
            require(entries[0]['serverTimestamp']>=proof['serverTimestamp']
                    and entries[0]['effectReceiptSha256']==digest(proof),'FORCE_CONSUMED_BEFORE_PUSH_VERIFICATION')
        else:
            intent=read_json(self.root/'rewrite-intent.json')
            require(entries[0]['effectReceiptSha256']==digest(intent) and intent['executionId']==self.identity['executionId']
                    and intent['custodyIdentitySha256']==digest(self.identity),
                    'REWRITE_CONSUMPTION_DRILL_MISMATCH')
        name='consumed-'+row['id']+'.json'
        value={'id':row['id'],'sealSha256':digest(self.seal),'action':row['action'],
               'registryEntrySha256':digest(entries[0]),'commentId':entries[0]['commentId']}
        if (self.root/name).exists():
            require(kind!='rewrite','REWRITE_APPROVAL_ALREADY_CONSUMED')
            previous=read_json(self.root/name)
            require(all(previous.get(k)==v for k,v in value.items()),'CONSUMPTION_RECEIPT_CHANGED')
        else:
            value.update(serverTimestamp=self.now(),timeReceipt=self.clock.last)
            immutable_json(self.root,name,value)

    def consume_rewrite_approval(self):self.consume('rewrite')
    def consume_force_approval(self):self.consume('forceUpdate')

    def command(self,argv):
        if argv[:3]==['git','push','--atomic'] and '--dry-run' not in argv:
            self.step8_scope.consume()
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
        snapshot=self.registry.readback()
        force_id=self.approvals['forceUpdate']['id']
        force_identity={**self.identity,'approvalId':force_id}
        force_identity['executionId']=execution_identity(force_identity)
        require(force_identity in snapshot['registrations'],'EXECUTION_IDENTITY_UNREGISTERED')
        require(not any(e['approvalId']==force_id for e in snapshot['entries']),'FORCE_APPROVAL_ALREADY_CONSUMED')
        rewrite=read_json(self.root/'rewrite-result.json')
        require(rewrite.get('targetsUnreachable') is True and self.git.local_refs()==rewrite['refs'],'REWRITE_OUTPUT_CHANGED')
        new={r['name']:r['oid'] for r in rewrite['refs']}
        rows=[{'ref':r['name'],'expectedOldOid':r['oid'],'newOid':new[r['name']]} for r in self.seal['refs']]
        scope_receipt=self.read_scope_at_push()
        # The independent signature was just verified against the GO-bound keys,
        # identity/head/policy and this one-use nonce. Pure planning still checks
        # the exact permission/expiry shape; its digest is not an authority source.
        scope={'repository':scope_receipt['repository'],'sourceHead':scope_receipt['sourceHead'],
            'sealSha256':scope_receipt['sealSha256'],'permissions':scope_receipt['permissions'],
            'readAt':scope_receipt['readAt'],'expiresAt':scope_receipt['tokenExpiresAt'],
            'exitCode':scope_receipt['exitCode'],'ownerDecisionCommentId':scope_receipt['commentId'],
            'receiptKind':'independent-scope-readback/v1','restorationWorkflow':scope_receipt['restorationWorkflow']}
        value=gate.prepare_execution_push(rows,seal=self.seal,current=self.seal,now=self.now(),approvals=self.approvals,
            scope_readback=scope,scope_receipt_sha256=digest(scope))
        require(value['verdict']=='PASS','PUSH_SCOPE_OR_APPROVAL_INVALID')
        self.verify_watchdog(read_json(self.root/'ruleset-pair.json'),scope_receipt)
        # filter-repo removes origin. Explicit URL overrides no inherited remote.
        return [REPO_URL if a=='origin' else a for a in value['dryRunArgv']]

    def read_scope_at_push(self):
        """Wait before relaxation for an independent signer, bounded by the seal.

        Heartbeat runs while the operator imports the challenge-bound envelope.
        The same <=120s receipt is reverified after dry-run; no old permit receipt
        is read or freshly timestamped as a substitute for authenticated evidence.
        """
        challenge=self.step8_scope.challenge()
        path=self.root/('scope-receipt-'+challenge['nonce']+'.json')
        while not path.exists():
            require(self.now()<self.seal['expiresAt'],'SEAL_EXPIRED')
            self.verify_watchdog(read_json(self.root/'ruleset-pair.json'))
            time.sleep(.25)
        return self.step8_scope.verify(read_json(path))

    def relax_ruleset(self):
        pair=read_json(self.root/'ruleset-pair.json');self.verify_watchdog(pair)
        restoration_state(self.api,[pair['before']],self.emit)
        self.api.put(pair['relaxation'])
        restoration_state(self.api,[{**pair['before'],**pair['relaxation']}],self.emit)

    def restore(self):
        proof=restore(self.api,read_json(self.root/'ruleset-pair.json'),self.emit)
        path=self.root/'restoration-proof.json'
        if not path.exists():
            proof.update(serverTimestamp=self.now(),timeReceipt=self.clock.last)
            immutable_json(self.root,path.name,proof)
        self.stop_heartbeat.set();return proof

    def restoration_proof(self):
        pair=read_json(self.root/'ruleset-pair.json')
        restoration_state(self.api,[pair['before']],self.emit)
        return read_json(self.root/'restoration-proof.json')

    def verify_pushed_refs(self):
        # Cross-service effects cannot be one distributed transaction. Publish
        # one success receipt only AFTER restoration and exact ref verification.
        # No clock/registry/approval check can delay the restoration attempt.
        if not (self.root/'restoration-proof.json').exists():self.restore()
        restoration=self.restoration_proof()
        expected=read_json(self.root/'rewrite-result.json')['refs']
        require(self.git.remote_refs()==expected,'POST_PUSH_REF_MISMATCH')
        require(self.api.repository().get('private') is True,'REPOSITORY_SCOPE_CHANGED')
        result={'remoteRefsMatch':True,'private':True,'head':next(r['oid'] for r in expected if r['name']=='refs/heads/main')}
        if not (self.root/'push-verified.json').exists():
            value={**result,'sealSha256':digest(self.seal),'executionId':self.identity['executionId'],
                   'restorationProofSha256':digest(restoration),'serverTimestamp':self.now(),'timeReceipt':self.clock.last}
            immutable_json(self.root,'push-verified.json',value)
            self.log.append('PUSH_VERIFIED',{'digest':digest(value),'sealSha256':digest(self.seal)})
        return result

    def verify_post_push(self):
        result=self.verify_pushed_refs()
        self.restoration_proof()
        return result

    def resume_rewrite_phase(self):
        """Resume verified completed effects only; ambiguous partial rewrite refuses.

        A consumed-F receipt is imported after push verification/restoration.
        Resume never repeats an already successful push or reuses an expired seal.
        """
        now=self.now()
        require(self.seal['capturedAt']<=now<self.seal['expiresAt'],'SEAL_EXPIRED')
        self.require_current_permit(8)
        rows=read_custody(self.root)
        require(bool(rows),'RESUME_CUSTODY_REQUIRED')
        completed={}
        for row in rows:
            if row['event']=='STEP_COMPLETED':
                values=row['values'];step=values.get('step')
                require(type(step) is int and step in range(6,11),'RESUME_STEP_INVALID')
                receipt=read_json(self.root/f'step-{step}.json')
                require(digest(receipt)==values.get('digest') and receipt.get('sealSha256')==digest(self.seal),
                        'RESUME_RECEIPT_MISMATCH')
                completed[step]=receipt
        require(set(completed)==set(range(6,6+len(completed))),'RESUME_STEP_GAP')
        rewrite_path=self.root/'rewrite-result.json'
        if rewrite_path.exists() and self.git.remote_refs()==read_json(rewrite_path)['refs']:
            require(6 in completed and 7 in completed,'RESUME_REWRITE_PROOF_REQUIRED')
            self.verify_pushed_refs();self.restore();self.consume_force_approval()
            if 8 not in completed:self.record_step(8,{'resumedVerifiedPush':True})
            for step in (9,10):
                if step not in completed:Executor(self).run(step)
            return {'verdict':'PAUSED','pause':'rewrite-push','nextStep':11}
        self.require_live_old_refs()
        if not completed:
            require(not (self.root/'ruleset-pair.json').exists(),'RESUME_PARTIAL_CAPTURE_REQUIRES_OWNER')
        if 6 in completed:self.verify_watchdog(read_json(self.root/'ruleset-pair.json'))
        if 7 in completed:
            require(self.git.local_refs()==read_json(rewrite_path)['refs'],'RESUME_REWRITE_OUTPUT_CHANGED')
        else:
            require(self.git.local_refs()==self.seal['refs'] and not (self.git.mirror/'filter-repo').exists(),
                    'RESUME_PARTIAL_REWRITE_REQUIRES_OWNER')
        try:
            for step in range(6+len(completed),11):Executor(self).run(step)
        finally:
            if (self.root/'ruleset-pair.json').exists():self.restore()
        return {'verdict':'PAUSED','pause':'rewrite-push','nextStep':11}

    def require_proceed(self,pause):
        row=read_json(self.root/('proceed-'+pause+'.json'))
        expected=self.permit.get('proceedReceiptSha256',{}).get(pause)
        require(gate._is_hex(expected,64) and digest(row)==expected and row.get('owner')==gate.OWNER_APPROVER
                and row.get('sealSha256')==digest(self.seal) and row.get('pause')==pause
                and row.get('decision')=='PROCEED','OWNER_PROCEED_REQUIRED')
        self.registry.readback(purpose='continuation')
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


def read_custody(root):
    path=private_root(root)/'events.jsonl'
    require(path.is_file() and not path.is_symlink(),'RESUME_CUSTODY_REQUIRED')
    rows=[];previous='0'*64
    try:
        for line in path.read_text().splitlines():
            row=json.loads(line)
            require(isinstance(row,dict) and set(row)=={'index','previous','event','values'}
                    and type(row['index']) is int and row['index']==len(rows)
                    and row['previous']==previous,'CUSTODY_CHAIN_INVALID')
            previous=digest(row);rows.append(row)
    except (ValueError,UnicodeError,OSError):raise Refusal('CUSTODY_CHAIN_INVALID') from None
    return rows


@contextlib.contextmanager
def capture_watchdog_stdio(log):
    """Child-owned capture survives parent SIGKILL; no raw text enters custody.

    Each stdout/stderr write is SHA-bound in the fsynced chain. Canonical refusal
    events are logged separately. Arbitrary library diagnostics are never echoed.
    """
    class Sink:
        def __init__(self,event):self.event=event
        def write(self,text):
            if text:log.append(self.event,{'digest':hashlib.sha256(text.encode('utf8',errors='replace')).hexdigest()})
            return len(text)
        def flush(self):pass
    with contextlib.redirect_stdout(Sink('WATCHDOG_STDOUT')),contextlib.redirect_stderr(Sink('WATCHDOG_STDERR')):
        try:yield
        except Exception as error:
            code=str(error) if isinstance(error,Refusal) and re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}',str(error)) else 'WATCHDOG_UNEXPECTED_REFUSAL'
            log.append(code,{})
            log.append('OWNER_ESCALATION_REQUIRED',{})
            print(json.dumps({'verdict':'BLOCKED','code':code}),file=sys.stderr)
            raise Refusal(code) from None


def capture_seal(root,credential):
    """Reviewed read-only Git/GitHub collector, explicit CLI only; no rewrite."""
    root=private_root(root);api=GitHub(credential);git=GitIO(root,credential)
    clock=AuthenticatedClock(api);started=clock()
    policy={'schemaVersion':gate.EXECUTION_SCHEMA_VERSION,'repository':gate.REPOSITORY,
            'visibility':'PRIVATE','defaultBranch':'main','targetManifest':list(gate.TARGETS),
            'filterRepoVersion':gate.FILTER_REPO_VERSION,'maxSnapshotAgeSeconds':2700}
    result=gate.capture_execution_seal(lambda:collect_observation(git,api),policy=policy,now=started)
    if result['verdict']!='PASS':
        codes=result.get('codes')
        require(isinstance(codes,list) and bool(codes) and all(
            isinstance(code,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}',code)
            for code in codes),'SEAL_CAPTURE_REFUSED')
        for code in codes:Custody(root).append(code,{})
        raise Refusal(','.join(codes))
    finished=clock();require(finished<result['seal']['expiresAt'],'SEAL_EXPIRED')
    immutable_json(root,'seal-policy.json',policy);immutable_json(root,'seal.json',result['seal'])
    receipt={'sealSha256':result['sealSha256'],'serverTimestamp':finished,'timeReceipt':clock.last,
             'protectedRootSha256':digest(str(configured_protected_roots()[0])),
             'executionAuthorized':False}
    immutable_json(root,'seal-capture-receipt.json',receipt)
    Custody(root).append('SEAL_CAPTURED',{'sealSha256':result['sealSha256'],'digest':digest(receipt)})
    return receipt


def watchdog(root,pair_sha256,parent_pid,credential):
    log=Custody(root)
    with capture_watchdog_stdio(log):return _watchdog(root,pair_sha256,parent_pid,credential)


def _watchdog(root,pair_sha256,parent_pid,credential):
    root=private_root(root);pair=read_json(root/'ruleset-pair.json')
    require(digest(pair)==pair_sha256,'WATCHDOG_PAIR_MISMATCH');api=GitHub(credential);log=Custody(root)
    restoration_state(api,[pair['before']],lambda event:log.append(event,{'digest':pair_sha256}))
    authenticated_clock=AuthenticatedClock(api);armed_at=authenticated_clock()
    immutable_json(root,'watchdog-armed.json',{'pairSha256':pair_sha256,'pid':os.getpid(),'armedAt':armed_at,
                                            'timeReceipt':authenticated_clock.last})
    while True:
        if (root/'restoration-proof.json').exists():
            restoration_state(api,[pair['before']],lambda event:log.append(event,{'digest':pair_sha256}));return
        try:os.kill(parent_pid,0);alive=True
        except OSError:alive=False
        try:heartbeat=int((root/'heartbeat').read_text())
        except (OSError,ValueError):heartbeat=None
        if watchdog_due(alive=alive,armed_at=armed_at,heartbeat=heartbeat,now=int(time.time())):
            result=restore(api,pair,lambda event:log.append(event,{'digest':pair_sha256}))
            if not (root/'restoration-proof.json').exists():
                result.update(serverTimestamp=authenticated_clock(),timeReceipt=authenticated_clock.last)
                immutable_json(root,'restoration-proof.json',result)
            return
        time.sleep(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-step',type=int,choices=range(11,16));parser.add_argument('--root',type=Path)
    parser.add_argument('--execute-rewrite-phase',action='store_true')
    parser.add_argument('--resume-rewrite-phase',action='store_true')
    parser.add_argument('--capture-seal',action='store_true')
    parser.add_argument('--prepare-rewrite-claim',action='store_true')
    parser.add_argument('--owner-permit-sha256');parser.add_argument('--watchdog',type=Path)
    parser.add_argument('--pair-sha256');parser.add_argument('--parent-pid',type=int)
    args=parser.parse_args()
    modes=sum([args.execute_step is not None,args.watchdog is not None,args.execute_rewrite_phase,args.resume_rewrite_phase,args.capture_seal,args.prepare_rewrite_claim])
    require(modes<=1,'EXECUTION_MODE_CONFLICT')
    if modes==0:print(json.dumps(plan(),sort_keys=True));return
    credential=os.environ.get('NYAY21_EXECUTION_CREDENTIAL','')
    if args.capture_seal:
        require(args.root is not None,'CAPTURE_ROOT_REQUIRED')
        print(json.dumps(capture_seal(args.root,credential),sort_keys=True));return
    if args.watchdog is not None:
        require(type(args.parent_pid) is int and args.parent_pid>1,'WATCHDOG_PARENT_REQUIRED')
        watchdog(args.watchdog,args.pair_sha256,args.parent_pid,credential);return
    require(args.root is not None and args.owner_permit_sha256 is not None,'OWNER_PERMIT_REQUIRED')
    context=Runtime(args.root,args.owner_permit_sha256,credential)
    if args.prepare_rewrite_claim:
        print(json.dumps(context.prepare_rewrite_claim(),sort_keys=True));return
    if args.resume_rewrite_phase:
        print(json.dumps(context.resume_rewrite_phase(),sort_keys=True));return
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

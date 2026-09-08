#!/usr/bin/env python3
"""Execution/v2 effect adapters. Import/default CLI is non-mutating plan-only.

Effectful methods are separated from the historical pure validator. The owner
must bind a reviewed execution permit through an independent channel; local
JSON and a successful unit test do not constitute execution approval. No live
operation is performed by this module's default command-line entry point.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

import nyay21_history_purge as gate

STEPS={6:'step6',7:'step7',8:'step8',9:'step9',10:'step10',11:'step11',
       12:'step12',13:'step13',14:'step14',15:'step15'}
PAUSES={5:'backup-drill',11:'rewrite-push',13:'ci-dispatch'}
PUT_FIELDS={'name','target','enforcement','bypass_actors','conditions','rules'}
GET_FIELDS=PUT_FIELDS|{'id','source','source_type','node_id','created_at','updated_at',
                       'current_user_can_bypass','_links'}
SUSPEND={'pull_request','required_status_checks','non_fast_forward'}


class Refusal(RuntimeError):
    """Canonical privacy-safe refusal; never include raw process/network text."""


def require(ok,code):
    if ok is not True:raise Refusal(code)


def digest(value):
    return gate._canonical_json_sha256(value)


def ruleset_pair(before,expected_get_sha256):
    require(isinstance(before,dict) and set(before)==GET_FIELDS and
            digest(before)==expected_get_sha256,'RULESET_SNAPSHOT_MISMATCH')
    require(type(before['id']) is int and before['id']==gate.RULESET_ID and
            before['source']==gate.REPOSITORY and before['source_type']=='Repository'
            and before['enforcement']=='active' and before['target']=='branch','RULESET_SCOPE_INVALID')
    rows=before['rules']
    require(isinstance(rows,list) and all(isinstance(r,dict) and isinstance(r.get('type'),str) for r in rows)
            and len({r['type'] for r in rows})==len(rows) and SUSPEND<={r['type'] for r in rows},'RULESET_RULE_INVENTORY_INVALID')
    restoration={k:copy.deepcopy(before[k]) for k in PUT_FIELDS}
    relaxation=copy.deepcopy(restoration)
    relaxation['rules']=[r for r in relaxation['rules'] if r['type'] not in SUSPEND]
    return {'before':copy.deepcopy(before),'relaxation':relaxation,'restoration':restoration,
            'fullGetSha256':digest(before),'relaxationSha256':digest(relaxation),
            'restorationSha256':digest(restoration)}


def restored(before,after):
    """Full GET comparison, transparently normalizing only server update time.

    Raw GET digests remain separate evidence; GitHub does not allow restoring its
    server-maintained updated_at clock. Every other field must match exactly.
    """
    if not isinstance(after,dict) or set(after)!=set(before):return False
    try:
        old=datetime.fromisoformat(before['updated_at'].replace('Z','+00:00'))
        new=datetime.fromisoformat(after['updated_at'].replace('Z','+00:00'))
        if old.tzinfo is None or new.tzinfo is None or new<old:return False
    except (ValueError,TypeError,KeyError,AttributeError):return False
    normalized={**after,'updated_at':before['updated_at']}
    return digest(normalized)==digest(before)


def restore(api,pair,emit):
    """GET before each bounded PUT; never overwrite an unrelated concurrent edit."""
    require(pair==ruleset_pair(pair['before'],pair['fullGetSha256']),'RULESET_PAIR_MISMATCH')
    relaxed={**pair['before'],**pair['relaxation']}
    for attempt in range(3):
        try:current=api.get()
        except Exception:
            emit('RESTORATION_GET_FAILED')
            raise Refusal('RESTORATION_READBACK_UNAVAILABLE') from None
        if restored(pair['before'],current):
            return {'restored':True,'fullGetBeforeSha256':pair['fullGetSha256'],
                    'fullGetAfterSha256':digest(current),'canonicalGetSha256':digest(pair['before']),
                    'normalizedServerField':'updated_at','putAttempts':attempt}
        require(restored(relaxed,current),'RULESET_CONCURRENT_CHANGE')
        try:api.put(copy.deepcopy(pair['restoration']))
        except Exception:emit('RESTORATION_PUT_FAILED')
    try:current=api.get()
    except Exception:
        emit('RESTORATION_GET_FAILED')
        raise Refusal('RESTORATION_READBACK_UNAVAILABLE') from None
    if restored(pair['before'],current):
        return {'restored':True,'fullGetBeforeSha256':pair['fullGetSha256'],
                'fullGetAfterSha256':digest(current),'canonicalGetSha256':digest(pair['before']),
                'normalizedServerField':'updated_at','putAttempts':3}
    emit('RESTORATION_OWNER_BREAK_GLASS')
    raise Refusal('RESTORATION_OWNER_BREAK_GLASS')


def private_root(root):
    root=Path(root)
    require(root.is_absolute() and not root.is_symlink(),'CUSTODY_PARENT_MODE')
    require(root.resolve()==root and root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700,'CUSTODY_PARENT_MODE')
    return root


class Custody:
    """Local append-only, fsynced hash chain; external anchoring still required.

    This prevents accidental edits and concurrent writers, not a malicious root
    custodian rewriting the whole log. Publish each pause's digest independently.
    """
    def __init__(self,root):self.root=private_root(root)

    def append(self,event,values):
        require(isinstance(event,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}',event) is not None,'CUSTODY_EVENT_INVALID')
        require(isinstance(values,dict) and all(k in {'digest','sealSha256','head','step','exitCode'} for k in values),'CUSTODY_FIELD_INVALID')
        require(all(type(v) is int and v>=0 if k in {'step','exitCode'} else
                    isinstance(v,str) and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',v) is not None
                    for k,v in values.items()),'CUSTODY_FIELD_INVALID')
        root=private_root(self.root)
        fd=os.open(root/'events.jsonl',os.O_CREAT|os.O_RDWR|os.O_APPEND|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+',encoding='utf8') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            require(stat.S_IMODE(os.fstat(stream.fileno()).st_mode)==0o600,'CUSTODY_FILE_MODE')
            previous='0'*64;index=0
            for line in stream:
                try:row=json.loads(line)
                except ValueError:raise Refusal('CUSTODY_CHAIN_INVALID') from None
                require(row.get('previous')==previous and type(row.get('index')) is int and row['index']==index,'CUSTODY_CHAIN_INVALID')
                previous=digest(row);index+=1
            row={'index':index,'previous':previous,'event':event,'values':values}
            stream.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n');stream.flush();os.fsync(stream.fileno())
            return row


def immutable_json(root,name,value):
    root=private_root(root)
    require(re.fullmatch(r'[a-zA-Z0-9._-]+\.json',name) is not None,'IMMUTABLE_NAME_INVALID')
    try:fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:raise Refusal('IMMUTABLE_REVISION_EXISTS') from None
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,sort_keys=True,separators=(',',':'));stream.write('\n');stream.flush();os.fsync(stream.fileno())
    return root/name


def write_rebinding(root,seal_sha256,mapping,campaign):
    require(isinstance(seal_sha256,str) and re.fullmatch(r'[a-f0-9]{64}',seal_sha256) is not None,'REBINDING_SEAL_INVALID')
    require(isinstance(campaign,dict) and campaign.get('passed') is True and
            type(campaign.get('assertions')) is int and campaign['assertions']>0,'CAMPAIGN_NOT_PASS')
    require(isinstance(mapping,list) and bool(mapping) and all(isinstance(r,dict) and set(r)=={'old','new'} and
            gate._is_nonzero_hex40(r['old']) and gate._is_hex(r['new'],40) for r in mapping)
            and len({r['old'] for r in mapping})==len(mapping),'REBINDING_MAP_INVALID')
    return immutable_json(root,'REBINDING_'+seal_sha256+'.json',{'schemaVersion':'nyay21-evidence-rebinding/v2',
        'sealSha256':seal_sha256,'historicalEvidence':'immutable; not retested by relabeling',
        'mapping':mapping,'campaign':campaign})


class Executor:
    """Concrete ordered step dispatch against a separately authorized context.

    The context owns authenticated I/O, consumed approval registry and immutable
    receipts. `run` never advances over an absent receipt or owner PROCEED.
    Unit tests inject no-network contexts; production context must be re-audited.
    """
    def __init__(self,context):self.context=context

    def run(self,step):
        require(type(step) is int and step in STEPS,'STEP_INVALID')
        self.context.require_predecessor(step)
        self.context.require_current_permit(step)
        result=getattr(self,STEPS[step])()
        self.context.record_step(step,result)
        return result

    def step6(self):
        pair=self.context.capture_ruleset_pair()
        self.context.arm_watchdog(pair)
        return self.context.verify_watchdog(pair)

    def step7(self):
        self.context.require_live_old_refs()
        self.context.verify_filter_version(gate.FILTER_REPO_VERSION)
        self.context.consume_rewrite_approval()
        argv=['git','filter-repo','--sensitive-data-removal','--no-fetch','--invert-paths','--preserve-commit-hashes',
              '--replace-refs','delete-no-add','--prune-empty','auto','--prune-degenerate','auto']
        for target in gate.TARGETS:argv+=['--path',target['path']]
        self.context.command(argv)
        return self.context.verify_rewrite()

    def step8(self):
        # Restoration runs even on lease/read-back/dry-run/live-push failure.
        try:
            argv=self.context.validated_push_plan()
            require(argv[:4]==['git','push','--atomic','--dry-run'] and
                    any(a.startswith('--force-with-lease=refs/') for a in argv),'EXPLICIT_LEASE_REQUIRED')
            self.context.relax_ruleset()
            self.context.command(argv)
            # Re-authenticate scope/head/approvals after dry-run, before live push.
            require(self.context.validated_push_plan()==argv,'HEAD_CHANGED')
            self.context.consume_force_approval()
            result=self.context.command([a for a in argv if a!='--dry-run'])
            return result
        finally:self.context.restore()

    def step9(self):return self.context.restoration_proof()

    def step10(self):return self.context.verify_post_push()

    def step11(self):return self.context.require_proceed('rewrite-push')

    def step12(self):return self.context.owner_dispatch_plan()

    def step13(self):
        self.context.verify_dispatch_readback()
        return self.context.require_proceed('ci-dispatch')

    def step14(self):
        campaign=self.context.verify_completed_campaign()
        return self.context.write_rebinding(campaign)

    def step15(self):
        self.context.verify_completed_campaign()
        self.context.restoration_proof()
        return self.context.verify_closure_signatures()


def plan():
    return {'mode':'plan-only','executionAuthorized':False,'steps':STEPS,'pausePoints':PAUSES,
            'productionContext':'requires independent review and fresh digest-bound owner GO',
            'ownerDispatchStep':12,'executorActionsPermission':'read'}


if __name__=='__main__':print(json.dumps(plan(),sort_keys=True))

import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,digest,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19SequenceReplacements as proposals} from './nyay66-s19-sequence-reapproval.test-fixture.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const baseline=JSON.parse(execFileSync('git',['show','3770614af04f6a0e56b006717a8a6b3475bd8b22:frontend/scripts/nyay66-policy.json'],{cwd:root}));
const targets=proposals.map(p=>baseline.exceptions.findIndex(e=>canonical(e)===canonical(p.predecessor)));
// The integrity pointer necessarily advances when this protected test changes.
// Trusted nyay66_trust.py verifies that pointer against the exact bundle/comment;
// this historical content snapshot must not pin its own superseded approval.
const contentSnapshot=policy=>{const {integrityApproval,...content}=s19TypedPolicyForTest(policy);return JSON.stringify(content);};
const history=contentSnapshot(baseline);
const candidate=(selected=proposals)=>{const policy=structuredClone(baseline);for(const p of selected)policy.exceptions[targets[proposals.indexOf(p)]]=structuredClone(p.replacement);return policy;};
const expectBoundary=policy=>expect(contentSnapshot(policy)).toBe(history);
const options={s19:true};

describe('exact 22-row S-19 capture-sequence replacement boundary',()=>{
  it('pins 22 distinct predecessors/replacements without relaxing their original disclosure or checks',()=>{
    expect(proposals).toHaveLength(22);expect(new Set(targets).size).toBe(22);expect(targets.every(i=>i>=0)).toBe(true);
    expect(baseline.exceptions).toHaveLength(190);
    for(const p of proposals){
      expect(approveException(p.predecessor,null,options)).toBe(p.predecessorHash);
      expect(approveException(p.replacement,null,options)).toBe(p.hash);
      expect(p.replacement.reason.startsWith(p.predecessor.reason+' Capture-sequence replacement only')).toBe(true);
      expect({...p.replacement,liveSha256:p.predecessor.liveSha256,reason:p.predecessor.reason,approvalPr:p.predecessor.approvalPr}).toEqual(p.predecessor);
    }
  });
  it('preserves the changing integrity pointer without normalizing it or relaxing any other policy setting',()=>{
    const policy=candidate();
    // Synthetic metadata only; trusted owner read-back is a separate unchanged check.
    policy.integrityApproval={pr:84,commentId:123,bundleSha256:'a'.repeat(64)};
    const before=JSON.stringify(policy);expectBoundary(policy);
    expect(s19TypedPolicyForTest(policy).integrityApproval).toEqual(policy.integrityApproval);
    expect(JSON.stringify(policy)).toBe(before);
    for(const field of Object.keys(baseline).filter(k=>!['exceptions','integrityApproval'].includes(k))){
      const changed=structuredClone(policy);changed[field]=null;expect(()=>expectBoundary(changed)).toThrow();
    }
    expect(()=>expectBoundary({...policy,unexpectedSetting:true})).toThrow();
  });
  it.each(proposals)('admits only the exact replacement for $row without mutating input',p=>{
    const policy=candidate([p]),before=JSON.stringify(policy);expectBoundary(policy);expect(JSON.stringify(policy)).toBe(before);
  });
  it('accepts all 22 exact proposals while preserving the other 168 current records byte-for-byte in order',()=>{
    const policy=candidate(),before=JSON.stringify(policy);expectBoundary(policy);expect(JSON.stringify(policy)).toBe(before);
    const remaining=entries=>entries.filter((_,i)=>!targets.includes(i));
    expect(remaining(policy.exceptions)).toHaveLength(168);
    expect(JSON.stringify(remaining(policy.exceptions))).toBe(JSON.stringify(remaining(baseline.exceptions)));
    expectBoundary(baseline);expectBoundary(JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))));
  });
  it.each(proposals)('rejects altered identity/scope/hash/fields for $row',p=>{
    for(const mutate of [e=>e.approvalPr=70,e=>e.screen='S-20',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.theme='dark',e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.approved=true]){
      const policy=candidate();mutate(policy.exceptions[targets[proposals.indexOf(p)]]);expect(()=>expectBoundary(policy)).toThrow();
    }
  });
  it('rejects missing, duplicate or reordered records and changes to every other current record',()=>{
    for(let i=0;i<190;i++){
      const removed=candidate();removed.exceptions.splice(i,1);expect(()=>expectBoundary(removed)).toThrow();
      const duplicated=candidate();duplicated.exceptions.push(structuredClone(duplicated.exceptions[i]));expect(()=>expectBoundary(duplicated)).toThrow();
      const changed=candidate();changed.exceptions[i].reason+=' widened';expect(()=>expectBoundary(changed)).toThrow();
    }
    const reordered=candidate();[reordered.exceptions[0],reordered.exceptions[1]]=[reordered.exceptions[1],reordered.exceptions[0]];expect(()=>expectBoundary(reordered)).toThrow();
  });
  it.each(proposals)('requires exact owner read-back for $row; predecessor or another row cannot authorize it',p=>{
    // Synthetic unit-test comment only, never a claimed owner approval.
    const comment={id:1,approvalPr:84,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${p.hash}`};
    expect(approveException(p.replacement,[comment],options)).toBe(true);
    const other=proposals.find(x=>x!==p);
    for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:70}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'approved generally'}],[{...comment,body:`NYAY66-EXCEPTION ${p.predecessorHash}`}],[{...comment,body:`NYAY66-EXCEPTION ${other.hash}`}]] ){
      expect(approveException(p.replacement,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[p.replacement]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
  it('keeps sequence replacement fixtures outside capture/evaluation/product code',()=>{
    for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
      expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s19-sequence-reapproval.test-fixture');
    for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
      expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s19-sequence-reapproval.test-fixture');
  });
});

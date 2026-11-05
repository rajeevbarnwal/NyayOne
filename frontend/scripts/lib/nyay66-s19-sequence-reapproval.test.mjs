import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19SequenceReplacements as proposals} from './nyay66-s19-sequence-reapproval.test-fixture.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const baseline=JSON.parse(execFileSync('git',['show','3770614af04f6a0e56b006717a8a6b3475bd8b22:frontend/scripts/nyay66-policy.json'],{cwd:root}));
const targets=proposals.map(p=>baseline.exceptions.findIndex(e=>canonical(e)===canonical(p.predecessor)));
// The integrity pointer necessarily advances when this protected test changes.
// Trusted nyay66_trust.py verifies that pointer against the exact bundle/comment;
// this historical content snapshot must not pin its own superseded approval.
const contentSnapshot=policy=>JSON.stringify(Object.fromEntries(Object.entries(s19TypedPolicyForTest(policy)).filter(([key])=>key!=='integrityApproval')));
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
    expectBoundary(baseline);
    const current=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
    // The additive S-28 cache is pinned here and revalidated by its exact-provenance import test.
    expect(current.s28).toEqual({cache:'s28-v32108-chromium-149.0.7827.55-41323481198',manifestSha256:'0e68f61b7b664ce41375893827e9d693f516ece614ca66fb6c1318a1a1ebf513',provenanceSha256:'36a33702d2f2eeedb9be2c48c55b8b1af3ca44817996da1b9820930ec8a683b4'});
    expect(current.s29).toEqual({"cache":"s29-v32108-chromium-149.0.7827.55-41352544483","manifestSha256":"207f0d96ed928beee038f02d193a5febe3e3eae58d5f0b80a5a6af540cd6334c","provenanceSha256":"5de0808e4f1baa04f9696dd2613d04012ded898c4223118e096e1015a9969f17"});expect(current.s30).toEqual({"cache":"s30-v32108-chromium-149.0.7827.55-41593102467","manifestSha256":"f0d18bfc11a72774c2f4ddb923ed98a8f3d24c8e0beaeebbb8a12cc604079aa2","provenanceSha256":"62f4b3ce31ad66bab4d4d79c980a64929264b0f9f6a572d5deba62c23b82d9e6"});expect(current.s31).toEqual({"cache":"s31-v32108-chromium-149.0.7827.55-41795771621","manifestSha256":"d16430a6a405418f506085111e4486741ba0d46aa25e7ad32fcc937d3f1778d9","provenanceSha256":"cef8aedce696d134f8cdbff97a024bdd7d412a5a5441e14c809f31533326ae07"});delete current.s31;delete current.s30;delete current.s29;delete current.s28;expectBoundary(current);
  });
  it.each(proposals)('rejects altered identity/scope/hash/fields for $row',p=>{
    for(const mutate of [e=>e.approvalPr=70,e=>e.screen='S-20',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.theme='dark',e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.approved=true]){
      const policy=candidate();mutate(policy.exceptions[targets[proposals.indexOf(p)]]);expect(()=>expectBoundary(policy)).toThrow();
    }
  });
  it.each(Array.from({length:190},(_,i)=>i))('rejects missing, duplicate or changed record %i',i=>{
    const removed=candidate();removed.exceptions.splice(i,1);expect(()=>expectBoundary(removed)).toThrow();
    const duplicated=candidate();duplicated.exceptions.push(structuredClone(duplicated.exceptions[i]));expect(()=>expectBoundary(duplicated)).toThrow();
    const changed=candidate();changed.exceptions[i].reason+=' widened';expect(()=>expectBoundary(changed)).toThrow();
  });
  it('rejects reordered records',()=>{
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

import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,digest,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedRasterPredecessor,s19TypedRasterReplacement,s19TypedRasterPredecessorHash,s19TypedRasterReplacementHash,normalizeS19TypedRasterForTest,s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const baseline=JSON.parse(execFileSync('git',['show','c49da59b7ecb58601feaf9bba1ec757ed150808f:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const target=baseline.findIndex(e=>JSON.stringify(e)===JSON.stringify(s19TypedRasterPredecessor));
const candidate=()=>{const entries=structuredClone(baseline);entries[target]=structuredClone(s19TypedRasterReplacement);return entries;};
const historyHash=digest(JSON.stringify(baseline));
const expectBoundary=entries=>expect(digest(JSON.stringify(normalizeS19TypedRasterForTest(entries)))).toBe(historyHash);
const options={s19:true};

describe('S-19 mobile typed-confirmation exact replacement boundary',()=>{
  it('accepts only the predecessor or exact replacement and preserves the other 189 records byte-for-byte in order',()=>{
    expect(baseline).toHaveLength(190);expect(target).toBeGreaterThanOrEqual(0);
    expect(approveException(s19TypedRasterPredecessor,null,options)).toBe(s19TypedRasterPredecessorHash);
    expect(approveException(s19TypedRasterReplacement,null,options)).toBe(s19TypedRasterReplacementHash);
    expectBoundary(baseline);const entries=candidate(),before=JSON.stringify(entries);
    expectBoundary(entries);expect(JSON.stringify(entries)).toBe(before);
    const untouched=x=>x.filter((_,i)=>i!==target);
    expect(untouched(entries)).toHaveLength(189);
    expect(JSON.stringify(untouched(entries))).toBe(JSON.stringify(untouched(baseline)));
  });
  it('normalizes a policy clone only for historical snapshot checks',()=>{
    const policy={schema:1,exceptions:candidate(),enforced:['S-01']},before=JSON.stringify(policy);
    expect(s19TypedPolicyForTest(policy)).toEqual({...policy,exceptions:baseline});
    expect(JSON.stringify(policy)).toBe(before);
    expectBoundary(s19TypedPolicyForTest(JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)))).exceptions);
  });
  it.each([
    ['wrong PR',e=>e.approvalPr=83],['changed reference',e=>e.referenceSha256='a'.repeat(64)],
    ['changed live hash',e=>e.liveSha256='b'.repeat(64)],['changed reason',e=>e.reason+=' widened'],
    ['changed checks',e=>e.checks=['pixels']],['accessibility waiver',e=>e.checks.push('accessibility')],
    ['other viewport',e=>e.viewport='desktop'],['other screen',e=>e.screen='S-20'],
    ['other theme',e=>e.theme='dark'],['extra field',e=>e.approved=true],
  ])('rejects %s',(_,mutate)=>{
    const entries=candidate();mutate(entries[target]);expect(()=>expectBoundary(entries)).toThrow();
  });
  it('rejects missing/duplicate targets and alteration/removal/reordering of every other historical record',()=>{
    const missing=candidate();missing.splice(target,1);expect(()=>expectBoundary(missing)).toThrow();
    const duplicate=candidate();duplicate.push(structuredClone(duplicate[target]));expect(()=>expectBoundary(duplicate)).toThrow();
    for(let i=0;i<baseline.length;i++)if(i!==target){
      const altered=candidate();altered[i].reason+=' widened';expect(()=>expectBoundary(altered)).toThrow();
      const removed=candidate();removed.splice(i,1);expect(()=>expectBoundary(removed)).toThrow();
    }
    const reordered=candidate();[reordered[0],reordered[1]]=[reordered[1],reordered[0]];expect(()=>expectBoundary(reordered)).toThrow();
  });
  it('still requires exact owner read-back; fixture pins never grant runtime approval',()=>{
    // Synthetic unit-test comment only; not a claimed owner approval.
    const comment={id:1,approvalPr:84,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s19TypedRasterReplacementHash}`};
    expect(approveException(s19TypedRasterReplacement,[comment],options)).toBe(true);
    for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:83}],
      [{...comment,user:{login:'not-owner'}}],[{...comment,body:'approved generally'}],
      [{...comment,body:`NYAY66-EXCEPTION ${s19TypedRasterPredecessorHash}`}]] ){
      expect(approveException(s19TypedRasterReplacement,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[s19TypedRasterReplacement]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
  it('keeps this fixture outside capture, evaluation and production',()=>{
    for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
      expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s19-typed-reapproval.test-fixture');
    for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
      expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s19-typed-reapproval.test-fixture');
  });
});

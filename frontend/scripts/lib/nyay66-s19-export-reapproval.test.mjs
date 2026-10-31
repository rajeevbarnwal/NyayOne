import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,digest,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19ExportRasterPredecessor,s19ExportRasterReplacement,s19ExportRasterPredecessorHash,s19ExportRasterReplacementHash,normalizeS19ExportRasterForTest} from './nyay66-s19-export-reapproval.test-fixture.mjs';
import {s19TypedRasterReplacement,normalizeS19TypedRasterForTest,s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const baseline=JSON.parse(execFileSync('git',['show','552ec838ad8e5c9f3b70a8e0d8e8383fc5fd97df:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const target=baseline.findIndex(e=>JSON.stringify(e)===JSON.stringify(s19ExportRasterPredecessor));
const candidate=()=>{const entries=structuredClone(baseline);entries[target]=structuredClone(s19ExportRasterReplacement);return entries;};
const historyHash=digest(JSON.stringify(baseline));
const expectBoundary=entries=>expect(digest(JSON.stringify(normalizeS19ExportRasterForTest(entries)))).toBe(historyHash);
const options={s19:true};

describe('S-19 desktop export-failed exact replacement boundary',()=>{
  it('accepts only the predecessor or exact replacement, preserving the other 189 current records including the bound mobile replacement',()=>{
    expect(baseline).toHaveLength(190);expect(target).toBeGreaterThanOrEqual(0);
    expect(approveException(s19ExportRasterPredecessor,null,options)).toBe(s19ExportRasterPredecessorHash);
    expect(approveException(s19ExportRasterReplacement,null,options)).toBe(s19ExportRasterReplacementHash);
    expectBoundary(baseline);const entries=candidate(),before=JSON.stringify(entries);
    expectBoundary(entries);expect(JSON.stringify(entries)).toBe(before);
    const untouched=x=>x.filter((_,i)=>i!==target);
    expect(untouched(entries)).toHaveLength(189);
    expect(JSON.stringify(untouched(entries))).toBe(JSON.stringify(untouched(baseline)));
    expect(entries).toContainEqual(s19TypedRasterReplacement);
  });
  it('composes only exact normalizations in cloned historical snapshot policies without changing real approval data',()=>{
    const policy={schema:1,exceptions:candidate(),enforced:['S-01']},before=JSON.stringify(policy);
    expect(s19TypedPolicyForTest(policy)).toEqual({...policy,exceptions:normalizeS19TypedRasterForTest(baseline)});
    expect(JSON.stringify(policy)).toBe(before);
    expectBoundary(JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))).exceptions);
  });
  it.each([
    ['wrong PR',e=>e.approvalPr=83],['changed reference',e=>e.referenceSha256='a'.repeat(64)],
    ['changed live hash',e=>e.liveSha256='b'.repeat(64)],['changed reason',e=>e.reason+=' widened'],
    ['changed checks',e=>e.checks=['pixels']],['accessibility waiver',e=>e.checks.push('accessibility')],
    ['other viewport',e=>e.viewport='mobile390'],['other screen',e=>e.screen='S-20'],
    ['other theme',e=>e.theme='dark'],['extra field',e=>e.approved=true],
  ])('rejects %s',(_,mutate)=>{
    const entries=candidate();mutate(entries[target]);expect(()=>expectBoundary(entries)).toThrow();
    expect(()=>s19TypedPolicyForTest({exceptions:entries})).toThrow();
  });
  it('rejects missing/duplicate targets and alteration/removal/reordering of every other current record',()=>{
    const missing=candidate();missing.splice(target,1);expect(()=>expectBoundary(missing)).toThrow();
    const duplicate=candidate();duplicate.push(structuredClone(duplicate[target]));expect(()=>expectBoundary(duplicate)).toThrow();
    for(let i=0;i<baseline.length;i++)if(i!==target){
      const altered=candidate();altered[i].reason+=' widened';expect(()=>expectBoundary(altered)).toThrow();
      const removed=candidate();removed.splice(i,1);expect(()=>expectBoundary(removed)).toThrow();
    }
    const reordered=candidate();[reordered[0],reordered[1]]=[reordered[1],reordered[0]];expect(()=>expectBoundary(reordered)).toThrow();
  });
  it('still requires exact owner read-back and rejects the predecessor approval or mobile approval for this desktop proposal',()=>{
    // Synthetic unit-test comment only; not a claimed owner approval.
    const comment={id:1,approvalPr:84,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s19ExportRasterReplacementHash}`};
    expect(approveException(s19ExportRasterReplacement,[comment],options)).toBe(true);
    for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:70}],
      [{...comment,user:{login:'not-owner'}}],[{...comment,body:'approved generally'}],
      [{...comment,body:`NYAY66-EXCEPTION ${s19ExportRasterPredecessorHash}`}],
      [{...comment,body:`NYAY66-EXCEPTION ${approveException(s19TypedRasterReplacement,null,options)}`}]] ){
      expect(approveException(s19ExportRasterReplacement,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[s19ExportRasterReplacement]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
  it('keeps this fixture outside capture, evaluation and production',()=>{
    for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
      expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s19-export-reapproval.test-fixture');
    for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
      expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s19-export-reapproval.test-fixture');
  });
});

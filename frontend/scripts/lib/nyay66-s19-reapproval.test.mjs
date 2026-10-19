import {describe,it,expect} from 'vitest';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19RasterPredecessor,s19RasterReplacement,normalizeS19RasterForTest} from './nyay66-s19-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const options={r2:true,s18:true,s19:true,s20:true};
const original=JSON.parse(execFileSync('git',['show','f458307c04ba81907395b0a2f29325c4f9aefde3:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const target=original.findIndex(e=>canonical(e)===canonical(s19RasterPredecessor));
const candidate=()=>{const entries=structuredClone(original);entries[target]=structuredClone(s19RasterReplacement);return entries;};
function expectPreserved(entries){expect(JSON.stringify(normalizeS19RasterForTest(entries))).toBe(JSON.stringify(original));}
describe('single S-19 raster replacement regression boundary, not approval',()=>{
  it('preserves all 131 other exception records byte-for-byte and in order',()=>{
    expect(original).toHaveLength(132);expect(target).toBeGreaterThanOrEqual(0);
    const current=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))).exceptions;
    expectPreserved(current);expectPreserved(candidate());
    const entries=candidate(),before=JSON.stringify(entries);
    normalizeS19RasterForTest(entries);expect(JSON.stringify(entries)).toBe(before);
    for(let i=0;i<original.length;i++)if(i!==target){const changed=candidate();changed[i].reason+=' widened';expect(()=>expectPreserved(changed)).toThrow();}
  });
  it.each([
    ['wrong PR',e=>e.approvalPr=70],['wrong screen',e=>e.screen='S-18'],
    ['wrong viewport',e=>e.viewport='desktop'],['wrong theme',e=>e.theme='dark'],
    ['changed reference',e=>e.referenceSha256='a'.repeat(64)],['different live pixels',e=>e.liveSha256='b'.repeat(64)],
    ['widened reason',e=>e.reason+=' extra scope'],['accessibility waiver',e=>e.checks.push('accessibility')],
    ['changed checks',e=>e.checks=['pixels']],['extra field',e=>e.arbitrary=true],
  ])('rejects %s even when the row otherwise resembles the candidate',(_,mutate)=>{
    const entries=candidate();mutate(entries[target]);expect(()=>expectPreserved(entries)).toThrow();
  });
  it.each([
    ['missing target',e=>e.splice(target,1)],['duplicate target',e=>e.push(structuredClone(e[target]))],
    ['deleted unrelated record',e=>e.shift()],['reordered records',e=>{[e[0],e[1]]=[e[1],e[0]];}],
  ])('rejects %s without weakening cardinality or historical order',(_,mutate)=>{
    const entries=candidate();mutate(entries);expect(()=>expectPreserved(entries)).toThrow();
  });
  it('still requires the real owner, correct PR and exact hash; fixture validity is not approval',()=>{
    const hash=approveException(s19RasterReplacement,null,options);
    const comment={id:1,approvalPr:72,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`};
    expect(approveException(s19RasterReplacement,[comment],options)).toBe(true);
    for(const comments of [[],[{...comment,approvalPr:70}],[{...comment,user:{login:'not-owner'}}],[{...comment,id:0}],[{...comment,body:'approved generally'}],[{...comment,body:`NYAY66-EXCEPTION ${approveException(s19RasterPredecessor,null,options)}`}]] ){
      expect(approveException(s19RasterReplacement,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[s19RasterReplacement]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
  it('keeps the normalization outside runtime capture, evaluation and import code',()=>{
    for(const name of ['nyay66-enforcement.mjs','nyay66-s19-live.mjs','nyay66-s20-live.mjs','nyay66-s19-import.mjs','nyay66-s20-import.mjs']){
      expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s19-reapproval.test-fixture');
    }
  });
});

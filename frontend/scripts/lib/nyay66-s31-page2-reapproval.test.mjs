import {withoutS32ProposalsForTest} from './nyay66-s32-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {withoutS31PolicyBytesForTest,withoutS31ProposalsForTest} from './nyay66-s31-exceptions.test-fixture.mjs';
import {s31Page2Predecessor as predecessor,s31Page2Replacement as replacement,s31Page2ReplacementHash,normalizeS31Page2ForTest,normalizeS31Page2PolicyBytesForTest} from './nyay66-s31-page2-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const beforeBytes=execFileSync('git',['show','1ea4890a2329edebc485f6fb3b89bc3962f398b2:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
const baseline=JSON.parse(beforeBytes),historical=JSON.stringify(baseline.exceptions);
const target=baseline.exceptions.findIndex(e=>canonical(e)===canonical(predecessor));
const candidate=()=>{const p=structuredClone(baseline);p.exceptions[target]=structuredClone(replacement);return p;};
const boundary=p=>expect(JSON.stringify(normalizeS31Page2ForTest(withoutS32ProposalsForTest(p.exceptions)))).toBe(historical);
const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
const options={s31:true};

describe('S-31 mobile page-2 exact capture-framing replacement',()=>{
 it('normalizes only the exact predecessor or replacement without mutating the other 247 records',()=>{
  expect(target).toBeGreaterThanOrEqual(0);expect(baseline.exceptions).toHaveLength(248);
  expect(approveException(replacement,null,options)).toBe(s31Page2ReplacementHash);
  const p=candidate(),bytes=JSON.stringify(p);boundary(baseline);boundary(p);expect(JSON.stringify(p)).toBe(bytes);
  const others=entries=>entries.filter((_,i)=>i!==target);
  expect(others(p.exceptions)).toHaveLength(247);expect(JSON.stringify(others(p.exceptions))).toBe(JSON.stringify(others(baseline.exceptions)));
 });
 it('passes existing import and continuation boundaries only for the exact replacement',()=>{
  const p=candidate(),bytes=JSON.stringify(p);
  expect(withoutS31ProposalsForTest(p.exceptions)).toEqual(withoutS31ProposalsForTest(baseline.exceptions));
  expect(s19TypedPolicyForTest(p)).toEqual(s19TypedPolicyForTest(baseline));expect(JSON.stringify(p)).toBe(bytes);
 });
 it('substitutes only the exact formatted record, preserving all other raw policy bytes',()=>{
  const bytes=beforeBytes.replace(record(predecessor),record(replacement));expect(bytes).not.toBe(beforeBytes);
  expect(normalizeS31Page2PolicyBytesForTest(beforeBytes)).toBe(beforeBytes);
  expect(normalizeS31Page2PolicyBytesForTest(bytes)).toBe(beforeBytes);
  expect(withoutS31PolicyBytesForTest(bytes)).toBe(withoutS31PolicyBytesForTest(beforeBytes));
  expect(()=>normalizeS31Page2PolicyBytesForTest(bytes.replace(record(replacement),record(replacement).replace('    {','   {')))).toThrow();
  expect(normalizeS31Page2PolicyBytesForTest(bytes.replace('"schema": 1','"schema": 2'))).not.toBe(beforeBytes);
 });
 it('validates the current policy without authorizing or binding the proposal',()=>{
  const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))),bytes=JSON.stringify(p);
  boundary(p);expect([canonical(predecessor),canonical(replacement)]).toContain(canonical(p.exceptions[target]));expect(JSON.stringify(p)).toBe(bytes);
 });
 it.each([
  ['wrong PR',e=>e.approvalPr=91],['changed reference',e=>e.referenceSha256='a'.repeat(64)],
  ['changed image',e=>e.liveSha256='b'.repeat(64)],['changed reason',e=>e.reason+=' widened'],
  ['changed checks',e=>e.checks=['pixels']],['accessibility waiver',e=>e.checks.push('accessibility')],
  ['other viewport',e=>e.viewport='desktop'],['other state',e=>e.referenceSha256=baseline.exceptions.at(-1).referenceSha256],
  ['other screen',e=>e.screen='S-32'],['other theme',e=>e.theme='dark'],['extra field',e=>e.approved=true],
 ])('rejects %s',(_label,mutate)=>{const p=candidate();mutate(p.exceptions[target]);expect(()=>boundary(p)).toThrow();expect(()=>withoutS31ProposalsForTest(p.exceptions)).toThrow();});
 it.each(baseline.exceptions.map((_,i)=>i).filter(i=>i!==target))('rejects mutation/removal/duplication of other record %i',i=>{
  for(const action of ['mutate','remove','duplicate']){
   const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));
   expect(()=>boundary(p)).toThrow();
  }
 });
 it('rejects missing/duplicate target and changed order',()=>{
  const missing=candidate();missing.exceptions.splice(target,1);expect(()=>boundary(missing)).toThrow();
  const duplicate=candidate();duplicate.exceptions.push(structuredClone(replacement));expect(()=>boundary(duplicate)).toThrow();
  for(const pair of [[0,1],[target,target+1]]){const p=candidate();[p.exceptions[pair[0]],p.exceptions[pair[1]]]=[p.exceptions[pair[1]],p.exceptions[pair[0]]];expect(()=>boundary(p)).toThrow();}
 });
 it('requires runtime owner/PR/exact-digest approval; fixture pins and the predecessor never grant it',()=>{
  const comment={id:1,approvalPr:90,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s31Page2ReplacementHash}`};
  expect(approveException(replacement,[comment],options)).toBe(true);
  for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:91}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'approved generally'}],[{...comment,body:`NYAY66-EXCEPTION ${approveException(predecessor,null,options)}`}]] ){
   expect(approveException(replacement,comments,options)).toBe(false);
   expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[replacement]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
 });
 it('keeps test proposal pins out of runtime captures, evaluator and product imports',()=>{
  for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
   expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s31-page2-reapproval.test-fixture');
  for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
   expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s31-page2-reapproval.test-fixture');
 });
});

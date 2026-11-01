import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {s18InvalidPredecessor as predecessor,s18InvalidReplacement as replacement,s18InvalidPredecessorHash,s18InvalidReplacementHash,normalizeS18InvalidPolicyBytesForTest} from './nyay66-s18-invalid-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const baseline=JSON.parse(execFileSync('git',['show','d1aa7f46cff579327b95370a4293d4145221c944:frontend/scripts/nyay66-policy.json'],{cwd:root}));
const target=baseline.exceptions.findIndex(e=>canonical(e)===canonical(predecessor));
const candidate=()=>{const p=structuredClone(baseline);p.exceptions[target]=structuredClone(replacement);return p;};
const snapshot=p=>JSON.stringify(s19TypedPolicyForTest(p).exceptions);
const expected=snapshot(baseline);
const boundary=p=>expect(snapshot(p)).toBe(expected);
const options={s18:true};

describe('S-18 desktop validation-error exact capture replacement',()=>{
 it('normalizes only the exact predecessor or replacement in a clone; other 189 records remain byte-identical',()=>{
  expect(target).toBeGreaterThanOrEqual(0);expect(baseline.exceptions).toHaveLength(190);
  expect(approveException(predecessor,null,options)).toBe(s18InvalidPredecessorHash);
  expect(approveException(replacement,null,options)).toBe(s18InvalidReplacementHash);
  const p=candidate(),bytes=JSON.stringify(p);boundary(baseline);boundary(p);expect(JSON.stringify(p)).toBe(bytes);
  const others=entries=>entries.filter((_,i)=>i!==target);
  expect(others(p.exceptions)).toHaveLength(189);expect(JSON.stringify(others(p.exceptions))).toBe(JSON.stringify(others(baseline.exceptions)));
  expect(s19TypedPolicyForTest(p).integrityApproval).toEqual(p.integrityApproval);
 });
 it('validates the current policy without changing its actual approval',()=>{
  const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
  const bytes=JSON.stringify(p);boundary(p);expect([canonical(predecessor),canonical(replacement)]).toContain(canonical(p.exceptions[target]));expect(JSON.stringify(p)).toBe(bytes);
 });
 it('normalizes only the exact replacement bytes, retaining every other raw byte and original record order',()=>{
  const bytes=execFileSync('git',['show','d1aa7f46cff579327b95370a4293d4145221c944:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
  const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    '),p=bytes.replace(record(predecessor),record(replacement));
  expect(p).not.toBe(bytes);expect(normalizeS18InvalidPolicyBytesForTest(bytes)).toBe(bytes);expect(normalizeS18InvalidPolicyBytesForTest(p)).toBe(bytes);
  expect(()=>normalizeS18InvalidPolicyBytesForTest(p.replace(record(replacement),record(replacement).replace('    {','   {')))).toThrow('S18_INVALID_REPLACEMENT_BYTES');
  const other=p.replace('"schema": 1','"schema": 2');expect(normalizeS18InvalidPolicyBytesForTest(other)).not.toBe(bytes);
 });
 it.each([
  ['wrong PR',e=>e.approvalPr=68],['changed reference',e=>e.referenceSha256='a'.repeat(64)],
  ['changed image',e=>e.liveSha256='b'.repeat(64)],['changed reason',e=>e.reason+=' widened'],
  ['changed checks',e=>e.checks=['pixels']],['accessibility waiver',e=>e.checks.push('accessibility')],
  ['other viewport',e=>e.viewport='mobile390'],['other state reference',e=>e.referenceSha256=baseline.exceptions[0].referenceSha256],
  ['other screen',e=>e.screen='S-19'],['other theme',e=>e.theme='dark'],['extra field',e=>e.approved=true],
 ])('rejects %s',(_label,mutate)=>{const p=candidate();mutate(p.exceptions[target]);expect(()=>boundary(p)).toThrow();});
 it.each(baseline.exceptions.map((_,i)=>i).filter(i=>i!==target))('rejects mutation, removal or duplication of other historical record %i',i=>{
  for(const action of ['mutate','remove','duplicate']){
   const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';
   else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));
   expect(()=>boundary(p)).toThrow();
  }
 });
 it('rejects missing/duplicate target and historical reordering',()=>{
  const missing=candidate();missing.exceptions.splice(target,1);expect(()=>boundary(missing)).toThrow();
  const duplicate=candidate();duplicate.exceptions.push(structuredClone(replacement));expect(()=>boundary(duplicate)).toThrow();
  const reordered=candidate();[reordered.exceptions[0],reordered.exceptions[1]]=[reordered.exceptions[1],reordered.exceptions[0]];expect(()=>boundary(reordered)).toThrow();
 });
 it('retains exact owner/PR/hash read-back; test pins do not grant runtime authorization',()=>{
  const comment={id:1,approvalPr:82,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s18InvalidReplacementHash}`};
  expect(approveException(replacement,[comment],options)).toBe(true);
  for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:68}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'approved generally'}],[{...comment,body:`NYAY66-EXCEPTION ${s18InvalidPredecessorHash}`}]] ){
   expect(approveException(replacement,comments,options)).toBe(false);
   expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[replacement]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
 });
 it('keeps the proposal fixture outside capture, evaluator and product imports',()=>{
  for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
   expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s18-invalid-reapproval.test-fixture');
  for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
   expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s18-invalid-reapproval.test-fixture');
 });
});

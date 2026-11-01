import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {s28Proposals,s28ProposalHashes,withoutS28ProposalsForTest,withoutS28PolicyBytesForTest} from './nyay66-s28-exceptions.test-fixture.mjs';
import {s18InvalidPredecessor,s18InvalidReplacement,normalizeS18InvalidPolicyBytesForTest} from './nyay66-s18-invalid-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const beforeBytes=execFileSync('git',['show','d1aa7f46cff579327b95370a4293d4145221c944:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
const baseline=JSON.parse(beforeBytes);
const candidate=()=>({...structuredClone(baseline),exceptions:[...structuredClone(baseline.exceptions),...structuredClone(s28Proposals)]});
const expected=JSON.stringify(s19TypedPolicyForTest(baseline).exceptions);
const boundary=p=>expect(JSON.stringify(s19TypedPolicyForTest(p).exceptions)).toBe(expected);
const options={s28:true};
describe('S-28 exact proposal boundary for historical snapshots',()=>{
 it('accepts only the final 14 exact proposals without modifying the 190 historical records',()=>{
  expect(s28Proposals).toHaveLength(14);expect(new Set(s28ProposalHashes).size).toBe(14);
  expect(s28Proposals.map(e=>approveException(e,null,options))).toEqual(s28ProposalHashes);
  const p=candidate(),bytes=JSON.stringify(p);boundary(baseline);boundary(p);
  expect(JSON.stringify(p)).toBe(bytes);
  expect(JSON.stringify(withoutS28ProposalsForTest(p.exceptions))).toBe(JSON.stringify(baseline.exceptions));
 });
 it('accepts the separately exact-pinned S-18 replacement together with the 14 additions',()=>{
  const p=candidate(),index=p.exceptions.findIndex(e=>canonical(e)===canonical(s18InvalidPredecessor));
  p.exceptions[index]=structuredClone(s18InvalidReplacement);boundary(p);
  p.exceptions[index].reason+=' widened';expect(()=>boundary(p)).toThrow();
 });
 it('validates the real current policy without binding proposals or changing it',()=>{
  const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))),bytes=JSON.stringify(p);
  boundary(p);expect(JSON.stringify(p)).toBe(bytes);
 });
 it('strips only the exact appended raw records; all historical bytes stay byte-identical',()=>{
  const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
  const suffix=',\n'+s28Proposals.map(record).join(',\n');
  const bytes=beforeBytes.replace(/\n {2}\]\n}\n$/,suffix+'\n  ]\n}\n');
  expect(bytes).not.toBe(beforeBytes);expect(JSON.parse(bytes).exceptions).toHaveLength(204);
  expect(withoutS28PolicyBytesForTest(beforeBytes)).toBe(beforeBytes);
  expect(withoutS28PolicyBytesForTest(bytes)).toBe(beforeBytes);
  const combined=bytes.replace(record(s18InvalidPredecessor),record(s18InvalidReplacement));
  expect(normalizeS18InvalidPolicyBytesForTest(withoutS28PolicyBytesForTest(combined))).toBe(beforeBytes);
  const changedHistory=bytes.replace('"schema": 1','"schema": 2');expect(withoutS28PolicyBytesForTest(changedHistory)).not.toBe(beforeBytes);
  expect(()=>withoutS28PolicyBytesForTest(bytes.replace(record(s28Proposals[0]),record(s28Proposals[0]).replace('    {','   {')))).toThrow();
 });
 it.each(s28Proposals.map((_,i)=>i))('rejects altered, missing, duplicated or relocated S-28 record %i',i=>{
  for(const mutate of [e=>e.approvalPr=83,e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.theme='dark',e=>e.screen='S-29',e=>e.extra=true]){
   const p=candidate();mutate(p.exceptions[190+i]);expect(()=>boundary(p)).toThrow();
  }
  const missing=candidate();missing.exceptions.splice(190+i,1);expect(()=>boundary(missing)).toThrow();
  const duplicate=candidate();duplicate.exceptions.push(structuredClone(s28Proposals[i]));expect(()=>boundary(duplicate)).toThrow();
  const relocated=candidate();relocated.exceptions.unshift(relocated.exceptions.splice(190+i,1)[0]);expect(()=>boundary(relocated)).toThrow();
 });
 it.each(baseline.exceptions.map((_,i)=>i))('retains mutation, removal and duplication rejection for historical record %i',i=>{
  for(const action of ['mutate','remove','duplicate']){
   const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));
   expect(()=>boundary(p)).toThrow();
  }
 });
 it('rejects reordered history and an unapproved extra continuation record',()=>{
  const p=candidate();[p.exceptions[0],p.exceptions[1]]=[p.exceptions[1],p.exceptions[0]];expect(()=>boundary(p)).toThrow();
  const extra=candidate();extra.exceptions.push({...structuredClone(s28Proposals[0]),screen:'S-29'});expect(()=>boundary(extra)).toThrow();
 });
 it.each(s28Proposals.map((entry,i)=>({entry,i})))('retains runtime owner/PR/digest authorization for row $i',({entry,i})=>{
  const comment={id:1,approvalPr:82,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s28ProposalHashes[i]}`};
  expect(approveException(entry,[comment],options)).toBe(true);
  for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:83}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'generally approved'}],[{...comment,body:`NYAY66-EXCEPTION ${'0'.repeat(64)}`}]] ){
   expect(approveException(entry,comments,options)).toBe(false);
   expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
 });
 it('keeps proposal pins outside runtime capture, evaluator and product modules',()=>{
  for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
   expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s28-exceptions.test-fixture');
  for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
   expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s28-exceptions.test-fixture');
 });
});

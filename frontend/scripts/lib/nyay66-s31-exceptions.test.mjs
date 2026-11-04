import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {s31Proposals,s31ProposalHashes,withoutS31ProposalsForTest,withoutS31PolicyBytesForTest} from './nyay66-s31-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const beforeBytes=execFileSync('git',['show','d5b015e0ae80c2d506b3465ad98f5397b208f5b4:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
const baseline=JSON.parse(beforeBytes),historical=JSON.stringify(baseline.exceptions);
const candidate=()=>({...structuredClone(baseline),exceptions:[...structuredClone(baseline.exceptions),...structuredClone(s31Proposals)]});
const boundary=p=>expect(JSON.stringify(withoutS31ProposalsForTest(p.exceptions))).toBe(historical);
const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
const appendBytes=()=>beforeBytes.replace(/\n {2}\]\n}\n$/,',\n'+s31Proposals.map(record).join(',\n')+'\n  ]\n}\n');
const options={s31:true};
describe('S-31 exact 16-addition boundary',()=>{
 it('admits only the exact final 16 additions while retaining 232 historical records in order',()=>{
  expect(baseline.exceptions).toHaveLength(232);expect(s31Proposals).toHaveLength(16);expect(new Set(s31ProposalHashes).size).toBe(16);
  expect(s31Proposals.map(e=>approveException(e,null,options))).toEqual(s31ProposalHashes);
  const p=candidate(),before=JSON.stringify(p);boundary(p);boundary(baseline);expect(JSON.stringify(p)).toBe(before);
 });
 it('keeps all historical import/continuation normalizations identical after the exact additions',()=>{
  const p=candidate(),before=JSON.stringify(p);
  expect(s19TypedPolicyForTest(p)).toEqual(s19TypedPolicyForTest(baseline));expect(JSON.stringify(p)).toBe(before);
 });
 it('preserves every historical raw policy byte when removing only the exact appended suffix',()=>{
  const bytes=appendBytes();expect(JSON.parse(bytes).exceptions).toHaveLength(248);
  expect(withoutS31PolicyBytesForTest(bytes)).toBe(beforeBytes);expect(withoutS31PolicyBytesForTest(beforeBytes)).toBe(beforeBytes);
  expect(()=>withoutS31PolicyBytesForTest(bytes.replace(record(s31Proposals[0]),record(s31Proposals[0]).replace('    {','   {')))).toThrow();
  expect(withoutS31PolicyBytesForTest(bytes.replace('"schema": 1','"schema": 2'))).not.toBe(beforeBytes);
 });
 it('validates actual current policy without binding proposals or modifying it',()=>{
  const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))),before=JSON.stringify(p);boundary(p);expect(JSON.stringify(p)).toBe(before);
 });
 it.each(s31Proposals.map((_,i)=>i))('rejects changed, missing, duplicate or relocated S-31 row %i',i=>{
  for(const mutate of [e=>e.approvalPr=91,e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.theme='dark',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.screen='S-32',e=>e.extra=true]){
   const p=candidate();mutate(p.exceptions[232+i]);expect(()=>boundary(p)).toThrow();
  }
  const missing=candidate();missing.exceptions.splice(232+i,1);expect(()=>boundary(missing)).toThrow();
  const duplicate=candidate();duplicate.exceptions.push(structuredClone(s31Proposals[i]));expect(()=>boundary(duplicate)).toThrow();
  const relocated=candidate();relocated.exceptions.unshift(relocated.exceptions.splice(232+i,1)[0]);expect(()=>boundary(relocated)).toThrow();
 });
 it.each(baseline.exceptions.map((_,i)=>i))('rejects mutation/removal/duplication of historical record %i',i=>{
  for(const action of ['mutate','remove','duplicate']){
   const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));
   expect(()=>boundary(p)).toThrow();
  }
 });
 it('rejects reordered history and any unapproved extra continuation entry',()=>{
  const p=candidate();[p.exceptions[0],p.exceptions[1]]=[p.exceptions[1],p.exceptions[0]];expect(()=>boundary(p)).toThrow();
  const extra=candidate();extra.exceptions.push({...structuredClone(s31Proposals[0]),screen:'S-32'});expect(()=>boundary(extra)).toThrow();
 });
 it.each(s31Proposals.map((entry,i)=>({entry,i})))('still requires exact runtime owner/PR/digest approval for row $i',({entry,i})=>{
  const comment={id:1,approvalPr:90,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s31ProposalHashes[i]}`};
  expect(approveException(entry,[comment],options)).toBe(true);
  for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:91}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'generally approved'}],[{...comment,body:`NYAY66-EXCEPTION ${'0'.repeat(64)}`}],[{...comment,body:`NYAY66-EXCEPTION ${s31ProposalHashes[(i+1)%16]}`}]] ){
   expect(approveException(entry,comments,options)).toBe(false);
   expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
 });
 it('keeps proposal pins out of runtime capture, evaluator and product code',()=>{
  for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
   expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s31-exceptions.test-fixture');
  for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
   expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s31-exceptions.test-fixture');
 });
});

import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {s32Proposals,s32ProposalHashes,withoutS32ProposalsForTest,withoutS32PolicyBytesForTest} from './nyay66-s32-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const beforeBytes=execFileSync('git',['show','e178fcfd9257b56fdc953fb9da4b99d9a39ac190:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
const baseline=JSON.parse(beforeBytes),historical=JSON.stringify(baseline.exceptions);
const candidate=()=>({...structuredClone(baseline),exceptions:[...structuredClone(baseline.exceptions),...structuredClone(s32Proposals)]});
const boundary=p=>expect(JSON.stringify(withoutS32ProposalsForTest(p.exceptions))).toBe(historical);
const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
const appendBytes=()=>beforeBytes.replace(/\n {2}\]\n}\n$/,',\n'+s32Proposals.map(record).join(',\n')+'\n  ]\n}\n');
const options={s32:true};
describe('S-32 exact 22-addition boundary',()=>{
 it('admits only the exact final 22 additions while retaining 248 historical records in order',()=>{
  expect(baseline.exceptions).toHaveLength(248);expect(s32Proposals).toHaveLength(22);expect(new Set(s32ProposalHashes).size).toBe(22);
  expect(s32Proposals.map(e=>approveException(e,null,options))).toEqual(s32ProposalHashes);
  const p=candidate(),before=JSON.stringify(p);boundary(p);boundary(baseline);expect(JSON.stringify(p)).toBe(before);
 });
 it('keeps all historical import/continuation normalizations identical after the exact additions',()=>{
  const p=candidate(),before=JSON.stringify(p);
  expect(s19TypedPolicyForTest(p)).toEqual(s19TypedPolicyForTest(baseline));expect(JSON.stringify(p)).toBe(before);
 });
 it('preserves every historical raw policy byte when removing only the exact appended suffix',()=>{
  const bytes=appendBytes();expect(JSON.parse(bytes).exceptions).toHaveLength(270);
  expect(withoutS32PolicyBytesForTest(bytes)).toBe(beforeBytes);expect(withoutS32PolicyBytesForTest(beforeBytes)).toBe(beforeBytes);
  expect(()=>withoutS32PolicyBytesForTest(bytes.replace(record(s32Proposals[0]),record(s32Proposals[0]).replace('    {','   {')))).toThrow();
  expect(withoutS32PolicyBytesForTest(bytes.replace('"schema": 1','"schema": 2'))).not.toBe(beforeBytes);
 });
 it('validates actual current policy without binding proposals or modifying it',()=>{
  const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))),before=JSON.stringify(p);boundary(p);expect(JSON.stringify(p)).toBe(before);
 });
 it.each(s32Proposals.map((_,i)=>i))('rejects changed, missing, duplicate or relocated S-32 row %i',i=>{
  for(const mutate of [e=>e.approvalPr=93,e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.theme='dark',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.screen='S-33',e=>e.extra=true]){
   const p=candidate();mutate(p.exceptions[248+i]);expect(()=>boundary(p)).toThrow();
  }
  const missing=candidate();missing.exceptions.splice(248+i,1);expect(()=>boundary(missing)).toThrow();
  const duplicate=candidate();duplicate.exceptions.push(structuredClone(s32Proposals[i]));expect(()=>boundary(duplicate)).toThrow();
  const relocated=candidate();relocated.exceptions.unshift(relocated.exceptions.splice(248+i,1)[0]);expect(()=>boundary(relocated)).toThrow();
 });
 it.each(baseline.exceptions.map((_,i)=>i))('rejects mutation/removal/duplication of historical record %i',i=>{
  for(const action of ['mutate','remove','duplicate']){
   const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));
   expect(()=>boundary(p)).toThrow();
  }
 });
 it('rejects reordered history and any unapproved extra continuation entry',()=>{
  const p=candidate();[p.exceptions[0],p.exceptions[1]]=[p.exceptions[1],p.exceptions[0]];expect(()=>boundary(p)).toThrow();
  const extra=candidate();extra.exceptions.push({...structuredClone(s32Proposals[0]),screen:'S-33'});expect(()=>boundary(extra)).toThrow();
 });
 it.each(s32Proposals.map((entry,i)=>({entry,i})))('still requires exact runtime owner/PR/digest approval for row $i',({entry,i})=>{
  const comment={id:1,approvalPr:92,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s32ProposalHashes[i]}`};
  expect(approveException(entry,[comment],options)).toBe(true);
  for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:93}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'generally approved'}],[{...comment,body:`NYAY66-EXCEPTION ${'0'.repeat(64)}`}],[{...comment,body:`NYAY66-EXCEPTION ${s32ProposalHashes[(i+1)%22]}`}]] ){
   expect(approveException(entry,comments,options)).toBe(false);
   expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
 });
 it('keeps proposal pins out of runtime capture, evaluator and product code',()=>{
  for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
   expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s32-exceptions.test-fixture');
  for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
   expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s32-exceptions.test-fixture');
 });
});

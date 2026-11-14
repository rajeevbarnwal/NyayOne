import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {s34Proposals,s34ProposalHashes,withoutS34ProposalsForTest,withoutS34PolicyBytesForTest} from './nyay66-s34-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const beforeBytes=execFileSync('git',['show','aaad8dd1e944bd1aa09ddce7ba0fe4ba575e87da:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
const baseline=JSON.parse(beforeBytes),historical=JSON.stringify(baseline.exceptions);
const candidate=()=>({...structuredClone(baseline),exceptions:[...structuredClone(baseline.exceptions),...structuredClone(s34Proposals)]});
const boundary=p=>expect(JSON.stringify(withoutS34ProposalsForTest(p.exceptions))).toBe(historical);
const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
const appendBytes=()=>beforeBytes.replace(/\n {2}\]\n}\n$/,',\n'+s34Proposals.map(record).join(',\n')+'\n  ]\n}\n');
const options={s34:true};
describe('S-34 exact 12-addition boundary',()=>{
 it('admits only the exact final 12 additions while retaining 298 historical records in order',()=>{
  expect(baseline.exceptions).toHaveLength(298);expect(s34Proposals).toHaveLength(12);expect(new Set(s34ProposalHashes).size).toBe(12);
  expect(s34Proposals.map(e=>approveException(e,null,options))).toEqual(s34ProposalHashes);
  const p=candidate(),before=JSON.stringify(p);boundary(p);boundary(baseline);expect(JSON.stringify(p)).toBe(before);
 });
 it('keeps all historical import/continuation normalizations identical after the exact additions',()=>{
  const p=candidate(),before=JSON.stringify(p);
  expect(s19TypedPolicyForTest(p)).toEqual(s19TypedPolicyForTest(baseline));expect(JSON.stringify(p)).toBe(before);
 });
 it('preserves every historical raw policy byte when removing only the exact appended suffix',()=>{
  const bytes=appendBytes();expect(JSON.parse(bytes).exceptions).toHaveLength(310);
  expect(withoutS34PolicyBytesForTest(bytes)).toBe(beforeBytes);expect(withoutS34PolicyBytesForTest(beforeBytes)).toBe(beforeBytes);
  expect(()=>withoutS34PolicyBytesForTest(bytes.replace(record(s34Proposals[0]),record(s34Proposals[0]).replace('    {','   {')))).toThrow();
  expect(withoutS34PolicyBytesForTest(bytes.replace('"schema": 1','"schema": 2'))).not.toBe(beforeBytes);
 });
 it('validates actual current policy without binding proposals or modifying it',()=>{
  const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))),before=JSON.stringify(p);boundary(p);expect(JSON.stringify(p)).toBe(before);
 });
 it.each(s34Proposals.map((_,i)=>i))('rejects changed, missing, duplicate or relocated S-34 row %i',i=>{
  for(const mutate of [e=>e.approvalPr=97,e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.theme='dark',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.screen='S-35',e=>e.extra=true]){
   const p=candidate();mutate(p.exceptions[298+i]);expect(()=>boundary(p)).toThrow();
  }
  const missing=candidate();missing.exceptions.splice(298+i,1);expect(()=>boundary(missing)).toThrow();
  const duplicate=candidate();duplicate.exceptions.push(structuredClone(s34Proposals[i]));expect(()=>boundary(duplicate)).toThrow();
  const relocated=candidate();relocated.exceptions.unshift(relocated.exceptions.splice(298+i,1)[0]);expect(()=>boundary(relocated)).toThrow();
 });
 it.each(baseline.exceptions.map((_,i)=>i))('rejects mutation/removal/duplication of historical record %i',i=>{
  for(const action of ['mutate','remove','duplicate']){
   const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));
   expect(()=>boundary(p)).toThrow();
  }
 });
 it('rejects reordered history and any unapproved extra continuation entry',()=>{
  const p=candidate();[p.exceptions[0],p.exceptions[1]]=[p.exceptions[1],p.exceptions[0]];expect(()=>boundary(p)).toThrow();
  const extra=candidate();extra.exceptions.push({...structuredClone(s34Proposals[0]),screen:'S-35'});expect(()=>boundary(extra)).toThrow();
 });
 it.each(s34Proposals.map((entry,i)=>({entry,i})))('still requires exact runtime owner/PR/digest approval for row $i',({entry,i})=>{
  const comment={id:1,approvalPr:96,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s34ProposalHashes[i]}`};
  expect(approveException(entry,[comment],options)).toBe(true);
  for(const comments of [[],[{...comment,id:0}],[{...comment,approvalPr:97}],[{...comment,user:{login:'not-owner'}}],[{...comment,body:'generally approved'}],[{...comment,body:`NYAY66-EXCEPTION ${'0'.repeat(64)}`}],[{...comment,body:`NYAY66-EXCEPTION ${s34ProposalHashes[(i+1)%12]}`}]] ){
   expect(approveException(entry,comments,options)).toBe(false);
   expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
 });
 it('keeps proposal pins out of runtime capture, evaluator and product code',()=>{
  for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
   expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s34-exceptions.test-fixture');
  for(const name of readdirSync(new URL('../../src/',import.meta.url),{recursive:true}).filter(n=>/\.(tsx?|mjs)$/.test(n)))
   expect(readFileSync(new URL(`../../src/${name}`,import.meta.url),'utf8')).not.toContain('nyay66-s34-exceptions.test-fixture');
 });
});

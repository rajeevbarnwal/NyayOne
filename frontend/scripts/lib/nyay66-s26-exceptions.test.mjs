import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,digest,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s26Proposals,s26ProposalHashes,withoutS26ProposalsForTest,historicalS26ExceptionsSha256} from './nyay66-s26-exceptions.test-fixture.mjs';
const options={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true};
const root=fileURLToPath(new URL('../../../',import.meta.url));
const baseline=JSON.parse(execFileSync('git',['show','51601fe9837d0156a22c198692d42284903efca9:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const candidate=()=>[...structuredClone(baseline),...structuredClone(s26Proposals)];
function expectBoundary(entries){
  const history=withoutS26ProposalsForTest(entries);
  expect(history).toHaveLength(160);
  expect(JSON.stringify(history)).toBe(JSON.stringify(baseline));
  expect(digest(JSON.stringify(history))).toBe(historicalS26ExceptionsSha256);
}
describe('S-26 exact additive exception regression boundary',()=>{
  it('allows zero or exactly eight pinned additions, preserving 160 historical records without mutation',()=>{
    expectBoundary(baseline);const entries=candidate(),before=JSON.stringify(entries);
    expectBoundary(entries);expect(JSON.stringify(entries)).toBe(before);
    expect(s26Proposals).toHaveLength(8);
    expect(s26Proposals.map(e=>approveException(e,null,options))).toEqual(s26ProposalHashes);
  });
  it('checks the actual policy without rewriting it',()=>{
    const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
    const before=JSON.stringify(policy);expectBoundary(policy.exceptions);expect(JSON.stringify(policy)).toBe(before);
  });
  it('rejects alteration or removal of every historical record and historical reordering',()=>{
    expectBoundary(candidate());
    for(let i=0;i<160;i++){
      const changed=candidate();changed[i].reason+=' widened';expect(()=>expectBoundary(changed)).toThrow();
      const missing=candidate();missing.splice(i,1);expect(()=>expectBoundary(missing)).toThrow();
    }
    const changed=candidate();[changed[0],changed[1]]=[changed[1],changed[0]];expect(()=>expectBoundary(changed)).toThrow();
  });
  it.each(s26Proposals.map((entry,index)=>({entry,index})))('rejects altered addition $index',({index})=>{
    expectBoundary(candidate());
    for(const mutate of [e=>e.screen='S-27',e=>e.viewport='mobile360',e=>e.theme='dark',e=>e.approvalPr=79,
      e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',
      e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.approved=true]){
      const entries=candidate();mutate(entries[160+index]);expect(()=>expectBoundary(entries)).toThrow();
    }
  });
  it.each([
    ['missing',e=>e.pop()],['duplicate',e=>e.push(structuredClone(e.at(-1)))],
    ['reordered',e=>{[e[160],e[161]]=[e[161],e[160]];}],
    ['unknown screen',e=>e.push({...structuredClone(e.at(-1)),screen:'S-27'})],
  ])('rejects %s additions',(_,mutate)=>{
    expectBoundary(candidate());const entries=candidate();mutate(entries);expect(()=>expectBoundary(entries)).toThrow();
  });
  it.each(s26Proposals.map((entry,index)=>({entry,index})))('requires actual owner read-back for addition $index',({entry,index})=>{
    // Synthetic unit-test comment only; never policy metadata or owner evidence.
    const comment={id:1,approvalPr:78,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s26ProposalHashes[index]}`};
    expect(approveException(entry,[comment],options)).toBe(true);
    for(const comments of [[],[{...comment,approvalPr:79}],[{...comment,id:0}],
      [{...comment,user:{login:'not-owner'}}],[{...comment,body:'approved generally'}],
      [{...comment,body:`NYAY66-EXCEPTION ${'0'.repeat(64)}`}]] ){
      expect(approveException(entry,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
  it('keeps this fixture outside every runtime module',()=>{
    for(const name of readdirSync(new URL('.',import.meta.url)).filter(n=>n.startsWith('nyay66-')&&n.endsWith('.mjs')&&!n.includes('.test')&&!n.includes('browser-contract')))
      expect(readFileSync(new URL(name,import.meta.url),'utf8')).not.toContain('nyay66-s26-exceptions.test-fixture');
  });
});

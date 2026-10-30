import {s26Proposals,withoutS26ProposalsForTest} from './nyay66-s26-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {approveException,digest,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s21Proposals,s21ProposalHashes,s21Round2Pins,s21Round2Proposals,s21Round2ProposalHashes,withoutS21ProposalsForTest} from './nyay66-s21-exceptions.test-fixture.mjs';
import {s25Proposals,withoutS25ProposalsForTest} from './nyay66-s25-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const options={r2:true,s18:true,s19:true,s20:true,s21:true};
const baseline=JSON.parse(execFileSync('git',['show','f9c84dce4f718eed0d5bb535a1337c0e7f16a189:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const historical=baseline.filter(e=>e.screen!=='S-21');
const targetIndices=s21Round2Pins.map(p=>baseline.findIndex(e=>JSON.stringify(e)===JSON.stringify(s21Proposals[p.index])));
const candidate=()=>[...structuredClone(historical),...structuredClone(s21Round2Proposals)];
function expectBoundary(entries){
  entries=withoutS25ProposalsForTest(withoutS26ProposalsForTest(entries));
  expect(entries).toHaveLength(148);
  expect(JSON.stringify(withoutS21ProposalsForTest(entries))).toBe(JSON.stringify(historical));
  for(let i=0;i<baseline.length;i++){
    const target=targetIndices.indexOf(i);
    if(target<0)expect(JSON.stringify(entries[i])).toBe(JSON.stringify(baseline[i]));
    else expect(approveException(entries[i],null,options)).toBe(s21Round2Pins[target].hash);
  }
}
describe('S-21 Round 2 exact ten destination-host replacements',()=>{
  it('admits only the twelve exact S-25 additions while preserving all 148 existing records',()=>{
    const entries=[...candidate(),...structuredClone(s25Proposals)],before=JSON.stringify(entries);
    expectBoundary(entries);
    expect(JSON.stringify(entries)).toBe(before);
    expect(withoutS25ProposalsForTest(withoutS26ProposalsForTest(entries))).toEqual(candidate());
    for(let i=0;i<entries.length;i++){
      const changed=structuredClone(entries);changed[i].reason+=' widened';
      expect(()=>expectBoundary(changed)).toThrow();
    }
    for(const mutate of [e=>e.pop(),e=>e.push(structuredClone(e.at(-1))),e=>e.shift(),e=>{[e[0],e[1]]=[e[1],e[0]];}]){
      const changed=structuredClone(entries);mutate(changed);
      expect(()=>expectBoundary(changed)).toThrow();
    }
  });
  it('pins only ten changed entries and preserves the other 138 bytes in order',()=>{
    expect(baseline).toHaveLength(148);expect(historical).toHaveLength(132);
    expect(s21Round2Pins).toHaveLength(10);expect(new Set(targetIndices).size).toBe(10);
    expect(targetIndices.every(i=>i>=132)).toBe(true);
    expect(s21Proposals).toEqual(baseline.filter(e=>e.screen==='S-21'));
    expect(s21Proposals.map(e=>approveException(e,null,options))).toEqual(s21ProposalHashes);
    expect(s21Round2Proposals.map(e=>approveException(e,null,options))).toEqual(s21Round2ProposalHashes);
    const entries=candidate(),before=JSON.stringify(entries);
    expectBoundary(entries);
    expect(JSON.stringify(entries)).toBe(before);
    const untouched=entries.filter((_,i)=>!targetIndices.includes(i));
    expect(untouched).toHaveLength(138);
    expect(digest(JSON.stringify(untouched))).toBe('9c80fbd6acd5097690b6ee03c4dc35a28cff3f9b6ab4140e37e67843ef92b7b8');
  });
  it('supports pre-binding and fully replaced test snapshots, never a partial mixture',()=>{
    expect(withoutS21ProposalsForTest(baseline)).toEqual(historical);
    expectBoundary(candidate());
    for(let count=1;count<s21Round2Pins.length;count++){
      const mixed=structuredClone(baseline);
      for(let i=0;i<count;i++)mixed[targetIndices[i]]=structuredClone(s21Round2Proposals[s21Round2Pins[i].index]);
      expect(()=>withoutS21ProposalsForTest(mixed)).toThrow('S21_PROPOSAL_CONTENT_CHANGED');
    }
  });
  it('checks the actual policy against one complete snapshot without rewriting it',()=>{
    const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
    const before=JSON.stringify(policy);
    const hashes=policy.exceptions.filter(e=>e.screen==='S-21').map(e=>approveException(e,null,options));
    if(JSON.stringify(hashes)===JSON.stringify(s21ProposalHashes))expect(withoutS25ProposalsForTest(withoutS26ProposalsForTest(policy.exceptions))).toEqual(baseline);
    else expectBoundary(policy.exceptions);
    expect(JSON.stringify(policy)).toBe(before);
  });
  it('rejects changes to every one of the other 138 records, including six retained S-21 rows',()=>{
    expectBoundary(candidate());
    for(let i=0;i<baseline.length;i++)if(!targetIndices.includes(i)){
      const entries=candidate();entries[i].reason+=' widened';
      expect(()=>expectBoundary(entries)).toThrow();
    }
  });
  it.each(s21Round2Pins)('rejects altered replacement $index identity, scope, bytes or extra fields',pin=>{
    expectBoundary(candidate());
    for(const mutate of [
      e=>e.screen='S-20',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.theme='dark',
      e=>e.approvalPr=72,e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),
      e=>e.reason+=' widened',e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.approved=true,
    ]){
      const entries=candidate();mutate(entries[132+pin.index]);expect(()=>expectBoundary(entries)).toThrow();
    }
    const restored=candidate();restored[132+pin.index]=structuredClone(s21Proposals[pin.index]);
    expect(()=>expectBoundary(restored)).toThrow();
  });
  it.each([
    ['missing replacement',e=>e.splice(targetIndices[0],1)],
    ['duplicate replacement',e=>e.push(structuredClone(e[targetIndices[0]]))],
    ['deleted historical record',e=>e.shift()],
    ['reordered historical records',e=>{[e[0],e[1]]=[e[1],e[0]];}],
    ['reordered replacements',e=>{const[a,b]=targetIndices;[e[a],e[b]]=[e[b],e[a]];}],
    ['eleventh replacement',e=>{e[132]=structuredClone(e[targetIndices[0]]);}],
  ])('rejects %s while preserving full inventory/order',(_,mutate)=>{
    expectBoundary(candidate());
    const entries=candidate();mutate(entries);expect(()=>expectBoundary(entries)).toThrow();
  });
  it.each(s21Round2Pins)('requires real owner read-back for replacement $index; fixture is not approval',pin=>{
    const entry=s21Round2Proposals[pin.index];
    // Synthetic unit-test comment only, never policy metadata or owner evidence.
    const comment={id:1,approvalPr:74,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${pin.hash}`};
    expect(approveException(entry,null,options)).toBe(pin.hash);
    expect(approveException(entry,[comment],options)).toBe(true);
    for(const comments of [[],[{...comment,approvalPr:72}],[{...comment,user:{login:'not-owner'}}],
      [{...comment,id:0}],[{...comment,body:'approved generally'}],
      [{...comment,body:`NYAY66-EXCEPTION ${s21ProposalHashes[pin.index]}`}]]){
      expect(approveException(entry,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
  it('keeps test normalization outside runtime capture, evaluation and import',()=>{
    for(const name of ['nyay66-enforcement.mjs','nyay66-continuation.mjs','nyay66-s19-import.mjs','nyay66-s20-import.mjs','nyay66-s21-import.mjs','nyay66-s21-live.mjs','nyay66-s21-capture.mjs']){
      const code=readFileSync(new URL(name,import.meta.url),'utf8');
      expect(code).not.toContain('nyay66-s21-exceptions.test-fixture');
      expect(code).not.toContain('nyay66-s25-exceptions.test-fixture');
      expect(code).not.toContain('s21Round2');
    }
  });
});

it('validates the eight exact S-26 additions before applying historical assertions',()=>{
  expectBoundary([...candidate(),...structuredClone(s25Proposals),...structuredClone(s26Proposals)]);
});

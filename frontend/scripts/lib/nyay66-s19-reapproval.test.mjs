import {s27Proposals,withoutS27ProposalsForTest} from './nyay66-s27-exceptions.test-fixture.mjs';
import {s26Proposals,withoutS26ProposalsForTest} from './nyay66-s26-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {approveException,canonical,digest,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {s19RasterPredecessor,s19RasterReplacement,normalizeS19RasterForTest} from './nyay66-s19-reapproval.test-fixture.mjs';
import {s21Proposals,withoutS21ProposalsForTest} from './nyay66-s21-exceptions.test-fixture.mjs';
import {s25Proposals,s25ProposalHashes,historicalS25ExceptionsSha256,withoutS25ProposalsForTest} from './nyay66-s25-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const options={r2:true,s18:true,s19:true,s20:true};
const original=JSON.parse(execFileSync('git',['show','f458307c04ba81907395b0a2f29325c4f9aefde3:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const target=original.findIndex(e=>canonical(e)===canonical(s19RasterPredecessor));
const candidate=()=>{const entries=structuredClone(original);entries[target]=structuredClone(s19RasterReplacement);return entries;};
function expectPreserved(entries){expect(JSON.stringify(normalizeS19RasterForTest(entries))).toBe(JSON.stringify(original));}
// Exact test-only pins for the ten owner-approved copy replacements on PR #72.
// They do not grant runtime approval: the hosted gate still reads owner comments.
const beforeCopy=JSON.parse(execFileSync('git',['show','4a0fda47720d10848deaff86786b8aeeda2de475:frontend/scripts/nyay66-policy.json'],{cwd:root})).exceptions;
const copyPins=[
  ['results mobile390','e34b3f263b363f887ef287f6ac619d23554c390ea7c7d63d0c5eb7c53fa6f80a','7871b3999e42b62dc02b4e218f677d4935a9cde040e42fe54567715d6310cc9a',6267075234],
  ['results desktop','470974124e4c077c702d3b8074d73a61c25aefbb95aa3759120b932d661c8045','25932ab1568ae72da2cc5b076f40ee8970742ad9a2245aff3f4e48f623b6aab8',6267077581],
  ['filters-open mobile390','7862c08a3747458379626c28cfd4f7b5a79f74a0ca2603bc19da96dad7bc9807','e736209338cf89bc25e57ed46d61174fe4f9524fc625722f977fc8b550f65e7b',6267079805],
  ['filters-open desktop','2332c15dc38322e1de2cb827cab9a85b9ffe522b15788fb4657bb657db6cf315','a667c79985a2137b6194b6d020118962e3b63045f60fa0fc454ba9d88252648f',6267082217],
  ['partial mobile390','ec52e6fdcfc90656ba26964a82771a4b82222a72874b6cf9949c2785dd2a53aa','4cb57bacae5b98a42cee5d0891385c35bea30ea3ead84ed28c89cac6d6bc1316',6267084353],
  ['partial desktop','e8ec75a2011488cf5fd03100190d901d8bcd29990329b4b78f94553dc676d598','5a5bfb9c594d9ebb6e18688c7e057753d85a47c2d6f9e5469af74894742a9429',6267086276],
  ['save-failed mobile390','e1972cf56396fecc667b34abb4b810eafd570a76fc9d8d66a8280befbcb8daf1','006b2c55f64781b5809d0feb48548eada24e90f1828fa1fddf87a100fc0be105',6267088643],
  ['save-failed desktop','49b1069380dc96c6d6b116abaacd109137efc6b6aca435b34103d67f0515f69e','e5e951d0b88a1ecbcd0690d63033711a63ee66a230d9fb72e3bcef60aea2ec14',6267090344],
  ['local-empty mobile390','b2f1de3e84fe970b4cab59d953e43435b91a92e5f97a1f7ef1b789418231ebba','65b8f0e3c98e6067c4325f58607f837830ea6c8d05dfa381ce1ee1bf38dafb59',6267091869],
  ['local-empty desktop','8e979e5ba453a879b4350687a60837efd129a606adeb285ad28f12bdf4273299','c1e57161fa970c6f1363063c75894db0d423b79659c04fce7edac6210fc6c2bb',6267092793],
].map(([label,previousHash,hash,commentId])=>({label,previousHash,hash,commentId,index:beforeCopy.findIndex(e=>approveException(e,null,options)===previousHash)}));
const currentPolicy=()=>JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url))).exceptions;
function expectApprovedCopyBoundary(entries){
  // Validate the exact additive set before retaining the unchanged historical checks.
  const historical=withoutS21ProposalsForTest(withoutS25ProposalsForTest(withoutS26ProposalsForTest(withoutS27ProposalsForTest(entries))));
  expect(historical).toHaveLength(beforeCopy.length);
  const normalized=historical.map((entry,index)=>{
    const pin=copyPins.find(p=>p.index===index);
    if(pin)expect(approveException(entry,null,options)).toBe(pin.hash);
    else expect(JSON.stringify(entry)).toBe(JSON.stringify(beforeCopy[index]));
    // Only the ten exact pinned entries normalize to their prior test snapshot.
    // No runtime data, approval lookup, policy bytes or historical evidence changes.
    return structuredClone(pin?beforeCopy[index]:entry);
  });
  expectPreserved(normalized);
}
describe('S-25 additions retain the S-19/S-20 historical regression boundary',()=>{
  const historical=()=>withoutS25ProposalsForTest(withoutS26ProposalsForTest(withoutS27ProposalsForTest(currentPolicy())));
  const candidate=()=>[...historical(),...structuredClone(s25Proposals)];
  const s25Options={...options,s21:true,s25:true};
  it('admits only the twelve pinned additions without mutating the 148 historical records',()=>{
    const baseline=historical();
    expect(baseline).toHaveLength(148);
    expect(digest(JSON.stringify(baseline))).toBe(historicalS25ExceptionsSha256);
    expect(s25Proposals).toHaveLength(12);
    expect(s25Proposals.map(e=>approveException(e,null,s25Options))).toEqual(s25ProposalHashes);
    for(const entries of [baseline,candidate(),currentPolicy()]){
      const before=JSON.stringify(entries);
      expectApprovedCopyBoundary(entries);
      expect(JSON.stringify(withoutS25ProposalsForTest(withoutS26ProposalsForTest(withoutS27ProposalsForTest(entries))))).toBe(JSON.stringify(baseline));
      expect(JSON.stringify(entries)).toBe(before);
    }
  });
  it('rejects altered S-25 identity, scope, hashes, checks and fields before historical comparison',()=>{
    expectApprovedCopyBoundary(candidate());
    for(let index=0;index<s25Proposals.length;index++)for(const mutate of [
      e=>e.approvalPr=74,e=>e.screen='S-26',e=>e.viewport='mobile360',e=>e.theme='dark',
      e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',
      e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.arbitrary=true,
    ]){
      const entries=candidate();mutate(entries[148+index]);
      expect(()=>expectApprovedCopyBoundary(entries)).toThrow();
    }
  });
  it('rejects partial or duplicate additions and changes to any historical record',()=>{
    expectApprovedCopyBoundary(candidate());
    for(let count=1;count<12;count++){
      expect(()=>expectApprovedCopyBoundary([...historical(),...structuredClone(s25Proposals.slice(0,count))])).toThrow();
    }
    for(let index=0;index<148;index++){
      const entries=candidate();entries[index].reason+=' widened';
      expect(()=>expectApprovedCopyBoundary(entries)).toThrow();
    }
    for(const mutate of [
      e=>e.push(structuredClone(e.at(-1))),e=>{e[149]=structuredClone(e[148]);},
      e=>e.shift(),e=>{[e[0],e[1]]=[e[1],e[0]];},
    ]){
      const entries=candidate();mutate(entries);expect(()=>expectApprovedCopyBoundary(entries)).toThrow();
    }
  });
  it.each(s25Proposals.map((entry,index)=>({entry,hash:s25ProposalHashes[index],index})))('requires exact owner/PR read-back for S-25 addition $index; test pins are not approval',({entry,hash})=>{
    // Synthetic unit-test comment only, never persisted as owner evidence.
    const comment={id:1,approvalPr:76,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`};
    expect(approveException(entry,[comment],s25Options)).toBe(true);
    for(const comments of [[],[{...comment,approvalPr:74}],[{...comment,user:{login:'not-owner'}}],
      [{...comment,id:0}],[{...comment,body:'approved generally'}],
      [{...comment,body:`NYAY66-EXCEPTION ${'a'.repeat(64)}`}],
    ]){
      expect(approveException(entry,comments,s25Options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,s25Options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
});
describe('ten exact S-20 copy replacements, not a general exception allowance',()=>{
  it.each([false,true])('preserves all 132 historical records with exact S-21 additions: %s',withS21=>{
    const historical=withoutS25ProposalsForTest(withoutS26ProposalsForTest(withoutS27ProposalsForTest(currentPolicy()))).filter(e=>e.screen!=='S-21');
    const entries=[...historical,...(withS21?structuredClone(s21Proposals):[])],before=JSON.stringify(entries);
    expect(historical).toHaveLength(132);
    expectApprovedCopyBoundary(entries);
    expect(JSON.stringify(entries)).toBe(before);
  });
  it('rejects every altered S-21 addition before comparing the historical boundary',()=>{
    const candidate=()=>[...withoutS25ProposalsForTest(withoutS26ProposalsForTest(withoutS27ProposalsForTest(currentPolicy()))).filter(e=>e.screen!=='S-21'),...structuredClone(s21Proposals)];
    expectApprovedCopyBoundary(candidate());
    for(let index=0;index<s21Proposals.length;index++)for(const mutate of [
      e=>e.approvalPr=73,e=>e.screen='S-22',e=>e.viewport='mobile360',e=>e.theme='dark',
      e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',
      e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.arbitrary=true,
    ]){
      const changed=candidate();mutate(changed[132+index]);
      expect(()=>expectApprovedCopyBoundary(changed)).toThrow();
    }
    for(const mutate of [
      e=>e.pop(),e=>e.push(structuredClone(e.at(-1))),e=>{e[133]=structuredClone(e[132]);},
      e=>e.shift(),e=>{[e[0],e[1]]=[e[1],e[0]];},
    ]){
      const changed=candidate();mutate(changed);expect(()=>expectApprovedCopyBoundary(changed)).toThrow();
    }
  });
  it('accepts all ten pinned replacements while preserving the other 122 records and historical boundary',()=>{
    expect(beforeCopy).toHaveLength(132);expect(copyPins).toHaveLength(10);
    expect(new Set(copyPins.map(p=>p.index)).size).toBe(10);
    expectPreserved(beforeCopy);
    for(const pin of copyPins){
      expect(pin.index).toBeGreaterThanOrEqual(0);
      expect(beforeCopy[pin.index].screen).toBe('S-20');
      expect(beforeCopy[pin.index].viewport).toBe(pin.label.split(' ')[1]);
      expect(approveException(beforeCopy[pin.index],null,options)).toBe(pin.previousHash);
    }
    const entries=currentPolicy(),before=JSON.stringify(entries);
    expectApprovedCopyBoundary(entries);expect(JSON.stringify(entries)).toBe(before);
    expect(entries.filter((e,i)=>JSON.stringify(e)===JSON.stringify(beforeCopy[i]))).toHaveLength(122);
  });
  it('rejects changes to every other record, including the already-approved S-19 replacement',()=>{
    for(let i=0;i<beforeCopy.length;i++)if(!copyPins.some(p=>p.index===i)){
      const changed=currentPolicy();changed[i].reason+=' widened';expect(()=>expectApprovedCopyBoundary(changed)).toThrow();
    }
  });
  it.each(copyPins)('rejects altered $label scope, pixels, identity, checks or extra fields',pin=>{
    for(const mutate of [
      e=>e.approvalPr=70,e=>e.screen='S-18',e=>e.viewport=e.viewport==='desktop'?'mobile390':'desktop',e=>e.theme='dark',
      e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',
      e=>e.checks.push('accessibility'),e=>e.checks=['pixels'],e=>e.arbitrary=true,
    ]){
      const changed=currentPolicy();mutate(changed[pin.index]);expect(()=>expectApprovedCopyBoundary(changed)).toThrow();
    }
    const restored=currentPolicy();restored[pin.index]=structuredClone(beforeCopy[pin.index]);
    expect(()=>expectApprovedCopyBoundary(restored)).toThrow();
  });
  it.each([
    ['missing replacement',e=>e.splice(copyPins[0].index,1)],
    ['duplicate replacement',e=>e.push(structuredClone(e[copyPins[0].index]))],
    ['deleted unrelated record',e=>e.shift()],
    ['reordered replacements',e=>{const [a,b]=copyPins;[e[a.index],e[b.index]]=[e[b.index],e[a.index]];}],
    ['reordered historical records',e=>{[e[0],e[1]]=[e[1],e[0]];}],
    ['replaced eleventh entry',e=>{const i=beforeCopy.findIndex((x,i)=>x.screen==='S-20'&&!copyPins.some(p=>p.index===i));e[i]=structuredClone(e[copyPins[0].index]);}],
  ])('rejects %s without weakening inventory or order',(_,mutate)=>{
    const changed=currentPolicy();mutate(changed);expect(()=>expectApprovedCopyBoundary(changed)).toThrow();
  });
  it.each(copyPins)('still requires exact owner/PR approval for $label; old approvals cannot authorize it',pin=>{
    const entry=currentPolicy()[pin.index];expect(approveException(entry,null,options)).toBe(pin.hash);
    const comment={id:pin.commentId,approvalPr:72,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${pin.hash}`};
    expect(approveException(entry,[comment],options)).toBe(true);
    for(const comments of [[],[{...comment,approvalPr:70}],[{...comment,user:{login:'not-owner'}}],[{...comment,id:0}],
      [{...comment,body:'approved generally'}],[{...comment,body:`NYAY66-EXCEPTION ${pin.previousHash}`}]] ){
      expect(approveException(entry,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
  });
});
describe('single S-19 raster replacement regression boundary, not approval',()=>{
  it('preserves all 131 other exception records byte-for-byte and in order',()=>{
    expect(original).toHaveLength(132);expect(target).toBeGreaterThanOrEqual(0);
    expectPreserved(candidate());
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

it('validates only the eight S-26 additions before preserving the historical copy boundary',()=>{
  const entries=[...withoutS26ProposalsForTest(withoutS27ProposalsForTest(currentPolicy())),...structuredClone(s26Proposals)];
  const before=JSON.stringify(entries);expectApprovedCopyBoundary(entries);expect(JSON.stringify(entries)).toBe(before);
  for(let i=0;i<8;i++){
    const changed=structuredClone(entries);changed.at(-8+i).reason+=' widened';
    expect(()=>expectApprovedCopyBoundary(changed)).toThrow();
  }
});

it('validates exactly 22 S-27 additions before the historical copy boundary',()=>{
  const entries=[...currentPolicy().filter(e=>e.screen!=='S-27'),...structuredClone(s27Proposals)],before=JSON.stringify(entries);expectApprovedCopyBoundary(entries);expect(JSON.stringify(entries)).toBe(before);
});

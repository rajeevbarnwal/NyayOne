import {s26Proposals,withoutS26ProposalsForTest} from './nyay66-s26-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException,digest} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S20_STATES} from './nyay66-s20-reference.mjs';
import {s19RasterPredecessor,s19RasterReplacement,normalizeS19RasterForTest} from './nyay66-s19-reapproval.test-fixture.mjs';
import {s21Proposals,withoutS21ProposalsForTest} from './nyay66-s21-exceptions.test-fixture.mjs';
import {s25Proposals,withoutS25ProposalsForTest} from './nyay66-s25-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const previous={r2:true,s18:true,s19:true},options={...previous,s20:true};
const rows=()=>S20_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-20',state:`S-20-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,evidenceKind:'live-route',syntheticServer:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[]})));
const readPolicy=()=>JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
const referenceRows=JSON.parse(readFileSync(new URL(`../../test-baselines/nyay66/${readPolicy().s20.cache}/manifest.json`,import.meta.url))).rows;
// Test-only candidate entries, never production approvals or PR comments.
const proposals=()=>referenceRows.map(row=>({screen:'S-20',viewport:row.viewport,theme:'light',referenceSha256:row.sha256,liveSha256:'a'.repeat(64),checks:['text'],reason:'synthetic regression fixture only',approvalPr:72}));
function expectS20Policy(policy){
  expect(policy.enforced).not.toContain('S-20');
  // Validate the exact additive set before retaining the unchanged historical checks.
  const historical=withoutS21ProposalsForTest(withoutS25ProposalsForTest(withoutS26ProposalsForTest(policy.exceptions)));
  const existing=normalizeS19RasterForTest(historical).filter(e=>e.screen!=='S-20');
  expect(existing).toHaveLength(112);
  expect(digest(JSON.stringify(existing))).toBe('f01c59f4e3fa842d9b0ca2b6145b4f595e05951aeabbbae906d2e63f56ba9814');
  const seen=new Set();
  for(const entry of policy.exceptions.filter(e=>e.screen==='S-20')){
    expect(entry.approvalPr).toBe(72);
    expect(approveException(entry,null,options)).toMatch(/^[a-f0-9]{64}$/);
    const key=`${entry.viewport}:${entry.referenceSha256}`;
    expect(referenceRows.some(row=>`${row.viewport}:${row.sha256}`===key)).toBe(true);
    expect(seen.has(key)).toBe(false);seen.add(key);
    // Structural validity is not approval. The unchanged hosted finalizer must
    // read an exact owner comment; an unsigned policy record still fails closed.
    expect(approveException(entry,[],options)).toBe(false);
    expect(()=>finalizeEnforcement(rows(),{enforced:[],exceptions:[entry]},[],options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  }
}
describe('S-20 additive product capture inventory',()=>{
  it('admits only the twelve exact S-25 additions without altering historical policy checks',()=>{
    const policy=readPolicy();
    policy.exceptions=[...withoutS25ProposalsForTest(withoutS26ProposalsForTest(policy.exceptions)),...structuredClone(s25Proposals)];
    const before=JSON.stringify(policy);
    expectS20Policy(policy);
    expect(JSON.stringify(policy)).toBe(before);
    for(let i=0;i<12;i++){
      const changed=structuredClone(policy);changed.exceptions.at(-12+i).reason+=' widened';
      expect(()=>expectS20Policy(changed)).toThrow();
    }
    for(const mutate of [e=>e.pop(),e=>e.push(structuredClone(e.at(-1))),e=>e.shift(),e=>{[e[0],e[1]]=[e[1],e[0]];}]){
      const changed=structuredClone(policy);mutate(changed.exceptions);
      expect(()=>expectS20Policy(changed)).toThrow();
    }
  });
  it.each([false,true])('preserves S-20 provenance and historical settings with exact S-21 additions: %s',withS21=>{
    const policy=readPolicy();
    policy.exceptions=[...policy.exceptions.filter(e=>e.screen!=='S-21'),...(withS21?structuredClone(s21Proposals):[])];
    const before=JSON.stringify(policy);
    expectS20Policy(policy);
    expect(JSON.stringify(policy)).toBe(before);
  });
  it('rejects every altered S-21 addition without masking S-20 rejection checks',()=>{
    const candidate=()=>{
      const policy=readPolicy();
      policy.exceptions=[...withoutS25ProposalsForTest(withoutS26ProposalsForTest(policy.exceptions)).filter(e=>e.screen!=='S-21'),...structuredClone(s21Proposals)];
      return policy;
    };
    expectS20Policy(candidate());
    for(let index=0;index<s21Proposals.length;index++)for(const mutate of [
      e=>e.approvalPr=73,e=>e.screen='S-22',e=>e.viewport='mobile360',e=>e.theme='dark',
      e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.reason+=' widened',
      e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.arbitrary=true,
    ]){
      const changed=candidate();mutate(changed.exceptions[132+index]);
      expect(()=>expectS20Policy(changed)).toThrow();
    }
    for(const mutate of [
      e=>e.pop(),e=>e.push(structuredClone(e.at(-1))),e=>{e[133]=structuredClone(e[132]);},
      e=>e.shift(),e=>{[e[0],e[1]]=[e[1],e[0]];},
    ]){
      const changed=candidate();mutate(changed.exceptions);expect(()=>expectS20Policy(changed)).toThrow();
    }
  });
  it('allows the pinned one-row S-19 raster replacement while retaining the pre-S-20 policy contract',()=>{
    const policy=readPolicy();
    const index=policy.exceptions.findIndex(e=>e.referenceSha256===s19RasterPredecessor.referenceSha256&&e.viewport===s19RasterPredecessor.viewport);
    policy.exceptions[index]=structuredClone(s19RasterReplacement);
    expect(()=>expectS20Policy(policy)).not.toThrow();
  });
  it('adds exactly 20 rows to the existing 142 without changing their identities or dark coverage',()=>{
    const all=lightRowInventory(options);
    expect(all).toHaveLength(162);
    expect(all.filter(r=>r.screen!=='S-20')).toEqual(lightRowInventory(previous));
    expect(all.filter(r=>r.screen==='S-20').map(r=>`${r.state}:${r.viewport}`).sort()).toEqual(rows().map(r=>`${r.state}:${r.viewport}`).sort());
    expect(coverage('dark',options)).toEqual(coverage('dark',previous));
  });
  it('replaces only the 20 S-20 gaps and preserves existing report rows, blockers and manual gaps',()=>{
    const old=lightRowInventory(previous).map(r=>({...r,executed:true,measured:true,verdict:'PARITY'}));
    const before={rows:[...old,...rows()],blocking:true,expectedLightRows:74,failures:['existing']};
    const result=appendContinuation(before,data,options);
    expect(result.rows.slice(0,142)).toEqual(old);
    expect(result.rows.filter(r=>r.screen==='S-20')).toHaveLength(20);
    expect(result.continuation.measuredLightRows).toBe(88);
    expect(result.continuation.unmeasuredLightRows).toBe(294);
    expect(result.continuation.importedReferenceRows).toBe(90);
    expect(result.rows.filter(r=>r.state?.endsWith('option-manual'))).toHaveLength(4);
    expect(result.rows.filter(r=>r.state?.endsWith('option-manual')).every(r=>r.verdict==='DESIGN-GAP'&&!r.executed&&!r.measured)).toBe(true);
    expect(result.blocking).toBe(before.blocking);expect(result.failures).toEqual(before.failures);expect(result.expectedLightRows).toBe(74);
  });
  it('rejects missing, duplicate, or unknown S-20 rows instead of replacing them with gaps',()=>{
    const all=rows();
    for(const broken of [all.slice(1),[...all,all[0]],all.map((r,i)=>i?r:{...r,state:'S-20-invented'})])
      expect(()=>appendContinuation({rows:broken},data,{s20:true})).toThrow('S20_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('does not call failed captures measured or waive unapproved visual differences',()=>{
    const all=rows();all[0].metrics.pass=false;
    const result=finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options);
    expect(result.failures).toEqual([]);expect(result.rows[0].verdict).toBe('NONCONFORMANT');
    all[1].verdict='CAPTURE-FAILED';all[1].measured=false;
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).blocking).toBe(true);
    expect(appendContinuation({rows:all},data,{s20:true}).continuation.measuredLightRows).toBe(19);
  });
  it('requires exact owner approval for S-20 exceptions without changing enforcement settings',()=>{
    const entry={screen:'S-20',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['text'],reason:'synthetic test only',approvalPr:72};
    expect(approveException(entry,null,options)).toMatch(/^[a-f0-9]{64}$/);
    expect(approveException(entry,[],options)).toBe(false);
    expect(()=>finalizeEnforcement(rows(),{enforced:[],exceptions:[entry]},[],options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expectS20Policy(readPolicy());
  });
  it('permits 20 structurally valid S-20 additions but still rejects them without owner comments',()=>{
    const policy=readPolicy();policy.exceptions=policy.exceptions.filter(e=>e.screen!=='S-20').concat(proposals());
    expectS20Policy(policy);
    expect(()=>finalizeEnforcement(rows(),{enforced:[],exceptions:proposals()},[],options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  });
  it.each([
    ['changed existing scope',p=>{p.exceptions[0].reason+=' changed';}],
    ['deleted existing exception',p=>{p.exceptions.shift();}],
    ['reordered existing exceptions',p=>{[p.exceptions[0],p.exceptions[1]]=[p.exceptions[1],p.exceptions[0]];}],
    ['wrong PR',p=>{p.exceptions.at(-1).approvalPr=71;}],
    ['unknown reference',p=>{p.exceptions.at(-1).referenceSha256='0'.repeat(64);}],
    ['invalid live hash',p=>{p.exceptions.at(-1).liveSha256='invalid';}],
    ['unsupported accessibility waiver',p=>{p.exceptions.at(-1).checks=['accessibility'];}],
    ['duplicate row',p=>{p.exceptions.push({...p.exceptions.at(-1)});}]
  ])('rejects %s while admitting S-20 additions',(_label,change)=>{
    const policy=readPolicy();policy.exceptions=policy.exceptions.filter(e=>e.screen!=='S-20').concat(proposals());
    change(policy);expect(()=>expectS20Policy(policy)).toThrow();
  });
  it('still requires the exact owner/PR/hash for each exception, not merely a valid-shaped entry',()=>{
    const entry=proposals()[0],hash=approveException(entry,null,options);
    const comment={id:1,approvalPr:72,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`};
    const captured=rows();captured[0]={...captured[0],referenceSha256:entry.referenceSha256,liveSha256:entry.liveSha256,structure:['text']};
    const config={enforced:[],exceptions:[entry]};
    expect(finalizeEnforcement(captured,config,[comment],options).rows[0].verdict).toBe('PARITY-WITH-DISCLOSED-DELTA');
    for(const comments of [[],[{...comment,user:{login:'not-the-owner'}}],[{...comment,approvalPr:71}],[{...comment,id:0}],[{...comment,body:`NYAY66-EXCEPTION ${'0'.repeat(64)}`}]] ){
      expect(approveException(entry,comments,options)).toBe(false);
      expect(()=>finalizeEnforcement(captured,config,comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    }
    for(const changed of [{...entry,reason:entry.reason+' widened'},{...entry,liveSha256:'b'.repeat(64)}])
      expect(()=>finalizeEnforcement(captured,{...config,exceptions:[changed]},[comment],options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  });
  it('wires verified cache loading, live capture and coverage accounting into the hosted entry point',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS20Cache(root,config.s20,continuation,manifest.fonts)');
    expect(live).toContain('await captureS20Rows({browser,origin,out,reference:s20})');
    expect(live.match(/s20:!!s20/g)).toHaveLength(2);
  });
});

it('validates the eight exact S-26 additions before applying historical assertions',()=>{
  const policy=readPolicy(); policy.exceptions=[...policy.exceptions.filter(e=>e.screen!=='S-26'),...structuredClone(s26Proposals)]; expectS20Policy(policy);
});

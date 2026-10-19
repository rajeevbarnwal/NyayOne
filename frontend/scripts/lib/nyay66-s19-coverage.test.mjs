import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S19_STATES} from './nyay66-s19-reference.mjs';
import {S19_MEASURED_STATES,S19_COVERAGE_APPROVAL} from './nyay66-s19-coverage.mjs';
import {normalizeS19RasterForTest} from './nyay66-s19-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const options={r2:true,s18:true,s19:true};
const rows=()=>lightRowInventory(options).filter(r=>r.screen==='S-19').map(r=>({...r,executed:true,measured:true,verdict:'PARITY',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],evidenceKind:'live-route',
  ...(['S-19-session','S-19-delete-accepted'].includes(r.state)?{evidenceKind:r.state==='S-19-session'?'component-visual':'live-redirect-destination',coverageApproval:S19_COVERAGE_APPROVAL,
    liveRouteBehavior:{executed:true,from:'/s-19',to:'/s-03',syntheticServer:true,artificialDelay:false,navigationFrozen:false,sessionAnonymous:true,...(r.state==='S-19-delete-accepted'?{deletionAccepted:true,noticeObserved:true}: {})}}:{})}));
describe('S-19 additive measured coverage',()=>{
  it('adds exactly 50 rows, preserving the existing 92 and leaving manual unmeasured',()=>{
    expect(S19_MEASURED_STATES).toEqual(S19_STATES.filter(s=>s!=='option-manual'));
    expect(lightRowInventory(options)).toHaveLength(142);
    expect(lightRowInventory(options).filter(r=>r.screen!=='S-19')).toEqual(lightRowInventory({r2:true,s18:true}));
    expect(coverage('dark',options).every(r=>r.status==='DESIGN-GAP')).toBe(true);
  });
  it('replaces exactly 50 S-19 gaps, without changing old report failures or rows',()=>{
    const before={rows:rows(),blocking:true,expectedLightRows:74,failures:['existing']};
    const after=appendContinuation(before,data,{s19:true});
    expect(after.rows.filter(r=>r.screen==='S-19')).toHaveLength(52);
    expect(after.rows.filter(r=>r.state==='S-19-option-manual').every(r=>!r.executed&&!r.measured&&r.verdict==='DESIGN-GAP')).toBe(true);
    expect(after.continuation.unmeasuredLightRows).toBe(332);
    expect(after.rows.slice(0,50)).toEqual(before.rows);
    expect(after.failures).toEqual(before.failures);expect(after.blocking).toBe(true);expect(after.expectedLightRows).toBe(74);
  });
  it('blocks missing or duplicate S-19 coverage instead of concealing it as a design gap',()=>{
    const all=rows();for(const broken of [all.slice(1),[...all,all[0]]])expect(()=>appendContinuation({rows:broken},data,{s19:true})).toThrow('S19_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('requires separate truthful route/session proof and the exact evidence label for transient states',()=>{
    const config={enforced:[],exceptions:[]};expect(finalizeEnforcement(rows(),config,[],options).blocking).toBe(false);
    for(const state of ['S-19-session','S-19-delete-accepted'])for(const change of [r=>delete r.liveRouteBehavior,r=>r.liveRouteBehavior.navigationFrozen=true,r=>r.liveRouteBehavior.sessionAnonymous=false,r=>r.coverageApproval='unapproved',r=>r.evidenceKind='live-route']){
      const bad=rows();change(bad.find(r=>r.state===state));expect(finalizeEnforcement(bad,config,[],options).blocking).toBe(true);
    }
    const bad=rows();bad.find(r=>r.state==='S-19-delete-accepted').liveRouteBehavior.noticeObserved=false;
    expect(finalizeEnforcement(bad,config,[],options).blocking).toBe(true);
  });
  it('requires fresh exact-image exceptions and does not silently enforce S-19',()=>{
    const entry={screen:'S-19',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['text'],reason:'test only',approvalPr:70};
    expect(approveException(entry,[],options)).toBe(false);expect(approveException(entry,null,options)).toMatch(/^[a-f0-9]{64}$/);
    expect(()=>finalizeEnforcement(rows(),{enforced:[],exceptions:[entry]},[],options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
    expect(policy.enforced).not.toContain('S-19');
    for(const proposal of normalizeS19RasterForTest(policy.exceptions).filter(e=>e.screen==='S-19')){
      expect(proposal.approvalPr).toBe(70);expect(approveException(proposal,[],options)).toBe(false);
    }
  });
  it('keeps the component fixture out of production and does not mutate navigation or fetch state',()=>{
    const component=readFileSync(new URL('../nyay66-s19-component.tsx',import.meta.url),'utf8');
    expect(component).toContain('import { PrivacySettingsView }');
    expect(component).not.toMatch(/setTimeout|fetch\(|localStorage|sessionStorage|usePrivacySettings|window.location/);
    expect(readFileSync(new URL('../../src/main.tsx',import.meta.url),'utf8')).not.toContain('nyay66-s19-component');
  });
});

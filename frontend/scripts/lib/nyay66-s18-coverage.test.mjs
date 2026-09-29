import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
const options={r2:true,s18:true};
const measured=()=>lightRowInventory(options).filter(r=>r.screen==='S-18').map(r=>({...r,executed:true,measured:true,verdict:'PARITY',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],
  ...(r.state==='S-18-session'?{evidenceKind:'component-visual',coverageApproval:'NYAY-88:16029',liveRouteBehavior:{executed:true,from:'/s-18',to:'/s-03',syntheticServer:true,artificialDelay:false,navigationFrozen:false}}:{evidenceKind:'live-route'})}));
describe('S-18 measured coverage is additive and honest',()=>{
  it('preserves the 74-row registry and adds exactly 18 default rows only with a verified cache',()=>{
    expect(lightRowInventory({r2:true})).toHaveLength(74);
    const all=lightRowInventory(options);expect(all).toHaveLength(92);
    expect(all.filter(r=>r.screen!=='S-18')).toEqual(lightRowInventory({r2:true}));
    expect(all.some(r=>r.state.includes('manual'))).toBe(false);
    expect(coverage('dark',options).every(r=>r.status==='DESIGN-GAP')).toBe(true);
  });
  it('replaces only 18 S-18 design gaps, leaving the two manual gaps and 362 other gaps',()=>{
    const rows=measured(),before={rows,blocking:false,expectedLightRows:74,failures:[]};
    const got=appendContinuation(before,data,{s18:true});
    expect(got.rows.filter(r=>r.screen==='S-18')).toHaveLength(20);
    expect(got.rows.filter(r=>r.verdict==='DESIGN-GAP')).toHaveLength(364);
    expect(got.rows.filter(r=>r.state==='S-18-option-manual').every(r=>!r.executed&&!r.measured)).toBe(true);
    expect(got.continuation.measuredLightRows).toBe(18);
    expect(got.expectedLightRows).toBe(74);expect(got.blocking).toBe(false);
  });
  it('blocks a missing/duplicate S-18 row instead of silently backfilling a gap',()=>{
    const rows=measured();
    for(const broken of [rows.slice(1),[...rows,rows[0]]])expect(()=>appendContinuation({rows:broken,blocking:false},data,{s18:true})).toThrow('S18_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('requires component AND genuine live-route evidence for session rows',()=>{
    const config={enforced:[],exceptions:[]},rows=measured();
    expect(finalizeEnforcement(rows,config,[],options).blocking).toBe(false);
    for(const change of [r=>delete r.liveRouteBehavior,r=>r.liveRouteBehavior.navigationFrozen=true,r=>r.coverageApproval='unapproved',r=>r.evidenceKind='live-route']){
      const bad=structuredClone(rows);change(bad.find(r=>r.state==='S-18-session'));
      expect(finalizeEnforcement(bad,config,[],options).blocking).toBe(true);
    }
  });
  it('requires fresh exact-image owner approvals; no new exceptions are pre-approved',()=>{
    const entry={screen:'S-18',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['text'],reason:'test only',approvalPr:68};
    expect(approveException(entry,[],options)).toBe(false);
    expect(approveException(entry,null,options)).toMatch(/^[a-f0-9]{64}$/);
    expect(()=>finalizeEnforcement(measured(),{enforced:[],exceptions:[entry]},[],options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expect(policy.enforced).not.toContain('S-18');
  });
  it('keeps session evidence test-only and the existing S-01 builder isolated',()=>{
    const main=readFileSync(new URL('../../src/main.tsx',import.meta.url),'utf8');
    const builder=readFileSync(new URL('../nyay66-s01-component-build.mjs',import.meta.url),'utf8');
    const component=readFileSync(new URL('../nyay66-s18-component.tsx',import.meta.url),'utf8');
    expect(main).not.toContain('nyay66-s18-component');
    expect(builder).toContain("outDir:'dist/__nyay66-components'");
    expect(builder).toContain("outDir:'dist/__nyay66-s18'");
    expect(component).toContain("import { NotificationsSettingsView }");
    expect(component).not.toMatch(/setTimeout|localStorage|sessionStorage|fetch\(|window.location|useNotificationSettings/);
  });
});

import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S20_STATES} from './nyay66-s20-reference.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const previous={r2:true,s18:true,s19:true},options={...previous,s20:true};
const rows=()=>S20_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-20',state:`S-20-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,evidenceKind:'live-route',syntheticServer:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[]})));
describe('S-20 additive product capture inventory',()=>{
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
    const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
    expect(policy.enforced).not.toContain('S-20');expect(policy.exceptions.filter(e=>e.screen==='S-20')).toEqual([]);
  });
  it('wires verified cache loading, live capture and coverage accounting into the hosted entry point',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS20Cache(root,config.s20,continuation,manifest.fonts)');
    expect(live).toContain('await captureS20Rows({browser,origin,out,reference:s20})');
    expect(live.match(/s20:!!s20/g)).toHaveLength(2);
  });
});

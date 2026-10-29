import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S25_MEASURED_STATES,hasS25LiveProof} from './nyay66-s25-coverage.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const previous={r2:true,s18:true,s19:true,s20:true,s21:true},options={...previous,s25:true};
const rows=()=>S25_MEASURED_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-25',state:`S-25-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],evidenceKind:'live-route',syntheticServer:true,navigationFrozen:false,artificialDelay:false,routeProof:{path:'/s-25',state,requestSequenceVerified:true,serverConfirmationVerified:true}})));
describe('S-25 additive product coverage',()=>{
  it('adds exactly 12 light rows without changing the 178 existing identities or dark inventory',()=>{
    expect(S25_MEASURED_STATES).toEqual(['loading','list','empty','remove-pending','remove-failed','error']);
    const all=lightRowInventory(options);expect(all).toHaveLength(190);
    expect(all.filter(r=>r.screen!=='S-25')).toEqual(lightRowInventory(previous));
    expect(all.filter(r=>r.screen==='S-25').map(r=>`${r.state}:${r.viewport}`).sort()).toEqual(rows().map(r=>`${r.state}:${r.viewport}`).sort());
    expect(coverage('dark',options)).toEqual(coverage('dark',previous));
  });
  it('replaces only S-25 gaps and preserves all earlier rows, manual gaps and blocking results',()=>{
    const old=lightRowInventory(previous).map(r=>({...r,executed:true,measured:true,verdict:'PARITY'}));
    const result=appendContinuation({rows:[...old,...rows()],blocking:true,expectedLightRows:74,failures:['existing']},data,options);
    expect(result.rows.slice(0,178)).toEqual(old);expect(result.rows.filter(r=>r.screen==='S-25')).toHaveLength(12);
    expect(result.continuation.measuredLightRows).toBe(116);expect(result.continuation.unmeasuredLightRows).toBe(266);expect(result.continuation.importedReferenceRows).toBe(118);
    const manual=result.rows.filter(r=>r.state?.endsWith('option-manual'));expect(manual).toHaveLength(4);expect(manual.every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);expect(result.failures).toEqual(['existing']);
    expect(appendContinuation({rows:[]},data).rows.filter(r=>r.screen==='S-25').every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
  });
  it('fails closed on missing, duplicate or invented S-25 rows',()=>{
    const all=rows();for(const broken of [all.slice(1),[...all,all[0]],all.map((r,i)=>i?r:{...r,state:'S-25-invented'})])expect(()=>appendContinuation({rows:broken},data,{s25:true})).toThrow('S25_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('rejects failed captures or incomplete route/server-confirmation proof',()=>{
    const all=rows();all[0].verdict='CAPTURE-FAILED';all[0].measured=false;
    expect(appendContinuation({rows:all},data,{s25:true}).continuation.measuredLightRows).toBe(11);
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).blocking).toBe(true);
    const row=rows()[0];expect(hasS25LiveProof(row)).toBe(true);expect(hasS25LiveProof({screen:'S-21'})).toBe(true);
    for(const change of [{evidenceKind:'component-visual'},{syntheticServer:false},{navigationFrozen:true},{artificialDelay:true},{routeProof:null},{routeProof:{...row.routeProof,path:'/s-20'}},{routeProof:{...row.routeProof,state:'invented'}},{routeProof:{...row.routeProof,requestSequenceVerified:false}},{routeProof:{...row.routeProof,serverConfirmationVerified:false}}]){
      const bad={...row,...change};expect(hasS25LiveProof(bad)).toBe(false);expect(finalizeEnforcement([bad],{enforced:[],exceptions:[]},[],options).rows[0].verdict).toBe('CAPTURE-FAILED');
    }
  });
  it('never waives differences, serious accessibility failures or unsigned exceptions',()=>{
    const all=rows();all[0].metrics.pass=false;all[1].accessibility=[{impact:'serious'}];
    const evaluated=finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options);expect(evaluated.rows.slice(0,2).map(r=>r.verdict)).toEqual(['NONCONFORMANT','NONCONFORMANT']);
    const entry={screen:'S-25',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['pixels'],reason:'test only',approvalPr:76};
    const hash=approveException(entry,null,options);expect(hash).toMatch(/^[a-f0-9]{64}$/);
    for(const comments of [[],[{id:1,approvalPr:76,user:{login:'not-owner'},body:`NYAY66-EXCEPTION ${hash}`}],[{id:1,approvalPr:75,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}]] )expect(()=>finalizeEnforcement(all,{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expect(approveException({...entry,checks:['accessibility']},null,options)).toBe(false);
  });
  it('loads the verified cache and captures S-25 only after all 178 historical rows',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS25Cache(root,config.s25,continuation,manifest.fonts)');
    expect(live).toContain('await captureS25Rows({browser,origin,out,reference:s25})');
    expect(live.indexOf('await captureS25Rows')).toBeGreaterThan(live.indexOf('await captureS21Rows'));
    expect(live.match(/s25:!!s25/g)).toHaveLength(2);
  });
});

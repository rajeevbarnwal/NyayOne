import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S31_MEASURED_STATES,hasS31LiveProof} from './nyay66-s31-coverage.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const previous={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true,s29:true,s30:true},options={...previous,s31:true};
const rows=()=>S31_MEASURED_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-31',state:`S-31-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],evidenceKind:'live-route',syntheticServer:true,navigationFrozen:false,artificialDelay:false,routeProof:{path:'/s-31',state,requestSequenceVerified:true,serverConfirmationVerified:true,searchPaginationVerified:true}})));
describe('S-31 additive product coverage',()=>{
  it('adds exactly 16 light rows without changing the 262 existing identities or dark inventory',()=>{
    expect(S31_MEASURED_STATES).toEqual(['loading','results','filters-open','no-matches','rate-limited','error','offline','page-2']);
    const all=lightRowInventory(options);expect(all).toHaveLength(278);
    expect(all.filter(r=>r.screen!=='S-31')).toEqual(lightRowInventory(previous));
    expect(all.filter(r=>r.screen==='S-31').map(r=>`${r.state}:${r.viewport}`).sort()).toEqual(rows().map(r=>`${r.state}:${r.viewport}`).sort());
    expect(coverage('dark',options)).toEqual(coverage('dark',previous));
  });
  it('replaces only S-31 gaps and preserves all earlier rows, manual gaps and blocking results',()=>{
    const old=lightRowInventory(previous).map(r=>({...r,executed:true,measured:true,verdict:'PARITY'}));
    const result=appendContinuation({rows:[...old,...rows()],blocking:true,expectedLightRows:74,failures:['existing']},data,options);
    expect(result.rows.slice(0,262)).toEqual(old);expect(result.rows.filter(r=>r.screen==='S-31')).toHaveLength(16);
    expect(result.continuation.measuredLightRows).toBe(204);expect(result.continuation.unmeasuredLightRows).toBe(178);expect(result.continuation.importedReferenceRows).toBe(206);
    const manual=result.rows.filter(r=>r.state?.endsWith('option-manual'));expect(manual).toHaveLength(4);expect(manual.every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);expect(result.failures).toEqual(['existing']);
    expect(appendContinuation({rows:[]},data).rows.filter(r=>r.screen==='S-31').every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
  });
  it('fails closed on missing, duplicate or invented S-31 rows',()=>{
    const all=rows();for(const broken of [all.slice(1),[...all,all[0]],all.map((r,i)=>i?r:{...r,state:'S-31-invented'})])expect(()=>appendContinuation({rows:broken},data,{s31:true})).toThrow('S31_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('rejects failed captures or incomplete route/server-confirmation proof',()=>{
    const all=rows();all[0].verdict='CAPTURE-FAILED';all[0].measured=false;
    expect(appendContinuation({rows:all},data,{s31:true}).continuation.measuredLightRows).toBe(15);
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).blocking).toBe(true);
    const row=rows()[0];expect(hasS31LiveProof(row)).toBe(true);expect(hasS31LiveProof({screen:'S-27'})).toBe(true);
    for(const change of [{evidenceKind:'component-visual'},{syntheticServer:false},{navigationFrozen:true},{artificialDelay:true},{routeProof:null},{routeProof:{...row.routeProof,path:'/s-20'}},{routeProof:{...row.routeProof,path:'/s-25'}},{routeProof:{...row.routeProof,state:'invented'}},{routeProof:{...row.routeProof,requestSequenceVerified:false}},{routeProof:{...row.routeProof,serverConfirmationVerified:false}},{routeProof:{...row.routeProof,searchPaginationVerified:false}}]){
      const bad={...row,...change};expect(hasS31LiveProof(bad)).toBe(false);expect(finalizeEnforcement([bad],{enforced:[],exceptions:[]},[],options).rows[0].verdict).toBe('CAPTURE-FAILED');
    }
  });
  it('never waives differences, serious accessibility failures or unsigned exceptions',()=>{
    const all=rows();all[0].metrics.pass=false;all[1].accessibility=[{impact:'serious'}];
    const evaluated=finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options);expect(evaluated.rows.slice(0,2).map(r=>r.verdict)).toEqual(['NONCONFORMANT','NONCONFORMANT']);
    const entry={screen:'S-31',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['pixels'],reason:'test only',approvalPr:90};
    const hash=approveException(entry,null,options);expect(hash).toMatch(/^[a-f0-9]{64}$/);
    for(const comments of [[],[{id:1,approvalPr:90,user:{login:'not-owner'},body:`NYAY66-EXCEPTION ${hash}`}],[{id:1,approvalPr:91,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}]] )expect(()=>finalizeEnforcement(all,{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expect(approveException({...entry,checks:['accessibility']},null,options)).toBe(false);
  });
  it('loads the verified cache and captures S-31 only after all 262 historical rows',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS31Cache(root,config.s31,continuation,manifest.fonts)');
    expect(live).toContain('await captureS31Rows({browser,origin,out,reference:s31})');
    expect(live.indexOf('await captureS31Rows')).toBeGreaterThan(live.indexOf('await captureS30Rows'));
    expect(live.match(/s31:!!s31/g)).toHaveLength(2);
  });
});

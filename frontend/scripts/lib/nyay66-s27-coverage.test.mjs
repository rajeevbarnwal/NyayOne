import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S27_MEASURED_STATES,hasS27LiveProof} from './nyay66-s27-coverage.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const previous={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true},options={...previous,s27:true};
const rows=()=>S27_MEASURED_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-27',state:`S-27-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],evidenceKind:'live-route',syntheticServer:true,navigationFrozen:false,artificialDelay:false,routeProof:{path:'/s-27',state,requestSequenceVerified:true,serverConfirmationVerified:true}})));
describe('S-27 additive product coverage',()=>{
  it('adds exactly 22 light rows without changing the 198 existing identities or dark inventory',()=>{
    expect(S27_MEASURED_STATES).toEqual(['loading','results','filters-open','compare','no-results','invalid-filter','error','offline','page-2','sort-fees','sort-nirf']);
    const all=lightRowInventory(options);expect(all).toHaveLength(220);
    expect(all.filter(r=>r.screen!=='S-27')).toEqual(lightRowInventory(previous));
    expect(all.filter(r=>r.screen==='S-27').map(r=>`${r.state}:${r.viewport}`).sort()).toEqual(rows().map(r=>`${r.state}:${r.viewport}`).sort());
    expect(coverage('dark',options)).toEqual(coverage('dark',previous));
  });
  it('replaces only S-27 gaps and preserves all earlier rows, manual gaps and blocking results',()=>{
    const old=lightRowInventory(previous).map(r=>({...r,executed:true,measured:true,verdict:'PARITY'}));
    const result=appendContinuation({rows:[...old,...rows()],blocking:true,expectedLightRows:74,failures:['existing']},data,options);
    expect(result.rows.slice(0,198)).toEqual(old);expect(result.rows.filter(r=>r.screen==='S-27')).toHaveLength(22);
    expect(result.continuation.measuredLightRows).toBe(146);expect(result.continuation.unmeasuredLightRows).toBe(236);expect(result.continuation.importedReferenceRows).toBe(148);
    const manual=result.rows.filter(r=>r.state?.endsWith('option-manual'));expect(manual).toHaveLength(4);expect(manual.every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);expect(result.failures).toEqual(['existing']);
    expect(appendContinuation({rows:[]},data).rows.filter(r=>r.screen==='S-27').every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
  });
  it('fails closed on missing, duplicate or invented S-27 rows',()=>{
    const all=rows();for(const broken of [all.slice(1),[...all,all[0]],all.map((r,i)=>i?r:{...r,state:'S-27-invented'})])expect(()=>appendContinuation({rows:broken},data,{s27:true})).toThrow('S27_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('rejects failed captures or incomplete route/server-confirmation proof',()=>{
    const all=rows();all[0].verdict='CAPTURE-FAILED';all[0].measured=false;
    expect(appendContinuation({rows:all},data,{s27:true}).continuation.measuredLightRows).toBe(21);
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).blocking).toBe(true);
    const row=rows()[0];expect(hasS27LiveProof(row)).toBe(true);expect(hasS27LiveProof({screen:'S-21'})).toBe(true);
    for(const change of [{evidenceKind:'component-visual'},{syntheticServer:false},{navigationFrozen:true},{artificialDelay:true},{routeProof:null},{routeProof:{...row.routeProof,path:'/s-20'}},{routeProof:{...row.routeProof,path:'/s-25'}},{routeProof:{...row.routeProof,state:'invented'}},{routeProof:{...row.routeProof,requestSequenceVerified:false}},{routeProof:{...row.routeProof,serverConfirmationVerified:false}}]){
      const bad={...row,...change};expect(hasS27LiveProof(bad)).toBe(false);expect(finalizeEnforcement([bad],{enforced:[],exceptions:[]},[],options).rows[0].verdict).toBe('CAPTURE-FAILED');
    }
  });
  it('never waives differences, serious accessibility failures or unsigned exceptions',()=>{
    const all=rows();all[0].metrics.pass=false;all[1].accessibility=[{impact:'serious'}];
    const evaluated=finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options);expect(evaluated.rows.slice(0,2).map(r=>r.verdict)).toEqual(['NONCONFORMANT','NONCONFORMANT']);
    const entry={screen:'S-27',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['pixels'],reason:'test only',approvalPr:80};
    const hash=approveException(entry,null,options);expect(hash).toMatch(/^[a-f0-9]{64}$/);
    for(const comments of [[],[{id:1,approvalPr:80,user:{login:'not-owner'},body:`NYAY66-EXCEPTION ${hash}`}],[{id:1,approvalPr:75,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}]] )expect(()=>finalizeEnforcement(all,{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expect(approveException({...entry,checks:['accessibility']},null,options)).toBe(false);
  });
  it('loads the verified cache and captures S-27 only after all 198 historical rows',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS27Cache(root,config.s27,continuation,manifest.fonts)');
    expect(live).toContain('await captureS27Rows({browser,origin,out,reference:s27})');
    expect(live.indexOf('await captureS27Rows')).toBeGreaterThan(live.indexOf('await captureS26Rows'));
    expect(live.match(/s27:!!s27/g)).toHaveLength(2);
  });
});

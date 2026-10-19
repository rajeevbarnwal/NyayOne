import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S21_MEASURED_STATES,hasS21LiveProof} from './nyay66-s21-coverage.mjs';
const data=await loadContinuation(fileURLToPath(new URL('../../../',import.meta.url)));
const previous={r2:true,s18:true,s19:true,s20:true},options={...previous,s21:true};
const rows=()=>S21_MEASURED_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-21',state:`S-21-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],evidenceKind:'live-route',syntheticServer:true,navigationFrozen:false,artificialDelay:false,routeProof:{path:'/s-21',listing:'arbitration-intern',state,requestSequenceVerified:true,applyDisabled:true},...(state==='session'?{sessionInvalidation:{observedAnonymous:true,responseCode:'authentication_required',productionHandler:true}}:{})})));
describe('S-21 additive product capture',()=>{
  it('adds only 16 light rows; preserves all 162 identities and dark coverage',()=>{
    const all=lightRowInventory(options);expect(all).toHaveLength(178);
    expect(all.filter(r=>r.screen!=='S-21')).toEqual(lightRowInventory(previous));
    expect(all.filter(r=>r.screen==='S-21').map(r=>`${r.state}:${r.viewport}`).sort()).toEqual(rows().map(r=>`${r.state}:${r.viewport}`).sort());
    expect(coverage('dark',options)).toEqual(coverage('dark',previous));
  });
  it('replaces only the 16 S-21 gaps, retaining manual gaps and enforcement',()=>{
    const old=lightRowInventory(previous).map(r=>({...r,executed:true,measured:true,verdict:'PARITY'}));
    const report={rows:[...old,...rows()],blocking:true,expectedLightRows:74,failures:['existing']};
    const result=appendContinuation(report,data,options);
    expect(result.rows.slice(0,162)).toEqual(old);expect(result.rows.filter(r=>r.screen==='S-21')).toHaveLength(16);
    expect(result.continuation.measuredLightRows).toBe(104);expect(result.continuation.unmeasuredLightRows).toBe(278);expect(result.continuation.importedReferenceRows).toBe(106);
    const manual=result.rows.filter(r=>r.state?.endsWith('option-manual'));expect(manual).toHaveLength(4);
    expect(manual.every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);expect(result.failures).toEqual(['existing']);
  });
  it('fails closed on missing, duplicate and invented coverage',()=>{
    const all=rows();
    for(const broken of [all.slice(1),[...all,all[0]],all.map((r,i)=>i?r:{...r,state:'S-21-invented'})])expect(()=>appendContinuation({rows:broken},data,{s21:true})).toThrow('S21_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('does not label failed captures measured or accept unsupported live proof',()=>{
    const all=rows();all[0].verdict='CAPTURE-FAILED';all[0].measured=false;
    expect(appendContinuation({rows:all},data,{s21:true}).continuation.measuredLightRows).toBe(15);
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).blocking).toBe(true);
    expect(hasS21LiveProof(rows()[0])).toBe(true);expect(hasS21LiveProof({screen:'S-20'})).toBe(true);
    for(const change of [{evidenceKind:'component-visual'},{syntheticServer:false},{navigationFrozen:true},{routeProof:null},{routeProof:{...rows()[0].routeProof,requestSequenceVerified:false}},{routeProof:{...rows()[0].routeProof,path:'/s-03'}},{routeProof:{...rows()[0].routeProof,applyDisabled:false}}]){
      const bad={...rows()[0],...change};expect(hasS21LiveProof(bad)).toBe(false);
      expect(finalizeEnforcement([bad],{enforced:[],exceptions:[]},[],options).rows[0].verdict).toBe('CAPTURE-FAILED');
    }
  });
  it('keeps visual differences unapproved and rejects unsigned or wrong-owner exceptions',()=>{
    const all=rows();all[0].metrics.pass=false;
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).rows[0].verdict).toBe('NONCONFORMANT');
    const entry={screen:'S-21',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['pixels'],reason:'test only',approvalPr:74};
    const hash=approveException(entry,null,options);expect(hash).toMatch(/^[a-f0-9]{64}$/);
    for(const comments of [[],[{id:1,approvalPr:74,user:{login:'not-owner'},body:`NYAY66-EXCEPTION ${hash}`}],[{id:1,approvalPr:73,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}]] )expect(()=>finalizeEnforcement(all,{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
  });
  it('requires the real 401/session invalidation proof for the session row',()=>{
    const row=rows().find(r=>r.designState==='session');expect(hasS21LiveProof(row)).toBe(true);
    for(const sessionInvalidation of [undefined,{...row.sessionInvalidation,observedAnonymous:false},{...row.sessionInvalidation,responseCode:'invented'},{...row.sessionInvalidation,productionHandler:false}])expect(hasS21LiveProof({...row,sessionInvalidation})).toBe(false);
  });
  it('loads the verified cache and appends S-21 only after existing captures',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS21Cache(root,config.s21,continuation,manifest.fonts)');
    expect(live).toContain('await captureS21Rows({browser,origin,out,reference:s21})');
    expect(live.indexOf('await captureS21Rows')).toBeGreaterThan(live.indexOf('await captureS20Rows'));
    expect(live.match(/s21:!!s21/g)).toHaveLength(2);
  });
});

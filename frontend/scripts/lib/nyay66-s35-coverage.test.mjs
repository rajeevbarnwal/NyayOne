import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {coverage} from './nyay66-conformance.mjs';
import {lightRowInventory,finalizeEnforcement,approveException} from './nyay66-enforcement.mjs';
import {loadContinuation,appendContinuation} from './nyay66-continuation.mjs';
import {S35_STATES} from './nyay66-s35-reference.mjs';
import {S35_MEASURED_STATES,hasS35LiveProof,s35EvidenceScope} from './nyay66-s35-coverage.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url)),data=await loadContinuation(root);
const previous={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true,s29:true,s30:true,s31:true,s32:true,s33:true,s34:true},options={...previous,s35:true};
const rows=()=>S35_MEASURED_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>({screen:'S-35',state:`S-35-${state}`,designState:state,viewport,theme:'light',executed:true,measured:true,verdict:'PENDING-EVALUATION',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),metrics:{pass:true},regions:[],structure:[],accessibility:[],errors:[],evidenceKind:['refund-pending','refund-failed'].includes(state)?'live-capability-gap':state==='left'?'live-route-destination':'live-route',realBackendTested:false,realMediaProviderTested:false,capabilityGap:['refund-pending','refund-failed'].includes(state)?'student-refund-settlement-status-unavailable':null,settlementStateObserved:false,mediaPhase:state==='room-connecting'?'retry-awaiting-server-admission-not-provider-connection':null,mediaEmulation:s35EvidenceScope(state).media?'synthetic-browser-devices-and-opt-in-deterministic-transport':null,syntheticServer:true,navigationFrozen:false,artificialDelay:false,routeProof:{path:'/s-35',state,view:s35EvidenceScope(state).view,terminalStateVerified:true,requestSequenceVerified:true,responseScenarioVerified:true,sessionIdentityVerified:true,capabilityLimitsDisclosed:true}})));
describe('S-35 additive product coverage',()=>{
  it('adds exactly 112 light rows without changing the 340 existing identities or dark inventory',()=>{
    expect(S35_MEASURED_STATES).toEqual(S35_STATES);expect(S35_MEASURED_STATES).toHaveLength(56); expect(new Set(S35_MEASURED_STATES).size).toBe(56);
    const all=lightRowInventory(options);expect(all).toHaveLength(452);
    expect(all.filter(r=>r.screen!=='S-35')).toEqual(lightRowInventory(previous));
    expect(all.filter(r=>r.screen==='S-35').map(r=>`${r.state}:${r.viewport}`).sort()).toEqual(rows().map(r=>`${r.state}:${r.viewport}`).sort());
    expect(coverage('dark',options)).toEqual(coverage('dark',previous));
  });
  it('replaces only S-35 gaps and preserves all earlier rows, manual gaps and blocking results',()=>{
    const old=lightRowInventory(previous).map(r=>({...r,executed:true,measured:true,verdict:'PARITY'}));
    const result=appendContinuation({rows:[...old,...rows()],blocking:true,expectedLightRows:74,failures:['existing']},data,options);
    expect(result.rows.slice(0,340)).toEqual(old);expect(result.rows.filter(r=>r.screen==='S-35')).toHaveLength(112);
    expect(result.continuation.measuredLightRows).toBe(378);expect(result.continuation.unmeasuredLightRows).toBe(4);expect(result.continuation.importedReferenceRows).toBe(380);
    const manual=result.rows.filter(r=>r.state?.endsWith('option-manual'));expect(manual).toHaveLength(4);expect(manual.every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);expect(result.failures).toEqual(['existing']);
    expect(appendContinuation({rows:[]},data).rows.filter(r=>r.screen==='S-35').every(r=>r.verdict==='DESIGN-GAP'&&!r.measured&&!r.executed)).toBe(true);
  });
  it('fails closed on missing, duplicate or invented S-35 rows',()=>{
    const all=rows();for(const broken of [all.slice(1),[...all,all[0]],all.map((r,i)=>i?r:{...r,state:'S-35-invented'})])expect(()=>appendContinuation({rows:broken},data,{s35:true})).toThrow('S35_MEASURED_COVERAGE_INCOMPLETE');
  });
  it('rejects failed captures or incomplete route/server-confirmation proof',()=>{
    const all=rows();all[0].verdict='CAPTURE-FAILED';all[0].measured=false;
    expect(appendContinuation({rows:all},data,{s35:true}).continuation.measuredLightRows).toBe(111);
    expect(finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options).blocking).toBe(true);
    const row=rows()[0];expect(hasS35LiveProof(row)).toBe(true);expect(hasS35LiveProof({screen:'S-27'})).toBe(true);
    for(const change of [{routeProof:{...row.routeProof,terminalStateVerified:false}},{realBackendTested:true},{realMediaProviderTested:true},{evidenceKind:'component-visual'},{syntheticServer:false},{navigationFrozen:true},{artificialDelay:true},{routeProof:null},{routeProof:{...row.routeProof,path:'/s-20'}},{routeProof:{...row.routeProof,path:'/s-25'}},{routeProof:{...row.routeProof,state:'invented'}},{routeProof:{...row.routeProof,requestSequenceVerified:false}},{routeProof:{...row.routeProof,responseScenarioVerified:false}},{routeProof:{...row.routeProof,sessionIdentityVerified:false}},{routeProof:{...row.routeProof,capabilityLimitsDisclosed:false}}]){
      const bad={...row,...change};expect(hasS35LiveProof(bad)).toBe(false);expect(finalizeEnforcement([bad],{enforced:[],exceptions:[]},[],options).rows[0].verdict).toBe('CAPTURE-FAILED');
    }
  });
  it('never waives differences, serious accessibility failures or unsigned exceptions',()=>{
    const all=rows();all[0].metrics.pass=false;all[1].accessibility=[{impact:'serious'}];
    const evaluated=finalizeEnforcement(all,{enforced:[],exceptions:[]},[],options);expect(evaluated.rows.slice(0,2).map(r=>r.verdict)).toEqual(['NONCONFORMANT','NONCONFORMANT']);
    const entry={screen:'S-35',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['pixels'],reason:'test only',approvalPr:98};
    const hash=approveException(entry,null,options);expect(hash).toMatch(/^[a-f0-9]{64}$/);
    for(const comments of [[],[{id:1,approvalPr:98,user:{login:'not-owner'},body:`NYAY66-EXCEPTION ${hash}`}],[{id:1,approvalPr:99,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}]] )expect(()=>finalizeEnforcement(all,{enforced:[],exceptions:[entry]},comments,options)).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expect(approveException({...entry,checks:['accessibility']},null,options)).toBe(false);
  });
  it('fails closed if unavailable settlement or the post-leave destination is relabelled',()=>{
    for(const state of ['refund-pending','refund-failed','left']){
      const r=rows().find(x=>x.designState===state);expect(hasS35LiveProof(r)).toBe(true);
      expect(hasS35LiveProof({...r,evidenceKind:'live-route'})).toBe(false);
      if(state==='left')expect(hasS35LiveProof({...r,routeProof:{...r.routeProof,view:'room'}})).toBe(false);
      else {expect(hasS35LiveProof({...r,settlementStateObserved:true})).toBe(false);expect(hasS35LiveProof({...r,capabilityGap:null})).toBe(false);}
    }
  });
  it('requires truthful media emulation and view labels',()=>{
    for(const r of rows()){expect(hasS35LiveProof(r)).toBe(true);expect(hasS35LiveProof({...r,routeProof:{...r.routeProof,view:'invented'}})).toBe(false);if(s35EvidenceScope(r.designState).media)expect(hasS35LiveProof({...r,mediaEmulation:null})).toBe(false);}
  });
  it('loads the verified cache and captures S-35 only after all 340 historical rows',()=>{
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).toContain('await loadS35Cache(root,config.s35,continuation,manifest.fonts)');
    expect(live).toContain('await captureS35Rows({browser,origin,out,reference:s35})');
    expect(live.indexOf('await captureS35Rows')).toBeGreaterThan(live.indexOf('await captureS34Rows'));
    expect(live.match(/s35:!!s35/g)).toHaveLength(2);
  });
});

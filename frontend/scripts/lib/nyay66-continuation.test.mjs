import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadContinuation,continuationRows,appendContinuation,validateContinuation} from './nyay66-continuation.mjs';
import {lightRowInventory,finalizeEnforcement,validateProgression} from './nyay66-enforcement.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const sha=b=>createHash('sha256').update(b).digest('hex');
describe('v3.2.1.08 source intake is unmeasured, never a product pass',()=>{
  const load=()=>loadContinuation(root);
  it('verifies the actual canonical ZIP and all manifest-bound source bytes at use',async()=>{
    const data=await load();
    expect(data.archiveSha256).toBe('0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964');
    const archive=readFileSync(resolve(root,data.archive));
    expect(sha(archive)).toBe(data.archiveSha256);
    const prefix='NYAYONE_S01_S35_v3.2.1.08/';
    const states=JSON.parse(execFileSync('unzip',['-p',resolve(root,data.archive),prefix+'source/continuation-states.json']));
    expect(Object.fromEntries(data.screens.map(s=>[s.screen,s.states]))).toEqual(states);
    expect(()=>validateContinuation({...data,archiveSha256:'0'.repeat(64)},archive)).toThrow();
    const tampered=Buffer.from(archive);tampered[100]^=1;
    expect(()=>validateContinuation(data,tampered)).toThrow();
  });
  it('has exactly 15 IDs, 191 states and 382 light DESIGN-GAP rows at existing two viewports',async()=>{
    const data=await load(),rows=continuationRows(data);
    expect(data.screens).toHaveLength(15);
    expect(data.screens.reduce((n,s)=>n+s.states.length,0)).toBe(191);
    expect(rows).toHaveLength(382);
    expect(new Set(rows.map(r=>`${r.screen}:${r.state}:${r.viewport}`)).size).toBe(382);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false&&r.designApproved===true&&r.blocking===false&&r.theme==='light')).toBe(true);
    expect(rows.some(r=>['S-22','S-23','S-24'].includes(r.screen))).toBe(false);
    expect(rows.every(r=>r.referenceSha256===undefined&&r.liveSha256===undefined&&r.metrics===undefined)).toBe(true);
  });
  it('rejects corrupt/duplicate/unknown state inventory rather than silently losing coverage',async()=>{
    const data=await load(),archive=readFileSync(resolve(root,data.archive));
    for(const changed of [
      {...data,screens:data.screens.slice(1)},
      {...data,screens:[...data.screens.slice(1),data.screens[1]]},
      {...data,screens:data.screens.map((s,i)=>i? s:{...s,states:[]})},
      {...data,viewports:[{id:'mobile390',width:320,height:844}]},
    ])expect(()=>validateContinuation(changed,archive)).toThrow();
  });
  it('preserves 74 existing blocking rows, settings and old dark gaps',async()=>{
    const policy=JSON.parse(readFileSync(resolve(root,'frontend/scripts/nyay66-policy.json')));
    const before=JSON.parse(execFileSync('git',['show','4a2827d37f60fc651b3a6dbace0dcddfab44b9c4:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    for(const key of ['enforced','tolerances','exceptions','r2','manifestSha256','ownerToleranceApproval'])expect(policy[key]).toEqual(before[key]);
    expect(lightRowInventory({r2:true})).toHaveLength(74);
    expect(()=>validateProgression(policy.enforced,[...policy.enforced,'S-18'],{r2:true})).toThrow();
    const original={blocking:true,expectedLightRows:74,failures:['MISSING_LIGHT_ROW:test'],rows:[{screen:'S-01',verdict:'CAPTURE-FAILED',blocking:true},{screen:'S-01',theme:'dark',verdict:'DESIGN-GAP',executed:false}]};
    const result=appendContinuation(original,await load());
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);
    expect(result.failures).toEqual(original.failures);expect(result.rows.slice(0,2)).toEqual(original.rows);
    expect(result.continuation.unmeasuredLightRows).toBe(382);
    expect(original.rows).toHaveLength(2);
  });
  it('keeps missing coverage, regressions and invalid exceptions blocking despite design intake',async()=>{
    const config=JSON.parse(readFileSync(resolve(root,'frontend/scripts/nyay66-policy.json')));
    const rows=lightRowInventory({r2:true}).map(x=>({...x,executed:false,verdict:'NONCONFORMANT'}));
    const blocked=finalizeEnforcement(rows,{...config,exceptions:[]},[],{r2:true});
    expect(appendContinuation(blocked,await load()).blocking).toBe(true);
    expect(()=>finalizeEnforcement(rows,config,[],{r2:true})).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    expect(appendContinuation(finalizeEnforcement([],{...config,exceptions:[]},[],{r2:true}),await load()).failures).toHaveLength(74);
  });
  it('discloses design fonts/logo separately without promoting unimplemented product census',async()=>{
    const data=await load();
    expect(data.inventory.fonts.length).toBeGreaterThan(0);
    expect(data.inventory.logo.kind).toBe('inline-svg');
    expect(data.inventory.embeddedResources.logoDefinitions.map(x=>x.name)).toEqual(['LOCKUP','LOCKUP_REV','MARK','MARK_REV']);
    expect(data.inventory.embeddedResources.fontFaces.every(x=>/^[a-f0-9]{64}$/.test(x.sha256))).toBe(true);
    expect(data.inventory.scope).toBe('approved-design-source-only');
    expect(data.pngBaselinesImported).toBe(false);
  });
});

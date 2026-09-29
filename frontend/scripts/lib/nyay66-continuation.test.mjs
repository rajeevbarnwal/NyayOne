import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadContinuation,continuationRows,appendContinuation,validateContinuation} from './nyay66-continuation.mjs';
import {lightRowInventory,finalizeEnforcement,validateProgression,approveException} from './nyay66-enforcement.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const sha=b=>createHash('sha256').update(b).digest('hex');
// Exact S-18 proposals read back from the owner's 18 top-level PR68 comments.
// These pins are regression fixtures, not a substitute for hosted approval read-back.
const s18ApprovalHashes=[
  'ca7859c7c639f71b942b45d83ac004837f462fbd4b67b4bd52104d3590d9b367',
  '7328c4c9d9a42884b9bfe5556738bb3c71c037f2a7a9ffa0c4c1e3673f77fcd0',
  'f6232f08470a8385d1b3f841c8689fa1ae9e879f1659c74ad2d4969afb83ef97',
  '43583860f1a3defb008cfc97e1db49e68e40e32aa55e1e59c391637fffc2593f',
  '31fca2799e5959bb953213b440192f9930b369b7ac010571d0e9c84157eaa30c',
  '4da4f950b6b281afec8ca398dd01600803674b209e7a41ee778c053d2c52fe5b',
  '073655fa79a0a1cb216c72917c828889b99ea6e715b77a554edd065a64dd0379',
  '683f17aee8e8b6ac0b9e3ace18dff572dd32b6d028355bb6755aa5921703653e',
  '33d9b8b33ffb9a5e74f95ef616e3151118173dbc3a28f2e584e7f922c3e597c8',
  'fa3094fba3ad64b089539336fad86c4a7e207fc8cd768759d4d304f03e6e9dfc',
  'b647f5383150d12abc2e38686ef14918e8ecf40e783bbd72b99a3ad8c879f93c',
  'f98fafd03b2e35cfb98eebdba5acdbfcfec91176ce6ac03de8d516cca54e3641',
  'a39c2ec4708d6d83f0ef1dfd6a0439c601c8fb944f23165adcd207e3fc95943e',
  '4b71252d23b66ddef1a8eb17fe3aada4f2a7819d0f54abfbf974470ab3ce3e52',
  '3677df860d2208ab8ff591152d0db4685614910076588d38e2c22f5ce6a845ec',
  'd6c8ba6d969c19f8271ea4c3a33c7b425d3156bce0af9d283da17c6ab71eebb6',
  '1eb3814e8aa8522e7378f5104c650f8944a724f8b84a358236997a01faafe0dc',
  '1ff4db8a47bfe7de27fd240c1412d483a743ab7a1dbf99507b1304c0040b5520',
];
const policies=()=>({
  policy:JSON.parse(readFileSync(resolve(root,'frontend/scripts/nyay66-policy.json'))),
  before:JSON.parse(execFileSync('git',['show','4a2827d37f60fc651b3a6dbace0dcddfab44b9c4:frontend/scripts/nyay66-policy.json'],{cwd:root})),
});
function expectApprovedExceptions(policy,before){
  // Preserve every original field, string and array order; permit only S-18 additions.
  expect(JSON.stringify(policy.exceptions.filter(e=>e.screen!=='S-18'))).toBe(JSON.stringify(before.exceptions));
  const additions=policy.exceptions.filter(e=>e.screen==='S-18');
  expect(additions).toHaveLength(18);
  expect(additions.every(e=>e.approvalPr===68&&e.theme==='light')).toBe(true);
  expect(additions.filter(e=>e.viewport==='mobile390')).toHaveLength(9);
  expect(additions.filter(e=>e.viewport==='desktop')).toHaveLength(9);
  expect(additions.map(e=>approveException(e,null,{r2:true,s18:true})).sort()).toEqual([...s18ApprovalHashes].sort());
}
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
    const {policy,before}=policies();
    for(const key of ['enforced','tolerances','r2','manifestSha256','ownerToleranceApproval'])expect(policy[key]).toEqual(before[key]);
    expectApprovedExceptions(policy,before);
    expect(lightRowInventory({r2:true})).toHaveLength(74);
    expect(()=>validateProgression(policy.enforced,[...policy.enforced,'S-18'],{r2:true})).toThrow();
    const original={blocking:true,expectedLightRows:74,failures:['MISSING_LIGHT_ROW:test'],rows:[{screen:'S-01',verdict:'CAPTURE-FAILED',blocking:true},{screen:'S-01',theme:'dark',verdict:'DESIGN-GAP',executed:false}]};
    const result=appendContinuation(original,await load());
    expect(result.blocking).toBe(true);expect(result.expectedLightRows).toBe(74);
    expect(result.failures).toEqual(original.failures);expect(result.rows.slice(0,2)).toEqual(original.rows);
    expect(result.continuation.unmeasuredLightRows).toBe(382);
    expect(original.rows).toHaveLength(2);
  });
  it.each([
    ['altered existing exception',p=>{p.exceptions.find(e=>e.screen!=='S-18').reason+=' changed';}],
    ['deleted existing exception',p=>{p.exceptions.splice(p.exceptions.findIndex(e=>e.screen!=='S-18'),1);}],
    ['missing S-18 approval',p=>{p.exceptions.splice(p.exceptions.findIndex(e=>e.screen==='S-18'),1);}],
    ['duplicate S-18 approval',p=>{const e=p.exceptions.filter(e=>e.screen==='S-18');Object.assign(e[1],e[0]);}],
    ['changed S-18 scope',p=>{p.exceptions.find(e=>e.screen==='S-18').reason+=' widened';}],
    ['changed S-18 image',p=>{p.exceptions.find(e=>e.screen==='S-18').liveSha256='0'.repeat(64);}],
    ['wrong approval PR',p=>{p.exceptions.find(e=>e.screen==='S-18').approvalPr=67;}],
    ['unapproved continuation screen',p=>{p.exceptions.find(e=>e.screen==='S-18').screen='S-19';}],
  ])('rejects %s in the additive exception regression contract',(_,mutate)=>{
    const {policy,before}=policies();
    mutate(policy);
    expect(()=>expectApprovedExceptions(policy,before)).toThrow();
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

// Additive owner-approved R2 continuation. Never replaces the Revision L oracle.
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {PNG} from 'pngjs';
import {actor,mockApplication} from './nyay66-fixtures.mjs';
export const R2_SOURCE_SHA256='3bfdbaac7536d8ceeae660c57286b58f1b03cdc6a53545c458b3bc7636198a07';
export const R2_SOURCE_PATH='docs/design/nyayone-option-3.2.1/r2/NYAYONE_S01_S02_S06_R2_STANDALONE.html';
export const R2_STATES=Object.entries({s01:['checking','error','resolved'],s02:['default','focus'],s06:['entry','invalidnum','submitting','challenge','wrong','expired','locked','neterr','success']}).flatMap(([view,states])=>states.map(state=>({id:`${view}-${state}`,view,state,screen:`S-${view.slice(1)}`})));
export const R2_VIEWPORTS=[{id:'mobile390',width:390,height:844,preset:'m390'},{id:'mobile360',width:360,height:800,preset:'m360'},{id:'desktop',width:1440,height:1024,preset:'d1440'}];
// Additional state fixtures are delivered with their screen PR, not fabricated
// by rewriting the live DOM to look like the prototype.
export const R2_LIVE_STATES=['s01-checking','s01-error','s01-resolved','s02-default','s02-focus',...R2_STATES.filter(state=>state.screen==='S-06').map(state=>state.id)];
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');

// The actual S-06 route consumes synthetic server projections through its
// normal API client. No DOM replacement, forced interaction or product delay.
async function mockS06Application(page,view,origin,errors){
  const state=view.slice(4),api='/api/v1/auth/student';
  const fixedDate='2026-09-12T09:00:00.000Z';
  const mobile='9876543210',code='419037';
  const unavailable=()=>({status:'unavailable',purpose:null,destination_masked:null,attempts_left:null,expires_in_seconds:null,resend_in_seconds:null,locked_for_seconds:null,resend_allowed:false});
  const pending=(delta={})=>({status:'pending',purpose:'recovery',destination_masked:'••••••0340',attempts_left:3,expires_in_seconds:272,resend_in_seconds:22,locked_for_seconds:0,resend_allowed:false,...delta});
  let current=unavailable(),stage='entry';
  const recoveryRequests=[],expectedHttpErrors=[];
  let notifySubmittingRequest;
  const submittingRequest=state==='submitting'?new Promise(resolve=>{notifySubmittingRequest=resolve;}):null;
  const expectedPaths=['entry','invalidnum'].includes(state)?[]:[`${api}/recovery/start`,...(['wrong','success'].includes(state)?[`${api}/recovery/verify`]:[]),...(state==='success'?[`${api}/recovery/complete`]:[])];
  // Only Date/new Date are fixed; browser timers, RAF, request processing and
  // navigation continue naturally. Live countdown behavior is tested separately.
  await page.clock.setFixedTime(new Date(fixedDate));
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    const respond=async(status,body)=>{
      await route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(body)});
      // Exact response tuples for the evaluator's narrowly scoped classification,
      // not blanket permission to suppress arbitrary console/network failures.
      if(status>=400)expectedHttpErrors.push({method,url:url.href,status});
    };
    if(method==='GET'&&url.pathname===`${api}/session`)return respond(200,{authenticated:false,actor:null});
    if(method==='GET'&&url.pathname===`${api}/otp/state`)return respond(200,current);
    if(method!=='POST'||!url.pathname.startsWith(`${api}/recovery/`)){
      errors.push('UNMATCHED_API');return route.abort();
    }
    let body;try{body=request.postDataJSON();}catch{body=null;}
    const matches=expected=>body&&typeof body==='object'&&!Array.isArray(body)
      &&Object.keys(body).length===Object.keys(expected).length
      &&Object.entries(expected).every(([key,value])=>body[key]===value);
    const expectedBody=url.pathname.endsWith('/start')?{mobile}:url.pathname.endsWith('/verify')?{code}:{};
    if(expectedPaths[recoveryRequests.length]!==url.pathname||!matches(expectedBody)){
      errors.push('UNEXPECTED_RECOVERY_MUTATION');return route.abort();
    }
    recoveryRequests.push(`${method} ${url.pathname}`);
    if(submittingRequest)notifySubmittingRequest();
    if(url.pathname===`${api}/recovery/start`&&stage==='entry'){
      stage='started';
      // Only this intentional pending response is left unresolved; closing the
      // fresh browser context cancels it after the submitting capture.
      if(state==='submitting')return;
      if(state==='neterr')return respond(503,{detail:{code:'otp_delivery_unavailable'}});
      current=pending(state==='expired'?{expires_in_seconds:0,resend_in_seconds:0,resend_allowed:true}
        :state==='locked'?{attempts_left:0,locked_for_seconds:1800}:{});
      return respond(202,current);
    }
    if(url.pathname===`${api}/recovery/verify`&&stage==='started'){
      if(state==='wrong'){
        stage='rejected';current=pending({attempts_left:2,expires_in_seconds:184,resend_in_seconds:8});
        return respond(401,{detail:{code:'recovery_failed',otp_state:current}});
      }
      if(state==='success'){
        stage='verified';current={...unavailable(),status:'verified',purpose:'recovery'};
        return respond(200,current);
      }
    }
    if(url.pathname===`${api}/recovery/complete`&&stage==='verified'&&state==='success'){
      stage='complete';current=unavailable();return respond(200,current);
    }
    errors.push('UNEXPECTED_RECOVERY_MUTATION');return route.abort();
  });
  const initial=page.waitForResponse(response=>response.url()===origin+api+'/otp/state'&&response.request().method()==='GET'&&response.status()===200);
  await page.goto(origin+'/s-06');await (await initial).finished();
  await page.locator('[data-screen="S-06"][data-state="entry"]').waitFor();
  await page.getByLabel('Registered mobile number',{exact:true}).fill(state==='invalidnum'?'98765':mobile);
  // The default oracle is unfocused. Use a normal pointer action on inert
  // content, never an injected blur or a DOM style change.
  if(state==='entry')await page.getByRole('heading',{name:'Recover your account.',exact:true}).click();
  if(state!=='entry'){
    await page.getByRole('button',{name:'Send recovery code',exact:true}).click();
    if(['wrong','success'].includes(state)){
      await page.locator('[data-screen="S-06"][data-state="challenge"]').waitFor();
      await page.getByLabel('Six-digit recovery code',{exact:true}).fill(code);
      await page.getByRole('button',{name:'Verify and continue',exact:true}).click();
    }
  }
  await page.locator(`[data-screen="S-06"][data-state="${state}"]`).waitFor();
  if(submittingRequest){
    // React can paint "Sending" before fetch reaches the route callback.
    // Wait for validated real request arrival, not a time-based settling delay.
    let timeout;
    try{await Promise.race([submittingRequest,new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('R2_S06_SUBMITTING_REQUEST_UNOBSERVED')),20_000);})]);}
    finally{clearTimeout(timeout);}
  }
  if(state==='success')await page.getByRole('heading',{name:'Your account is ready.',exact:true}).waitFor();
  if(new URL(page.url()).pathname!=='/s-06')throw Error('R2_S06_UNEXPECTED_NAVIGATION');
  if(JSON.stringify(recoveryRequests)!==JSON.stringify(expectedPaths.map(path=>`POST ${path}`)))throw Error('R2_S06_REQUEST_SEQUENCE_MISMATCH');
  return {evidenceKind:'live-route',syntheticServer:true,state:view,displayClock:{kind:'fixed-date',value:fixedDate,timersRunning:true},artificialDelay:false,navigationFrozen:false,recoveryRequests,expectedHttpErrors,
    ...(state==='submitting'?{pendingResponse:{method:'POST',url:origin+api+'/recovery/start',cancelledBy:'context-disposal'}}:{})};
}
export async function mockR2Application(page,view,origin,errors){
  if(!R2_LIVE_STATES.includes(view))throw Error('R2_LIVE_STATE_NOT_IMPLEMENTED');
  const state=R2_STATES.find(x=>x.id===view);
  if(state.screen==='S-06')return mockS06Application(page,view,origin,errors);
  if(view==='s02-focus'){
    await mockApplication(page,state.screen,origin,errors);
    await page.keyboard.press('Tab');
    const focused=await page.getByRole('button',{name:'Continue',exact:true}).evaluate(element=>document.activeElement===element&&element.matches(':focus-visible'));
    if(!focused)throw Error('R2_S02_KEYBOARD_FOCUS_MISSING');
    return {evidenceKind:'live-route',interaction:'keyboard-Tab'};
  }
  if(state.screen!=='S-01')return mockApplication(page,state.screen,origin,errors);
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    // A pending response holds the existing splash. Context disposal cancels it.
    if(url.pathname==='/api/v1/auth/student/session'){
      if(view==='s01-checking')return;
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(view==='s01-error'?{invalid:'synthetic-session-projection'}:{authenticated:true,actor})});
    }
    // Hold the destination's independent profile request, never navigation.
    if(view==='s01-resolved'&&url.pathname==='/api/v1/student/profile')return;
    if(url.pathname.startsWith('/api/v1/')){errors.push('UNMATCHED_API');return route.abort();}
    return route.continue();
  });
  await page.goto(origin+'/s-01');
  if(view==='s01-resolved'){
    await page.waitForURL('**/s-07');
    await page.locator('[data-screen="S-01"]').waitFor({state:'detached'});
    await page.goto(origin+'/__nyay66-components/scripts/nyay66-s01-component.html');
    await page.locator('[data-nyay66-evidence="component-only"]').waitFor();
    await page.getByText('Session confirmed. Opening your workspace…',{exact:true}).waitFor();
    return {evidenceKind:'component-visual',coverageApproval:'NYAY-77:15493',liveRouteBehavior:{executed:true,from:'/s-01',to:'/s-07',syntheticServer:true,artificialDelay:false,navigationFrozen:false}};
  }
  await page.locator('[data-screen="S-01"]').waitFor();
  if(view==='s01-error')await page.getByRole('heading',{name:'We could not reach NyayOne.',exact:true}).waitFor();
  return {evidenceKind:'live-route'};
}
export function pendingStateRow(screen,state,viewport,enforced){
  return {screen,state,viewport,theme:'light',source:'r2',executed:false,verdict:'NOT-YET-MEASURED',reason:'LIVE_STATE_FIXTURE_PENDING_SCREEN_PR',blocking:enforced.includes(screen)};
}
export function validateR2Manifest(manifest){
  if(manifest?.schema!==1||manifest.sourceSha256!==R2_SOURCE_SHA256||manifest.approval!=='NYAY-50:15422'||manifest.theme!=='light')throw Error('R2_SOURCE_OR_APPROVAL_MISMATCH');
  const expected=new Set(R2_STATES.flatMap(s=>R2_VIEWPORTS.map(v=>`${s.id}:${v.id}`)));
  if(!Array.isArray(manifest.rows)||manifest.rows.length!==expected.size)throw Error('R2_INCOMPLETE_INVENTORY');
  for(const row of manifest.rows){
    const vp=R2_VIEWPORTS.find(v=>v.id===row.viewport);
    if(!expected.delete(`${row.view}:${row.viewport}`)||row.file!==`${row.view}-${row.viewport}-0.png`||!/^[a-f0-9]{64}$/.test(row.sha256)||!vp||JSON.stringify(row.dimensions)!==JSON.stringify([vp.width,vp.height])||!row.surface||!Array.isArray(row.surface.controls)||!Array.isArray(row.surface.headings)||typeof row.surface.text!=='string'||JSON.stringify(row.surface.dimensions)!==JSON.stringify(row.dimensions))throw Error('R2_INVALID_REFERENCE_ROW');
  }
  return true;
}
export function verifyR2PNG(row,bytes){
  if(hash(bytes)!==row.sha256)throw Error('R2_REFERENCE_BYTES_MISMATCH');
  const png=PNG.sync.read(bytes);
  if(JSON.stringify([png.width,png.height])!==JSON.stringify(row.dimensions))throw Error('R2_REFERENCE_DIMENSION_MISMATCH');
  return bytes;
}
// Staging is not approval: the trusted gate still requires the owner's fresh
// exact bundle comment before these candidate references can be used by CI.
export async function verifyR2Calibration(sums,read,expectedHead,expectedFonts){
  if(!/^[a-f0-9]{40}$/.test(expectedHead))throw Error('R2_INVALID_PRODUCER_HEAD');
  const files=new Map();
  const names=new Set(['manifest.json','runtime-pins.json',...R2_STATES.flatMap(s=>R2_VIEWPORTS.map(v=>`${s.id}-${v.id}-0.png`))]);
  for(const line of sums.trim().split('\n')){
    const match=/^([a-f0-9]{64}) {2}([a-z0-9.-]+)$/.exec(line);
    if(!match||!names.delete(match[2]))throw Error('R2_CHECKSUM_INVENTORY_MISMATCH');
    const bytes=await read(match[2]);
    if(hash(bytes)!==match[1])throw Error('R2_ARTIFACT_BYTES_MISMATCH');
    files.set(match[2],bytes);
  }
  if(names.size)throw Error('R2_CHECKSUM_INVENTORY_MISMATCH');
  const manifest=JSON.parse(files.get('manifest.json')),pins=JSON.parse(files.get('runtime-pins.json'));
  validateR2Manifest(manifest);
  if(manifest.producerHead!==expectedHead||pins.sourceHead!==expectedHead||pins.reference!=='r2')throw Error('R2_PRODUCER_HEAD_MISMATCH');
  for(const [key,value] of Object.entries({chromium:'149.0.7827.55',playwright:'1.61.1',platform:'linux-x64'})){
    if(manifest[key]!==value||pins[key]!==value)throw Error('R2_RUNTIME_PIN_MISMATCH');
  }
  if(pins.node!=='v22.21.1')throw Error('R2_NODE_PIN_MISMATCH');
  const canonical=o=>JSON.stringify(Object.entries(o||{}).sort(([a],[b])=>a.localeCompare(b)));
  if(!Object.keys(expectedFonts).length||canonical(manifest.fonts)!==canonical(expectedFonts)||canonical(pins.fonts)!==canonical(expectedFonts))throw Error('R2_FONT_PIN_MISMATCH');
  for(const row of manifest.rows){
    if(row.sampleHashes?.length!==3||row.sampleHashes.some(x=>x!==row.sha256))throw Error('R2_REFERENCE_VARIANCE');
    verifyR2PNG(row,files.get(row.file));
  }
  return {files,manifest,manifestSha256:hash(files.get('manifest.json'))};
}
export async function loadR2(root,config){
  if(!config)return null;
  if(!/^[a-z0-9][a-z0-9.-]*$/.test(config.cache)||!/^[a-f0-9]{64}$/.test(config.manifestSha256))throw Error('R2_INVALID_CACHE_BINDING');
  const source=await readFile(resolve(root,R2_SOURCE_PATH));
  if(hash(source)!==R2_SOURCE_SHA256)throw Error('R2_SOURCE_BYTES_MISMATCH');
  const cache=resolve(root,'frontend/test-baselines/nyay66',config.cache);
  const bytes=await readFile(resolve(cache,'manifest.json'));
  if(hash(bytes)!==config.manifestSha256)throw Error('R2_MANIFEST_BYTES_MISMATCH');
  const manifest=JSON.parse(bytes);validateR2Manifest(manifest);
  // Verify all states, even ones whose live fixture has not been implemented.
  for(const row of manifest.rows)verifyR2PNG(row,await readFile(resolve(cache,row.file)));
  return {cache,manifest};
}

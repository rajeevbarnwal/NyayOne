// S-18 route-only synthetic server projections. Never rewrite product DOM/state.
import {actor} from './nyay66-fixtures.mjs';
import {S18_STATES} from './nyay66-s18-reference.mjs';
export const S18_SETTINGS={theme:'system',language:'en',notif_email:true,notif_sms:false,notif_updates:false,version:7,
  privacy:['analytics','marketing','share_partners'].map(kind=>({kind,enabled:false}))};
const negative={invalid:{method:'PATCH',status:422,reason:'Unprocessable Entity'},conflict:{method:'PATCH',status:409,reason:'Conflict'},
  network:{method:'PATCH',status:503,reason:'Service Unavailable'},forbidden:{method:'GET',status:403,reason:'Forbidden'},session:{method:'GET',status:401,reason:'Unauthorized'}};
export function classifyS18Errors(state,origin,consoleErrors,httpResponses,expectedHttpErrors){
  const rule=negative[state],expected=rule?{method:rule.method,url:origin+'/api/v1/student/settings',status:rule.status}:null;
  const same=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const diagnostic=x=>expected&&x.url===expected.url&&x.text===`Failed to load resource: the server responded with a status of ${rule.status} (${rule.reason})`;
  const match=expected&&expectedHttpErrors.length===1&&same(expectedHttpErrors[0])&&httpResponses.length===1&&same(httpResponses[0])&&consoleErrors.length===1&&diagnostic(consoleErrors[0]);
  const errors=[];
  if(expected&&!match)errors.push('S18_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!match&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!match&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,expectedHttpErrors,expectedHttpErrorCount:match?1:0,errors};
}
export async function mockS18Application(page,state,origin,errors){
  if(!S18_STATES.includes(state))throw Error('S18_FIXTURE_SCOPE');
  const expectedHttpErrors=[],settingsRequests=[];let sessionLost=false;
  const needsPatch=['saving','saved','invalid','conflict','network'].includes(state);
  let observedRequest;const requestObserved=new Promise(resolve=>{observedRequest=resolve;});
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),method=req.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    const respond=(status,body)=>{
      if(status>=400)expectedHttpErrors.push({method,url:url.href,status});
      return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(body)});
    };
    if(url.pathname==='/api/v1/auth/student/session'&&method==='GET')return respond(200,sessionLost?{authenticated:false,actor:null}:{authenticated:true,actor});
    if(sessionLost&&url.pathname==='/api/v1/auth/student/login/channels'&&method==='GET')return respond(200,{channels:[{channel:'mobile',enabled:true},{channel:'email',enabled:true}]});
    if(url.pathname!=='/api/v1/student/settings'){errors.push('UNMATCHED_API');return route.abort();}
    settingsRequests.push({method,path:url.pathname,...(method==='PATCH'?{body:req.postDataJSON()}:{})});
    if(method==='GET'&&settingsRequests.length===1){
      if(state==='loading'){observedRequest();return;}
      if(state==='forbidden')return respond(403,{detail:{code:'forbidden'}});
      if(state==='session'){sessionLost=true;return respond(401,{detail:{code:'authentication_required'}});}
      return respond(200,S18_SETTINGS);
    }
    if(method==='PATCH'&&needsPatch&&settingsRequests.length===2){
      const body=req.postDataJSON();
      if(JSON.stringify(Object.entries(body).sort())!==JSON.stringify(Object.entries({notif_sms:true,expected_version:7}).sort())){errors.push('UNEXPECTED_SETTINGS_PATCH');return route.abort();}
      observedRequest();
      if(state==='saving')return;
      if(state==='saved')return respond(200,{...S18_SETTINGS,notif_sms:true,version:8});
      if(state==='conflict')return respond(409,{detail:{code:'settings_version_conflict',current_version:8}});
      if(state==='network')return respond(503,{detail:{code:'unavailable'}});
      // Synthetic validation rejection tests the normal error adapter. It is
      // not a claim that this valid notification input fails on a real backend.
      return respond(422,{detail:[{loc:['body','notif_sms'],type:'value_error',msg:'Synthetic validation rejection'}]});
    }
    errors.push('UNEXPECTED_SETTINGS_REQUEST');return route.abort();
  });
  await page.goto(origin+'/s-18');
  if(state==='session'){
    // Do not counterfeit a stable session-error screen by inventing a 401 code
    // or suppressing the shared auth guard. Real typed auth loss redirects.
    await page.waitForURL('**/s-03');await page.locator('[data-screen="S-03"]').waitFor();
    await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
    await page.goto(origin+'/__nyay66-s18/scripts/nyay66-s18-component.html');
    await page.locator('[data-nyay66-evidence="component-only"][data-coverage-approval="NYAY-88:16029"]').waitFor();
    await page.locator('[data-screen="S-18"][data-settings-state="session"]').waitFor();
    return {evidenceKind:'component-visual',coverageApproval:'NYAY-88:16029',syntheticServer:true,expectedHttpErrors,settingsRequests,
      reason:'Session-error component visual; genuine authentication_required response separately verified to redirect to S-03 without delay.',
      liveRouteBehavior:{executed:true,from:'/s-18',to:'/s-03',syntheticServer:true,artificialDelay:false,navigationFrozen:false}};
  }
  if(needsPatch){
    await page.locator('[data-settings-state="loaded"]').waitFor();
    await page.getByRole('switch',{name:'SMS notifications',exact:true}).click();
  }
  await page.locator(`[data-screen="S-18"][data-settings-state="${state}"]`).waitFor();
  if(['loading','saving'].includes(state)){
    let timer;try{await Promise.race([requestObserved,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('S18_PENDING_REQUEST_UNOBSERVED')),20_000);})]);}finally{clearTimeout(timer);}
  }
  if(settingsRequests.length!==(needsPatch?2:1)||new URL(page.url()).pathname!=='/s-18')throw Error('S18_REQUEST_SEQUENCE_MISMATCH');
  return {evidenceKind:'live-route',syntheticServer:true,expectedHttpErrors,settingsRequests,artificialDelay:false,navigationFrozen:false,
    ...(['loading','saving'].includes(state)?{pendingResponse:{method:state==='loading'?'GET':'PATCH',url:origin+'/api/v1/student/settings',cancelledBy:'context-disposal'}}:{})};
}

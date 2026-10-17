// Synthetic transport, real product route/controller. No DOM/state rewrites.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S19_MEASURED_STATES,S19_COVERAGE_APPROVAL} from './nyay66-s19-coverage.mjs';
const SETTINGS='/api/v1/student/settings',EXPORT='/api/v1/student/privacy/export',DELETE='/api/v1/student/privacy/delete';
const OTP='/api/v1/auth/student/otp/state',START='/api/v1/auth/student/recovery/start',VERIFY='/api/v1/auth/student/recovery/verify';
const REQUEST_ID='7f3a9c217f3a9c217f3a9c217f3a9c21',REQUEST=`/api/v1/student/privacy/requests/${REQUEST_ID}`;
const settings={theme:'system',language:'en',notif_email:true,notif_sms:false,notif_updates:false,version:7,privacy:['analytics','marketing','share_partners'].map(kind=>({kind,enabled:false}))};
const idle={status:'unavailable',purpose:null,destination_masked:null,attempts_left:null,expires_in_seconds:null,resend_in_seconds:null,locked_for_seconds:null,resend_allowed:false};
const pending={...idle,status:'pending',purpose:'recovery',destination_masked:'••••••0340',attempts_left:3,expires_in_seconds:300,resend_in_seconds:30,locked_for_seconds:0};
const verified={...idle,status:'verified',purpose:'recovery'};
const rule=(method,path,status,reason)=>({method,path,status,reason});
export const S19_NEGATIVE_RESPONSES={
  conflict:[rule('PATCH',SETTINGS,409,'Conflict')],network:[rule('PATCH',SETTINGS,503,'Service Unavailable')],
  session:[rule('GET',SETTINGS,401,'Unauthorized')],
  'request-not-found':[rule('GET',REQUEST,404,'Not Found')],
  'export-check-failed':[rule('GET',REQUEST,503,'Service Unavailable')],
  'delete-reauth-rejected':[rule('POST',VERIFY,400,'Bad Request')],
  'delete-conflict':[rule('POST',DELETE,409,'Conflict')],
  'delete-start-failed':[rule('POST',START,503,'Service Unavailable')],
  'delete-rate-limited':[rule('POST',START,429,'Too Many Requests')],
  'delete-code-expired':[rule('POST',VERIFY,410,'Gone')],
};
export function classifyS19Errors(state,origin,consoleErrors,httpResponses,expectedHttpErrors){
  const rules=S19_NEGATIVE_RESPONSES[state]||[];
  const responses=rules.map(r=>({method:r.method,url:origin+r.path,status:r.status}));
  const diagnostics=rules.map(r=>({url:origin+r.path,text:`Failed to load resource: the server responded with a status of ${r.status} (${r.reason})`}));
  const exact=canonical(responses)===canonical(httpResponses)&&canonical(responses)===canonical(expectedHttpErrors)&&canonical(diagnostics)===canonical(consoleErrors);
  const errors=[];
  if(rules.length&&!exact)errors.push('S19_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!exact&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!exact&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(!rules.length&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,expectedHttpErrors,expectedHttpErrorCount:exact?rules.length:0,errors};
}
export async function mockS19Application(page,state,origin,errors){
  if(!S19_MEASURED_STATES.includes(state))throw Error('S19_FIXTURE_SCOPE');
  const expectedHttpErrors=[],apiRequests=[];let sessionLost=false,flow=idle,sessionAnonymous=false,accepted=false;
  let observePending;const pendingObserved=new Promise(resolve=>{observePending=resolve;});
  const needsPatch=['saving','saved','conflict','network'].includes(state);
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method(),path=url.pathname;
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!path.startsWith('/api/v1/'))return route.continue();
    const body=request.postData()?request.postDataJSON():null;
    // Assert raw synthetic transport below, but never publish recovery inputs.
    const reportedBody=body&&Object.fromEntries(Object.entries(body).map(([key,value])=>[key,['mobile','code'].includes(key)?`[synthetic-${key}-redacted]`:value]));
    apiRequests.push({path,method,body:reportedBody});
    const respond=(status,data)=>{
      if(status>=400)expectedHttpErrors.push({method,url:url.href,status});
      return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(data)});
    };
    const fail=()=>{errors.push('S19_UNEXPECTED_API_REQUEST');return route.abort();};
    if(path==='/api/v1/auth/student/session'&&method==='GET'){
      sessionAnonymous ||= sessionLost;return respond(200,sessionLost?{authenticated:false,actor:null}:{authenticated:true,actor});
    }
    if(sessionLost&&path==='/api/v1/auth/student/login/channels'&&method==='GET')return respond(200,{channels:[{channel:'mobile',enabled:true},{channel:'email',enabled:true}]});
    if(path===SETTINGS&&method==='GET'){
      if(state==='loading'){observePending();return;}
      if(state==='session'){sessionLost=true;return respond(401,{detail:{code:'authentication_required'}});}
      return respond(200,settings);
    }
    if(path===SETTINGS&&method==='PATCH'&&needsPatch){
      if(canonical(body)!==canonical({privacy:[{kind:'analytics',enabled:true}],expected_version:7}))return fail();
      if(state==='saving'){observePending();return;}
      if(state==='conflict')return respond(409,{detail:{code:'settings_version_conflict',current_version:8}});
      if(state==='network')return respond(503,{detail:{code:'unavailable'}});
      return respond(200,{...settings,version:8,privacy:settings.privacy.map(p=>({...p,enabled:p.kind==='analytics'}))});
    }
    if(path===EXPORT&&method==='POST'&&(state.startsWith('export-')||state==='request-not-found')){
      if(body!==null||!request.headers()['idempotency-key'])return fail();
      return respond(202,{request_id:REQUEST_ID,status:'pending'});
    }
    if(path===REQUEST&&method==='GET'){
      if(state==='request-not-found')return respond(404,{detail:{code:'not_found'}});
      if(state==='export-check-failed')return respond(503,{detail:{code:'unavailable'}});
      return respond(200,{request_id:REQUEST_ID,kind:'export',status:({'export-processing':'processing','export-complete':'complete','export-failed':'failed'})[state]||'pending',created_at:'2026-10-17T00:00:00Z'});
    }
    if(path===OTP&&method==='GET'&&state.startsWith('delete-'))return respond(200,flow);
    if(path===START&&method==='POST'&&state.startsWith('delete-')){
      if(canonical(body)!==canonical({mobile:'9876500340'}))return fail();
      if(state==='delete-start-failed')return respond(503,{detail:{code:'unavailable'}});
      if(state==='delete-rate-limited')return respond(429,{detail:{code:'otp_rate_limited',otp_state:idle}});
      flow=pending;return respond(202,flow);
    }
    if(path===VERIFY&&method==='POST'&&state.startsWith('delete-')){
      if(canonical(body)!==canonical({code:'123456'}))return fail();
      if(state==='delete-reauth-rejected'){flow={...pending,attempts_left:2};return respond(400,{detail:{code:'otp_invalid',otp_state:flow}});}
      if(state==='delete-code-expired'){flow={...pending,expires_in_seconds:0};return respond(410,{detail:{code:'otp_expired',otp_state:flow}});}
      flow=state==='delete-reauth-required'?idle:verified;return respond(200,flow);
    }
    if(path===DELETE&&method==='POST'&&['delete-accepted','delete-conflict'].includes(state)){
      if(flow.status!=='verified'||canonical(body)!==canonical({confirmation:'DELETE'}))return fail();
      if(state==='delete-conflict')return respond(409,{detail:{code:'settings_version_conflict'}});
      sessionLost=true;flow=idle;accepted=true;return respond(202,{request_id:'b'.repeat(32),status:'pending'});
    }
    return fail();
  });
  const evidence={evidenceKind:'live-route',syntheticServer:true,expectedHttpErrors,apiRequests,artificialDelay:false,navigationFrozen:false};
  await page.goto(origin+'/s-19');
  if(state==='session'){
    await page.waitForURL('**/s-03');await page.locator('[data-screen="S-03"]').waitFor();
    // The shared auth guard owns navigation. Finish actual route work before
    // opening the separate presentation-only fixture; do not cancel it.
    await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
    if(!sessionAnonymous)throw Error('S19_ANONYMOUS_SESSION_UNOBSERVED');
    await page.goto(origin+'/__nyay66-s19/scripts/nyay66-s19-component.html');
    await page.locator(`[data-nyay66-evidence="component-only"][data-coverage-approval="${S19_COVERAGE_APPROVAL}"]`).waitFor();
    await page.locator('[data-screen="S-19"][data-privacy-state="session"]').waitFor();
    return {...evidence,evidenceKind:'component-visual',coverageApproval:S19_COVERAGE_APPROVAL,
      evidenceDescription:'Actual S-19 session component; genuine 401 redirect to S-03 separately verified. Not a stable live-page capture.',
      liveRouteBehavior:{executed:true,from:'/s-19',to:'/s-03',syntheticServer:true,sessionAnonymous,artificialDelay:false,navigationFrozen:false}};
  }
  await page.locator(`[data-screen="S-19"][data-privacy-state="${state==='loading'?'loading':'loaded'}"]`).waitFor();
  if(needsPatch){
    await page.getByRole('switch',{name:'Usage analytics',exact:true}).click();
    await page.locator(`[data-privacy-state="${state}"]`).waitFor();
  }
  if(state.startsWith('export-')||state==='request-not-found'){
    await page.getByRole('button',{name:'Request a copy of my data',exact:true}).click();
    await page.getByText('Export requested.',{exact:true}).waitFor();
    if(state!=='export-accepted'){
      await page.getByRole('button',{name:'Check status',exact:true}).click();
      const title={'export-processing':'Your export is being prepared.','export-complete':'Your export is complete.','export-failed':'The export request failed.','request-not-found':'That request was not found.','export-check-failed':'Status check failed.'}[state];
      await page.getByText(title,{exact:true}).waitFor();
    }
  }
  if(state.startsWith('delete-')){
    const authority=page.waitForResponse(r=>new URL(r.url()).pathname===OTP);
    await page.getByRole('button',{name:'Delete my account',exact:true}).click();
    await page.getByLabel('Registered mobile number',{exact:true}).waitFor();
    // Await real authority discovery before starting recovery.
    await authority;
    if(state==='delete-mobile-invalid'){
      await page.getByLabel('Registered mobile number',{exact:true}).fill('123');
      if(!await page.getByRole('button',{name:'Send code',exact:true}).isDisabled())throw Error('S19_INVALID_MOBILE_NOT_BLOCKED');
      evidence.evidenceDescription='Live invalid input with disabled Send code; no invented submit/error state.';
    }else if(state!=='delete-confirm'){
      await page.getByLabel('Registered mobile number',{exact:true}).fill('9876500340');
      await page.getByRole('button',{name:'Send code',exact:true}).click();
      if(['delete-start-failed','delete-rate-limited'].includes(state)){
        await page.getByText(state==='delete-start-failed'?'Could not start re-authentication.':'Too many codes requested.',{exact:true}).waitFor();
      }else{
        await page.getByLabel('Six-digit code',{exact:true}).waitFor();
        if(state!=='delete-reauth'){
          await page.getByLabel('Six-digit code',{exact:true}).fill('123456');
          await page.getByRole('button',{name:'Verify code',exact:true}).click();
          const errorTitle={'delete-reauth-rejected':'That code did not match.','delete-code-expired':'That code has expired.','delete-reauth-required':'The server did not confirm re-authentication.'}[state];
          if(errorTitle)await page.getByText(errorTitle,{exact:true}).waitFor();
          else{
            await page.getByLabel('Type DELETE to continue',{exact:true}).waitFor();
            if(state==='delete-invalid'){
              await page.getByLabel('Type DELETE to continue',{exact:true}).fill('delete');
              if(!await page.getByRole('button',{name:'Request account deletion',exact:true}).isDisabled())throw Error('S19_INVALID_CONFIRMATION_NOT_BLOCKED');
              evidence.evidenceDescription='Live wrong-case confirmation with disabled deletion; no fabricated server 422.';
            }
            if(['delete-conflict','delete-accepted'].includes(state)){
              await page.getByLabel('Type DELETE to continue',{exact:true}).fill('DELETE');
              await page.getByRole('button',{name:'Request account deletion',exact:true}).click();
              if(state==='delete-accepted'){
                await page.waitForURL('**/s-03');await page.getByText('DELETION REQUEST ACCEPTED',{exact:true}).waitFor();
                if(!accepted||!sessionAnonymous)throw Error('S19_DELETION_AUTHORITY_PROOF_MISSING');
                return {...evidence,evidenceKind:'live-redirect-destination',coverageApproval:S19_COVERAGE_APPROVAL,
                  evidenceDescription:'Actual S-03 accepted-deletion destination, not a stable S-19 page or prototype placeholder. Synthetic 202 and anonymous session confirmed.',
                  liveRouteBehavior:{executed:true,from:'/s-19',to:'/s-03',syntheticServer:true,sessionAnonymous,deletionAccepted:accepted,noticeObserved:true,artificialDelay:false,navigationFrozen:false}};
              }
              await page.getByText(/Nothing (was deleted|is confirmed)/).waitFor();
            }
          }
        }
      }
    }
  }
  if(new URL(page.url()).pathname!=='/s-19')throw Error('S19_ROUTE_MISMATCH');
  if(['loading','saving'].includes(state)){
    let timer;try{await Promise.race([pendingObserved,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('S19_PENDING_REQUEST_UNOBSERVED')),10000);})]);}finally{clearTimeout(timer);}
    if(!apiRequests.some(r=>r.path===SETTINGS&&r.method===(state==='loading'?'GET':'PATCH')))throw Error('S19_PENDING_REQUEST_UNOBSERVED');
    evidence.pendingResponse={method:state==='loading'?'GET':'PATCH',url:origin+SETTINGS,cancelledBy:'context-disposal'};
  }
  return evidence;
}

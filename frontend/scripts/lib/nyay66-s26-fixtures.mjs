// S-26 only: real route and shared saved query with synthetic server responses.
// No UI-state injection, auth bypass, DOM edits or navigation freeze.
import {actor} from './nyay66-fixtures.mjs';
import {S20_LISTINGS} from './nyay66-s20-fixtures.mjs';
import {S26_MEASURED_STATES} from './nyay66-s26-coverage.mjs';
export const S26_LISTINGS=Object.freeze(S20_LISTINGS.slice(1));
const saved='/api/v1/student/internships/saved',session='/api/v1/auth/student/session';
export function classifyS26Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const expected=state==='error'?{method:'GET',url:origin+saved,status:500}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text==='Failed to load resource: the server responded with a status of 500 (Internal Server Error)'&&failedRequests.length===0;
  const errors=[];
  if(!S26_MEASURED_STATES.includes(state))errors.push('S26_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S26_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export function verifyS26Requests(state,requests){
  if(!S26_MEASURED_STATES.includes(state))return false;
  const expected=[['GET',session],['GET',saved]];
  return requests.length===expected.length&&requests.every((r,i)=>!r.search&&r.method===expected[i][0]&&r.path===expected[i][1]);
}
export async function mockS26Application(page,state,origin,errors){
  if(!S26_MEASURED_STATES.includes(state))throw Error('S26_FIXTURE_SCOPE');
  const apiRequests=[],expectedHttpErrors=[];
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    apiRequests.push({method,path:url.pathname,search:url.search});
    if(url.search||url.hash){errors.push('UNEXPECTED_API_QUERY');return route.abort();}
    const respond=(status,body)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(body)});};
    if(url.pathname===session&&method==='GET')return respond(200,{authenticated:true,actor});
    if(url.pathname===saved&&method==='GET'){
      if(state==='loading')return; // Held pending, cancelled only by context disposal.
      if(state==='error')return respond(500,{detail:{code:'unavailable'}});
      return respond(200,{items:state==='empty'?[]:S26_LISTINGS});
    }
    errors.push('UNMATCHED_API');return route.abort();
  });
  const read=page.waitForRequest(r=>r.method()==='GET'&&new URL(r.url()).pathname===saved);
  await page.goto(origin+'/s-26');await read;
  await page.getByRole('heading',{name:'Saved internships.',exact:true}).waitFor();
  if(state==='loading')await page.getByRole('status',{name:'Loading saved internships',exact:true}).waitFor();
  else if(state==='error'){
    await page.getByRole('heading',{name:'Could not check your saved list.',exact:true}).waitFor();
    await page.getByText('HTTP 500',{exact:true}).waitFor();
    await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
  }else await page.getByRole('heading',{name:state==='empty'?'No saved internships yet.':`You have ${S26_LISTINGS.length} saved internships.`,exact:true}).waitFor();
  await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));
  if(!verifyS26Requests(state,apiRequests)||new URL(page.url()).pathname!=='/s-26'||new URL(page.url()).search)throw Error(`S26_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s26-recovery main').evaluate(host=>({
    heading:host.querySelector('h2')?.textContent??'',loading:!!host.querySelector('[role="status"]'),error:!!host.querySelector('[role="alert"]'),
    status:host.querySelector('.s20-code')?.textContent??'',actions:[...host.querySelectorAll('button')].map(e=>e.textContent),
  }));
  const expectedHeading={empty:'No saved internships yet.',loading:'',error:'Could not check your saved list.',nonempty:`You have ${S26_LISTINGS.length} saved internships.`};
  const serverConfirmationVerified=snapshot.heading===expectedHeading[state]&&snapshot.loading===(state==='loading')&&snapshot.error===(state==='error')
    &&snapshot.status===(state==='error'?'HTTP 500':'')&&JSON.stringify(snapshot.actions)===JSON.stringify(state==='loading'?[]:[state==='error'?'Retry':state==='empty'?'Browse internships':'Open saved internships']);
  if(!serverConfirmationVerified)throw Error('S26_SERVER_CONFIRMATION_PROOF_MISSING');
  return {evidenceKind:'live-route',evidenceDescription:'Live S-26 route and shared saved query with synthetic API responses; not live-backend or independent QA evidence',syntheticServer:true,artificialDelay:false,navigationFrozen:false,
    apiRequests,expectedHttpErrors,routeProof:{path:'/s-26',state,requestSequenceVerified:true,serverConfirmationVerified},savedQueryProof:snapshot,
    ...(state==='loading'?{pendingResponse:{method:'GET',url:origin+saved,cancelledBy:'context-disposal'}}:{})};
}

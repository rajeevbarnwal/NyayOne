// S-21 only: synthetic backend responses, genuine route, save and 401 handling.
// No DOM replacement, auth bypass, navigation freeze or manufactured success.
import {actor} from './nyay66-fixtures.mjs';
import {S21_MEASURED_STATES} from './nyay66-s21-coverage.mjs';
export const S21_LISTING=Object.freeze({id:'arbitration-intern',organisation_id:'00000000-0000-4000-8000-000000000304',role:'Arbitration intern',organisation:'Nirvikar & Co.',location:'Bengaluru',stipend_monthly_paise:3500000,verification_status:'verified',application_deadline:'2026-08-18',eligibility:'Any year, ADR coursework preferred',tags:['Arbitration','ADR'],description:'Sit with the domestic arbitration team on document review, chronology drafting and hearing logistics.',source:{name:'Nirvikar & Co.',url:'https://example.test/internships/arbitration-intern',retrieved_at:'2026-08-03T00:00:00Z',verified_at:'2026-08-04T00:00:00Z'}});
const detail=`/api/v1/internships/${S21_LISTING.id}`,saved='/api/v1/student/internships/saved',save=`/api/v1/student/internships/${S21_LISTING.id}/saved`,session='/api/v1/auth/student/session';
const negative={
  'save-failed':{method:'PUT',path:save,status:503,reason:'Service Unavailable'},
  session:{method:'PUT',path:save,status:401,reason:'Unauthorized'},
  missing:{method:'GET',path:detail,status:404,reason:'Not Found'},
  error:{method:'GET',path:detail,status:500,reason:'Internal Server Error'},
};
export function classifyS21Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const rule=negative[state],expected=rule?{method:rule.method,url:origin+rule.path,status:rule.status}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${rule.status} (${rule.reason})`&&failedRequests.length===0;
  const errors=[];
  if(!S21_MEASURED_STATES.includes(state))errors.push('S21_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S21_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export function verifyS21Requests(state,requests){
  if(!S21_MEASURED_STATES.includes(state))return false;
  const expected=new Map([[`GET ${session}`,state==='session'?2:1],[`GET ${detail}`,state==='session'?2:1],[`GET ${saved}`,state==='save-failed'?2:1]]);
  if(['save-pending','save-failed','session'].includes(state))expected.set(`PUT ${save}`,1);
  for(const request of requests){const key=`${request.method} ${request.path}`;if(request.search||!expected.get(key))return false;expected.set(key,expected.get(key)-1);}
  return [...expected.values()].every(count=>count===0);
}
export async function mockS21Application(page,state,origin,errors){
  if(!S21_MEASURED_STATES.includes(state))throw Error('S21_FIXTURE_SCOPE');
  const apiRequests=[],expectedHttpErrors=[];let authenticated=true,observedAnonymous=false;
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    apiRequests.push({method,path:url.pathname,search:url.search});
    if(url.search||url.hash){errors.push('UNEXPECTED_API_QUERY');return route.abort();}
    const respond=(status,body)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(body)});};
    if(url.pathname===session&&method==='GET'){
      if(!authenticated)observedAnonymous=true;
      return respond(200,authenticated?{authenticated:true,actor}:{authenticated:false,actor:null});
    }
    if(url.pathname===detail&&method==='GET'){
      if(state==='loading')return; // Deliberately unresolved server request, cancelled on context disposal.
      if(state==='missing')return respond(404,{detail:{code:'internship_listing_not_found'}});
      if(state==='error')return respond(500,{detail:{code:'unavailable'}});
      return respond(200,S21_LISTING);
    }
    if(url.pathname===saved&&method==='GET')return respond(200,{items:state==='saved'?[S21_LISTING]:[]});
    if(url.pathname===save&&method==='PUT'){
      if(state==='save-pending')return;
      if(state==='save-failed')return respond(503,{detail:{code:'unavailable'}});
      if(state==='session'){authenticated=false;return respond(401,{detail:{code:'authentication_required'}});}
    }
    errors.push('UNMATCHED_API');return route.abort();
  });
  const detailRequest=page.waitForRequest(r=>new URL(r.url()).pathname===detail);
  const savedResponse=page.waitForResponse(r=>new URL(r.url()).pathname===saved);
  await page.goto(`${origin}/s-21?listing=${S21_LISTING.id}`);await detailRequest;await (await savedResponse).finished();
  if(state==='loading')await page.getByRole('status',{name:'Loading internship',exact:true}).waitFor();
  else if(state==='missing')await page.getByText('This listing is no longer available.',{exact:true}).waitFor();
  else if(state==='error')await page.getByText('The listing did not load.',{exact:true}).waitFor();
  else{
    await page.getByRole('heading',{name:'Arbitration intern.',exact:true}).waitFor();
    const button=page.getByRole('button',{name:state==='saved'?'Saved':'Save listing',exact:true});await button.waitFor();
    await page.waitForFunction(()=>document.querySelector('.s21-actions button')?.getAttribute('aria-disabled')==='false');
    if(['save-pending','save-failed','session'].includes(state)){
      const mutation=page.waitForRequest(r=>r.method()==='PUT'&&new URL(r.url()).pathname===save);await button.click();await mutation;
      if(state==='save-pending')await page.getByRole('button',{name:'Saving',exact:true}).waitFor();
      if(state==='save-failed'){
        await page.getByText('Could not confirm this change. Reload your saved list before trying again.',{exact:true}).waitFor();
        await page.getByRole('button',{name:'Reload saved state',exact:true}).waitFor();
      }
      if(state==='session')await page.getByRole('button',{name:'Sign in again',exact:true}).waitFor();
      if(state==='save-failed'||state==='session')await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
    }
  }
  // Permit React's request completions/remount to settle, without a timed wait,
  // suppressing requests or selecting a screenshot by an expected hash.
  await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));
  if(!verifyS21Requests(state,apiRequests)||new URL(page.url()).pathname!=='/s-21')throw Error(`S21_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const apply=page.getByRole('button',{name:'Apply',exact:true});
  const applyDisabled=await apply.count()===0||await apply.getAttribute('aria-disabled')==='true';
  if(!applyDisabled||state==='session'&&!observedAnonymous)throw Error('S21_ROUTE_PROOF_MISSING');
  return {evidenceKind:'live-route',evidenceDescription:'Live S-21 route and actions with synthetic API responses; not live-backend evidence',syntheticServer:true,artificialDelay:false,navigationFrozen:false,
    apiRequests,expectedHttpErrors,routeProof:{path:'/s-21',listing:S21_LISTING.id,state,requestSequenceVerified:true,applyDisabled},
    ...(['loading','save-pending'].includes(state)?{pendingResponse:{method:state==='loading'?'GET':'PUT',url:origin+(state==='loading'?detail:save),cancelledBy:'context-disposal'}}:{}),
    ...(state==='session'?{sessionInvalidation:{responseCode:'authentication_required',observedAnonymous,productionHandler:true}}:{})};
}

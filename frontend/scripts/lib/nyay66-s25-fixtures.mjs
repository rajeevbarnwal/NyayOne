// S-25 only: real product route/actions with synthetic backend responses.
// No DOM replacement, auth bypass, navigation freeze or fabricated success.
import {actor} from './nyay66-fixtures.mjs';
import {S20_LISTINGS} from './nyay66-s20-fixtures.mjs';
import {S25_MEASURED_STATES} from './nyay66-s25-coverage.mjs';
export const S25_LISTINGS=Object.freeze(S20_LISTINGS.slice(1));
const saved='/api/v1/student/internships/saved',remove=`/api/v1/student/internships/${S25_LISTINGS[0].id}/saved`,session='/api/v1/auth/student/session';
const negative={
  'remove-failed':{method:'DELETE',path:remove,status:503,reason:'Service Unavailable'},
  error:{method:'GET',path:saved,status:500,reason:'Internal Server Error'},
};
export function classifyS25Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const rule=negative[state],expected=rule?{method:rule.method,url:origin+rule.path,status:rule.status}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${rule.status} (${rule.reason})`&&failedRequests.length===0;
  const errors=[];
  if(!S25_MEASURED_STATES.includes(state))errors.push('S25_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S25_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export function verifyS25Requests(state,requests){
  if(!S25_MEASURED_STATES.includes(state))return false;
  const expected=[['GET',session],['GET',saved]];
  if(['remove-pending','remove-failed'].includes(state))expected.push(['DELETE',remove]);
  if(state==='remove-failed')expected.push(['GET',saved]);
  return requests.length===expected.length&&requests.every((r,i)=>!r.search&&r.method===expected[i][0]&&r.path===expected[i][1]);
}
export async function mockS25Application(page,state,origin,errors){
  if(!S25_MEASURED_STATES.includes(state))throw Error('S25_FIXTURE_SCOPE');
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
      if(state==='loading')return; // Deliberately unresolved; context disposal cancels it.
      if(state==='error')return respond(500,{detail:{code:'unavailable'}});
      return respond(200,{items:state==='empty'?[]:S25_LISTINGS});
    }
    if(url.pathname===remove&&method==='DELETE'){
      if(state==='remove-pending')return; // No success response, so no optimistic removal.
      if(state==='remove-failed')return respond(503,{detail:{code:'unavailable'}});
    }
    errors.push('UNMATCHED_API');return route.abort();
  });
  const read=page.waitForRequest(r=>r.method()==='GET'&&new URL(r.url()).pathname===saved);
  await page.goto(origin+'/s-25');await read;
  await page.getByRole('heading',{name:'Saved internships.',exact:true}).waitFor();
  if(state==='loading')await page.getByRole('status',{name:'Loading saved internships',exact:true}).waitFor();
  else if(state==='error'){
    await page.getByText('Your saved list did not load.',{exact:true}).waitFor();
    await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
  }else if(state==='empty')await page.getByRole('heading',{name:'No saved internships yet.',exact:true}).waitFor();
  else{
    const button=page.getByRole('button',{name:`Remove ${S25_LISTINGS[0].role} from saved`,exact:true});await button.waitFor();
    await page.waitForFunction(()=>document.querySelector('.s25-saved [data-remove-id]')?.getAttribute('aria-disabled')==='false');
    if(['remove-pending','remove-failed'].includes(state)){
      const mutation=page.waitForRequest(r=>r.method()==='DELETE'&&new URL(r.url()).pathname===remove);
      await button.click();await mutation;
      if(state==='remove-pending')await page.waitForFunction(()=>document.querySelector('.s25-saved [data-remove-id]')?.getAttribute('aria-busy')==='true');
      else{
        await page.getByText('Could not confirm removal. Reload your saved list.',{exact:true}).waitFor();
        await page.getByRole('button',{name:'Reload saved list',exact:true}).waitFor();
        await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert'&&!document.querySelector('.s25-saved [aria-busy="true"]'));
      }
    }
  }
  // Settle completed React work without timers, DOM edits or hash-selected retries.
  await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));
  if(!verifyS25Requests(state,apiRequests)||new URL(page.url()).pathname!=='/s-25'||new URL(page.url()).search)throw Error(`S25_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s25-saved').evaluate(host=>({
    items:host.querySelectorAll('article').length,success:host.querySelector('.s20-announcement')?.textContent,
    controls:[...host.querySelectorAll('[data-remove-id]')].map(el=>({saved:el.getAttribute('aria-pressed'),disabled:el.getAttribute('aria-disabled'),busy:el.getAttribute('aria-busy')})),
  }));
  const listed=['list','remove-pending','remove-failed'].includes(state);
  const serverConfirmationVerified=snapshot.items===(listed?S25_LISTINGS.length:0)&&snapshot.success===''
    &&(!listed||snapshot.controls.length===S25_LISTINGS.length&&snapshot.controls.every(c=>c.saved===(state==='remove-failed'?null:'true')&&c.disabled===(state==='list'?'false':'true')))
    &&(state!=='remove-pending'||snapshot.controls[0].busy==='true');
  if(!serverConfirmationVerified)throw Error('S25_SERVER_CONFIRMATION_PROOF_MISSING');
  return {evidenceKind:'live-route',evidenceDescription:'Live S-25 route and removal action with synthetic API responses; not live-backend or independent QA evidence',syntheticServer:true,artificialDelay:false,navigationFrozen:false,
    apiRequests,expectedHttpErrors,routeProof:{path:'/s-25',state,requestSequenceVerified:true,serverConfirmationVerified},savedStateProof:snapshot,
    ...(['loading','remove-pending'].includes(state)?{pendingResponse:{method:state==='loading'?'GET':'DELETE',url:origin+(state==='loading'?saved:remove),cancelledBy:'context-disposal'}}:{})};
}

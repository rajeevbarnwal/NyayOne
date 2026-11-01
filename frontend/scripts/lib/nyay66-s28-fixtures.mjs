// S-28 only: real detail route and supported Save/Follow requests.
// Design-aligned synthetic facts are not live institutional/backend evidence.
// No notification field invented in GET, DOM replacement or navigation freeze.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S28_MEASURED_STATES} from './nyay66-s28-coverage.mjs';
export const S28_ID='00000000-0000-4000-8000-000000000704';
export const S28_DETAIL_PATH=`/api/v1/law-schools/${S28_ID}`;
export const S28_SAVE_PATH=`/api/v1/student/law-schools/${S28_ID}/saved`;
export const S28_FOLLOW_PATH=`/api/v1/student/law-schools/${S28_ID}/follow`;
export const S28_ROUTE=`/s-28?id=${S28_ID}`;
const session='/api/v1/auth/student/session';
export const S28_SCHOOL=Object.freeze({id:S28_ID,slug:'synthetic-sabarmati-law-college',name:'Sabarmati Law College',state:'Gujarat',institution_type:'private',
  accreditation:'BCI approved',entrance_exam:'Institution test',fees_min:410000,fees_max:455000,nirf_rank:null,
  programmes:Object.freeze([Object.freeze({degree:'B.B.A. LL.B.',duration_years:5})]),
  facts:Object.freeze([['established','2009'],['location','Ahmedabad'],['intake','180'],['hostel','Off campus']].map(([key,value])=>Object.freeze({key,value,source_name:'Institution website',source_url:'https://example.test/sabarmati',retrieved_at:'2026-07-02T00:00:00Z'}))),
  saved:false,followed:true});
export function s28DetailResponse(state){
  if(!S28_MEASURED_STATES.includes(state))throw Error('S28_FIXTURE_SCOPE');
  // GET does not project notify_opt_in. "following" is achieved by a real PUT.
  return {...structuredClone(S28_SCHOOL),followed:state!=='following'};
}
export function expectedS28Requests(state){
  if(!S28_MEASURED_STATES.includes(state))throw Error('S28_FIXTURE_SCOPE');
  const request=(method,path,body=null)=>({method,path,search:'',body});
  return [request('GET',session),request('GET',S28_DETAIL_PATH),
    ...(state==='following'?[request('PUT',S28_FOLLOW_PATH,{notify_opt_in:false})]
      :state==='save-pending'?[request('PUT',S28_SAVE_PATH)]
      :state==='follow-error'?[request('DELETE',S28_FOLLOW_PATH)]:[])];
}
export function verifyS28Requests(state,requests){
  return S28_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(expectedS28Requests(state));
}
export function classifyS28Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const status=state==='missing'?404:['error','follow-error'].includes(state)?500:null;
  const expected=status?{method:state==='follow-error'?'DELETE':'GET',url:origin+(state==='follow-error'?S28_FOLLOW_PATH:S28_DETAIL_PATH),status}:null;
  const reason=status===404?'Not Found':'Internal Server Error';
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${status} (${reason})`&&failedRequests.length===0;
  const errors=[];
  if(!S28_MEASURED_STATES.includes(state))errors.push('S28_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S28_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export async function mockS28Application(page,state,origin,errors){
  if(!S28_MEASURED_STATES.includes(state))throw Error('S28_FIXTURE_SCOPE');
  const apiRequests=[],expectedHttpErrors=[];let releaseFollow;
  const followPending=new Promise(resolve=>{releaseFollow=resolve;});
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    let body;try{body=request.postDataJSON();}catch{errors.push('S28_INVALID_REQUEST_BODY');return route.abort();}
    const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
    const expected=expectedS28Requests(state)[apiRequests.length-1];
    if(url.hash||canonical(item)!==canonical(expected)){errors.push('S28_UNEXPECTED_REQUEST');return route.abort();}
    const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
    if(url.pathname===session)return respond(200,{authenticated:true,actor});
    if(url.pathname===S28_DETAIL_PATH){
      if(state==='loading')return; // Explicit pending GET; cancelled only by context disposal.
      if(state==='missing')return respond(404,{detail:{code:'school_not_found'}});
      if(state==='error')return respond(500,{detail:{code:'unavailable'}});
      return respond(200,s28DetailResponse(state));
    }
    if(state==='following'&&url.pathname===S28_FOLLOW_PATH){releaseFollow(()=>respond(200,{followed:true,notify_opt_in:false}));return;}
    if(state==='follow-error'&&url.pathname===S28_FOLLOW_PATH)return respond(500,{detail:{code:'unavailable'}});
    if(state==='save-pending'&&url.pathname===S28_SAVE_PATH)return; // No optimistic acknowledgment.
    errors.push('UNMATCHED_API');return route.abort();
  });
  const detailRead=page.waitForRequest(r=>r.method()==='GET'&&new URL(r.url()).pathname===S28_DETAIL_PATH);
  await page.goto(origin+S28_ROUTE);await detailRead;
  let followConfirmation;
  if(state==='loading')await page.getByRole('status',{name:'Loading law school',exact:true}).waitFor();
  else if(['missing','error'].includes(state)){
    await page.getByRole('heading',{name:state==='missing'?'This school page is not available.':'The school did not load.',exact:true}).waitFor();
    await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
  }else{
    await page.getByRole('heading',{name:'Sabarmati Law College.',exact:true}).waitFor();
    if(state==='following'){
      await page.getByRole('button',{name:'Follow',exact:true}).press('Enter');
      const complete=await followPending;
      await page.getByRole('button',{name:'Updating',exact:true}).waitFor();
      const before=await page.locator('.s28-actions button').nth(1).evaluate(el=>({pressed:el.getAttribute('aria-pressed'),disabled:el.getAttribute('aria-disabled'),busy:el.getAttribute('aria-busy'),checkbox:!!document.querySelector('#s28-notify'),announcement:document.querySelector('.s20-announcement')?.textContent}));
      if(before.pressed!=='false'||before.disabled!=='true'||before.busy!=='true'||before.checkbox||before.announcement)throw Error('S28_PREMATURE_FOLLOW_CONFIRMATION');
      await complete();await page.getByRole('button',{name:'Following',exact:true}).waitFor();
      await page.getByRole('checkbox',{name:'Notify me about updates to this school',exact:true}).waitFor();
      followConfirmation={noSuccessBeforeResponse:true,response:{followed:true,notify_opt_in:false}};
    }
    if(state==='save-pending'){
      const put=page.waitForRequest(r=>r.method()==='PUT'&&new URL(r.url()).pathname===S28_SAVE_PATH);
      await page.getByRole('button',{name:'Save',exact:true}).press('Enter');await put;
      await page.getByRole('button',{name:'Saving',exact:true}).waitFor();
    }
    if(state==='follow-error'){
      await page.getByRole('button',{name:'Following',exact:true}).press('Enter');
      await page.getByRole('heading',{name:'Sabarmati Law College.',exact:true}).waitFor();
      await page.getByRole('button',{name:'Reload school',exact:true}).waitFor();
      await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
    }
  }
  // The frozen reference is a top-of-document viewport. Restore that viewport
  // after genuine keyboard actions; preserve active focus, DOM and all pixels.
  await page.evaluate(()=>{window.scrollTo(0,0);return new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  if(!verifyS28Requests(state,apiRequests)||page.url()!==origin+S28_ROUTE)throw Error(`S28_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s28-detail main').evaluate(host=>{
    const button=el=>el?{text:el.textContent,pressed:el.getAttribute('aria-pressed'),disabled:el.getAttribute('aria-disabled'),busy:el.getAttribute('aria-busy')}:null;
    const checkbox=host.querySelector('#s28-notify');
    return {heading:host.querySelector('h1')?.textContent,loading:!!host.querySelector('[aria-label="Loading law school"]'),error:!!host.querySelector('[role="alert"]'),status:host.querySelector('.s20-code')?.textContent??'',
      save:button(host.querySelector('.s28-actions button')),follow:button(host.querySelectorAll('.s28-actions button')[1]),
      notification:checkbox?{checked:checkbox.checked,disabled:checkbox.getAttribute('aria-disabled')}:null,
      unknownNotification:host.textContent.includes('Your notification preference is not available here.'),
      facts:[...host.querySelectorAll('.s28-fact .s28-kv b')].map(e=>e.textContent),sources:[...host.querySelectorAll('.s28-fact a')].map(e=>e.href),
      announcement:host.querySelector('.s20-announcement')?.textContent??'',reload:!![...host.querySelectorAll('button')].find(e=>e.textContent==='Reload school'),
      focusRole:document.activeElement?.getAttribute('role'),scroll:[scrollX,scrollY]};
  });
  const loaded=!['loading','missing','error'].includes(state),locked=['save-pending','follow-error'].includes(state);
  const serverConfirmationVerified=snapshot.heading===(loaded?'Sabarmati Law College.':'Law school.')&&snapshot.loading===(state==='loading')
    &&snapshot.error===['missing','error','follow-error'].includes(state)&&snapshot.status===(state==='missing'?'HTTP 404':state==='error'?'HTTP 500':'')
    &&canonical(snapshot.save)===canonical(loaded?{text:state==='save-pending'?'Saving':'Save',pressed:'false',disabled:String(locked),busy:state==='save-pending'?'true':null}:null)
    &&canonical(snapshot.follow)===canonical(loaded?{text:'Following',pressed:'true',disabled:String(locked),busy:null}:null)
    &&canonical(snapshot.notification)===canonical(state==='following'?{checked:false,disabled:'false'}:null)
    &&snapshot.unknownNotification===(loaded&&state!=='following')&&snapshot.reload===(state==='follow-error')
    &&snapshot.announcement===(state==='following'?'Following preference confirmed.':'')
    &&canonical(snapshot.facts)===canonical(loaded?['2009','Ahmedabad','180','Off campus']:[])
    &&canonical(snapshot.sources)===canonical(loaded?Array(4).fill('https://example.test/sabarmati'):[])
    &&canonical(snapshot.scroll)===canonical([0,0]);
  if(!serverConfirmationVerified)throw Error(`S28_SERVER_CONFIRMATION_PROOF_MISSING:${JSON.stringify(snapshot)}`);
  return {evidenceKind:'live-route',evidenceDescription:'Live S-28 detail route with synthetic API responses and genuine Save/Follow keyboard actions; top-of-document viewport with focus retained; not live-backend or independent QA evidence',
    syntheticServer:true,artificialDelay:false,navigationFrozen:false,apiRequests,expectedHttpErrors,
    routeProof:{path:'/s-28',state,requestSequenceVerified:true,serverConfirmationVerified},detailProof:snapshot,
    ...(followConfirmation?{followConfirmation}:{}),
    ...(['loading','save-pending'].includes(state)?{pendingResponse:{method:state==='loading'?'GET':'PUT',url:origin+(state==='loading'?S28_DETAIL_PATH:S28_SAVE_PATH),cancelledBy:'context-disposal'}}:{})};
}

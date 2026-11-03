// S-29-only live-route fixtures; all institutional facts are synthetic.
// API-shaped responses, real navigation and no product DOM/CSS substitution.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S29_MEASURED_STATES} from './nyay66-s29-coverage.mjs';
const session='/api/v1/auth/student/session';
export const S29_COMPARE_PATH='/api/v1/law-schools/compare';
export const S29_IDS=Object.freeze([1,2,3,4].map(n=>`00000000-0000-4000-8000-00000000080${n}`));
const facts=(pairs,source)=>pairs.map(([key,value])=>({key,value,source_name:source,source_url:'https://example.test/synthetic-school-prospectus',retrieved_at:'2026-06-12T00:00:00Z'}));
export const S29_SCHOOLS=Object.freeze([
  {id:S29_IDS[0],slug:'synthetic-kaveri',name:'Kaveri National Law University',state:'Karnataka',institution_type:'national_law_university',accreditation:'BCI approved',entrance_exam:'CLAT',fees_min:285000,fees_max:310000,nirf_rank:null,
    programmes:[{degree:'B.A. LL.B. (Hons.)',duration_years:5},{degree:'LL.M.',duration_years:1}],facts:facts([['established','1998'],['location','Bengaluru'],['intake','120'],['hostel','Available']],'Institution prospectus 2026')},
  {id:S29_IDS[1],slug:'synthetic-sabarmati',name:'Sabarmati Law College',state:'Gujarat',institution_type:'private',accreditation:'BCI approved',entrance_exam:'Institution test',fees_min:410000,fees_max:455000,nirf_rank:null,
    programmes:[{degree:'B.B.A. LL.B.',duration_years:5}],facts:facts([['established','2009'],['location','Ahmedabad'],['intake','180'],['hostel','Off campus']],'Institution website')},
  {id:S29_IDS[2],slug:'synthetic-vindhya',name:'Vindhya School of Law',state:'Madhya Pradesh',institution_type:'government',accreditation:'BCI approved',entrance_exam:'State CET',fees_min:96000,fees_max:96000,nirf_rank:null,
    programmes:[{degree:'B.A. LL.B.',duration_years:5}],facts:facts([['established','1972'],['location','Bhopal'],['intake','60']],'State admissions bulletin 2026')},
  {id:S29_IDS[3],slug:'synthetic-meghna',name:'Meghna Law Institute',state:'Assam',institution_type:'deemed',accreditation:null,entrance_exam:null,fees_min:null,fees_max:null,nirf_rank:null,programmes:[],facts:[]},
].map(s=>Object.freeze({...s,saved:false,followed:false})));
function scope(state){if(!S29_MEASURED_STATES.includes(state))throw Error('S29_FIXTURE_SCOPE');}
export function s29Ids(state){scope(state);return state==='three'?S29_IDS.slice(0,3):state==='incomplete'?[S29_IDS[0],S29_IDS[3]]:state==='too-few'?S29_IDS.slice(0,1):S29_IDS.slice(0,2);}
export function s29Route(state){return `/s-29?${new URLSearchParams({ids:s29Ids(state).join(',')})}`;}
export function s29Response(state){scope(state);return {comparison_id:'00000000-0000-4000-8000-000000004471',compare_max:4,items:s29Ids(state).map(id=>structuredClone(S29_SCHOOLS.find(s=>s.id===id)))};}
export function expectedS29Requests(state){
  scope(state);return [{method:'GET',path:session,search:'',body:null},...(state==='too-few'?[]:[{method:'POST',path:S29_COMPARE_PATH,search:'',body:{school_ids:s29Ids(state)}}])];
}
export function verifyS29Requests(state,requests){return S29_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(expectedS29Requests(state));}
export function classifyS29Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const expected=state==='error'?{method:'POST',url:origin+S29_COMPARE_PATH,status:500}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text==='Failed to load resource: the server responded with a status of 500 (Internal Server Error)'&&failedRequests.length===0;
  const errors=[];
  if(!S29_MEASURED_STATES.includes(state))errors.push('S29_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S29_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export async function mockS29Application(page,state,origin,errors){
  scope(state);const apiRequests=[],expectedHttpErrors=[];
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    let body;try{body=request.postDataJSON();}catch{errors.push('S29_INVALID_REQUEST_BODY');return route.abort();}
    const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
    if(url.hash||canonical(item)!==canonical(expectedS29Requests(state)[apiRequests.length-1])){errors.push('S29_UNEXPECTED_REQUEST');return route.abort();}
    const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
    if(url.pathname===session)return respond(200,{authenticated:true,actor});
    if(url.pathname===S29_COMPARE_PATH){
      if(state==='loading')return; // Explicit pending POST; context disposal cancels it.
      if(state==='error')return respond(500,{detail:'Internal Server Error'}); // No invented backend error code.
      return respond(200,s29Response(state));
    }
    errors.push('UNMATCHED_API');return route.abort();
  });
  const sessionRead=page.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname===session);
  await page.goto(origin+s29Route(state));await sessionRead;
  if(state==='loading'){
    await page.getByRole('status',{name:'Loading comparison',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('.s29-comparison'));
  }else if(['too-few','error'].includes(state)){
    await page.getByRole('heading',{name:state==='too-few'?'Pick one more school.':'The comparison did not load.',exact:true}).waitFor();
    await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
  }else await page.locator('.s29-table').first().waitFor();
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  if(!verifyS29Requests(state,apiRequests)||page.url()!==origin+s29Route(state))throw Error(`S29_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s29-comparison main').evaluate(host=>({
    heading:host.querySelector('h1')?.textContent,loading:!!host.querySelector('[aria-label="Loading comparison"]'),error:!!host.querySelector('[role="alert"]'),
    tables:host.querySelectorAll('table').length,columns:[...host.querySelectorAll('thead:first-of-type a')].slice(0,host.querySelector('thead')?.querySelectorAll('a').length??0).map(a=>({name:a.textContent,path:a.getAttribute('href')})),
    comparisonId:document.querySelector('.s29-comparison-id')?.textContent??null,count:host.querySelector('.s29-count')?.textContent??null,
    http:host.querySelector('.s20-code')?.textContent??'',errorCode:host.querySelector('.s29-error-code')?.textContent??'',
    differencesOnly:host.querySelector('[role="switch"]')?.getAttribute('aria-checked')??null,
    pairs:[...host.querySelectorAll('input[type="radio"]')].map(r=>r.checked),
    notProvided:host.querySelectorAll('td .s29-na').length,factsOpen:host.querySelector('details')?.open??null,
    focusRole:document.activeElement?.getAttribute('role'),scroll:[scrollX,scrollY],
  }));
  const loaded=['complete','three','incomplete'].includes(state),wire=loaded?s29Response(state):null;
  const mobile=page.viewportSize().width<900,shown=wire?(mobile&&state==='three'?wire.items.slice(0,2):wire.items):[];
  const selectionVerified=canonical(snapshot.columns)===canonical(shown.map(item=>({name:item.name,path:`/s-28?${new URLSearchParams({id:item.id,from:'s29',ids:s29Ids(state).join(',')})}`})))
    &&canonical(snapshot.pairs)===canonical(loaded&&mobile&&state==='three'?[true,false,false]:[]);
  const serverConfirmationVerified=snapshot.heading==='Compare schools.'&&snapshot.loading===(state==='loading')&&snapshot.error===['too-few','error'].includes(state)
    &&snapshot.tables===(loaded?2:0)&&snapshot.comparisonId===(wire?.comparison_id??null)&&snapshot.count===(wire?`${wire.items.length} of ${wire.compare_max} schools`:null)
    &&snapshot.http===(state==='error'?'HTTP 500':'')&&snapshot.errorCode===(state==='error'?'http_500':'')&&snapshot.differencesOnly===(loaded?'false':null)
    &&(!loaded||(snapshot.notProvided>0&&snapshot.factsOpen===true))&&canonical(snapshot.scroll)===canonical([0,0]);
  if(!serverConfirmationVerified||!selectionVerified)throw Error(`S29_COMPARISON_PROOF_MISSING:${JSON.stringify(snapshot)}`);
  return {evidenceKind:'live-route',evidenceDescription:'Live S-29 route with synthetic API responses; actual ordered comparison, null handling and mobile pair selection; not live-backend or independent QA evidence'
      +(state==='too-few'?'; actual client-side minimum guard, no comparison POST; frozen server CompareError variant not executed':''),
    syntheticServer:true,artificialDelay:false,navigationFrozen:false,apiRequests,expectedHttpErrors,
    routeProof:{path:'/s-29',state,requestSequenceVerified:true,serverConfirmationVerified,selectionVerified},comparisonProof:snapshot,
    ...(state==='too-few'?{coverageLimitation:'Actual client-side minimum guard for one selected school; no comparison POST or server CompareError. The frozen server-error variant is not claimed as executed.'}:{}),
    ...(state==='loading'?{pendingResponse:{method:'POST',url:origin+S29_COMPARE_PATH,cancelledBy:'context-disposal'}}:{})};
}

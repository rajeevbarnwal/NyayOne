// S-31-only synthetic backend-shaped replies on the actual authenticated route.
// No product DOM/CSS substitutions, invented server filters, or frozen navigation.
import {actor} from './nyay66-fixtures.mjs';
import {canonical,digest} from './nyay66-enforcement.mjs';
import {S31_MEASURED_STATES} from './nyay66-s31-coverage.mjs';
export const S31_PATHS=Object.freeze({session:'/api/v1/auth/student/session',tutors:'/api/v1/tutors'});
export const S31_TUTORS=Object.freeze([
  ['Adv. Meera Krishnan','Arbitration and ADR practice, Bengaluru',9,'4.80',31,true,true,89900],
  ['Rohan Iyer','Senior student mentor, moot court preparation',2,'4.60',18,true,false,29900],
  ['Adv. Farhan Qureshi','Criminal trial practice, sessions courts',5,null,0,false,false,119900],
  ['Adv. Kavya Menon','Constitutional writs, High Court practice',7,'4.70',12,true,true,99900],
  ['Sneha Rao','Senior student mentor, legal research and writing',1,null,0,false,false,24900],
].map(([display_name,headline,experience_years,rating_avg,rating_count,verified_identity,verified_credentials,session_price_paise],i)=>Object.freeze({
  id:`00000000-0000-4000-8000-00000000310${i+1}`,display_name,headline,experience_years,rating_avg,rating_count,verified_identity,verified_credentials,session_price_paise,currency:'INR',status:'active',
})));
const sorts=Object.freeze(['rating_desc','rating_asc','experience_desc','experience_asc','name_asc','newest']);
function scope(state){if(!S31_MEASURED_STATES.includes(state))throw Error('S31_FIXTURE_SCOPE');}
function queryFor(state){
  scope(state);
  return `${state==='filters-open'?'?subject=Arbitration&':state==='no-matches'?'?q=no-synthetic-match&':'?'}sort=rating_desc&limit=3&offset=${state==='page-2'?3:0}`;
}
function routeQuery(state){return state==='filters-open'?'?subject=Arbitration&limit=3':state==='no-matches'?'?q=no-synthetic-match&limit=3':state==='page-2'?'?limit=3&offset=3':'?limit=3';}
export function s31Response(state){
  scope(state);
  // The synthetic server returns a supported three-item page, sorted before
  // slicing. This intentionally does not reproduce an inconsistent sample order.
  const items=state==='no-matches'?[]:state==='filters-open'?[S31_TUTORS[0],S31_TUTORS[1]]:[...S31_TUTORS];
  items.sort((a,b)=>(b.rating_avg===null?-1:Number(b.rating_avg))-(a.rating_avg===null?-1:Number(a.rating_avg))||a.display_name.localeCompare(b.display_name));
  const offset=state==='page-2'?3:0;
  return {items:items.slice(offset,offset+3),total:items.length,limit:3,offset,has_more:offset+3<items.length,sort:'rating_desc',allowed_sorts:[...sorts]};
}
export function expectedS31Requests(state){
  scope(state);const get=(path,search='')=>({method:'GET',path,search,body:null});
  return [get(S31_PATHS.session),...(state==='offline'?[]:state==='page-2'?[get(S31_PATHS.tutors,queryFor('results')),get(S31_PATHS.tutors,queryFor(state))]:[get(S31_PATHS.tutors,queryFor(state))])];
}
export function verifyS31Requests(state,requests){return S31_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(expectedS31Requests(state));}
export function classifyS31Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const status=state==='rate-limited'?429:state==='error'?500:null,reason=status===429?'Too Many Requests':'Internal Server Error';
  const expected=status?{method:'GET',url:origin+S31_PATHS.tutors+queryFor(state),status}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${status} (${reason})`&&failedRequests.length===0;
  const errors=[];
  if(!S31_MEASURED_STATES.includes(state))errors.push('S31_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S31_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export async function mockS31Application(page,state,origin,errors){
  scope(state);const apiRequests=[],expectedHttpErrors=[],pendingResponses=[];let finishSession,cachedLogo;
  const sessionPending=new Promise(resolve=>{finishSession=resolve;});
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/')){
      // Playwright routing disables Chromium's HTTP cache. Replay only the real
      // logo bytes fetched before disconnect, at the unchanged asset URL. This
      // is a disclosed test-only static cache, never an API/offline exemption.
      if(state==='offline'&&url.pathname==='/brand/nyayone-mark.svg'&&method==='GET'&&!url.search){
        if(!cachedLogo){const original=await route.fetch();if(original.status()!==200)throw Error('S31_LOGO_PRELOAD_FAILED');const body=await original.body();cachedLogo={body,contentType:original.headers()['content-type'],sha256:digest(body),replays:0};}
        else cachedLogo.replays++;
        return route.fulfill({status:200,contentType:cachedLogo.contentType,body:cachedLogo.body});
      }
      return route.continue();
    }
    let body;try{body=request.postDataJSON();}catch{errors.push('S31_INVALID_REQUEST_BODY');return route.abort();}
    const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
    if(url.hash||canonical(item)!==canonical(expectedS31Requests(state)[apiRequests.length-1])){errors.push('S31_UNEXPECTED_REQUEST');return route.abort();}
    const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
    if(url.pathname===S31_PATHS.session){const complete=()=>respond(200,{authenticated:true,actor});if(state==='offline'){finishSession(complete);return;}return complete();}
    if(state==='loading'){pendingResponses.push({method,url:url.href,cancelledBy:'context-disposal'});return;}
    if(state==='error')return respond(500,{detail:'Internal Server Error'});
    if(state==='rate-limited')return respond(429,{detail:{code:'rate_limit_exceeded',message:'Too many requests',limit:30,window_seconds:60,retry_after_seconds:1}});
    return respond(200,s31Response(state==='page-2'&&url.searchParams.get('offset')==='0'?'results':state));
  });
  const initialState=state==='page-2'?'results':state;
  await page.goto(origin+'/s-31'+routeQuery(initialState));
  if(state==='offline'){
    // Prime the existing font assets, then genuinely disconnect the browser
    // before releasing the pending session response. Product offline handling
    // must prevent the private GET; no navigator shim or synthetic network error.
    const complete=await sessionPending;
    // This private screen mounts after session validation. Preload the real
    // logo into the explicit static cache; no product DOM or asset substitution.
    await page.evaluateHandle(async()=>{const logo=new Image();logo.src='/brand/nyayone-mark.svg';await logo.decode();await Promise.all([...document.fonts].map(f=>f.load()));await document.fonts.ready;return logo;});
    await page.context().setOffline(true);await complete();
  }
  await page.getByRole('heading',{name:'Find a mentor.',exact:true}).waitFor();
  const negative=['rate-limited','error','offline'].includes(state),positive=!negative&&state!=='loading';
  if(state==='loading')await page.getByRole('status',{name:'Loading mentors',exact:true}).waitFor();
  else if(negative){
    await page.getByRole('heading',{name:{'rate-limited':'Too many searches in a short time.',error:'Mentors did not load.',offline:'You are offline.'}[state],exact:true}).waitFor();
    await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
    if(state==='rate-limited')await page.waitForFunction(()=>document.querySelector('[data-s31-retry]')?.getAttribute('aria-disabled')==='false'); // Real one-second server cooldown; no clock override.
  }else{
    await page.locator('#s31-results-summary').waitFor();
    if(state==='page-2'){
      await page.getByRole('button',{name:'Next page',exact:true}).press('Enter');
      await page.waitForURL(origin+'/s-31'+routeQuery(state));
      await page.waitForFunction(()=>document.activeElement?.id==='s31-results-summary');
    }
    if(state==='filters-open')await page.getByText('Filters and sort',{exact:true}).click();
    if(state==='no-matches')await page.getByRole('heading',{name:'No mentors match.',exact:true}).waitFor();
    else await page.locator('.s31-discovery article').first().waitFor();
  }
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  if(!verifyS31Requests(state,apiRequests)||page.url()!==origin+'/s-31'+routeQuery(state))throw Error(`S31_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s31-discovery').evaluate(host=>({
    heading:host.querySelector('h1')?.textContent,loading:!!host.querySelector('[aria-label="Loading mentors"]'),
    summary:host.querySelector('#s31-results-summary')?.textContent??'',filtersOpen:host.querySelector('details').open,
    subject:host.querySelector('#s31-subject')?.value,search:host.querySelector('#s31-q')?.value,sort:host.querySelector('#s31-sort')?.value,
    cards:[...host.querySelectorAll('article')].map(a=>({name:a.querySelector('.s20-title span')?.textContent,path:a.querySelector('a')?.getAttribute('href'),headline:a.querySelector('.s20-title small')?.textContent,metadata:[...a.querySelectorAll('.s20-meta p')].map(p=>p.textContent),claims:[...a.querySelectorAll('.s20-chip')].map(c=>c.textContent)})),
    errorHeading:host.querySelector('[role="alert"] h2')?.textContent??'',errorCopy:host.querySelector('[role="alert"] p')?.textContent??'',http:host.querySelector('.s20-code')?.textContent??'',
    retryDisabled:host.querySelector('[data-s31-retry]')?.getAttribute('aria-disabled'),online:navigator.onLine,
    pager:[...host.querySelectorAll('.s20-pager button')].map(b=>({name:b.getAttribute('aria-label'),disabled:b.getAttribute('aria-disabled')})),
    sessions:[...host.querySelectorAll('a')].filter(a=>a.textContent==='My sessions').map(a=>a.getAttribute('href')),
    focusRole:document.activeElement?.getAttribute('role'),focusId:document.activeElement?.id,scroll:[scrollX,scrollY],
  }));
  const response=positive?s31Response(state):null;
  const shown=response?.items??[],money=t=>new Intl.NumberFormat('en-IN',{style:'currency',currency:t.currency,minimumFractionDigits:t.session_price_paise%100?2:0,maximumFractionDigits:2}).format(t.session_price_paise/100);
  const expectedCards=shown.map(t=>({name:t.display_name,path:`/s-32?tutor=${t.id}`,headline:t.headline||'Headline not provided',metadata:[`${t.experience_years} ${t.experience_years===1?'year':'years'} · ${t.rating_count===0||t.rating_avg===null?'No ratings yet':`${t.rating_avg} from ${t.rating_count} ratings`}`,`${money(t)} per session`],claims:[...(t.verified_identity?['Identity verified']:[]),...(t.verified_credentials?['Credentials verified']:[]),...(!t.verified_identity?['Identity not verified']:[]),...(!t.verified_credentials?['Credentials not verified']:[])]}));
  const serverConfirmationVerified=snapshot.heading==='Find a mentor.'&&snapshot.loading===(state==='loading')&&canonical(snapshot.cards)===canonical(expectedCards)
    &&snapshot.http===(state==='error'?'HTTP 500':state==='rate-limited'?'HTTP 429 · rate_limit_exceeded':'')
    &&snapshot.errorHeading===({error:'Mentors did not load.',offline:'You are offline.','rate-limited':'Too many searches in a short time.'}[state]??'')
    &&snapshot.errorCopy===({error:'Your booked sessions are unaffected.',offline:'No request was sent. Reconnect and retry.','rate-limited':'Wait a moment, then try again.'}[state]??'')
    &&snapshot.online===(state!=='offline')&&(!negative||snapshot.focusRole==='alert')&&canonical(snapshot.sessions)===canonical(['/s-35','/s-35']);
  const searchPaginationVerified=snapshot.summary===(response?`${response.total} mentors · page ${Math.floor(response.offset/3)+1} of ${Math.max(1,Math.ceil(response.total/3))} · highest rated`:'')
    &&snapshot.filtersOpen===(state==='filters-open')&&snapshot.subject===(state==='filters-open'?'Arbitration':'')&&snapshot.search===(state==='no-matches'?'no-synthetic-match':'')&&snapshot.sort==='rating_desc'
    &&canonical(snapshot.pager)===canonical(response?[{name:'Previous page',disabled:response.offset<=0?'true':'false'},{name:'Next page',disabled:response.has_more?'false':'true'}]:[])
    &&(state!=='page-2'||snapshot.focusId==='s31-results-summary');
  if(!serverConfirmationVerified||!searchPaginationVerified)throw Error(`S31_DISCOVERY_PROOF_MISSING:${JSON.stringify(snapshot)}`);
  return {evidenceKind:'live-route',evidenceDescription:'Live authenticated S-31 route with synthetic backend replies, server-supported queries, actual Next/disclosure actions, real browser offline with a test-only cache of the unchanged logo and HTTP 429/500; not live-backend or independent QA evidence',syntheticServer:true,artificialDelay:false,navigationFrozen:false,
    apiRequests,expectedHttpErrors,pendingResponses,routeProof:{path:'/s-31',state,requestSequenceVerified:true,serverConfirmationVerified,searchPaginationVerified},discoveryProof:snapshot,
    ...(state==='offline'?{browserOffline:true,fontsPrimedBeforeOffline:true,sessionResponseReleasedAfterDisconnect:true,directoryRequestSent:false,staticAssetCache:{path:'/brand/nyayone-mark.svg',sha256:cachedLogo.sha256,replays:cachedLogo.replays,testOnly:true}}:{}),
    ...(state==='rate-limited'?{serverRetryAfterSeconds:1,cooldownObservedWithoutClockOverride:true}:{}),
  };
}

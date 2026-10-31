// S-27 only: real public route, supported server queries and genuine UI actions.
// Synthetic design-aligned summaries are not live institutional/backend evidence.
// No DOM replacement, private counts, navigation freeze or automatic approvals.
import {S27_MEASURED_STATES} from './nyay66-s27-coverage.mjs';
const directory='/api/v1/law-schools',session='/api/v1/auth/student/session';
export const S27_QUERY='?sort=name&page=1&page_size=4';
// Four is a supported page_size (backend permits 1..50), selected in the URL.
// compare_max=4 is the backend default, not the prototype's illustrative three.
export const S27_SCHOOLS=Object.freeze([
  ['Kaveri National Law University','Karnataka','national_law_university','CLAT',285000,310000,18],
  ['Mahanadi National Law University','Odisha','national_law_university','CLAT',240000,265000,8],
  ['Meghna Law Institute','Assam','deemed','CLAT',150000,180000,12],
  ['Sabarmati Law College','Gujarat','private','Institution test',410000,455000,25],
  ['Vindhya School of Law','Madhya Pradesh','government','State CET',96000,96000,null],
  ['Yamuna Institute of Legal Studies','Delhi','private','Institution test',380000,380000,null],
].map(([name,state,institution_type,entrance_exam,fees_min,fees_max,nirf_rank],i)=>Object.freeze({
  id:`00000000-0000-4000-8000-00000000070${i+1}`,slug:`synthetic-school-${i+1}`,name,state,institution_type,
  accreditation:'BCI approved',entrance_exam,fees_min,fees_max,nirf_rank,
})));
function queryFor(state){
  if(state==='invalid-filter')return '?sort=unsupported&page=1&page_size=4';
  if(state==='page-2')return '?sort=name&page=2&page_size=4';
  if(state==='sort-fees')return '?sort=fees&page=1&page_size=4';
  if(state==='sort-nirf')return '?sort=nirf_rank&page=1&page_size=4';
  if(state==='no-results')return '?q=no-synthetic-match&sort=name&page=1&page_size=4';
  return S27_QUERY;
}
export function parseS27Query(url,method){
  const keys=[...url.searchParams.keys()].sort(),q=url.searchParams.get('q'),sort=url.searchParams.get('sort'),page=url.searchParams.get('page');
  const expected=q===null?['page','page_size','sort']:['page','page_size','q','sort'];
  if(method!=='GET'||url.pathname!==directory||url.hash||JSON.stringify(keys)!==JSON.stringify(expected)
    ||(q!==null&&q!=='no-synthetic-match')||!['name','fees','nirf_rank','unsupported'].includes(sort)
    ||!['1','2'].includes(page)||url.searchParams.get('page_size')!=='4')throw Error('S27_DIRECTORY_QUERY');
  return {q,sort,page:Number(page),pageSize:4};
}
export function s27Response(query){
  if(query.sort==='unsupported')throw Error('S27_INVALID_FILTER_REQUIRES_HTTP_422');
  let items=query.q?[]:[...S27_SCHOOLS];
  items.sort((a,b)=>query.sort==='fees'?a.fees_min-b.fees_min||a.name.localeCompare(b.name)
    :query.sort==='nirf_rank'?(a.nirf_rank??Infinity)-(b.nirf_rank??Infinity)||a.name.localeCompare(b.name):a.name.localeCompare(b.name));
  const total=items.length,offset=(query.page-1)*query.pageSize;
  return {items:items.slice(offset,offset+query.pageSize),total,page:query.page,page_size:query.pageSize,compare_max:4};
}
export function expectedS27Requests(state){
  if(!S27_MEASURED_STATES.includes(state))throw Error('S27_FIXTURE_SCOPE');
  return [{method:'GET',path:session,search:''},...(state==='offline'?[]:[{method:'GET',path:directory,search:queryFor(state)}])];
}
export function verifyS27Requests(state,requests){
  if(!S27_MEASURED_STATES.includes(state))return false;
  const expected=expectedS27Requests(state);
  return requests.length===expected.length&&requests.every((r,i)=>['method','path','search'].every(k=>r[k]===expected[i][k]));
}
export function classifyS27Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const status=state==='invalid-filter'?422:state==='error'?500:null,reason=status===422?'Unprocessable Entity':'Internal Server Error';
  const expected=status?{method:'GET',url:origin+directory+queryFor(state),status}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${status} (${reason})`&&failedRequests.length===0;
  const errors=[];
  if(!S27_MEASURED_STATES.includes(state))errors.push('S27_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S27_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export async function mockS27Application(page,state,origin,errors){
  if(!S27_MEASURED_STATES.includes(state))throw Error('S27_FIXTURE_SCOPE');
  const apiRequests=[],expectedHttpErrors=[];let finishSession;
  const sessionPending=new Promise(resolve=>{finishSession=resolve;});
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    apiRequests.push({method,path:url.pathname,search:url.search});
    const respond=(status,body)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(body)});};
    if(url.pathname===session&&method==='GET'&&!url.search&&!url.hash){
      const complete=()=>respond(200,{authenticated:false,actor:null});
      if(state==='offline'){finishSession(complete);return;}
      return complete();
    }
    if(url.pathname===directory){
      let query;try{query=parseS27Query(url,method);}catch{errors.push('S27_DIRECTORY_QUERY');return route.abort();}
      if(url.search!==queryFor(state)){errors.push('S27_UNEXPECTED_QUERY');return route.abort();}
      if(state==='loading')return; // Deliberately pending GET, cancelled only by context disposal.
      if(state==='invalid-filter')return respond(422,{detail:{code:'unsupported_sort',allowed:['fees','name','nirf_rank']}});
      if(state==='error')return respond(500,{detail:{code:'unavailable'}});
      return respond(200,s27Response(query));
    }
    errors.push('UNMATCHED_API');return route.abort();
  });
  const firstRead=page.waitForRequest(r=>r.method()==='GET'&&new URL(r.url()).pathname===(state==='offline'?session:directory));
  await page.goto(origin+'/s-27'+queryFor(state));
  await page.getByRole('heading',{name:'Find a law school.',exact:true}).waitFor();
  if(state==='offline'){
    // Let real assets finish while the initial session response is held. Change
    // the browser's connectivity, then release that already-started response.
    // Product navigator.onLine handling must prevent the public directory GET.
    // Prime all existing font faces: error/axe probes can need faces unused by
    // the skeleton. This loads pinned assets without changing any declaration.
    const complete=await sessionPending;
    await page.evaluate(async()=>{await Promise.all([...document.fonts].map(face=>face.load()));await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
    await page.context().setOffline(true);await complete();
  }
  await firstRead;
  const negative=['invalid-filter','error','offline'].includes(state),positive=!negative&&state!=='loading';
  if(state==='loading')await page.getByRole('status',{name:'Loading law schools',exact:true}).waitFor();
  else if(negative){
    await page.getByRole('heading',{name:{'invalid-filter':'The server did not accept a filter.',error:'Schools did not load.',offline:'You are offline.'}[state],exact:true}).waitFor();
    await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
  }else{
    await page.locator('#s27-results-summary').waitFor();
    if(state==='no-results')await page.getByRole('heading',{name:'No schools match.',exact:true}).waitFor();
    else await page.locator('main article').first().waitFor();
    if(state==='filters-open')await page.getByText('Filters',{exact:true}).click();
    if(state==='compare')for(const school of S27_SCHOOLS.slice(0,2))await page.getByRole('button',{name:`Add ${school.name} to comparison`,exact:true}).click();
  }
  await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));
  if(!verifyS27Requests(state,apiRequests)||new URL(page.url()).pathname!=='/s-27'||new URL(page.url()).search!==queryFor(state))throw Error(`S27_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s27-search').evaluate(host=>({
    heading:host.querySelector('h2')?.textContent??'',loading:!!host.querySelector('[aria-label="Loading law schools"]'),error:!!host.querySelector('[role="alert"]'),
    status:host.querySelector('.s20-code')?.textContent??'',summary:host.querySelector('#s27-results-summary')?.textContent??'',
    visibleCardIds:[...host.querySelectorAll('article .s20-title')].map(e=>new URL(e.href).searchParams.get('id')),
    selectedIds:[...host.querySelectorAll('article')].filter(e=>e.querySelector('[aria-pressed="true"]')).map(e=>new URL(e.querySelector('a').href).searchParams.get('id')),
    filtersOpen:host.querySelector('main details').open,online:navigator.onLine,
    comparison:[...host.querySelectorAll('[aria-label="Comparison"]')].filter(e=>e.getClientRects().length).map(e=>({text:e.querySelector('[role="status"]')?.textContent,disabled:e.querySelector('button')?.getAttribute('aria-disabled')})),
  }));
  const response=positive?s27Response(parseS27Query(new URL(origin+directory+queryFor(state)),'GET')):null;
  const headings={'no-results':'No schools match.','invalid-filter':'The server did not accept a filter.',error:'Schools did not load.',offline:'You are offline.'};
  const order={'sort-fees':'lowest fees first','sort-nirf':'nirf rank, ranked schools first'}[state]??'name, a to z';
  const expectedSummary=response?`${response.total} schools${response.total>4?` · page ${response.page} of 2`:''} · ${order}`:'';
  const compareOK=state==='compare'?snapshot.comparison.length===1&&snapshot.comparison[0].text==='2 of 4 selected'&&snapshot.comparison[0].disabled==='false':snapshot.comparison.length===0;
  const serverConfirmationVerified=snapshot.heading===(headings[state]??'')&&snapshot.loading===(state==='loading')&&snapshot.error===negative
    &&snapshot.status===(state==='error'?'HTTP 500':state==='invalid-filter'?'HTTP 422 · unsupported_sort':'')&&snapshot.summary===expectedSummary
    &&JSON.stringify(snapshot.visibleCardIds)===JSON.stringify(response?.items.map(i=>i.id)??[])
    &&JSON.stringify(snapshot.selectedIds)===JSON.stringify(state==='compare'?S27_SCHOOLS.slice(0,2).map(s=>s.id):[])
    &&snapshot.filtersOpen===(state==='filters-open')&&snapshot.online===(state!=='offline')&&compareOK;
  if(!serverConfirmationVerified)throw Error(`S27_SERVER_CONFIRMATION_PROOF_MISSING:${JSON.stringify(snapshot)}`);
  return {evidenceKind:'live-route',evidenceDescription:'Live S-27 public route with synthetic API responses and UI comparison/disclosure actions; not live-backend or independent QA evidence',
    syntheticServer:true,artificialDelay:false,navigationFrozen:false,apiRequests,expectedHttpErrors,
    routeProof:{path:'/s-27',state,requestSequenceVerified:true,serverConfirmationVerified},
    directoryProof:{...snapshot,compareMax:response?.compare_max??null,query:queryFor(state),pageSize:4,serverPaginationAndSort:true,comparisonLocalOnly:true},
    ...(state==='loading'?{pendingResponse:{method:'GET',url:origin+directory+queryFor(state),cancelledBy:'context-disposal'}}:{}),
    ...(state==='offline'?{browserOffline:true,fontsPrimedBeforeOffline:true,sessionResponseReleasedAfterDisconnect:true,directoryRequestSent:false}:{})};
}

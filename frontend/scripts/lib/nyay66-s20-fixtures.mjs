// S-20-only synthetic server, genuine product route/actions. No DOM replacement,
// product clock freeze, fabricated auth, or unsupported server search parameters.
import {actor} from './nyay66-fixtures.mjs';
import {S20_MEASURED_STATES} from './nyay66-s20-coverage.mjs';
export const S20_QUERY='?page=1&page_size=20&verified_only=false';
export const S20_LISTINGS=Object.freeze([
  ['litigation-intern','Litigation intern','Menon Chambers','New Delhi',1500000,'verified','2026-08-31'],
  ['summer-associate','Summer associate','Kalpavriksha Legal','Mumbai',4000000,'verified','2026-08-25'],
  ['policy-research','Policy research intern','Sarvatra Policy Centre','Remote',null,'unverified','2026-08-20'],
  ['arbitration-intern','Arbitration intern','Nirvikar & Co.','Bengaluru',3500000,'verified','2026-08-18'],
].map(([id,role,organisation,location,stipend_monthly_paise,verification_status,application_deadline],i)=>Object.freeze({id,role,organisation,location,stipend_monthly_paise,verification_status,application_deadline,
  organisation_id:`00000000-0000-4000-8000-00000000030${i+1}`,eligibility:'Law student',tags:[],description:'Synthetic design-aligned internship fixture; not a live listing.',source:{name:'Synthetic organisation submission',url:null,retrieved_at:null,verified_at:null}})));
export function parseS20CatalogueQuery(url,method){
  const keys=[...url.searchParams.keys()].sort(),page=url.searchParams.get('page'),size=url.searchParams.get('page_size'),verified=url.searchParams.get('verified_only');
  if(method!=='GET'||url.pathname!=='/api/v1/internships'||url.hash||JSON.stringify(keys)!==JSON.stringify(['page','page_size','verified_only'])||!(/^[1-9]\d*$/).test(page||'')||!Number.isSafeInteger(Number(page))||size!=='20'||!['true','false'].includes(verified))throw Error('S20_CATALOGUE_QUERY');
  return {page:Number(page),pageSize:20,verifiedOnly:verified==='true'};
}
const negative={partial:{method:'GET',path:'/api/v1/student/internships/saved',status:503,reason:'Service Unavailable'},
  'save-failed':{method:'PUT',path:`/api/v1/student/internships/${S20_LISTINGS[0].id}/saved`,status:503,reason:'Service Unavailable'},
  error:{method:'GET',path:'/api/v1/internships'+S20_QUERY,status:500,reason:'Internal Server Error'}};
export function classifyS20Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const rule=negative[state],expected=rule?{method:rule.method,url:origin+rule.path,status:rule.status}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${rule.status} (${rule.reason})`&&failedRequests.length===0;
  const offlineURL=origin+'/api/v1/internships'+S20_QUERY;
  const offlineOK=state==='offline'&&httpResponses.length===0&&expectedHttpErrors.length===0&&failedRequests.length===1
    &&failedRequests[0].method==='GET'&&failedRequests[0].url===offlineURL&&failedRequests[0].errorText==='net::ERR_INTERNET_DISCONNECTED'
    &&consoleErrors.length===1&&consoleErrors[0].url===offlineURL&&consoleErrors[0].text==='Failed to load resource: net::ERR_INTERNET_DISCONNECTED';
  const errors=[];
  if(expected&&!httpOK)errors.push('S20_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(state==='offline'&&!offlineOK)errors.push('S20_OFFLINE_FAILURE_UNOBSERVED');
  if(!httpOK&&!offlineOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(!offlineOK&&failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,expectedOfflineFailureCount:offlineOK?1:0,errors};
}
export async function installS20Server(page,state,origin,errors,{paginated=false}={}){
  if(!S20_MEASURED_STATES.includes(state))throw Error('S20_FIXTURE_SCOPE');
  const expectedHttpErrors=[],apiRequests=[],catalogueRequests=[];let offlineRoute,saved=[];
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),method=req.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    apiRequests.push({method,path:url.pathname,search:url.search});
    const respond=(status,body)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(body)});};
    if(url.pathname==='/api/v1/internships'){
      let query;try{query=parseS20CatalogueQuery(url,method);}catch{errors.push('S20_CATALOGUE_QUERY');return route.abort();}
      catalogueRequests.push(query);
      if(state==='loading')return; // Deliberately pending server response; context disposal cancels it.
      if(state==='offline'){offlineRoute=route;return;}
      if(state==='error')return respond(500,{detail:{code:'unavailable'}});
      let items=state==='empty'||state==='verified-empty'&&query.verifiedOnly?[]:[...S20_LISTINGS];
      if(query.verifiedOnly)items=items.filter(i=>i.verification_status==='verified');
      if(paginated&&!query.verifiedOnly)items=Array.from({length:21},(_,i)=>({...S20_LISTINGS[0],id:`synthetic-page-${i+1}`,role:i===20?'Second page only':i===0?S20_LISTINGS[0].role:`Synthetic listing ${i+1}`}));
      return respond(200,{items:items.slice((query.page-1)*20,query.page*20),total:items.length,page:query.page,page_size:query.pageSize});
    }
    if(url.search||url.hash){errors.push('UNEXPECTED_API_QUERY');return route.abort();}
    if(url.pathname==='/api/v1/auth/student/session'&&method==='GET')return respond(200,{authenticated:true,actor});
    if(url.pathname==='/api/v1/student/internships/saved'&&method==='GET')return state==='partial'?respond(503,{detail:{code:'unavailable'}}):respond(200,{items:saved});
    const listing=S20_LISTINGS.find(i=>url.pathname===`/api/v1/student/internships/${i.id}/saved`);
    if(listing&&['PUT','DELETE'].includes(method)){
      if(state==='save-failed')return respond(503,{detail:{code:'unavailable'}});
      saved=method==='PUT'?[listing,...saved.filter(i=>i.id!==listing.id)]:saved.filter(i=>i.id!==listing.id);
      return respond(200,{listing_id:listing.id,saved:method==='PUT'});
    }
    errors.push('UNMATCHED_API');return route.abort();
  });
  return {expectedHttpErrors,apiRequests,catalogueRequests,disconnect:async()=>{if(!offlineRoute)throw Error('S20_OFFLINE_REQUEST_UNOBSERVED');await page.context().setOffline(true);await offlineRoute.abort('internetdisconnected');}};
}
export async function mockS20Application(page,state,origin,errors){
  const server=await installS20Server(page,state,origin,errors);
  const catalogue=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/v1/internships');
  const saved=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/student/internships/saved');
  await page.goto(origin+'/s-20');await catalogue;await (await saved).finished();
  await page.getByRole('heading',{name:'Browse internships.',exact:true}).waitFor();
  if(state==='offline'){
    // Prime the existing pinned font faces before disconnecting. The error
    // badge/axe probe can use faces absent from the loading skeleton; do not
    // mistake a late font download for the deliberately failed catalogue call.
    // This does not alter font declarations, DOM, product state or network mode.
    await page.evaluate(async()=>{await Promise.all([...document.fonts].map(face=>face.load()));await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
    await server.disconnect();
  }
  if(['loading','error','offline'].includes(state))await page.locator(`[data-screen="S-20"][data-s20-state="${state}"]`).waitFor();
  else{
    await page.locator('[data-screen="S-20"][data-s20-state="results"]').waitFor();
    if(state==='partial')await page.getByText('Your saved list did not load.',{exact:true}).waitFor();
    else if(state==='empty')await page.getByText('No internships are listed right now.',{exact:true}).waitFor();
    else{
      const save=page.getByRole('button',{name:'Save Litigation intern',exact:true});await save.waitFor();
      await page.waitForFunction(()=>document.querySelector('.s20-save')?.disabled===false);
      if(state==='filters-open'||state==='verified-empty')await page.locator('.s20-filters summary').click();
      if(state==='verified-empty'){
        await page.getByRole('button',{name:'Verified listings only',exact:true}).click();
        await page.getByText('No verified listings right now.',{exact:true}).waitFor();
        await page.locator('.s20-filters summary').click();
      }
      if(state==='local-empty'){await page.getByLabel('Search this page',{exact:true}).fill('No synthetic match');await page.getByText('No matching listings on this page',{exact:true}).waitFor();}
      if(state==='save-failed'){await save.click();await page.locator('[data-save-error="litigation-intern"]').waitFor();await page.getByText('Your saved state needs confirmation.',{exact:true}).waitFor();}
    }
  }
  const expectedCatalogue=state==='verified-empty'?2:1,expectedCalls=2+expectedCatalogue+(state==='save-failed'?1:0);
  if(server.catalogueRequests.length!==expectedCatalogue||server.apiRequests.length!==expectedCalls||new URL(page.url()).pathname!=='/s-20')throw Error('S20_REQUEST_SEQUENCE_MISMATCH');
  return {evidenceKind:'live-route',evidenceDescription:'Live S-20 route with synthetic API responses; not live-backend evidence',syntheticServer:true,artificialDelay:false,navigationFrozen:false,
    apiRequests:server.apiRequests,catalogueRequests:server.catalogueRequests,expectedHttpErrors:server.expectedHttpErrors,
    filtering:{server:['page','page_size','verified_only'],pageLocal:['search','stipend'],...(state==='local-empty'?{query:'No synthetic match',extraCatalogueRequests:0}:{})},
    ...(state==='loading'?{pendingResponse:{method:'GET',url:origin+'/api/v1/internships'+S20_QUERY,cancelledBy:'context-disposal'}}:{}),
    ...(state==='offline'?{browserOffline:true,fontsPrimedBeforeOffline:true,syntheticFailure:'net::ERR_INTERNET_DISCONNECTED'}:{})};
}

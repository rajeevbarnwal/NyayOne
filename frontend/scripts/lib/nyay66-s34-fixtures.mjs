// Actual S-34 route; synthetic backend-shaped responses, not backend or QA proof.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S34_MEASURED_STATES} from './nyay66-s34-coverage.mjs';
const ID='00000000-0000-4000-8000-000000003401';
export const S34_PATHS=Object.freeze({session:'/api/v1/auth/student/session',detail:`/api/v1/tutoring/sessions/${ID}`});
function scope(state){if(!S34_MEASURED_STATES.includes(state))throw Error('S34_FIXTURE_SCOPE');}
export function s34Wire(state){
 scope(state);const pending=state==='pending-provider';
 return {id:ID,slot_id:'00000000-0000-4000-8000-000000003402',tutor_id:'00000000-0000-4000-8000-000000003403',student_user_id:actor.sub,order_id:'00000000-0000-4000-8000-000000003404',
  status:pending?'pending_provider':state==='cancelled'?'cancelled':'confirmed',version:1,
  start_utc:'2026-08-18T13:00:00+00:00',end_utc:'2026-08-18T13:45:00+00:00',iana_timezone:'Asia/Kolkata',start_local:'2026-08-18T18:30:00+05:30',end_local:'2026-08-18T19:15:00+05:30',attendance_state:null,attendance_version:null};
}
export function expectedS34Requests(state){scope(state);return [S34_PATHS.session,S34_PATHS.detail].map(path=>({method:'GET',path,search:'',body:null}));}
export function verifyS34Requests(state,requests){return S34_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(expectedS34Requests(state));}
export function s34HttpError(state){scope(state);const e={error:[503,'Service Unavailable','http_503'],missing:[404,'Not Found','NOT_FOUND']}[state];return e?{status:e[0],reason:e[1],code:e[2],path:S34_PATHS.detail,method:'GET'}:null;}
export function classifyS34Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
 const e=s34HttpError(state),expected=e?{method:e.method,url:origin+e.path,status:e.status}:null;
 const match=x=>canonical(x)===canonical(expected);
 const httpOK=expected&&expectedHttpErrors.length===1&&match(expectedHttpErrors[0])&&httpResponses.length===1&&match(httpResponses[0])&&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${e.status} (${e.reason})`&&failedRequests.length===0;
 const errors=[];if(expected&&!httpOK)errors.push('S34_EXPECTED_HTTP_ERROR_UNOBSERVED');if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');if(failedRequests.length)errors.push('NETWORK_ERROR');if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
 return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}

// Test-only camera: document-top framing, without DOM/CSS or focus mutation.
export async function frameS34Viewport(page,state){
 scope(state);return page.evaluate(async()=>{
  if(location.pathname!=='/s-34'||!document.querySelector('.s34-session'))throw Error('S34_FRAME_SCOPE');
  const active=document.activeElement;await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  if(document.activeElement!==active)throw Error('S34_FRAME_FOCUS_CHANGED');const before=[scrollX,scrollY];window.scrollTo({left:0,top:0,behavior:'instant'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  if(document.activeElement!==active||scrollX||scrollY)throw Error('S34_FRAME_UNSTABLE');
  return {testOnly:true,origin:'document-top-after-live-interaction',before,after:[scrollX,scrollY],focusPreserved:true,domModified:false,pixelPostprocessing:false};
 });
}
export async function mockS34Application(page,state,origin,errors){
 scope(state);const wire=s34Wire(state),apiRequests=[],expectedHttpErrors=[],pendingResponses=[];
 let release;const requested=new Promise(r=>{release=r;});
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),method=req.method();
  if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
  if(!url.pathname.startsWith('/api/v1/'))return route.continue();
  let body;try{body=req.postDataJSON();}catch{errors.push('S34_INVALID_REQUEST_BODY');return route.abort();}
  const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
  if(url.hash||canonical(item)!==canonical(expectedS34Requests(state)[apiRequests.length-1])){errors.push('S34_UNEXPECTED_REQUEST');return route.abort();}
  const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
  if(url.pathname===S34_PATHS.session)return respond(200,{authenticated:true,actor});
  release(()=>{const e=s34HttpError(state);return e?respond(e.status,e.status===503?{detail:'Service Unavailable'}:{detail:{code:e.code,message:'not found'}}):respond(200,wire);});
  if(state==='loading')pendingResponses.push({method,url:url.href,cancelledBy:'context-disposal'});
 });
 await page.goto(`${origin}/s-34?session=${ID}`);
 let timer,respond;try{respond=await Promise.race([requested,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('S34_EXPECTED_REQUEST_TIMEOUT')),10000);})]);}finally{clearTimeout(timer);}
 await page.getByRole('status',{name:'Loading session',exact:true}).waitFor();
 const premature=await page.locator('.s34-facts,.s34-notice,a[href*="view=detail"]').count();if(premature)throw Error('S34_PREMATURE_CONFIRMATION');
 if(state!=='loading'){
  await respond();
  if(s34HttpError(state))await page.getByRole('heading',{name:state==='missing'?'This session is not available.':'The session did not load.',exact:true}).waitFor();
  else await page.getByRole('heading',{name:state==='confirmed'?'Confirmed.':state==='cancelled'?'This session was cancelled.':'Not confirmed yet.',exact:true}).waitFor();
 }
 const viewportFraming=await frameS34Viewport(page,state);
 if(!verifyS34Requests(state,apiRequests))throw Error('S34_REQUEST_SEQUENCE_MISMATCH');
 const snapshot=await page.evaluate(()=>({id:new URLSearchParams(location.search).get('session'),path:location.pathname,text:document.querySelector('main')?.textContent??'',
  heading:document.querySelector('h1')?.textContent,timeInstants:[...document.querySelectorAll('.s34-facts time')].map(e=>e.getAttribute('datetime')),facts:[...document.querySelectorAll('.s34-facts dd')].map(e=>e.textContent),notice:document.querySelector('.s34-notice h2')?.textContent??null,
  manage:document.querySelector('a[href*="view=detail"]')?.getAttribute('href')??null,code:document.querySelector('.s20-code')?.textContent??null,loading:!!document.querySelector('[data-loading]'),focusRole:document.activeElement?.getAttribute('role'),scroll:[scrollX,scrollY]}));
 const loaded=['confirmed','pending-provider','cancelled'].includes(state),e=s34HttpError(state);
 const sessionIdentityVerified=snapshot.id===ID&&snapshot.path==='/s-34'&&(!loaded||(canonical(snapshot.facts)===canonical(['Tue 18 Aug 2026, 6:30 PM','7:15 PM',wire.iana_timezone,wire.order_id])&&canonical(snapshot.timeInstants)===canonical([wire.start_utc,wire.end_utc])));
 const noInventedPaymentOrJoin=!/₹|Confirmed and paid|Join now|refund|receipt/i.test(snapshot.text)&&snapshot.manage===(state==='confirmed'?`/s-35?session=${ID}&view=detail`:null)&&snapshot.heading==='Session.';
 const serverConfirmationVerified=!premature&&(loaded?snapshot.notice===({confirmed:'Confirmed.','pending-provider':'Not confirmed yet.',cancelled:'This session was cancelled.'}[state]):snapshot.facts.length===0&&snapshot.loading===(state==='loading'))&&(!e||snapshot.code===`HTTP ${e.status} · ${e.code}`);
 if(!sessionIdentityVerified||!noInventedPaymentOrJoin||!serverConfirmationVerified)throw Error(`S34_LIVE_PROOF_MISSING:${JSON.stringify(snapshot)}`);
 return {evidenceKind:'live-route',evidenceDescription:'Actual S-34 route with synthetic backend-shaped session reads and genuine HTTP errors. Loading response held until context disposal; no fabricated mentor cache, payment, join or refund authority. Document-top camera preserves real focus. Not real backend or independent QA.',
  syntheticServer:true,navigationFrozen:false,artificialDelay:false,apiRequests,expectedHttpErrors,pendingResponses,viewportFraming,
  routeProof:{path:'/s-34',state,requestSequenceVerified:true,sessionIdentityVerified,noInventedPaymentOrJoin,serverConfirmationVerified},sessionProof:snapshot};
}

// Real product routes with synthetic backend-shaped responses. No provider,
// payment webhook or real backend is exercised. Pending requests stay pending.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S33_MEASURED_STATES} from './nyay66-s33-coverage.mjs';
import {S32_MENTOR,s32AvailabilityResponse} from './nyay66-s32-fixtures.mjs';
export const S33_NOW='2027-08-17T12:50:00.000Z';
export const S33_PATHS=Object.freeze({session:'/api/v1/auth/student/session',hold:'/api/v1/tutoring/booking-holds',order:'/api/v1/payments/orders',confirm:'/api/v1/tutoring/sessions'});
const HOLD='00000000-0000-4000-8000-000000003301',ORDER='00000000-0000-4000-8000-000000003302',SESSION='00000000-0000-4000-8000-000000003303';
function scope(state){if(!S33_MEASURED_STATES.includes(state))throw Error('S33_FIXTURE_SCOPE');}
export function s33Wire(state){
 scope(state);const other=state==='hold-other-mentor',duration=state==='hold-60min'?60:45;
 const mentor={...S32_MENTOR,...(other?{id:'00000000-0000-4000-8000-000000003304',display_name:'Adv. Arjun Menon',headline:'Constitutional law practice, Delhi'}:{})};
 mentor.rating_aggregate={...mentor.rating_aggregate,tutor_id:mentor.id};
 const availability=structuredClone(s32AvailabilityResponse('complete'));availability.tutor_id=mentor.id;availability.limit=100;availability.iana_timezone='Asia/Calcutta';
 const slot={...availability.slots[0],tutor_id:mentor.id,iana_timezone:'Asia/Calcutta',duration_minutes:duration,end_utc:duration===60?'2027-08-17T14:00:00+00:00':'2027-08-17T13:45:00+00:00',end_local:duration===60?'2027-08-17T19:30:00+05:30':'2027-08-17T19:15:00+05:30'};
 availability.slots=[slot];
 const hold={id:HOLD,slot_id:slot.slot_id,status:'active',expires_at:'2027-08-17T13:00:00+00:00',hold_minutes:10,price_paise:slot.price_paise,currency:'INR',replayed:false};
 const order={id:ORDER,hold_id:HOLD,provider:'synthetic',provider_order_ref:'synthetic-order-reference',amount_paise:hold.price_paise,currency:'INR',status:state==='payment-failed'?'failed':'created',brand:null,masked_last4:null,replayed:state==='payment-failed'};
 const session={id:SESSION,slot_id:slot.slot_id,tutor_id:mentor.id,student_user_id:actor.sub,order_id:ORDER,status:'confirmed',version:1,start_utc:slot.start_utc,end_utc:slot.end_utc,iana_timezone:slot.iana_timezone,start_local:slot.start_local,end_local:slot.end_local,attendance_state:null,attendance_version:null,replayed:false,reminder_jobs:0};
 return {mentor,availability,slot,hold,expired:{...hold,status:'expired',expired:true,replayed:false},order,session};
}
const orderStates=['order-pending','payment-failed','creating-session','payment-unverified','confirmed'];
export function expectedS33Requests(state){
 const w=s33Wire(state),get=(path,search='')=>({method:'GET',path,search,body:null}),post=(path,body)=>({method:'POST',path,search:'',body});
 return [get(S33_PATHS.session),get(`/api/v1/tutors/${w.mentor.id}`),get(`/api/v1/tutors/${w.mentor.id}/availability`,'?timezone=Asia%2FCalcutta&limit=100&offset=0'),post(S33_PATHS.hold,{slot_id:w.slot.slot_id,idempotency_key:'hold-key'}),
 ...(state==='hold-expired'?[get(`${S33_PATHS.hold}/${HOLD}`)]:[]),
 ...(orderStates.includes(state)?[post(S33_PATHS.order,{hold_id:HOLD,idempotency_key:'order-key'})]:[]),
 ...(['creating-session','payment-unverified','confirmed'].includes(state)?[post(S33_PATHS.confirm,{hold_id:HOLD})]:[]),
 ...(state==='session'?[get(S33_PATHS.session)]:[])];
}
function normalize(request){
 const copy=structuredClone(request);
 if(copy.method==='POST'&&[S33_PATHS.hold,S33_PATHS.order].includes(copy.path)){
  const prefix=copy.path===S33_PATHS.hold?'hold':'order';
  if(typeof copy.body?.idempotency_key==='string'&&new RegExp(`^${prefix}-[a-zA-Z0-9_-]+$`).test(copy.body.idempotency_key))copy.body.idempotency_key=`${prefix}-key`;
 }
 return copy;
}
export function verifyS33Requests(state,requests){return S33_MEASURED_STATES.includes(state)&&canonical(requests.map(normalize))===canonical(expectedS33Requests(state));}
export function s33HttpError(state){
 scope(state);const spec={
  'slot-conflict':[409,'Conflict','SLOT_UNAVAILABLE',S33_PATHS.hold],
  'payment-unverified':[400,'Bad Request','PAYMENT_UNVERIFIED',S33_PATHS.confirm],
  'rate-limited':[429,'Too Many Requests','rate_limit_exceeded',S33_PATHS.hold],
  network:[503,'Service Unavailable','http_503',S33_PATHS.hold],
  session:[401,'Unauthorized','authentication_required',S33_PATHS.hold]
 }[state];return spec?{status:spec[0],reason:spec[1],code:spec[2],path:spec[3],method:'POST'}:null;
}
export function classifyS33Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
 const e=s33HttpError(state),expected=e?{method:e.method,url:origin+e.path,status:e.status}:null;
 const match=x=>canonical(x)===canonical(expected);
 const httpOK=expected&&expectedHttpErrors.length===1&&match(expectedHttpErrors[0])&&httpResponses.length===1&&match(httpResponses[0])&&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${e.status} (${e.reason})`&&failedRequests.length===0;
 const errors=[];if(expected&&!httpOK)errors.push('S33_EXPECTED_HTTP_ERROR_UNOBSERVED');if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');if(failedRequests.length)errors.push('NETWORK_ERROR');if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
 return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
// Camera framing only; never repairs product focus or changes DOM/CSS.
export async function frameS33Viewport(page,state){
 scope(state);return page.evaluate(async session=>{
  if(location.pathname!==(session?'/s-03':'/s-33')||!document.querySelector(session?'[data-screen="S-03"]':'.s33-booking'))throw Error('S33_FRAME_SCOPE');
  const active=document.activeElement;await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  if(document.activeElement!==active)throw Error('S33_FRAME_FOCUS_CHANGED');const before=[scrollX,scrollY];window.scrollTo({left:0,top:0,behavior:'instant'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  if(document.activeElement!==active||scrollX||scrollY)throw Error('S33_FRAME_UNSTABLE');
  return {testOnly:true,origin:'document-top-after-live-interaction',before,after:[scrollX,scrollY],focusPreserved:true,domModified:false,pixelPostprocessing:false};
 },state==='session');
}
async function awaitRequest(promise){
 let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('S33_EXPECTED_REQUEST_TIMEOUT')),10000);})]);}finally{clearTimeout(timer);}
}
export async function mockS33Application(page,state,origin,errors){
 scope(state);const w=s33Wire(state),apiRequests=[],expectedHttpErrors=[],pendingResponses=[];let sessionLost=false,sessionAnonymous=false,releaseHold,releaseOrder,releaseSession;
 const holdReady=new Promise(r=>{releaseHold=r;}),orderReady=new Promise(r=>{releaseOrder=r;}),sessionReady=new Promise(r=>{releaseSession=r;});
 // Fixed Date only. Timers and navigation run normally; this is deterministic
 // synthetic deadline/cooldown data, not evidence that clocks or providers work.
 await page.clock.setFixedTime(new Date(S33_NOW));
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),method=req.method();
  if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
  if(!url.pathname.startsWith('/api/v1/'))return route.continue();
  let body;try{body=req.postDataJSON();}catch{errors.push('S33_INVALID_REQUEST_BODY');return route.abort();}
  const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
  if(url.hash||canonical(normalize(item))!==canonical(expectedS33Requests(state)[apiRequests.length-1])){errors.push('S33_UNEXPECTED_REQUEST');return route.abort();}
  const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
  if(url.pathname===S33_PATHS.session){if(sessionLost)sessionAnonymous=true;return respond(200,sessionLost?{authenticated:false,actor:null}:{authenticated:true,actor});}
  if(url.pathname===`/api/v1/tutors/${w.mentor.id}`)return respond(200,w.mentor);
  if(url.pathname.endsWith('/availability'))return respond(200,w.availability);
  const e=s33HttpError(state);
  const response=()=>{if(e?.path===url.pathname){if(e.status===401)sessionLost=true;return respond(e.status,e.status===503?{detail:'Service Unavailable'}:{detail:{code:e.code,message:e.code,...(e.status===429?{retry_after_seconds:30}:{})}});}
   if(url.pathname===S33_PATHS.hold)return respond(w.hold.replayed?200:201,w.hold);
   if(url.pathname===S33_PATHS.order)return respond(w.order.replayed?200:201,w.order);
   if(url.pathname===S33_PATHS.confirm)return respond(201,w.session);
   return respond(200,w.expired);
  };
  if(url.pathname===S33_PATHS.hold){releaseHold(response);if(state==='hold-creating')pendingResponses.push({method,url:url.href,cancelledBy:'context-disposal'});return;}
  if(url.pathname===S33_PATHS.order){releaseOrder(response);return;}
  if(url.pathname===S33_PATHS.confirm){releaseSession(response);if(state==='creating-session')pendingResponses.push({method,url:url.href,cancelledBy:'context-disposal'});return;}
  return response();
 });
 const route=`/s-33?tutor=${w.mentor.id}&slot=${w.slot.slot_id}`;await page.goto(origin+route);
 const finishHold=await awaitRequest(holdReady);await page.getByRole('heading',{name:'Holding this time for you.',exact:true}).waitFor();
 const beforeHold=await page.locator('.s33-summary').innerText();
 const holdPendingVerified=beforeHold.includes('Hold not confirmed')&&beforeHold.includes('Not yet confirmed')&&await page.getByRole('button',{name:'Create payment order',exact:true}).count()===0;
 if(!holdPendingVerified)throw Error('S33_PREMATURE_HOLD');
 let orderPendingVerified=true,sessionPendingVerified=true;
 if(state!=='hold-creating'){
  await finishHold();
  if(state==='session'){await page.waitForURL('**/s-03');await page.locator('[data-screen="S-03"]').waitFor();if(!sessionAnonymous)throw Error('S33_ANONYMOUS_SESSION_UNOBSERVED');}
  else if(s33HttpError(state)?.path===S33_PATHS.hold)await page.getByRole('alert').waitFor();
  else if(state==='hold-expired'){
   await page.locator('.s33-held').waitFor();await page.clock.setFixedTime(new Date('2027-08-17T13:00:01.000Z'));
   await page.getByRole('button',{name:'Check hold',exact:true}).click();await page.getByRole('heading',{name:'The hold expired.',exact:true}).waitFor();
  }else await page.getByRole('button',{name:'Create payment order',exact:true}).waitFor();
 }
 if(orderStates.includes(state)){
  await page.getByRole('button',{name:'Create payment order',exact:true}).press('Enter');const finishOrder=await awaitRequest(orderReady);
  await page.getByRole('heading',{name:'Creating your payment order.',exact:true}).waitFor();
  orderPendingVerified=await page.getByRole('link',{name:'View session',exact:true}).count()===0&&await page.getByRole('button',{name:'Check payment',exact:true}).count()===0;
  if(!orderPendingVerified)throw Error('S33_PREMATURE_ORDER');await finishOrder();
  await page.getByRole('button',{name:'Check payment',exact:true}).waitFor();
  if(['creating-session','payment-unverified','confirmed'].includes(state)){
   await page.getByRole('button',{name:'Check payment',exact:true}).press('Enter');const finishSession=await awaitRequest(sessionReady);
   await page.getByRole('heading',{name:'Checking your payment.',exact:true}).waitFor();sessionPendingVerified=await page.getByRole('link',{name:'View session',exact:true}).count()===0;
   if(!sessionPendingVerified)throw Error('S33_PREMATURE_SESSION');
   if(state!=='creating-session'){await finishSession();if(state==='confirmed')await page.getByRole('link',{name:'View session',exact:true}).waitFor();else await page.getByRole('heading',{name:'Payment not confirmed yet.',exact:true}).waitFor();}
  }
 }
 const viewportFraming=await frameS33Viewport(page,state);
 if(!verifyS33Requests(state,apiRequests))throw Error(`S33_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
 const snapshot=await page.evaluate(()=>({path:location.pathname,bookingVisible:!!document.querySelector('.s33-booking'),summary:document.querySelector('.s33-summary')?.textContent??'',facts:[...document.querySelectorAll('.s33-summary dd')].map(e=>e.textContent),
  notices:[...document.querySelectorAll('.s33-notice h2')].map(e=>e.textContent),error:document.querySelector('[data-error-code]')?.textContent??'',confirmed:document.querySelector('a[href^="/s-34?session="]')?.getAttribute('href')??null,
  focusRole:document.activeElement?.getAttribute('role'),scroll:[scrollX,scrollY],retryDisabled:document.querySelector('[data-action=retry]')?.getAttribute('aria-disabled')??null}));
 const sessionState=state==='session',hasHold=!['hold-creating','slot-conflict','rate-limited','network','session'].includes(state);
 const holdAuthorityVerified=holdPendingVerified&&(sessionState?!snapshot.bookingVisible:snapshot.facts[0]===w.mentor.display_name&&snapshot.facts[2]===`${w.slot.duration_minutes} min`&&snapshot.facts[3]===(hasHold?'₹899':'Not yet confirmed'));
 const paymentAuthorityVerified=orderPendingVerified&&sessionPendingVerified&&snapshot.confirmed===(state==='confirmed'?`/s-34?session=${SESSION}`:null);
 const expectedNotice={'hold-creating':'Holding this time for you.','slot-conflict':'That time was just taken.','hold-expired':'The hold expired.','order-pending':'Waiting for the payment provider.','payment-failed':'The payment did not complete.','creating-session':'Checking your payment.','payment-unverified':'Payment not confirmed yet.',confirmed:'Booking confirmed.','rate-limited':'Too many attempts in a short time.',network:'Could not reach NyayOne.'}[state];
 const serverConfirmationVerified=sessionState?sessionAnonymous&&snapshot.path==='/s-03'&&!snapshot.bookingVisible: snapshot.path==='/s-33'&&(!expectedNotice||snapshot.notices.includes(expectedNotice))&&snapshot.error===(s33HttpError(state)?.code??'')&&(state!=='rate-limited'||snapshot.retryDisabled==='true');
 if(!holdAuthorityVerified||!paymentAuthorityVerified||!serverConfirmationVerified)throw Error(`S33_LIVE_PROOF_MISSING:${JSON.stringify({holdAuthorityVerified,paymentAuthorityVerified,serverConfirmationVerified,snapshot})}`);
 return {evidenceKind:sessionState?'live-redirect-destination':'live-route',evidenceDescription:sessionState?'Actual S-03 redirect destination after genuine S-33 HTTP 401 and anonymous-session read-back. Not an S-33 page visual; synthetic backend, not independent/backend QA.':'Actual S-33 route and UI actions with synthetic backend-shaped responses and fixed Date for deadline text. Pending responses held until proof or context disposal. Document-top camera retains real focus. No real payment provider, webhook, backend or independent QA.',
  syntheticServer:true,navigationFrozen:false,artificialDelay:false,clockEvidence:{initialFixedDate:S33_NOW,deadlineAdvancedAfterHoldConfirmed:state==='hold-expired',timersRunning:true,cooldownProgressionTested:false},apiRequests,expectedHttpErrors,pendingResponses,viewportFraming,
  routeProof:{path:'/s-33',state,requestSequenceVerified:true,serverConfirmationVerified,holdAuthorityVerified,paymentAuthorityVerified,...(sessionState?{destination:'/s-03',sessionCleared:true,httpStatus:401}:{})},bookingProof:snapshot};
}

// Live S-32 route with synthetic backend-shaped data, not live-backend QA.
// Public availability currently returns available slots at one published tutor
// price. Never invent held/booked rows, per-slot price overrides or booking writes.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S32_MEASURED_STATES} from './nyay66-s32-coverage.mjs';
export const S32_ID='00000000-0000-4000-8000-000000003201';
export const S32_PATHS=Object.freeze({session:'/api/v1/auth/student/session',detail:`/api/v1/tutors/${S32_ID}`,availability:`/api/v1/tutors/${S32_ID}/availability`,hold:'/api/v1/tutoring/booking-holds'});
export const S32_MENTOR=Object.freeze({id:S32_ID,display_name:'Adv. Meera Krishnan',headline:'Arbitration and ADR practice, Bengaluru',experience_years:9,rating_avg:'4.81',rating_count:31,
 verified_identity:true,verified_credentials:true,status:'active',session_price_paise:89900,currency:'INR',source:'Bar Council roll',source_url:'https://example.test/mentor',retrieved_at:'2026-07-03T00:00:00+00:00',
 subjects:[{subject:'Arbitration',level:'Advanced'},{subject:'Contract drafting',level:'Intermediate'}],rating_aggregate:{tutor_id:S32_ID,rating_avg:'4.81',rating_count:31,distribution:{'4':6,'5':25}}});
function scope(state){if(!S32_MEASURED_STATES.includes(state))throw Error('S32_FIXTURE_SCOPE');}
const zones=state=>state==='zone-changed'||state.startsWith('dst-')?'Europe/London':'Asia/Kolkata';
const localStart=state=>state==='dst-gap'?'2027-03-28T01:30:00':'2027-10-31T01:30:00';
export function s32Route(state){
 scope(state);const q=new URLSearchParams({tutor:S32_ID,tz:zones(state)});
 if(state==='day-empty')q.set('date','2027-08-18');
 if(state.startsWith('dst-'))q.set('from_local',localStart(state));
 return `/s-32?${q}`;
}
function queryFor(state){
 const q=new URLSearchParams({timezone:zones(state)});
 if(state==='day-empty')q.set('date','2027-08-18');if(state.startsWith('dst-'))q.set('from_local',localStart(state));
 q.set('limit','50');q.set('offset','0');return `?${q}`;
}
function localISO(instant,zone){
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:zone,hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'longOffset'}).formatToParts(new Date(instant)).map(p=>[p.type,p.value]));
 const offset=parts.timeZoneName==='GMT'?'+00:00':parts.timeZoneName.slice(3);
 return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}${offset}`;
}
export function s32AvailabilityResponse(state){
 scope(state);const zone=zones(state),window={from_utc:null,to_utc:null},local_resolution={};
 let slots=[['2027-08-17T13:00:00+00:00',45],['2027-08-19T14:30:00+00:00',60],['2027-08-21T05:30:00+00:00',45]];
 if(state==='no-slots'||state==='day-empty')slots=[];
 if(state==='day-empty'){
  window.from_utc='2027-08-17T18:30:00+00:00';window.to_utc='2027-08-18T18:29:59.999999+00:00';
  local_resolution.from_local={requested_local:'2027-08-18T00:00:00',resolved_local:'2027-08-18T00:00:00+05:30',instant_utc:window.from_utc,classification:'unique',dst_adjusted:false};
  local_resolution.to_local={requested_local:'2027-08-18T23:59:59.999999',resolved_local:'2027-08-18T23:59:59.999999+05:30',instant_utc:window.to_utc,classification:'unique',dst_adjusted:false};
 }
 if(state.startsWith('dst-')){
  const gap=state==='dst-gap';window.from_utc=gap?'2027-03-28T01:30:00+00:00':'2027-10-31T00:30:00+00:00';
  local_resolution.from_local={requested_local:localStart(state),resolved_local:gap?'2027-03-28T02:30:00+01:00':'2027-10-31T01:30:00+01:00',instant_utc:window.from_utc,classification:gap?'nonexistent':'ambiguous',dst_adjusted:true};
  slots=gap?[[window.from_utc,45],['2027-03-28T09:00:00+00:00',45]]:[[window.from_utc,45],['2027-10-31T01:30:00+00:00',45],['2027-10-31T09:00:00+00:00',45]];
 }
 return {tutor_id:S32_ID,iana_timezone:zone,window,local_resolution,limit:50,offset:0,slots:slots.map(([start,duration],i)=>{
  const end=new Date(Date.parse(start)+duration*60_000).toISOString().replace('.000Z','+00:00');
  return {slot_id:`00000000-0000-4000-8000-00000000321${i+1}`,tutor_id:S32_ID,start_utc:start,end_utc:end,iana_timezone:zone,status:'available',start_local:localISO(start,zone),end_local:localISO(end,zone),duration_minutes:duration,price_paise:S32_MENTOR.session_price_paise,currency:'INR'};
 })};
}
export function expectedS32Requests(state){
 scope(state);const get=(path,search='')=>({method:'GET',path,search,body:null}),initial=['zone-changed','day-empty'].includes(state)?'complete':state;
 return [get(S32_PATHS.session),get(S32_PATHS.detail),...(['loading','profile-error','missing'].includes(state)?[]:[get(S32_PATHS.availability,queryFor(initial))]),...(['zone-changed','day-empty'].includes(state)?[get(S32_PATHS.availability,queryFor(state))]:[])];
}
export function verifyS32Requests(state,requests){return S32_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(expectedS32Requests(state));}
export function classifyS32Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
 const status=state==='missing'?404:['profile-error','availability-error'].includes(state)?500:null,request=status?expectedS32Requests(state).at(-1):null;
 const expected=status?{method:'GET',url:origin+request.path+request.search,status}:null,reason=status===404?'Not Found':'Internal Server Error';
 const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
 const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
  &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text===`Failed to load resource: the server responded with a status of ${status} (${reason})`&&failedRequests.length===0;
 const errors=[];
 if(!S32_MEASURED_STATES.includes(state))errors.push('S32_FIXTURE_SCOPE');if(expected&&!httpOK)errors.push('S32_EXPECTED_HTTP_ERROR_UNOBSERVED');
 if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');if(failedRequests.length)errors.push('NETWORK_ERROR');if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
 return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
// Disclosed camera framing after genuine interactions: restore the reference's
// document-top viewport, retaining focus and DOM. No product focus repair,
// injected style, image rewriting, delay, retry or approval-hash selection.
export async function frameS32Viewport(page){
 return page.evaluate(async()=>{
  if(location.pathname!=='/s-32'||!document.querySelector('.s32-detail'))throw Error('S32_FRAME_SCOPE');
  const focused=document.activeElement;
  await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));
  if(document.activeElement!==focused)throw Error('S32_FRAME_FOCUS_CHANGED');
  const before=[scrollX,scrollY];window.scrollTo({left:0,top:0,behavior:'instant'});await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));
  if(document.activeElement!==focused)throw Error('S32_FRAME_FOCUS_CHANGED');if(scrollX!==0||scrollY!==0)throw Error('S32_FRAME_UNSTABLE');
  return {testOnly:true,origin:'document-top-after-live-interaction',before,after:[scrollX,scrollY],focusId:focused.id,focusSlot:focused.getAttribute('data-slot'),focusPreserved:true,domModified:false,pixelPostprocessing:false};
 });
}
export async function mockS32Application(page,state,origin,errors){
 scope(state);const apiRequests=[],expectedHttpErrors=[],pendingResponses=[];let releaseChange,controlFontReadiness;
 const changePending=new Promise(resolve=>{releaseChange=resolve;});
 await page.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url()),method=request.method();
  if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
  if(!url.pathname.startsWith('/api/v1/'))return route.continue();
  let body;try{body=request.postDataJSON();}catch{errors.push('S32_INVALID_REQUEST_BODY');return route.abort();}
  const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
  if(url.hash||canonical(item)!==canonical(expectedS32Requests(state)[apiRequests.length-1])){errors.push('S32_UNEXPECTED_REQUEST');return route.abort();}
  const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
  if(url.pathname===S32_PATHS.session)return respond(200,{authenticated:true,actor});
  if(url.pathname===S32_PATHS.detail){
   // Native select text can retain fallback-font metrics after a font swap.
   // Load the existing shipped face before the synthetic profile mounts it;
   // no CSS/DOM rewrite, fixed delay or replacement font is introduced.
   controlFontReadiness=await page.evaluate(async()=>{
    const faces=await document.fonts.load('400 15px "Public Sans"','Asia/Kolkata Europe/London');
    if(faces.length!==1||faces.some(f=>f.status!=='loaded')||document.querySelector('#s32-zone'))throw Error('S32_CONTROL_FONT_NOT_READY');
    return {family:'Public Sans',weight:'400',loadedBeforeProfile:true,loadedFaces:faces.length};
   });
   if(state==='loading'){pendingResponses.push({method,url:url.href,cancelledBy:'context-disposal'});return;}
   if(state==='missing')return respond(404,{detail:{code:'NOT_FOUND',message:'tutor not found',resource:'tutor'}});
   if(state==='profile-error')return respond(500,{detail:'Internal Server Error'});
   return respond(200,S32_MENTOR);
  }
  if(state==='availability-error')return respond(500,{detail:'Internal Server Error'});
  if(['zone-changed','day-empty'].includes(state)&&apiRequests.length===4){releaseChange(()=>respond(200,s32AvailabilityResponse(state)));return;}
  return respond(200,s32AvailabilityResponse(['zone-changed','day-empty'].includes(state)?'complete':state));
 });
 const initial=['zone-changed','day-empty'].includes(state)?'complete':state;
 await page.goto(origin+s32Route(initial));
 const negative=['profile-error','missing','availability-error'].includes(state),loaded=!['loading','profile-error','missing'].includes(state);
 if(state==='loading')await page.getByRole('status',{name:'Loading mentor',exact:true}).waitFor();
 else if(negative){await page.getByRole('heading',{name:state==='missing'?'This mentor profile is not available.':state==='profile-error'?'The profile did not load.':'Times did not load.',exact:true}).waitFor();await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');}
 else{
  await page.getByRole('heading',{name:S32_MENTOR.display_name,exact:true}).waitFor();
  if(state==='no-slots')await page.getByRole('heading',{name:'No open times right now.',exact:true}).waitFor();else await page.getByRole('radiogroup').waitFor();
 }
 let selectionReset;
 if(['selected','zone-changed','day-empty'].includes(state)){
  const radio=page.getByRole('radio').first();await radio.press('Space');await page.waitForFunction(()=>document.querySelector('[role=radio][aria-checked=true]'));
  if(await page.getByRole('button',{name:'Continue to booking',exact:true}).isDisabled())throw Error('S32_SLOT_SELECTION_NOT_CONFIRMED');
  if(state!=='selected'){
   if(state==='zone-changed'){await page.getByLabel('Show times in',{exact:true}).focus();await page.getByLabel('Show times in',{exact:true}).selectOption('Europe/London');}
   else await page.getByLabel('On a single day',{exact:true}).fill('2027-08-18');
   const complete=await changePending;await page.getByRole('status',{name:'Loading times',exact:true}).waitFor();
   selectionReset={noSelectionWhilePending:await page.locator('[role=radio][aria-checked=true]').count()===0,continueDisabledWhilePending:await page.getByRole('button',{name:'Continue to booking',exact:true}).isDisabled()};
   if(!selectionReset.noSelectionWhilePending||!selectionReset.continueDisabledWhilePending)throw Error('S32_SELECTION_NOT_CLEARED');
   await complete();
   if(state==='day-empty')await page.getByRole('heading',{name:'No open times in this window.',exact:true}).waitFor();else await page.getByRole('radiogroup').waitFor();
  }
 }
 const viewportFraming=await frameS32Viewport(page);
 if(!verifyS32Requests(state,apiRequests)||page.url()!==origin+s32Route(state))throw Error(`S32_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
 const snapshot=await page.locator('.s32-detail').evaluate(host=>({
  heading:host.querySelector('h1')?.textContent,loading:!!host.querySelector('[aria-label="Loading mentor"]'),error:!!host.querySelector('[role=alert]'),status:host.querySelector('.s20-code')?.textContent??'',
  facts:[...host.querySelectorAll('.s32-facts dd')].map(e=>e.textContent),source:host.querySelector('.s32-source a')?.href??null,
  zone:host.querySelector('#s32-zone')?.value??null,day:host.querySelector('#s32-day')?.value??null,timesHeading:host.querySelector('#s32-times')?.textContent??null,
  radios:[...host.querySelectorAll('[role=radio]')].map(e=>({id:e.dataset.slot,checked:e.getAttribute('aria-checked')==='true',disabled:e.disabled,text:e.textContent})),
  continueDisabled:host.querySelector('.s32-continue')?.disabled??null,empty:host.querySelector('.s32-times .s20-empty h3')?.textContent??'',
  resolutionNotices:[...host.querySelectorAll('.s32-controls [role=status]')].map(e=>e.textContent),asidePrice:host.querySelector('.s32-aside-price b')?.textContent,
  focusRole:document.activeElement?.getAttribute('role'),focusId:document.activeElement?.id,focusSlot:document.activeElement?.getAttribute('data-slot'),scroll:[scrollX,scrollY]
 }));
 const wire=loaded&&!negative?s32AvailabilityResponse(state):null;
 const expectedFacts=loaded?['9 years','4.81 from 31 ratings','Arbitration (Advanced), Contract drafting (Intermediate)','₹899']:[];
 const serverConfirmationVerified=snapshot.heading===(loaded?S32_MENTOR.display_name:'Mentor.')&&snapshot.loading===(state==='loading')&&snapshot.error===negative
  &&snapshot.status===(negative?`HTTP ${state==='missing'?404:500}`:'')&&canonical(snapshot.facts)===canonical(expectedFacts)
  &&snapshot.source===(loaded?S32_MENTOR.source_url:null)&&snapshot.asidePrice===(loaded?'₹899':'Unavailable')
  &&canonical(snapshot.radios.map(s=>s.id))===canonical(wire?.slots.map(s=>s.slot_id)??[])&&snapshot.radios.every(s=>!s.disabled&&s.text.includes('₹899'))
  &&(!negative||snapshot.focusRole==='alert');
 const selectionBeforeBookingVerified=apiRequests.every(r=>r.method==='GET')&&snapshot.radios.filter(s=>s.checked).length===(state==='selected'?1:0)
  &&snapshot.continueDisabled===(loaded?state!=='selected':null)&&(!selectionReset||selectionReset.noSelectionWhilePending&&selectionReset.continueDisabledWhilePending)
  &&(state!=='selected'||snapshot.focusSlot===wire.slots[0].slot_id);
 const timezoneResolutionVerified=snapshot.zone===(loaded?zones(state):null)&&snapshot.day===(loaded?state==='day-empty'?'2027-08-18':'':null)
  &&snapshot.timesHeading===(loaded?`Times in ${zones(state)}`:null)
  &&snapshot.resolutionNotices.length===(state.startsWith('dst-')?1:0)
  &&(!state.startsWith('dst-')||snapshot.resolutionNotices[0].includes(wire.local_resolution.from_local.instant_utc)&&snapshot.resolutionNotices[0].includes(wire.local_resolution.from_local.resolved_local));
 if(!serverConfirmationVerified||!selectionBeforeBookingVerified||!timezoneResolutionVerified)throw Error(`S32_LIVE_PROOF_MISSING:${JSON.stringify({serverConfirmationVerified,selectionBeforeBookingVerified,timezoneResolutionVerified,snapshot})}`);
 return {evidenceKind:'live-route',evidenceDescription:'Actual S-32 route, synthetic backend-shaped profile/availability, real slot and timezone/day interactions, server-resolved DST instants; shipped control font loaded before synthetic profile response; document-top camera with real focus preserved. Not live-backend or independent QA.',
  syntheticServer:true,navigationFrozen:false,artificialDelay:false,apiRequests,expectedHttpErrors,pendingResponses,controlFontReadiness,viewportFraming,
  routeProof:{path:'/s-32',state,requestSequenceVerified:true,serverConfirmationVerified,selectionBeforeBookingVerified,timezoneResolutionVerified},detailProof:snapshot,...(selectionReset?{selectionReset}:{})};
}

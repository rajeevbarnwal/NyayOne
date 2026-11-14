// S-35 product route with synthetic API/device/transport inputs. Never backend,
// native permission, provider settlement, or independent QA evidence.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S35_MEASURED_STATES} from './nyay66-s35-coverage.mjs';
export const S35_IDS=Object.freeze(Object.fromEntries(['session','slot','tutor','order','nextSlot','review','refund'].map((k,i)=>[k,`00000000-0000-4000-8000-00000000350${i+1}`])));
export const S35_NOW='2026-09-28T10:00:00.000Z';
const base='/api/v1/tutoring',detail=`${base}/sessions/${S35_IDS.session}`,caps=`${base}/capabilities`,review=`${base}/reviews/${S35_IDS.review}`;
const roomStates=['room','room-connecting','room-reconnecting','room-failed','room-token-expired','room-leave-confirm','left','join-refused'];
const cancelStates=['cancel-confirm','cancel-failed','cancelled-full-refund','cancelled-no-auto-refund','refund-pending','refund-failed','cancel-stale','cancel-started','cancel-invalid'];
const scope=s=>{if(!S35_MEASURED_STATES.includes(s))throw Error('S35_FIXTURE_SCOPE');};
const request=s=>({method:s.method,path:s.path,search:s.search,body:s.body});
const step=(path,response,{method='GET',body=null,status=200,search='',hold=false}={})=>({path,response,method,body,status,search,hold});
const refusal=(path,code,status=409,body=null,method='POST')=>step(path,{detail:{code,message:code,retryable:false}},{status,body,method});
function wire(state){
 const past=state==='past'||state.startsWith('attendance')||['dispute','disputed'].includes(state)||state.startsWith('review');
 const attendance=state.startsWith('review')?'confirmed':({attendance:'recorded',dispute:'recorded',disputed:'disputed','attendance-pending':'pending','attendance-confirmed':'confirmed','attendance-refused':'recorded','attendance-resolved':'resolved'}[state]??null);
 return {id:S35_IDS.session,slot_id:S35_IDS.slot,tutor_id:S35_IDS.tutor,student_user_id:actor.sub,order_id:S35_IDS.order,status:past?'completed':'confirmed',version:1,
 start_utc:past?'2026-09-27T13:00:00+00:00':'2026-09-30T13:00:00+00:00',end_utc:past?'2026-09-27T13:45:00+00:00':'2026-09-30T13:45:00+00:00',iana_timezone:'Asia/Kolkata',
 start_local:past?'2026-09-27T18:30:00+05:30':'2026-09-30T18:30:00+05:30',end_local:past?'2026-09-27T19:15:00+05:30':'2026-09-30T19:15:00+05:30',attendance_state:attendance,attendance_version:attendance?1:null};
}
function capability(state){return {video_calls_enabled:state!=='video-disabled',video_transport:'deterministic',recording_enabled:false,join_credential_ttl_seconds:300,video_room_url:null,video_ice_transport_policy:'all'};}
function reviewWire(state){return {id:S35_IDS.review,session_id:S35_IDS.session,tutor_id:S35_IDS.tutor,rating:5,body:'The session explained the legal concepts clearly.',published:state!=='review-moderation',edit_deadline_at:state==='review-window-closed'?'2026-09-27T10:00:00Z':'2026-09-29T10:00:00Z',deleted:false,moderation_state:state==='review-moderation'?'pending':'approved',rating_aggregate:null};}
export function s35Plan(state){
 scope(state);let view='manage';const steps=[step('/api/v1/auth/student/session',{authenticated:true,actor})],session=wire(state);
 const list=pathState=>step(`${base}/sessions`,{items:pathState==='list-empty'?[]:[wire(pathState)],role:'student',limit:50,offset:0},{search:pathState==='past'?'?status=completed&status=disputed&limit=50&offset=0':'?status=confirmed&status=pending_provider&status=rescheduled&limit=50&offset=0'});
 if(['loading','list','past','list-empty','list-error','rate-limited'].includes(state)){
  view='list';steps.push(list(state==='past'?'list':state));
  if(state==='loading')steps[1].hold=true;
  if(['list-error','rate-limited'].includes(state)){steps[1].status=state==='list-error'?503:429;steps[1].response={detail:{code:state==='list-error'?'PROVIDER_UNAVAILABLE':'rate_limit_exceeded',message:'Synthetic service refusal',retryable:false,...(state==='rate-limited'?{retry_after_seconds:30,window_seconds:60,limit:10}:{})}};}
  if(state==='past')steps.push(list('past'));
 }else if(roomStates.includes(state)){
  view='room';steps.push(step(caps,capability(state)),step(detail,session));
  const join=step(`${detail}/join-credentials`,{session_id:S35_IDS.session,grant_id:'synthetic-grant',room_ref:'synthetic-room',participant_ref:'synthetic-student',permissions:['publish','subscribe'],join_token:'synthetic-test-only-token',issued_at:S35_NOW,expires_at:'2026-09-28T10:05:00Z',ttl_seconds:300,superseded:false,video_room_url:null,video_ice_transport_policy:'all'},{method:'POST',status:201});
  steps.push(state==='join-refused'?refusal(join.path,'SESSION_STATE_INVALID'):join);
  if(state==='room-connecting')steps.push({...join,hold:true});
 }else{
  steps.push(state==='detail-error'?refusal(detail,'NOT_FOUND',404,null,'GET'):step(detail,session));
  if(state.startsWith('reschedule')){
   view='reschedule';steps.push(step(`/api/v1/tutors/${S35_IDS.tutor}/availability`,{tutor_id:S35_IDS.tutor,iana_timezone:'Asia/Kolkata',window:{from_utc:null,to_utc:null},local_resolution:{},slots:state==='reschedule-unavailable'?[]:[{id:S35_IDS.nextSlot,slot_id:S35_IDS.nextSlot,tutor_id:S35_IDS.tutor,start_utc:'2026-10-01T13:00:00Z',end_utc:'2026-10-01T13:45:00Z',start_local:'2026-10-01T18:30:00+05:30',end_local:'2026-10-01T19:15:00+05:30',iana_timezone:'Asia/Kolkata',duration_minutes:45,status:'available',price_paise:150000,currency:'INR'}],limit:50,offset:0},{search:'?timezone=Asia%2FKolkata&limit=50&offset=0'}));
   const error={'reschedule-closed':['RESCHEDULE_WINDOW_CLOSED',409],'reschedule-conflict':['SESSION_STALE_VERSION',409],'reschedule-wrong-tutor':['VALIDATION_ERROR',422]}[state];
   if(error)steps.push(refusal(`${detail}/reschedule`,...error,{new_slot_id:S35_IDS.nextSlot,expected_version:1}));
  }else if(state.startsWith('attendance')||['dispute','disputed'].includes(state)){
   view='attendance';if(state==='attendance-refused')steps.push(refusal(`${detail}/attendance/confirm`,'ATTENDANCE_STALE_VERSION',409,{expected_version:1}));
  }else if(state.startsWith('review')){
   view='review';
   if(!['review','review-invalid'].includes(state)){
    const response=reviewWire(state);steps.push(state==='review-refused'?refusal(`${detail}/review`,'REVIEW_BLOCKED',409,{rating:5,body:response.body}):step(`${detail}/review`,response,{method:'POST',body:{rating:5,body:response.body},status:201}));
    if(['review-deleted','review-delete-failed'].includes(state))steps.push(state==='review-deleted'?step(review,{...response,deleted:true,published:false},{method:'DELETE'}):refusal(review,'PROVIDER_UNAVAILABLE',503,null,'DELETE'));
   }
  }else if(state.startsWith('prejoin')||state==='video-disabled'){
   view='prejoin';steps.push(step(caps,capability(state)));
  }else if(state!=='detail-error'){
   steps.push(step(caps,capability(state)));
   if(cancelStates.includes(state)&&state!=='cancel-confirm'){
    const body={expected_version:1},error={'cancel-failed':['PROVIDER_UNAVAILABLE',503],'cancel-stale':['SESSION_STALE_VERSION',409],'cancel-started':['SESSION_STATE_INVALID',409],'cancel-invalid':['VALIDATION_ERROR',422]}[state];
    if(error)steps.push(refusal(`${detail}/cancel`,...error,body));
    else {const no=state==='cancelled-no-auto-refund',cancelled={...session,status:'cancelled',version:2};steps.push(step(`${detail}/cancel`,{...cancelled,refund:{decision:no?'no_auto_refund':'full_refund',amount_paise:no?0:150000,reason:'server_assessment',hours_before_start:'51.00',policy_window_hours:24},refund_id:S35_IDS.refund,reminders_revoked:1},{method:'POST',body}),step(detail,cancelled));}
   }
  }
 }
 return {state,view,steps,realBackendTested:false,realMediaProviderTested:false,capabilityGap:['refund-pending','refund-failed'].includes(state)?'student-refund-settlement-status-unavailable':null,mediaEmulation:roomStates.includes(state)||state.startsWith('prejoin')?'synthetic-browser-devices-and-opt-in-deterministic-transport':null};
}
export function verifyS35Requests(state,requests){return S35_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(s35Plan(state).steps.map(request));}
export function classifyS35Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
 const plan=s35Plan(state),expected=plan.steps.filter(s=>s.status>=400).map(s=>({method:s.method,url:origin+s.path+s.search,status:s.status}));
 const reasons={404:'Not Found',409:'Conflict',422:'Unprocessable Entity',429:'Too Many Requests',503:'Service Unavailable'};
 const wanted=expected.map(e=>({url:e.url,text:`Failed to load resource: the server responded with a status of ${e.status} (${reasons[e.status]})`}));
 const errors=[];if(canonical(expectedHttpErrors)!==canonical(expected)||canonical(httpResponses)!==canonical(expected))errors.push('S35_EXPECTED_HTTP_ERROR_UNOBSERVED');
 if(canonical(consoleErrors)!==canonical(wanted))errors.push('CONSOLE_ERROR');if(failedRequests.length)errors.push('NETWORK_ERROR');
 return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:errors.length?0:expected.length,errors};
}

// Browser API emulation only: no component state, DOM/CSS, query cache or auth
// overrides. The production app's existing opt-in deterministic transport is
// used explicitly; it is not evidence of provider admission or real media.
async function installS35Devices(page,state){
 await page.addInitScript(({state})=>{
  window.__nyayoneVideoTransport='deterministic';
  window.__s35DeviceCalls=[];
  const failure={'prejoin-denied':'NotAllowedError','prejoin-no-device':'NotFoundError','prejoin-busy':'NotReadableError','prejoin-failed':'UnknownError'}[state];
  const devices=[{kind:'videoinput',deviceId:'synthetic-camera',groupId:'synthetic',label:''},{kind:'audioinput',deviceId:'synthetic-mic',groupId:'synthetic',label:''}];
  const media={enumerateDevices:async()=>devices,getUserMedia:async constraints=>{
   window.__s35DeviceCalls.push({audio:!!constraints.audio,video:!!constraints.video});
   if(failure||state==='prejoin-audio-only'&&constraints.video)throw new DOMException('Synthetic device refusal',failure||'NotAllowedError');
   const result=new MediaStream();
   if(constraints.video){const canvas=document.createElement('canvas');canvas.width=320;canvas.height=240;const c=canvas.getContext('2d');c.fillStyle='#26334a';c.fillRect(0,0,320,240);for(const t of canvas.captureStream(0).getTracks())result.addTrack(t);}
   if(constraints.audio){const a=new AudioContext(),d=a.createMediaStreamDestination();for(const t of d.stream.getTracks())result.addTrack(t);}
   return result;
  }};
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:state==='prejoin-unsupported'?undefined:media});
  if(state==='prejoin-insecure')Object.defineProperty(window,'isSecureContext',{configurable:true,value:false});
 },{state});
}
export async function frameS35Viewport(page,state){
 scope(state);
 await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
 const framing=await page.evaluate(()=>{
  if(location.pathname!=='/s-35'||!document.querySelector('.s35-lifecycle'))throw Error('S35_FRAME_SCOPE');
  const active=document.activeElement,before=[scrollX,scrollY];scrollTo({left:0,top:0,behavior:'instant'});
  if(active!==document.activeElement)throw Error('S35_FRAME_FOCUS_CHANGED');
  return {testOnly:true,origin:'document-top-after-live-interaction',before,after:[scrollX,scrollY],focusPreserved:true,domModified:false,pixelPostprocessing:false};
 });
 return framing;
}
async function visible(page,locator){
 let done=false,failure;const waiting=locator.waitFor().catch(e=>{failure=e;}).finally(()=>{done=true;});
 while(!done){await page.clock.runFor(0);await new Promise(r=>setTimeout(r,10));}
 await waiting;if(failure)throw failure;
}
export async function mockS35Application(page,state,origin,errors){
 const plan=s35Plan(state),apiRequests=[],expectedHttpErrors=[],pendingResponses=[];
 await page.clock.install({time:new Date(S35_NOW)});await page.clock.pauseAt(new Date(S35_NOW));
 if(plan.mediaEmulation)await installS35Devices(page,state);
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
  if(!url.pathname.startsWith('/api/v1/'))return route.continue();
  const item={method:req.method(),path:url.pathname,search:url.search,body:req.postDataJSON()};apiRequests.push(item);
  const next=plan.steps[apiRequests.length-1];
  if(!next||canonical(item)!==canonical(request(next))){errors.push(`S35_UNEXPECTED_REQUEST:${item.method}:${item.path}:${item.search}`);return route.abort();}
  if(next.hold){pendingResponses.push({...item,cancelledBy:'context-disposal'});return;}
  if(next.status>=400)expectedHttpErrors.push({method:item.method,url:url.href,status:next.status});
  await route.fulfill({status:next.status,contentType:'application/json',headers:{'cache-control':'no-store',...(next.status===429?{'retry-after':'30'}:{})},body:JSON.stringify(next.response)});
 });
 const url=plan.view==='list'?'/s-35':`/s-35?session=${S35_IDS.session}&view=${plan.view}`;
 await page.goto(origin+url);
 const click=async(name)=>{await visible(page,page.getByRole('button',{name,exact:true}));await page.getByRole('button',{name,exact:true}).click();await page.clock.runFor(32);};
 const refused=async()=>{const code=plan.steps.find(s=>s.status>=400)?.response.detail.code;await visible(page,page.locator('.tt-banner__code').filter({hasText:code}).first());};
 const text=async value=>{await visible(page,page.getByText(value,{exact:true}).first());};
 // Application responses are awaited through their resulting UI, not arbitrary
 // network sleeps. Only the two deliberately pending states retain a response.
 if(plan.view==='list'){
  if(state==='loading')await visible(page,page.getByText('Loading your sessions',{exact:true}));
  else if(['list-error','rate-limited'].includes(state))await refused();
  else if(state==='list-empty')await text('Nothing here yet');
  else {await visible(page,page.locator('.tt-tut').first());if(state==='past'){await click('Finished');await text('completed');}}
 }else if(state==='detail-error')await refused();
 else if(plan.view==='manage'){
  await visible(page,page.getByRole('heading',{name:'Session details.',exact:true}));await visible(page,page.getByRole('button',{name:'Enter the room',exact:true}));
  if(cancelStates.includes(state)){
   await click('Cancel this session');await visible(page,page.getByRole('dialog'));
   if(state!=='cancel-confirm'){
    await click('Yes, cancel and assess the refund');
    if(plan.steps.some(s=>s.status>=400))await refused();
    else await text(state==='cancelled-no-auto-refund'?'Cancelled: server refund assessment':'Refund assessed; settlement not confirmed');
   }
  }
 }else if(plan.view==='reschedule'){
  if(state==='reschedule-unavailable')await text('No other open times');
  else {await visible(page,page.getByRole('radio').first());await page.getByRole('radio').first().click();await page.clock.runFor(32);if(state!=='reschedule'){await click('Confirm the new time');await refused();}}
 }else if(plan.view==='attendance'){
  await visible(page,page.getByRole('heading',{name:'Session details.',exact:true}));
  if(state==='dispute'){await click('Dispute this');await visible(page,page.getByRole('dialog'));}
  if(state==='attendance-refused'){await click('Confirm attendance');await refused();}
 }else if(plan.view==='review'){
  await visible(page,page.getByRole('heading',{name:'Write a review',exact:true}));
  if(state!=='review'){
   await page.getByRole('radio',{name:'5 stars',exact:true}).check();await page.locator('#s35-review-body').fill(state==='review-invalid'?'short':reviewWire(state).body);
   if(state!=='review-invalid'){
    await click('Submit review');
    if(state==='review-refused')await visible(page,page.getByRole('alert').first());
    else {
     await visible(page,page.getByRole('region',{name:'Server review record',exact:true}));
     if(state==='review-edit')await click('Edit review');
     if(state.startsWith('review-delete')){await click('Delete review');await text('Delete this review?');if(state!=='review-delete-confirm'){await click('Confirm delete review');if(state==='review-deleted')await text('Review deleted');else await visible(page,page.getByRole('alert').first());}}
    }
   }
  }
 }else if(plan.view==='prejoin'){
  if(state==='video-disabled')await text('Video calls are temporarily unavailable');
  else {
   await visible(page,page.getByRole('heading',{name:'Room entry check',exact:true}));
   if(state!=='prejoin'){
    await click('Test camera and microphone');
    if(state==='prejoin-audio-only'){await click('Enter with audio only');await text('Your devices are ready');}
    else if(state==='prejoin-ready')await text('Your devices are ready');
    else await visible(page,page.getByText(/PERMISSION_DENIED|NO_DEVICE|DEVICE_BUSY|INSECURE|UNSUPPORTED|UNKNOWN/).first());
   }
  }
 }else if(plan.view==='room'){
  if(state==='join-refused')await visible(page,page.locator('[data-tt-transport="failed"]'));
  else {
   await visible(page,page.locator('[data-tt-transport="connected"]'));
   if(state==='room-reconnecting')await page.evaluate(()=>window.__nyayoneVideoRoom.dropTransport());
   if(['room-failed','room-token-expired','room-connecting'].includes(state))await page.evaluate(code=>window.__nyayoneVideoRoom.failTerminally(code),state==='room-token-expired'?'CREDENTIAL_EXPIRED':'PROVIDER_UNAVAILABLE');
   if(state==='room-connecting'){await click('Session, connection and privacy details');await click('Ask for entry again');await page.getByRole('dialog',{name:'Session details',exact:true}).getByRole('button',{name:'Close session details',exact:true}).click();}
   if(['room-leave-confirm','left'].includes(state)){await click('Leave the session');await visible(page,page.getByRole('dialog'));if(state==='left'){await page.getByRole('dialog').getByRole('button',{name:'Leave the session',exact:true}).click();await visible(page,page.getByRole('heading',{name:'Session details.',exact:true}));}}
   const target={'room-reconnecting':'reconnecting','room-failed':'failed','room-token-expired':'failed','room-connecting':'connecting'}[state];if(target)await visible(page,page.locator(`[data-tt-transport="${target}"]`));
  }
 }
 await page.clock.runFor(64);
 // The ordered plan must be complete, including post-mutation reads. Poll in
 // the node realm because the deliberately controlled product clock is paused.
 for(let i=0;i<100&&apiRequests.length<plan.steps.length;i++)await new Promise(r=>setTimeout(r,20));
 if(!verifyS35Requests(state,apiRequests))throw Error(`S35_REQUEST_SEQUENCE_MISMATCH:${canonical(apiRequests)}`);
 const viewportFraming=await frameS35Viewport(page,state);
 const sessionProof=await page.evaluate(()=>({path:location.pathname,view:new URLSearchParams(location.search).get('view')||'list',id:new URLSearchParams(location.search).get('session'),text:document.querySelector('.s35-lifecycle')?.textContent??'',focusTag:document.activeElement?.tagName,focusRole:document.activeElement?.getAttribute('role'),transport:document.querySelector('[data-tt-transport]')?.getAttribute('data-tt-transport')??null,selectedSlots:[...document.querySelectorAll('[role=radio][aria-checked=true]')].map(e=>e.textContent),reviewRecord:document.querySelector('[aria-label="Server review record"]')?.textContent??null,reviewDisabled:document.querySelector('.s35-review button')?.getAttribute('aria-disabled')??null,dialog:document.querySelector('.tt-modal h2')?.textContent??null,deviceCalls:window.__s35DeviceCalls??[],scroll:[scrollX,scrollY]}));
 const sessionIdentityVerified=sessionProof.path==='/s-35'&&(plan.view==='list'?sessionProof.id===null:sessionProof.id===S35_IDS.session);
 const terminalStateVerified=verifyS35Terminal(state,sessionProof);
 const responseScenarioVerified=verifyS35Requests(state,apiRequests)&&terminalStateVerified&&!errors.length;
 const gap=!!plan.capabilityGap,evidenceKind=gap?'live-capability-gap':state==='left'?'live-route-destination':'live-route';
 if(!sessionIdentityVerified||!responseScenarioVerified||gap&&!sessionProof.text.includes('settlement not confirmed'))throw Error(`S35_LIVE_PROOF_MISSING:${state}:${JSON.stringify(sessionProof)}`);
 return {evidenceKind,evidenceDescription:'Actual S-35 routes/actions with synthetic backend-shaped responses and genuine HTTP error statuses. Media rows use synthetic browser APIs and the existing opt-in deterministic transport; not native device, real backend/provider, settlement or independent QA proof. Clock frozen for repeatable media/elapsed framing; no DOM/CSS or pixel editing. Refund pending/failed capture only unavailable settlement authority; left captures the actual attendance destination.',
 syntheticServer:true,navigationFrozen:false,artificialDelay:false,realBackendTested:false,realMediaProviderTested:false,capabilityGap:plan.capabilityGap,settlementStateObserved:false,mediaEmulation:plan.mediaEmulation,clock:{testOnly:true,start:S35_NOW,pausedAtImage:true},mediaPhase:state==='room-connecting'?'retry-awaiting-server-admission-not-provider-connection':plan.mediaEmulation?'simulated-only':null,apiRequests,expectedHttpErrors,pendingResponses,viewportFraming,sessionProof,
 routeProof:{path:'/s-35',state,view:sessionProof.view,requestSequenceVerified:true,terminalStateVerified,responseScenarioVerified,sessionIdentityVerified,capabilityLimitsDisclosed:true}};
}

// Assert rendered outcome against the declared API/browser scenario. These are
// product observations, never reference-state injection or a backend QA verdict.
export function verifyS35Terminal(state,s){
 scope(state);const p=s35Plan(state),t=s.text??'',has=x=>t.includes(x);
 if(s.path!=='/s-35'||s.view!==(state==='left'?'attendance':p.view))return false;
 const e=p.steps.find(x=>x.status>=400);if(e&&!has(e.response.detail.code))return false;
 if(e)return true;
 const required={loading:'Loading your sessions',list:'confirmed',past:'completed','list-empty':'Nothing here yet',detail:'Session details.',reschedule:'Choose a new time','reschedule-unavailable':'No other open times',
 'cancel-confirm':'Cancel this session?','cancelled-full-refund':'Refund assessed; settlement not confirmed','cancelled-no-auto-refund':'Cancelled: server refund assessment','refund-pending':'settlement not confirmed','refund-failed':'settlement not confirmed',
 attendance:'An administrator recorded this session as attended',dispute:'Dispute this attendance record?',disputed:'Your dispute is open','attendance-pending':'Attendance is not decided yet','attendance-confirmed':'You confirmed attendance','attendance-resolved':'The dispute was resolved',
 review:'Write a review','review-invalid':'5 / 1,000 characters','review-moderation':'Not published · pending','review-edit':'Save changes','review-window-closed':'Edit deadline:','review-delete-confirm':'Delete this review?','review-deleted':'Review deleted',
 prejoin:'Test your camera and microphone','prejoin-ready':'Your devices are ready','prejoin-audio-only':'Your devices are ready','prejoin-denied':'PERMISSION_DENIED','prejoin-no-device':'NO_DEVICE','prejoin-busy':'DEVICE_BUSY','prejoin-insecure':'INSECURE','prejoin-unsupported':'UNSUPPORTED','prejoin-failed':'UNKNOWN','video-disabled':'Video calls are temporarily unavailable',
 room:'In the room','room-connecting':'Connecting','room-reconnecting':'Reconnecting','room-failed':'PROVIDER_UNAVAILABLE','room-token-expired':'CREDENTIAL_EXPIRED','room-leave-confirm':'Leave this session?',left:'Attendance is not decided yet'}[state];
 if(!required||!has(required))return false;
 if(state==='review-invalid'&&s.reviewDisabled!=='true')return false;
 if(state==='reschedule'&&s.selectedSlots?.length!==1)return false;
 const transport={room:'connected','room-connecting':'connecting','room-reconnecting':'reconnecting','room-failed':'failed','room-token-expired':'failed','room-leave-confirm':'connected'}[state];
 return !transport||s.transport===transport;
}

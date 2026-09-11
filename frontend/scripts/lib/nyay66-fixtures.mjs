// Synthetic read-only projections, not application authority or live account data.
export const actor={sub:'00000000-0000-4000-8000-000000002701',roles:['student'],student_profile_id:'00000000-0000-4000-8000-000000002702',student_verification:'draft',is_minor:false,consent_state:['privacy_notice','terms']};
export function projection(id){
  const complete=id==='S-12',personal=id!=='S-10',academic=personal&&id!=='S-10-academic';
  return {profile_version:1,completion_version:'v1',completion_percent:complete?100:academic?67:personal?34:0,
    completed_sections:complete?['personal','academic','interests']:academic?['personal','academic']:personal?['personal']:[],
    missing_requirements:[...(!personal?['personal.preferred_language','personal.city']:[]),...(!academic?['academic.college','academic.year_of_study','academic.enrolment_number']:[]),...(!complete?['interests.interests','interests.goals']:[])],
    next_incomplete_section:complete?null:academic?'interests':personal?'academic':'personal',is_complete:complete,institutional_email_status:'not_provided',
    guardian:{required:id==='S-16',status:id==='S-16'?'required_pending':'not_required'},access_mode:id==='S-16'?'limited':'full',disabled_capabilities:id==='S-16'?['community','sharing']:[],
    profile_prompt:{should_show:id==='S-07-popup',dismissed_for_session:id!=='S-07-popup'},
    profile:{personal:{first_name:'Synthetic',middle_name:null,last_name:'Student',date_of_birth:'2000-01-01',preferred_language:personal?'en':null,city:personal?'Synthetic City':null,pronouns:null},academic:{college:academic?'Synthetic College':null,year_of_study:academic?'3':null,enrolment_number:academic?'KA/1234/2023':null,institutional_email:null,bar_enrolment_number:null},interests:{interests:complete?['Constitutional']:[],goals:complete?['Undecided']:[]}}};
}
export async function mockApplication(page,id,origin,errors){
  const authenticated=['S-07','S-07-popup','S-10','S-10-academic','S-11','S-12','S-13','S-14','S-15','S-16','S-17'].includes(id);
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==origin&&!url.pathname.startsWith('/api/v1/')){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    const path=url.pathname;
    const headers={'access-control-allow-origin':origin,'access-control-allow-credentials':'true','access-control-allow-methods':'GET,OPTIONS','access-control-allow-headers':'content-type,idempotency-key,x-csrf-token'};
    if(route.request().method()==='OPTIONS')return route.fulfill({status:204,headers});
    const json=body=>route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify(body)});
    if(path.endsWith('/auth/student/session'))return json({authenticated,actor:authenticated?{...actor,is_minor:id==='S-16'}:null});
    if(path.endsWith('/login/channels'))return json({channels:[{channel:'mobile',enabled:true},{channel:'email',enabled:true}]});
    if(path.endsWith('/otp/state'))return json({status:'pending',purpose:id==='S-09'?'signup':'login',destination_masked:'••••••0340',attempts_left:3,expires_in_seconds:272,resend_in_seconds:0,locked_for_seconds:0,resend_allowed:true});
    if(path==='/api/v1/student/profile')return json(projection(id));
    if(path.endsWith('/email-identities'))return json({identities:[],login_channel_enabled:true,max_identities:5});
    if(path==='/api/v1/calendar/view-preferences')return json({view_mode:'week',source_types:[],from_date:null,to_date:null,timezone:'Asia/Kolkata',version:1,updated_at:'2026-09-09T12:00:00Z'});
    if(path==='/api/v1/calendar/events')return json({items:[],total:0,failed_sources:[]});
    errors.push('UNMATCHED_API');return route.fulfill({status:404,headers,body:'{}'});
  });
  const target=`/${id.slice(0,4).toLowerCase()}${id==='S-10-academic'?'?section=academic':''}`;
  const calendar=['S-07','S-14'].includes(id)?page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/calendar/events'&&r.status()===200):null;
  const session=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/auth/student/session'));
  if(['S-05','S-09'].includes(id)){
    await page.goto(origin+'/s-03');await (await session).finished();await page.locator('[data-screen="S-03"]').waitFor();
    const otp=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/otp/state'));
    await page.evaluate(target=>{history.pushState({},'',target);dispatchEvent(new PopStateEvent('popstate'));},target);await (await otp).finished();
  }else{await page.goto(origin+target);await (await session).finished();}
  if(id==='S-07')await page.waitForURL('**/s-14');
  if(calendar)await (await calendar).finished();
  await page.locator(`[data-screen="${id==='S-07'?'S-14':id.slice(0,4)}"]`).waitFor();
  if(id==='S-07-popup')await page.getByRole('dialog').waitFor();
  if(authenticated)await page.waitForFunction(()=>!document.body.innerText.includes('Loading your profile'));
}

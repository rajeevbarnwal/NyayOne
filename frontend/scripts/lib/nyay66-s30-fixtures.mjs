// S-30-only synthetic backend-shaped fixtures. Actual private route, no DOM/CSS
// substitution, no production navigation freeze and no fabricated success.
import {actor} from './nyay66-fixtures.mjs';
import {canonical} from './nyay66-enforcement.mjs';
import {S30_MEASURED_STATES} from './nyay66-s30-coverage.mjs';
const session='/api/v1/auth/student/session';
export const S30_IDS=Object.freeze([1,2,3].map(n=>`00000000-0000-4000-8000-00000000090${n}`));
export const S30_PATHS=Object.freeze({saved:'/api/v1/student/law-schools/saved',followed:'/api/v1/student/law-schools/followed',remove:`/api/v1/student/law-schools/${S30_IDS[0]}/saved`});
export const S30_SCHOOLS=Object.freeze([
  {id:S30_IDS[0],slug:'synthetic-kaveri',name:'Kaveri National Law University',state:'Karnataka',institution_type:'national_law_university',accreditation:'BCI approved',entrance_exam:'CLAT',fees_min:285000,fees_max:310000,nirf_rank:null},
  {id:S30_IDS[1],slug:'synthetic-sabarmati',name:'Sabarmati Law College',state:'Gujarat',institution_type:'private',accreditation:'BCI approved',entrance_exam:'Institution test',fees_min:410000,fees_max:455000,nirf_rank:null},
  {id:S30_IDS[2],slug:'synthetic-vindhya',name:'Vindhya School of Law',state:'Madhya Pradesh',institution_type:'government',accreditation:null,entrance_exam:null,fees_min:null,fees_max:null,nirf_rank:null},
].map(Object.freeze));
function scope(state){if(!S30_MEASURED_STATES.includes(state))throw Error('S30_FIXTURE_SCOPE');}
export function s30Response(state,kind){
  scope(state);if(!['saved','followed'].includes(kind))throw Error('S30_LIST_KIND');
  const schools=kind==='saved'?S30_SCHOOLS.slice(0,2):[S30_SCHOOLS[0],S30_SCHOOLS[2]];
  const empty=(kind==='saved'&&state==='saved-empty')||(kind==='followed'&&state==='followed-empty');
  return {items:empty?[]:schools.map((school,index)=>({...school,...(kind==='followed'?{notify_opt_in:index===0}:{})}))};
}
export function expectedS30Requests(state){
  scope(state);return [session,S30_PATHS.saved,S30_PATHS.followed].map(path=>({method:'GET',path,search:'',body:null}))
    .concat(state.startsWith('item-')?[{method:'DELETE',path:S30_PATHS.remove,search:'',body:null}]:[]);
}
export function verifyS30Requests(state,requests){return S30_MEASURED_STATES.includes(state)&&canonical(requests)===canonical(expectedS30Requests(state));}
export function classifyS30Errors(state,origin,consoleErrors,httpResponses,failedRequests,expectedHttpErrors){
  const expected=state==='error'?{method:'GET',url:origin+S30_PATHS.saved,status:500}:state==='item-error'?{method:'DELETE',url:origin+S30_PATHS.remove,status:500}:null;
  const matches=x=>expected&&x.method===expected.method&&x.url===expected.url&&x.status===expected.status;
  const httpOK=expected&&expectedHttpErrors.length===1&&matches(expectedHttpErrors[0])&&httpResponses.length===1&&matches(httpResponses[0])
    &&consoleErrors.length===1&&consoleErrors[0].url===expected.url&&consoleErrors[0].text==='Failed to load resource: the server responded with a status of 500 (Internal Server Error)'&&failedRequests.length===0;
  const errors=[];
  if(!S30_MEASURED_STATES.includes(state))errors.push('S30_FIXTURE_SCOPE');
  if(expected&&!httpOK)errors.push('S30_EXPECTED_HTTP_ERROR_UNOBSERVED');
  if(!httpOK&&consoleErrors.length)errors.push('CONSOLE_ERROR');
  if(!httpOK&&httpResponses.length)errors.push('HTTP_RESPONSE_ERROR');
  if(failedRequests.length)errors.push('NETWORK_ERROR');
  if(!expected&&expectedHttpErrors.length)errors.push('UNEXPECTED_HTTP_DECLARATION');
  return {consoleErrors,httpResponses,failedRequests,expectedHttpErrors,expectedHttpErrorCount:httpOK?1:0,errors};
}
export async function mockS30Application(page,state,origin,errors){
  scope(state);const apiRequests=[],expectedHttpErrors=[],pendingResponses=[];
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    if(url.origin!==origin){errors.push('OUTBOUND_REQUEST');return route.abort();}
    if(!url.pathname.startsWith('/api/v1/'))return route.continue();
    let body;try{body=request.postDataJSON();}catch{errors.push('S30_INVALID_REQUEST_BODY');return route.abort();}
    const item={method,path:url.pathname,search:url.search,body};apiRequests.push(item);
    if(url.hash||canonical(item)!==canonical(expectedS30Requests(state)[apiRequests.length-1])){errors.push('S30_UNEXPECTED_REQUEST');return route.abort();}
    const respond=(status,value)=>{if(status>=400)expectedHttpErrors.push({method,url:url.href,status});return route.fulfill({status,contentType:'application/json',headers:{'cache-control':'no-store'},body:JSON.stringify(value)});};
    if(url.pathname===session)return respond(200,{authenticated:true,actor});
    if(state==='loading'||(state==='item-pending'&&method==='DELETE')){
      pendingResponses.push({method,url:url.href,cancelledBy:'context-disposal'});return; // Explicit pending response; never pretend it succeeded.
    }
    if((state==='error'&&url.pathname===S30_PATHS.saved)||state==='item-error'&&method==='DELETE')return respond(500,{detail:'Internal Server Error'});
    if(method==='GET'&&url.pathname===S30_PATHS.saved)return respond(200,s30Response(state,'saved'));
    if(method==='GET'&&url.pathname===S30_PATHS.followed)return respond(200,s30Response(state,'followed'));
    errors.push('UNMATCHED_API');return route.abort();
  });
  const sessionRead=page.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname===session);
  await page.goto(origin+'/s-30');await sessionRead;
  if(state==='loading'){
    await page.getByRole('status',{name:'Loading schools',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('.s30-schools'));
  }else{
    await page.getByRole('tab',{name:`Following (${s30Response(state,'followed').items.length})`,exact:true}).waitFor();
    if(state==='error'){
      await page.getByRole('heading',{name:'This list did not load.',exact:true}).waitFor();
      await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
    }else{
      await page.getByRole('tab',{name:`Saved (${s30Response(state,'saved').items.length})`,exact:true}).waitFor();
      if(['following-tab','followed-empty'].includes(state))await page.getByRole('tab',{name:`Following (${s30Response(state,'followed').items.length})`,exact:true}).click();
      if(state.startsWith('item-')){
        await page.getByRole('button',{name:`Remove ${S30_SCHOOLS[0].name} from saved`,exact:true}).press('Enter');
        if(state==='item-error'){
          await page.getByRole('alert').waitFor();await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
        }else await page.waitForFunction(()=>document.querySelector('[data-s30-remove][aria-busy="true"]'));
      }
      if(state==='saved-empty')await page.getByRole('heading',{name:'No saved schools.',exact:true}).waitFor();
      if(state==='followed-empty')await page.getByRole('heading',{name:'You are not following any school.',exact:true}).waitFor();
    }
  }
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  if(!verifyS30Requests(state,apiRequests)||page.url()!==origin+'/s-30')throw Error(`S30_REQUEST_SEQUENCE_MISMATCH:${JSON.stringify(apiRequests)}`);
  const snapshot=await page.locator('.s30-schools').evaluate(host=>({
    heading:host.querySelector('h1')?.textContent,loading:!!host.querySelector('[aria-label="Loading schools"]'),
    tabs:[...host.querySelectorAll('[role="tab"]')].map(t=>({text:t.textContent,selected:t.getAttribute('aria-selected')})),
    cards:[...host.querySelectorAll('article .s20-title')].map(a=>({name:a.querySelector('span')?.textContent,path:a.getAttribute('href')})),
    removals:[...host.querySelectorAll('[data-s30-remove]')].map(b=>({id:b.dataset.s30Remove,name:b.getAttribute('aria-label'),pressed:b.getAttribute('aria-pressed'),disabled:b.getAttribute('aria-disabled'),busy:b.getAttribute('aria-busy')})),
    notifications:[...host.querySelectorAll('.s20-meta p')].map(p=>p.textContent).filter(t=>t.startsWith('Update notifications:')),
    alert:host.querySelector('[role="alert"]')?.textContent??'',http:host.querySelector('.s20-code')?.textContent??'',
    empty:host.querySelector('.s30-panel .s20-empty h2')?.textContent??'',announcement:host.querySelector('.s20-announcement')?.textContent??'',
    compare:[...host.querySelectorAll('button')].filter(b=>b.textContent==='Compare saved schools').map(b=>b.disabled),
    focusRole:document.activeElement?.getAttribute('role'),scroll:[scrollX,scrollY],
  }));
  const kind=['following-tab','followed-empty'].includes(state)?'followed':'saved';
  const shown=['loading','error'].includes(state)?[]:s30Response(state,kind).items;
  const membershipVerified=canonical(snapshot.cards)===canonical(shown.map(s=>({name:s.name,path:`/s-28?${new URLSearchParams({id:s.id,from:'s30'})}`})))
    &&canonical(snapshot.removals)===canonical(shown.map((s,i)=>({id:s.id,name:kind==='saved'?`Remove ${s.name} from saved`:`Unfollow ${s.name}`,pressed:state==='item-error'?null:'true',disabled:state.startsWith('item-')?'true':'false',busy:state==='item-pending'&&i===0?'true':null})))
    &&canonical(snapshot.notifications)===canonical(kind==='followed'?shown.map(s=>`Update notifications: ${s.notify_opt_in?'on':'off'}`):[]);
  const savedCount=['loading','error','item-error'].includes(state)?'…':s30Response(state,'saved').items.length;
  const followedCount=state==='loading'?'…':s30Response(state,'followed').items.length;
  const serverConfirmationVerified=snapshot.heading==='Saved and followed schools.'&&snapshot.loading===(state==='loading')
    &&canonical(snapshot.tabs)===canonical([{text:`Saved (${savedCount})`,selected:kind==='saved'?'true':'false'},{text:`Following (${followedCount})`,selected:kind==='followed'?'true':'false'}])
    &&snapshot.http===(state==='error'?'HTTP 500':'')&&snapshot.announcement===''
    &&(state==='item-error'?snapshot.alert.includes('last known list')&&snapshot.alert.includes('Reload saved list'):state==='error'?snapshot.alert.includes('The other list may still work.'):snapshot.alert==='')
    &&snapshot.empty===(state==='error'?'This list did not load.':state==='saved-empty'?'No saved schools.':state==='followed-empty'?'You are not following any school.':'')
    &&snapshot.compare.length===2&&snapshot.compare.every(disabled=>disabled===['loading','saved-empty','item-pending','item-error','error'].includes(state))
    &&(!['error','item-error'].includes(state)||snapshot.focusRole==='alert')&&canonical(snapshot.scroll)===canonical([0,0]);
  if(!serverConfirmationVerified||!membershipVerified)throw Error(`S30_MEMBERSHIP_PROOF_MISSING:${JSON.stringify(snapshot)}`);
  return {evidenceKind:'live-route',evidenceDescription:'Live S-30 route with synthetic API responses; independent saved/followed membership, notification consent, actual pending/failed removal and error focus; not live-backend or independent QA evidence',
    syntheticServer:true,artificialDelay:false,navigationFrozen:false,apiRequests,expectedHttpErrors,pendingResponses,
    routeProof:{path:'/s-30',state,requestSequenceVerified:true,serverConfirmationVerified,membershipVerified},membershipProof:snapshot};
}

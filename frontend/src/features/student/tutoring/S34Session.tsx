import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Link,useNavigate,useSearchParams} from 'react-router-dom';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {useAuth,useStudentSession} from '../../../app/authContext';
import {NyayOneRevLLockup} from '../auth/NyayOneRevLIcon';
import {Icon} from '../internships/S20BrowseView';
import {TutoringApiError} from '../lib/tutoringApi';
import {canonicalSessionId,readSessionDetail,type SessionDetail} from './s34Api';
import type {MentorDetail} from './s32Api';
import './S34Session.css';
class OfflineRead extends Error {}
function Calendar({size=18}:{size?:number}){return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5.5" width="16" height="15" rx="2.5" fill="currentColor" opacity=".14"/><rect x="4" y="5.5" width="16" height="15" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M4 10h16M8 3.5v4M16 3.5v4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></svg>;}
function StatusIcon({kind}:{kind:'check'|'clock'|'info'}){return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/>{kind==='check'?<path d="m8 12 2.8 2.8L16 9.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>:kind==='clock'?<path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>:<path d="M12 10.5v6M12 7.5v.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>}</svg>;}
const labels:Record<SessionDetail['status'],[string,string,string,'check'|'clock'|'info']>={
 confirmed:['Confirmed','Confirmed.','The server reports this session as confirmed.','check'],
 pending_provider:['Confirming with provider','Not confirmed yet.','The server is waiting for the payment provider. This session is not booked until it is confirmed.','clock'],
 cancelled:['Cancelled','This session was cancelled.','','info'],
 rescheduled:['Rescheduled','This session was rescheduled.','The times below are the current server record.','info'],
 completed:['Completed','This session is completed.','','info'],
 disputed:['Disputed','This session is disputed.','Review attendance in My sessions.','info'],
};
export function S34Session(){const auth=useAuth(),[sp]=useSearchParams();return <Session key={`${auth.userId}:${auth.roles.join(',')}:${canonicalSessionId(sp.get('session')??'')}`}/>;}
function Session(){
 const auth=useAuth(),identity=useStudentSession(),nav=useNavigate(),cache=useQueryClient(),[sp]=useSearchParams();
 const id=canonicalSessionId(sp.get('session')??''),authorized=auth.isAuthenticated&&identity.phase==='authenticated'&&auth.roles.includes('student');
 const [retrying,setRetrying]=useState(false),[now,setNow]=useState(Date.now());
 const root=useRef<HTMLDivElement>(null),first=useRef(true),lock=useRef(false),mounted=useRef(true),action=useRef<HTMLElement|null>(null),lastError=useRef<unknown>(null);
 const query=useQuery({queryKey:['s34-session',auth.userId,id],queryFn:({signal})=>{if(!navigator.onLine)throw new OfflineRead();return readSessionDetail(id,auth.userId!,signal);},enabled:authorized&&!!id,retry:false,staleTime:0,networkMode:'always',refetchOnWindowFocus:false,refetchOnReconnect:false});
 if(query.error)lastError.current=query.error;else if(query.isSuccess&&!query.isFetching)lastError.current=null;
 const error=query.error??(retrying?lastError.current:null),busy=query.isFetching||retrying;
 const data=authorized&&!error&&!busy?query.data:undefined;
 // Optional name comes only from an already loaded, same-actor S-32 cache entry.
 // No extra endpoint, fixture name, payment or policy lookup is invented.
 const mentor=data?cache.getQueryData<MentorDetail>(['s32-profile',auth.userId,data.tutor_id]):undefined;
 const name=mentor?.id===data?.tutor_id&&typeof mentor?.display_name==='string'?mentor.display_name:null;
 const api=error instanceof TutoringApiError?error:null;
 const wait=api?.status===429&&Number.isFinite(api.retryAfterSeconds)?Math.max(0,api.retryAfterSeconds!):0;
 const deadline=query.errorUpdatedAt+wait*1000,remaining=wait>0?Math.max(0,Math.ceil((deadline-now)/1000)):0;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{if(!wait)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),250);return()=>clearInterval(timer);},[wait,deadline]);
 useLayoutEffect(()=>{
  const host=root.current;if(!host)return;
  if(action.current&&document.activeElement!==action.current&&document.activeElement!==document.body){action.current=null;return;}
  if(busy){if(action.current&&!host.contains(action.current)){const pending=host.querySelector<HTMLElement>('[data-loading]');if(pending){action.current=pending;pending.focus({preventScroll:true});}}return;}
  if(identity.phase==='pending')return;
  const alert=host.querySelector<HTMLElement>('[role="alert"]');
  if(first.current){first.current=false;if(alert&&document.activeElement===document.body)alert.focus({preventScroll:true});}
  if(action.current){action.current=null;(alert??host.querySelector<HTMLElement>('h1'))?.focus({preventScroll:true});}
 });
 async function retry(trigger:HTMLElement){
  if(lock.current||busy||remaining>0)return;lock.current=true;action.current=trigger;trigger.focus({preventScroll:true});setRetrying(true);
  try{if(identity.phase==='unavailable')await identity.refresh();else if(authorized&&id)await query.refetch({cancelRefetch:false});}
  finally{lock.current=false;if(mounted.current)setRetrying(false);}
 }
 const calendar=<span className="s20-action-icon"><Calendar/></span>;
 const mySessions=(primary=false)=><Link className={`s20-btn${primary?' s20-primary':''}`} to="/s-35">{calendar}My sessions</Link>;
 const missing=api?.status===404,invalidLink=api?.status===422,offline=error instanceof OfflineRead;
 function failure(){
  const unavailable=identity.phase==='unavailable';
  const title=unavailable?'Your session could not be checked.':missing?'This session is not available.':invalidLink?'Check the session link.':offline?'You are offline.':api?.code==='invalid_response'?'The response could not be verified.':'The session did not load.';
  const description=unavailable?'Your private session details remain locked.':missing?'It may belong to another account or the link is out of date.':invalidLink?'Open a session from My sessions.':offline?'No request was sent. Reconnect and retry.':api?.status===429?remaining?`Try again in ${remaining} seconds.`:'You can retry now.':api?.status===403?'This account cannot access this session.':api?.code==='invalid_response'?'No session status is assumed. Try loading the record again.':'Try again in a moment.';
  return <section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name={offline?'offline':'warning'} size={20}/></span><h2>{title}</h2><p>{description}</p>{api&&api.status>=400&&<div className="s20-code">HTTP {api.status} · {api.code}</div>}<div className="s20-actions">{missing||invalidLink||api?.status===403?mySessions(true):<button className="s20-btn s20-primary" aria-disabled={busy||remaining>0} aria-busy={busy||undefined} onClick={e=>void retry(e.currentTarget)}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>Retry</button>}</div>{busy&&<p role="status">Loading the session.</p>}</section>;
 }
 const state=data?labels[data.status]:null;
 return <div className="v321-internships s34-session" data-screen="S-34" data-v34-screen="S-34" ref={root} onFocusCapture={e=>{first.current=false;if(action.current&&e.target!==action.current)action.current=null;}}>
  <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Session</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={()=>nav('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={()=>nav('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={()=>nav('/s-17')}><Icon name="person"/></button></header>
  <div className="s20-layout"><main id="main-content"><Link className="s20-btn s34-back" to="/s-35"><span className="s20-action-icon"><Icon name="back" size={18}/></span>My sessions</Link><h1 tabIndex={-1}><span className="s20-heading-icon"><Calendar size={20}/></span>{name?`Session with ${name}.`:'Session.'}</h1>
   {!id?<section className="s20-empty" role="alert" tabIndex={-1}><h2>Choose a session first.</h2><p>Open a session from My sessions.</p>{mySessions(true)}</section>:identity.phase==='unavailable'||error?failure():!data?<div className="s20-skeletons" role="status" aria-label="Loading session" tabIndex={-1} data-loading><div/><div/></div>:state&&<>
    <div className="s20-chips"><span className={`s20-chip s34-chip s34-${data.status}`}><span className="s34-dot" aria-hidden="true"/>{state[0]}</span></div>
    <section className={`s34-notice s34-${data.status}`} role="status"><StatusIcon kind={state[3]}/><div><h2>{state[1]}</h2>{state[2]&&<p>{state[2]}</p>}</div></section>
    <dl className="s34-facts"><div><dt>Starts</dt><dd><time dateTime={data.start_utc}>{data.start_local}</time></dd></div><div><dt>Ends</dt><dd><time dateTime={data.end_utc}>{data.end_local}</time></dd></div><div><dt>Timezone</dt><dd>{data.iana_timezone}</dd></div><div><dt>Order</dt><dd className="s34-code">{data.order_id??'Not provided'}</dd></div></dl>
    <div className="s20-actions">{data.status==='confirmed'||data.status==='rescheduled'?<Link className="s20-btn s20-primary" to={`/s-35?session=${encodeURIComponent(data.id)}&view=detail`}>{calendar}Manage session</Link>:mySessions()}<button className="s20-btn" aria-disabled={busy} onClick={e=>void retry(e.currentTarget)}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>Refresh session</button></div>
   </>}
  </main><aside aria-label="Joining"><section className="s20-card"><h2 className="s20-eyebrow" id="s34-joining">Joining</h2><p>Join is offered from My sessions when video is available and the server issues your join credentials.</p></section></aside></div><footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
 </div>;
}

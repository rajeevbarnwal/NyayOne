import { useEffect, useLayoutEffect, useRef, useState, type MutableRefObject } from 'react';
import { useIsMutating, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams, useLocation } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { Icon } from '../internships/S20BrowseView';
import { LawSchoolsApiError, DEFAULT_COMPARE_MAX } from '../lib/lawSchoolsApi';
import { useStudentMutation } from '../lib/useStudentMutation';
import { captureStudentContextFence, isStudentContextFenceCurrent } from '../lib/studentBrowserContext';
import { inrAmount, institutionTypeLabel, FACT_LABELS, S28_FACT_KEY_ORDER } from './lawschoolFormat.mjs';
import { readSchoolDetail, writeSchoolSaved, writeSchoolFollow, safeSource, schoolReturn, type S28Detail } from './s28Api';
import type { SchoolSelection } from './S27SearchScreen';
import './S28Detail.css';
type Store = { readSelection: () => SchoolSelection[]; writeSelection: (items: SchoolSelection[]) => SchoolSelection[] };
type Action = { trigger: HTMLElement; anchor?: HTMLElement; done: boolean };
type Continuation = { focus: Action | null; expired: boolean };
type Write = { kind: 'saved'|'follow'; desired: boolean; notify: boolean; fence: ReturnType<typeof captureStudentContextFence> };
class OfflineDetail extends Error {}
function SchoolIcon({ compare = false, size = 20 }: {compare?:boolean;size?:number}) {
 return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">{compare ? [3.5,13.5].map(x=><g key={x}><rect x={x} y="5" width="7" height="14" rx="2" fill="currentColor" opacity=".16"/><rect x={x} y="5" width="7" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.9"/></g>) : <><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="currentColor" opacity=".16"/><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M6.5 11.5v4.5c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3v-4.5M21 9.5v5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}</svg>;
}
function Bell() { return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 9a6 6 0 0 1 12 0v5l2 3H4l2-3z" fill="currentColor" opacity=".16"/><path d="M6 9a6 6 0 0 1 12 0v5l2 3H4l2-3zM10 20h4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function fees(d:S28Detail) { if(d.feesMin===null&&d.feesMax===null)return 'Not provided'; if(d.feesMin===null)return `Up to ${inrAmount(d.feesMax!)}`; if(d.feesMax===null)return `From ${inrAmount(d.feesMin)}`;return `${inrAmount(d.feesMin)}${d.feesMin===d.feesMax?'':` to ${inrAmount(d.feesMax)}`} per year`; }
function date(value:string|null) { if(!value||Number.isNaN(Date.parse(value)))return 'Retrieval date not provided';return `retrieved ${new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(value))}`; }
export function S28DetailScreen(props:Store) {
 const auth=useAuth(), [params]=useSearchParams(), location=useLocation(); const id=params.get('id')??'';
 const continuation=useRef<Continuation>({focus:null,expired:false}), previousId=useRef(location.key);
 if(previousId.current!==location.key){previousId.current=location.key;continuation.current={focus:null,expired:false};}
 return <Detail key={`${location.key}:${id}:${auth.userId}:${auth.roles.join(',')}`} {...props} continuation={continuation}/>;
}
function Detail({readSelection,writeSelection,continuation}: Store & {continuation:MutableRefObject<Continuation>}) {
 const auth=useAuth(),session=useStudentSession(),client=useQueryClient(),nav=useNavigate(),[sp]=useSearchParams();
 const id=sp.get('id')??'', valid=!!id.trim()&&id.length<=200, back=schoolReturn(sp), root=useRef<HTMLDivElement>(null);
 const mounted=useRef(true),lock=useRef(false),first=useRef(true);
 const [error,setError]=useState(''),[uncertain,setUncertain]=useState(false),[notice,setNotice]=useState(''),[busy,setBusy]=useState(''),[attempt,setAttempt]=useState(0),[tray,setTray]=useState(readSelection);
 const activeWrites=useIsMutating({mutationKey:['s28-write',auth.userId,id]});
 const key=['s28-detail',auth.userId,id], canWrite=session.phase==='authenticated'&&auth.isAuthenticated&&auth.roles.includes('student')&&!!auth.userId;
 const query=useQuery({queryKey:key,queryFn:async({signal})=>{
  if(!navigator.onLine)throw new OfflineDetail();
  try{return await readSchoolDetail(id,signal);}catch(e){if(e instanceof LawSchoolsApiError&&e.status===401)continuation.current.expired=true;throw e;}
 },enabled:valid&&session.phase!=='pending'&&session.phase!=='unavailable'&&!continuation.current.expired&&activeWrites===0&&!uncertain,retry:false,networkMode:'always',staleTime:Infinity,refetchOnMount:'always',refetchOnWindowFocus:false,refetchOnReconnect:false});
 // Cancel reads started before a write commits. A late private-list response
 // must not restore stale membership on S-30 after navigating away from S-28.
 async function invalidatePrivate(fence:Write['fence']) {
  const filters=[{queryKey:['law-schools-saved']},{queryKey:['law-schools-followed']},{queryKey:['law-school',id]},{queryKey:['s28-detail',auth.userId,id]}];
  for(const filter of filters)await client.cancelQueries(filter);
  if(!isStudentContextFenceCurrent(fence))return;
  for(const filter of filters)void client.invalidateQueries({...filter,refetchType:'none'});
 }
 const mutation=useStudentMutation({mutationKey:['s28-write',auth.userId,id],retry:false,networkMode:'always',
  mutationFn:async(v:Write)=>{try{return v.kind==='saved'?await writeSchoolSaved(id,v.desired):await writeSchoolFollow(id,v.desired,v.notify);}catch(e){if(e instanceof LawSchoolsApiError&&e.status===401)continuation.current.expired=true;throw e;}},
  onSuccess:async(result,v)=>{await invalidatePrivate(v.fence);if(!isStudentContextFenceCurrent(v.fence))return;client.setQueryData<S28Detail>(key,d=>d?{...d,...result}:d);
   for(const prefix of [['law-schools-saved'],['law-schools-followed'],['law-school',id]])void client.invalidateQueries({queryKey:prefix});},
  onError:async(_e,v)=>{await invalidatePrivate(v.fence);},
 });
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const expired=continuation.current.expired, unavailable=session.phase==='unavailable', loading=session.phase==='pending'||(!expired&&!unavailable&&valid&&query.isPending);
 const data=!loading&&!expired&&!query.isError?query.data:undefined;
 const initialError=!valid||expired||unavailable||query.isError;
 const blocked=!!busy||activeWrites>0||query.isFetching||uncertain||!canWrite||!data;
 useLayoutEffect(()=>{
  const host=root.current;if(!host)return; const alert=host.querySelector<HTMLElement>('[role="alert"]');
  if(first.current&&!loading){first.current=false;if(alert&&document.activeElement===document.body)alert.focus({preventScroll:true});}
  const action=continuation.current.focus;if(!action)return;
  if(document.activeElement!==action.trigger&&document.activeElement!==action.anchor&&document.activeElement!==document.body){continuation.current.focus=null;return;}
  if(expired)action.done=true;
  if(!action.done){if(!action.trigger.isConnected&&document.activeElement===document.body){action.anchor=host.querySelector<HTMLElement>('h1')??undefined;action.anchor?.focus({preventScroll:true});}return;}
  continuation.current.focus=null;
  if(alert)alert.focus({preventScroll:true});else if(!action.trigger.isConnected)(host.querySelector<HTMLElement>('h1'))?.focus({preventScroll:true});
 });
 function begin(trigger:HTMLElement){trigger.focus({preventScroll:true});continuation.current.focus={trigger,done:false};setAttempt(n=>n+1);}
 function finish(){if(continuation.current.focus)continuation.current.focus.done=true;}
 async function write(kind:Write['kind'],desired:boolean,notify:boolean,trigger:HTMLElement){
  if(lock.current||blocked)return;begin(trigger);setNotice('');
  if(!navigator.onLine){finish();setError('You are offline. No request was sent. Reconnect and try again.');return;}
  lock.current=true;setBusy(kind);setError('');
  try{await mutation.mutateAsync({kind,desired,notify,fence:captureStudentContextFence()});if(mounted.current)setNotice(kind==='saved'?(desired?'School saved.':'School removed from saved schools.'):(desired?'Following preference confirmed.':'School unfollowed.'));}
  catch(e){if(mounted.current){setUncertain(true);setError(e instanceof LawSchoolsApiError&&e.status===403?'This action requires a student account. Reload to confirm your access.':`Could not confirm ${kind==='saved'?'saved state':'following'}. Reload the school before trying again.`);}}
  finally{lock.current=false;finish();if(mounted.current)setBusy('');}
 }
 async function reload(trigger:HTMLElement){
  if(lock.current||busy||query.isFetching)return;begin(trigger);lock.current=true;setBusy('read');setNotice('');
  try{
   if(!navigator.onLine){setError('You are offline. No request was sent. Reconnect and retry.');return;}
   if(unavailable){await session.refresh();return;}
   const result=await query.refetch({cancelRefetch:false});if(mounted.current){if(result.isSuccess){setUncertain(false);setError('');setNotice('School reloaded.');}else setError('The school did not load. Try again in a moment.');}
  }finally{lock.current=false;finish();if(mounted.current)setBusy('');}
 }
 function compare(trigger:HTMLElement){
  if(!data)return;const current=readSelection(),exists=current.some(item=>item.id===id);
  if(!exists&&current.length>=DEFAULT_COMPARE_MAX){begin(trigger);finish();setError(`You can compare up to ${DEFAULT_COMPARE_MAX} schools. Remove one from comparison first.`);return;}
  if(!uncertain)setError('');setTray(writeSelection(exists?current.filter(item=>item.id!==id):[...current,{id,name:data.name}]));setNotice(exists?'Removed from comparison.':'Added to comparison.');
 }
 const status=query.error instanceof LawSchoolsApiError&&query.error.status>=400&&query.error.status<=599?query.error.status:null;
 const missing=status===404, offline=query.error instanceof OfflineDetail;
 const facts=data?[...data.facts].sort((a,b)=>{const rank=(k:string)=>S28_FACT_KEY_ORDER.includes(k)?S28_FACT_KEY_ORDER.indexOf(k):99;return rank(a.key)-rank(b.key);}):[];
 const absent=S28_FACT_KEY_ORDER.filter(k=>!facts.some(f=>f.key===k));
 const errorTitle=!valid?'No school in this link.':expired?'Sign in again.':unavailable?'Account access could not be checked.':missing?'This school page is not available.':offline?'You are offline.':'The school did not load.';
 return <div ref={root} className="v321-internships s28-detail" data-screen="S-28" data-v34-screen="S-28"
  onFocusCapture={event=>{first.current=false;const action=continuation.current.focus;if(action&&event.target!==action.trigger&&event.target!==action.anchor)continuation.current.focus=null;}}>
  <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Law school</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={()=>nav('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={()=>nav('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={()=>nav('/s-17')}><span><Icon name="person"/></span></button></header>
  <div className="s20-layout"><main id="main-content">
   <Link className="s20-btn s28-back" to={back.path}><span className="s20-action-icon"><Icon name="back" size={18}/></span>{back.label}</Link>
   <div><h1 tabIndex={-1}><span className="s20-heading-icon"><SchoolIcon/></span>{data?`${data.name.replace(/\.$/,'')}.`:'Law school.'}</h1>{data&&<p className="s20-sub">{institutionTypeLabel(data.institutionType)} · {data.state}</p>}</div>
   {loading&&<div className="s20-skeletons" role="status" aria-label="Loading law school">{[1,2,3].map(i=><div key={i}/>)}</div>}
   {initialError&&!loading&&<section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name="warn"/></span><h2>{errorTitle}</h2><p key={attempt}>{!valid?'Choose a school from the directory.':expired?'Your session ended. Sign in to save or follow schools.':missing?'The record was removed or the link is out of date.':offline?'No request was sent. Reconnect and retry.':'Try again in a moment.'}</p>{status!==null&&!expired&&<div className="s20-code">HTTP {status}</div>}<div className="s20-actions">{expired?<Link className="s20-btn s20-primary" to="/s-03">Sign in</Link>:missing||!valid?<Link className="s20-btn s20-primary" to="/s-27"><SchoolIcon size={18}/>Find a law school</Link>:<button className="s20-btn s20-primary" aria-disabled={!!busy||query.isFetching} aria-busy={!!busy||undefined} onClick={e=>void reload(e.currentTarget)}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>Retry</button>}</div></section>}
   {data&&<>
    <div className="s20-chips"><span className="s20-chip s28-accreditation"><span className="s28-chip-dot" aria-hidden="true"/>{data.accreditation||'Accreditation not provided'}</span><span className="s20-chip">{data.entranceExam||'Entrance exam not provided'}</span></div>
    {error&&<section className="s20-note s28-error" role="alert" tabIndex={-1}><Icon name="warn" size={18}/><div><b>{uncertain?'Change needs confirmation.':'Could not complete this action.'}</b><p key={attempt}>{error}</p>{uncertain&&<button className="s20-btn" aria-disabled={!!busy||query.isFetching} aria-busy={busy==='read'||undefined} onClick={e=>void reload(e.currentTarget)}><Icon name="refresh" size={18}/>Reload school</button>}</div></section>}
    <div className="s28-kvs">{[['Fees',fees(data)],['NIRF rank',data.nirfRank===null?'Not provided':String(data.nirfRank)],['Programmes',data.programmes.length?data.programmes.map(p=>`${p.degree} (${p.durationYears} yr)`).join(', '):'Not provided']].map(([label,value])=><div className="s28-kv" key={label}><span>{label}</span><b className={value==='Not provided'?'s28-na':undefined}>{value}</b></div>)}</div>
    <section className="s28-facts" aria-labelledby="s28-facts-heading"><h2 className="s28-eyebrow" id="s28-facts-heading">Published facts</h2>{facts.map((f,index)=>{const source=safeSource(f.sourceUrl);return <div className="s28-fact" key={`${f.key}:${index}`}><div className="s28-kv"><span>{FACT_LABELS[f.key]??f.key}</span><b>{f.value||'Not provided'}</b></div><p className="s28-source">{source?<a href={source.url} target="_blank" rel="noopener noreferrer" aria-label={`${f.sourceName||'Source'} (${source.host}, opens in a new tab)`}>{f.sourceName||source.host}</a>:f.sourceName||'Source not provided'}, {date(f.retrievedAt)}</p></div>;})}{absent.length>0&&<p className="s28-source">Not published: {absent.map(k=>FACT_LABELS[k]??k).join(', ')}</p>}</section>
    <div className="s20-actions s28-actions"><button data-s28-save className="s20-btn" aria-pressed={canWrite&&data.saved} aria-disabled={blocked} aria-busy={busy==='saved'||undefined} onClick={e=>void write('saved',!data.saved,false,e.currentTarget)}><span className={`s20-action-icon ${data.saved?'s28-gold':'s20-indigo'}`}><Icon name={data.saved?'bookmarkf':'bookmark'} size={18}/></span>{busy==='saved'?'Saving':canWrite&&data.saved?'Saved':'Save'}</button><button className="s20-btn" aria-pressed={canWrite&&data.followed} aria-disabled={blocked} aria-busy={busy==='follow'||undefined} onClick={e=>void write('follow',!data.followed,false,e.currentTarget)}><span className={`s20-action-icon ${data.followed?'s28-green':'s20-indigo'}`}><Bell/></span>{busy==='follow'?'Updating':canWrite&&data.followed?'Following':'Follow'}</button></div>
    {!canWrite&&<p className="s28-help">{auth.isAuthenticated?'A student account is required to save or follow schools.':<><Link className="s28-signin" to="/s-03">Sign in</Link> to save or follow schools.</>}</p>}
    {canWrite&&data.followed?(data.notifyOptIn===null?<section className="s28-preference"><p>Your notification preference is not available here. Choose explicitly to update it.</p><div className="s20-actions"><button className="s20-btn" aria-disabled={blocked} onClick={e=>void write('follow',true,true,e.currentTarget)}>Turn notifications on</button><button className="s20-btn" aria-disabled={blocked} onClick={e=>void write('follow',true,false,e.currentTarget)}>Keep notifications off</button></div></section>:<label className="s28-checkbox"><input id="s28-notify" type="checkbox" checked={data.notifyOptIn} aria-label="Notify me about updates to this school" aria-disabled={blocked} onChange={e=>{if(!blocked)void write('follow',true,e.currentTarget.checked,e.currentTarget);}}/><span><b>Notify me about updates to this school</b><small>A separate choice from following</small></span></label>):<p className="s28-help">Following keeps the school in your Following list. You choose separately whether to get update notifications.</p>}
    <button className="s20-btn s28-compare" aria-pressed={tray.some(item=>item.id===id)} onClick={e=>compare(e.currentTarget)}><span className="s20-action-icon s20-indigo"><SchoolIcon compare size={18}/></span>{tray.some(item=>item.id===id)?'Remove from comparison':'Add to comparison'}</button>
   </>}
   <span role="status" className="s20-announcement">{notice}</span>
  </main><aside aria-label="Law school context"><section className="s20-card"><h2 className="s20-eyebrow">Reading the figures</h2><p>Each figure shows where it came from and when NyayOne retrieved it. A retrieval date is not certification by NyayOne or the institution.</p></section></aside></div>
  <footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
 </div>;
}

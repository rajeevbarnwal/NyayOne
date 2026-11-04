import { useEffect, useLayoutEffect, useRef, useState, type MutableRefObject } from 'react';
import { useIsMutating, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { Icon } from '../internships/S20BrowseView';
import { useStudentMutation } from '../lib/useStudentMutation';
import { captureStudentContextFence, isStudentContextFenceCurrent } from '../lib/studentBrowserContext';
import { DEFAULT_COMPARE_MAX, LawSchoolsApiError } from '../lib/lawSchoolsApi';
import { readPrivateSchools, removePrivateSchool, reconcileSchoolRemoval, type PrivateSchool, type SchoolListKind } from './s30Api';
import { institutionTypeLabel, inrAmount } from './lawschoolFormat.mjs';
import type { SchoolSelection } from './S27SearchScreen';
import './S30SavedSchools.css';
type FocusAction={anchor:HTMLElement;index:number;kind:SchoolListKind;done:boolean};
type Continuation={expired:boolean;focus:FocusAction|null};
type Write={kind:SchoolListKind;id:string;fence:ReturnType<typeof captureStudentContextFence>};
type Failure={id:string;message:string;uncertain:boolean;attempt:number};
class OfflineList extends Error {}
const kinds:SchoolListKind[]=['saved','followed'];
function SchoolIcon({compare=false}:{compare?:boolean}){return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{compare?[3.5,13.5].map(x=><g key={x}><rect x={x} y="5" width="7" height="14" rx="2" fill="currentColor" opacity=".16"/><rect x={x} y="5" width="7" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.9"/></g>):<><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="currentColor" opacity=".16"/><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M6.5 11.5v4.5c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3v-4.5M21 9.5v5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}</svg>;}
function Bell(){return <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" fill="currentColor" opacity=".14"/><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/></svg>;}
function fees(item:PrivateSchool){return item.feesMin===null&&item.feesMax===null?'Fees not provided':item.feesMin===null?`Up to ${inrAmount(item.feesMax!)} per year`:item.feesMax===null?`From ${inrAmount(item.feesMin)} per year`:`${inrAmount(item.feesMin)}${item.feesMin===item.feesMax?'':` to ${inrAmount(item.feesMax)}`} per year`;}
export function S30SavedSchools({writeSelection}:{writeSelection:(items:SchoolSelection[])=>SchoolSelection[]}){
 const auth=useAuth(),location=useLocation(),previous=useRef(location.key),continuation=useRef<Continuation>({expired:false,focus:null});
 if(previous.current!==location.key){previous.current=location.key;continuation.current={expired:false,focus:null};}
 return <SavedSchools key={`${location.key}:${auth.userId}:${auth.roles.join(',')}`} continuation={continuation} writeSelection={writeSelection}/>;
}
function SavedSchools({continuation,writeSelection}:{continuation:MutableRefObject<Continuation>;writeSelection:(items:SchoolSelection[])=>SchoolSelection[]}){
 const auth=useAuth(),session=useStudentSession(),client=useQueryClient(),nav=useNavigate(),root=useRef<HTMLDivElement>(null),mounted=useRef(true),lock=useRef(false),initial=useRef(true);
 const [tab,setTab]=useState<SchoolListKind>('saved'),[busy,setBusy]=useState<{kind:SchoolListKind;id:string}|null>(null),[failures,setFailures]=useState<Partial<Record<SchoolListKind,Failure>>>({}),[notice,setNotice]=useState('');
 const [offlineRetries,setOfflineRetries]=useState<Partial<Record<SchoolListKind,boolean>>>({});
 const activeWrites=useIsMutating({mutationKey:['s30-write',auth.userId]});
 const authorized=session.phase==='authenticated'&&auth.isAuthenticated&&auth.roles.includes('student')&&!!auth.userId;
 function options(kind:SchoolListKind){return {queryKey:[`law-schools-${kind}`,auth.userId],queryFn:async({signal}:{signal:AbortSignal})=>{
  if(!navigator.onLine)throw new OfflineList();
  // Any actual read, including a mutation-triggered refetch, supersedes earlier
  // no-request feedback. Keep uncertain writes gated until a successful reload.
  if(mounted.current&&!signal.aborted){
   setOfflineRetries(old=>old[kind]?{...old,[kind]:false}:old);
   setFailures(old=>old[kind]&&!old[kind].uncertain?{...old,[kind]:undefined}:old);
  }
  try{return await readPrivateSchools(kind,signal);}catch(e){if(e instanceof LawSchoolsApiError&&e.status===401)continuation.current.expired=true;throw e;}
 },enabled:authorized&&!continuation.current.expired&&activeWrites===0&&!failures[kind]?.uncertain,retry:false,networkMode:'always' as const,staleTime:Infinity,refetchOnMount:'always' as const,refetchOnWindowFocus:false,refetchOnReconnect:false};}
 const saved=useQuery(options('saved')),followed=useQuery(options('followed')),queries={saved,followed},query=queries[tab];
 const mutation=useStudentMutation({mutationKey:['s30-write',auth.userId],retry:false,networkMode:'always',mutationFn:async(v:Write)=>{
  try{await removePrivateSchool(v.kind,v.id);}catch(e){if(e instanceof LawSchoolsApiError&&e.status===401)continuation.current.expired=true;throw e;}
 },onSuccess:(_data,v)=>reconcileSchoolRemoval(client,auth.userId!,v.kind,v.id,true,()=>isStudentContextFenceCurrent(v.fence)),onError:(_e,v)=>reconcileSchoolRemoval(client,auth.userId!,v.kind,v.id,false,()=>isStudentContextFenceCurrent(v.fence))});
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const expired=continuation.current.expired,accessError=expired||session.phase==='anonymous'||(session.phase==='authenticated'&&!authorized),unavailable=session.phase==='unavailable';
 const loading=session.phase==='pending'||(authorized&&!expired&&query.isPending),failure=failures[tab];
 const blocked=!!busy||activeWrites>0||query.isFetching||!authorized||expired;
 useLayoutEffect(()=>{
  const host=root.current;if(!host)return;const alert=host.querySelector<HTMLElement>('[role="alert"]'),heading=host.querySelector<HTMLElement>('h1');
  if(initial.current&&!loading){initial.current=false;if(alert&&document.activeElement===document.body)alert.focus({preventScroll:true});}
  const action=continuation.current.focus;if(!action)return;
  if(document.activeElement!==action.anchor&&document.activeElement!==document.body){continuation.current.focus=null;return;}
  if(!action.done&&!expired&&!accessError)return;
  const controls=[...host.querySelectorAll<HTMLElement>('[data-s30-remove]')],next=controls[Math.min(action.index,controls.length-1)];
  continuation.current.focus=null;(alert??(action.anchor.isConnected?action.anchor:next??heading))?.focus({preventScroll:true});
 });
 function own(trigger:HTMLElement,kind:SchoolListKind,index:number,retry=false){const anchor=retry?root.current?.querySelector<HTMLElement>('h1')??trigger:trigger;continuation.current.focus={anchor,index,kind,done:false};anchor.focus({preventScroll:true});}
 function failed(kind:SchoolListKind,id:string,message:string,uncertain:boolean){setFailures(old=>({...old,[kind]:{id,message,uncertain,attempt:(old[kind]?.attempt??0)+1}}));}
 function finish(){if(continuation.current.focus)continuation.current.focus.done=true;}
 async function remove(item:PrivateSchool,index:number,trigger:HTMLElement){
  if(lock.current||blocked||failure?.uncertain)return;own(trigger,tab,index);setNotice('');
  if(!navigator.onLine){finish();failed(tab,item.id,'You are offline. No request was sent. Reconnect and try again.',false);return;}
  const kind=tab;lock.current=true;setBusy({kind,id:item.id});setFailures(old=>({...old,[kind]:undefined}));
  try{await mutation.mutateAsync({kind,id:item.id,fence:captureStudentContextFence()});if(mounted.current)setNotice(`${item.name} ${kind==='saved'?'removed from saved schools':'unfollowed'}.`);}
  catch{if(mounted.current)failed(kind,item.id,`Could not confirm ${kind==='saved'?'removal':'unfollowing'}. This is the last known list. Reload to check the server before trying again.`,true);}
  finally{lock.current=false;finish();if(mounted.current)setBusy(null);}
 }
 async function retry(trigger:HTMLElement){
  if(lock.current||busy||query.isFetching)return;own(trigger,tab,-1,true);lock.current=true;setBusy({kind:tab,id:'read'});setNotice('');
  try{if(unavailable){await session.refresh();return;}
   if(!navigator.onLine){setOfflineRetries(old=>({...old,[tab]:true}));failed(tab,failure?.id??'','You are offline. No request was sent. Reconnect and retry.',!!failure?.uncertain);return;}
   setOfflineRetries(old=>({...old,[tab]:false}));
   const result=await query.refetch({cancelRefetch:false});if(mounted.current&&result.isSuccess){setFailures(old=>({...old,[tab]:undefined}));setNotice('List reloaded.');}
  }finally{lock.current=false;finish();if(mounted.current)setBusy(null);}
 }
 function select(kind:SchoolListKind){continuation.current.focus=null;setTab(kind);}
 const items=query.isSuccess?query.data:[],status=query.error instanceof LawSchoolsApiError&&query.error.status>=400?query.error.status:null;
 const compareReady=authorized&&!expired&&!unavailable&&saved.isSuccess&&!failures.saved?.uncertain&&saved.data.length>=2&&saved.data.length<=DEFAULT_COMPARE_MAX&&!busy;
 const compareHint=saved.isSuccess&&!failures.saved?.uncertain?(saved.data.length===1?'Save at least 2 schools to compare.':saved.data.length>DEFAULT_COMPARE_MAX?`Choose up to ${DEFAULT_COMPARE_MAX} schools in the directory to compare.`:undefined):undefined;
 const readOffline=offlineRetries[tab]||query.error instanceof OfflineList;
 const find=<Link className="s20-btn s20-primary" to="/s-27"><span className="s20-action-icon"><SchoolIcon/></span>Find schools</Link>;
 const compare=<button className="s20-btn" disabled={!compareReady} aria-describedby={compareHint?'s30-compare-help':undefined} onClick={()=>{if(!compareReady)return;writeSelection(saved.data!.map(({id,name})=>({id,name})));nav(`/s-29?${new URLSearchParams({ids:saved.data!.map(s=>s.id).join(',')})}`);}}><span className="s20-indigo"><span className="s20-action-icon"><SchoolIcon compare/></span></span>Compare saved schools</button>;
 const noticeBlock=(f:Failure)=><div className="s30-item-error" role="alert" tabIndex={-1} key={`${tab}:${f.attempt}`}><Icon name="warn" size={16}/><div><p>{f.message}</p>{f.uncertain&&<button className="s20-btn" aria-disabled={blocked} onClick={e=>void retry(e.currentTarget)}>Reload {tab==='saved'?'saved':'following'} list</button>}</div></div>;
 return <div ref={root} className="v321-internships s30-schools" data-screen="S-30" data-v34-screen="S-30" data-saved-empty={authorized&&!expired&&!unavailable&&saved.isSuccess&&!failures.saved?.uncertain&&saved.data.length===0||undefined} onFocusCapture={e=>{initial.current=false;const action=continuation.current.focus;if(action&&e.target!==action.anchor)continuation.current.focus=null;}}>
  <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Schools</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={()=>nav('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={()=>nav('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={()=>nav('/s-17')}><span><Icon name="person"/></span></button></header>
  <div className="s20-layout"><main id="main-content"><div><h1 tabIndex={-1}><span className="s20-heading-icon"><Icon name="bookmark"/></span>Saved and followed schools.</h1><p className="s20-sub">Saved keeps a school in your list. Following is separate, and update notifications are a further choice.</p></div>
   <nav className="s20-related" aria-label="Related">{compare}{compareHint&&<p id="s30-compare-help" className="s30-compare-help">{compareHint}</p>}</nav><div className="s30-tabs" role="tablist" aria-label="Schools">{kinds.map(kind=><button key={kind} role="tab" id={`s30-tab-${kind}`} aria-selected={kind===tab} aria-controls="s30-panel" tabIndex={kind===tab?0:-1} onClick={()=>select(kind)} onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?'saved':e.key==='End'?'followed':kind==='saved'?'followed':'saved';select(next);root.current?.querySelector<HTMLElement>(`#s30-tab-${next}`)?.focus();}}>{kind==='saved'?'Saved':'Following'} ({authorized&&!expired&&queries[kind].isSuccess&&!failures[kind]?.uncertain?queries[kind].data!.length:'…'})</button>)}</div>
   <div role="tabpanel" id="s30-panel" aria-labelledby={`s30-tab-${tab}`} tabIndex={0} className="s30-panel">
    {loading&&<div className="s20-skeletons" role="status" aria-label="Loading schools"><div/><div/></div>}
    {(accessError||unavailable)&&!loading&&<section className="s20-empty" role="alert" tabIndex={-1}><h2>{unavailable?'Account access could not be checked.':auth.isAuthenticated&&!expired?'Student account required.':'Sign in to view your schools.'}</h2><p>Your saved and followed schools are private to your student account.</p>{unavailable?<button className="s20-btn s20-primary" aria-disabled={!!busy} onClick={e=>void retry(e.currentTarget)}>Retry</button>:(!auth.isAuthenticated||expired)&&<Link className="s20-btn s20-primary" to="/s-03">Sign in</Link>}</section>}
    {!loading&&!accessError&&!unavailable&&query.isError&&<section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name="warn"/></span><h2>This list did not load.</h2><p>{readOffline?'You are offline. No request was sent. Reconnect and retry.':'The other list may still work.'}</p>{!readOffline&&status!==null&&<div className="s20-code">HTTP {status}</div>}<div className="s20-actions"><button className="s20-btn s20-primary" aria-disabled={blocked} aria-busy={busy?.id==='read'||undefined} onClick={e=>void retry(e.currentTarget)}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>Retry</button></div></section>}
    {!loading&&!accessError&&!unavailable&&query.isSuccess&&<>{failure&&!items.some(i=>i.id===failure.id)&&noticeBlock(failure)}{items.length===0&&!failure?.uncertain?<section className="s20-empty"><span className="s20-state-icon s20-indigo">{tab==='saved'?<Icon name="bookmark"/>:<Bell/>}</span><h2>{tab==='saved'?'No saved schools.':'You are not following any school.'}</h2><p>{tab==='saved'?'Save a school from its page to keep it here.':'Follow a school from its page. Notifications are a separate choice.'}</p><div className="s20-actions">{find}</div></section>:<div className="s20-results">{items.map((item,index)=><article className="s20-result" key={item.id}><Link className="s20-title" aria-label={item.name} to={`/s-28?${new URLSearchParams({id:item.id,from:'s30'})}`}><span>{item.name}</span><small>{institutionTypeLabel(item.institutionType)} · {item.state}</small></Link><button className="s30-remove" data-s30-remove={item.id} aria-label={tab==='saved'?`Remove ${item.name} from saved`:`Unfollow ${item.name}`} aria-pressed={failure?.uncertain?undefined:true} aria-disabled={blocked||!!failure?.uncertain} aria-busy={busy?.id===item.id||undefined} onClick={e=>void remove(item,index,e.currentTarget)}>{tab==='saved'?<Icon name="bookmark-filled" size={20}/>:<Bell/>}</button><div className="s20-meta"><p>{fees(item)} · {item.entranceExam||'Entrance exam not provided'}</p>{tab==='followed'&&<p>Update notifications: {item.notifyOptIn?'on':'off'}</p>}{failure?.id===item.id&&noticeBlock(failure)}</div></article>)}</div>}</>}
   </div><span className="s20-announcement" role="status">{notice}</span>
  </main><aside aria-label="Saved schools context"><section className="s20-card"><h2 className="s20-eyebrow">Compare saved schools</h2><p>Two or more saved schools can be compared in one step.</p>{saved.data&&saved.data.length>DEFAULT_COMPARE_MAX&&<p>Choose up to {DEFAULT_COMPARE_MAX} schools in the directory.</p>}{compare}</section></aside></div><footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
 </div>;
}

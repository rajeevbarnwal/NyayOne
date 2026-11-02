import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { Icon } from '../internships/S20BrowseView';
import { COMPARE_ROWS, FACT_LABELS } from './lawschoolFormat.mjs';
import { safeSource, schoolReturn } from './s28Api';
import { ComparisonError, comparisonDetailPath, comparisonIds, comparisonValue, readComparison, type ComparisonSchool } from './s29Api';
import type { SchoolSelection } from './S27SearchScreen';
import '../internships/S20Browse.css';
import './S29Comparison.css';
type Store={readSelection:()=>SchoolSelection[];writeSelection:(items:SchoolSelection[])=>SchoolSelection[]};
type FocusAction={trigger:HTMLElement;anchor?:HTMLElement;selectionKey?:string};
type Continuation={expired:boolean;focus:FocusAction|null};
function CompareIcon({size=20}:{size?:number}){return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">{[3.5,13.5].map(x=><g key={x}><rect x={x} y="5" width="7" height="14" rx="2" fill="currentColor" opacity=".16"/><rect x={x} y="5" width="7" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.9"/></g>)}</svg>;}
function DetailIcon({name}:{name:'trash'|'info'|'school'}){return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{name==='trash'?<><path d="M6 7h12l-1 13H7z" fill="currentColor" opacity=".14"/><path d="M6 7h12l-1 13H7zM4 7h16M9 7V4.5h6V7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/></>:name==='info'?<><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M12 11v5M12 8v.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></>:<><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="currentColor" opacity=".16"/><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M6.5 11.5v4.5c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3v-4.5M21 9.5v5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}</svg>;}
function retrieved(value:string|null){if(!value||Number.isNaN(Date.parse(value)))return 'Retrieval date not provided';return `retrieved ${new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(value))}`;}
export function S29ComparisonScreen(props:Store){
 const auth=useAuth(),continuation=useRef<Continuation>({expired:false,focus:null});
 return <ComparisonScreen key={`${auth.userId}:${auth.roles.join(',')}`} {...props} continuation={continuation}/>;
}
function ComparisonScreen({readSelection,writeSelection,continuation}:Store&{continuation:MutableRefObject<Continuation>}){
 const auth=useAuth(),session=useStudentSession(),nav=useNavigate(),location=useLocation(),[sp,setSp]=useSearchParams();
 const idsParam=sp.get('ids'),ids=useMemo(()=>comparisonIds(idsParam,readSelection()),[idsParam,readSelection]);
 const selectionKey=ids.join(','),root=useRef<HTMLDivElement>(null),first=useRef(true),lock=useRef(false),lastFailure=useRef<unknown>(null);
 const [diffOnly,setDiffOnly]=useState(false),[attempt,setAttempt]=useState(0);
 const [mobile,setMobile]=useState(()=>window.matchMedia('(max-width: 899px)').matches);
 const [pair,setPair]=useState<{selection:string;index:number}>({selection:'',index:0});
 useEffect(()=>{const media=window.matchMedia('(max-width: 899px)'),changed=()=>setMobile(media.matches);media.addEventListener('change',changed);return()=>media.removeEventListener('change',changed);},[]);
 useEffect(()=>{if(idsParam===null&&ids.length){const next=new URLSearchParams(sp);next.set('ids',selectionKey);setSp(next,{replace:true});}},[idsParam,ids,selectionKey,sp,setSp]);
 const validIds=ids.every(id=>id.trim()&&id.length<=200),tooFew=ids.length<2;
 const query=useQuery({queryKey:['s29-comparison',auth.userId,selectionKey,location.key],queryFn:async({signal})=>{
  if(!navigator.onLine)throw new Error('offline');
  try{return await readComparison(ids,signal);}catch(e){if(e instanceof ComparisonError&&e.status===401)continuation.current.expired=true;throw e;}
 },enabled:idsParam!==null&&validIds&&!tooFew&&session.phase!=='pending'&&session.phase!=='unavailable'&&!continuation.current.expired,retry:false,networkMode:'always',staleTime:Infinity,refetchOnMount:'always',refetchOnWindowFocus:false,refetchOnReconnect:false});
 if(query.isError)lastFailure.current=query.error;
 if(query.isSuccess)lastFailure.current=null;
 const expired=continuation.current.expired,unavailable=session.phase==='unavailable';
 const error=query.error??(query.isFetching?lastFailure.current:null);
 const waiting=session.phase==='pending'||(!tooFew&&validIds&&!expired&&!unavailable&&query.isPending&&!error);
 const initialFailure=expired||unavailable||!validIds||tooFew||!!error;
 const data=!initialFailure&&!waiting?query.data:undefined,items=data?.items??[];
 const back=schoolReturn(new URLSearchParams({ret:sp.get('ret')??''})).path;
 useLayoutEffect(()=>{
  const host=root.current;if(!host)return;
  const alert=host.querySelector<HTMLElement>('[role="alert"]'),heading=host.querySelector<HTMLElement>('h1');
  if(first.current&&!waiting){first.current=false;if(alert&&document.activeElement===document.body)alert.focus({preventScroll:true});}
  const action=continuation.current.focus;if(!action)return;
  if(document.activeElement!==action.trigger&&document.activeElement!==action.anchor&&document.activeElement!==document.body){continuation.current.focus=null;return;}
  if(!action.trigger.isConnected&&document.activeElement===document.body){action.anchor=heading??undefined;heading?.focus({preventScroll:true});}
  if(waiting||query.isFetching||(action.selectionKey!==undefined&&action.selectionKey!==selectionKey))return;
  continuation.current.focus=null;lock.current=false;
  if(alert)alert.focus({preventScroll:true});else if(!action.trigger.isConnected)heading?.focus({preventScroll:true});
 });
 useEffect(()=>{if(!waiting&&!query.isFetching)lock.current=false;},[waiting,query.isFetching]);
 function begin(trigger:HTMLElement){trigger.focus({preventScroll:true});continuation.current.focus={trigger};setAttempt(n=>n+1);}
 async function retry(trigger:HTMLElement){if(lock.current||query.isFetching)return;lock.current=true;begin(trigger);try{if(unavailable)await session.refresh();else await query.refetch({cancelRefetch:false});}finally{lock.current=false;}}
 function remove(id:string,trigger:HTMLElement){
  if(lock.current||query.isFetching)return;lock.current=true;begin(trigger);lastFailure.current=null;
  const nextIds=ids.filter(value=>value!==id);
  // Anchor focus before removing the trigger. The action belongs to the new
  // selection and must not settle against the preceding comparison's render.
  const anchor=root.current?.querySelector<HTMLElement>('h1')??undefined;
  continuation.current.focus={trigger,anchor,selectionKey:nextIds.join(',')};anchor?.focus({preventScroll:true});
  writeSelection(readSelection().filter(item=>item.id!==id));
  const next=new URLSearchParams(sp);next.set('ids',nextIds.join(','));setSp(next,{replace:true});
 }
 const typed=error instanceof ComparisonError?error:null;
 const http=typed&&typed.status>=400&&typed.status<=599?typed.status:null;
 const selectionError=!!typed&&[404,422].includes(typed.status)&&['school_not_found','COMPARE_LIMIT_EXCEEDED','COMPARE_MIN_NOT_MET','validation_error','DUPLICATE_SCHOOL'].includes(typed.code);
 const serverCount=(key:string)=>{const value=typed?.extra[key];return typeof value==='number'&&Number.isSafeInteger(value)&&value>=2?value:null;};
 const selectionDescription=typed?.code==='school_not_found'?'A selected school could not be found. Remove it or choose different schools.':typed?.code==='COMPARE_LIMIT_EXCEEDED'?(serverCount('max_allowed')!==null?`Comparison is limited to ${serverCount('max_allowed')} schools. Remove schools to meet the server limit.`:'The selection exceeds the server comparison limit. Change the schools selected.'):typed?.code==='COMPARE_MIN_NOT_MET'?(serverCount('min_required')!==null?`Choose at least ${serverCount('min_required')} schools, as required by the server.`:'The server requires more schools. Change the schools selected.'):'The school selection could not be accepted. Remove invalid entries or choose schools from the directory.';
 const title=expired?'Sign in again.':unavailable?'Account access could not be checked.':!validIds?'The school selection is not valid.':tooFew?'Pick one more school.':selectionError?'Change the school selection.':'The comparison did not load.';
 const description=expired?'Your session ended. Sign in to continue.':unavailable?'Retry to check your account access.':!validIds?'Choose schools from the directory.':tooFew?'Pick at least 2 schools to compare.':selectionError?selectionDescription:typed?.code==='invalid_response'?'The response could not be verified. Your selection is kept.':error instanceof Error&&error.message==='offline'?'You are offline. No request was sent. Reconnect and retry.':'Your selection is kept.';
 const missing=items.some(item=>COMPARE_ROWS.some(row=>comparisonValue(item,row.key)==='Not provided'));
 const pairIndex=pair.selection===selectionKey?pair.index:0;
 // Apply the existing accessible pair interaction to every server-supported
 // selection with more than two schools; never truncate the server result.
 const pairs=items.length>2?items.flatMap((item,index)=>items.slice(index+1).map(other=>[item,other])):[];
 const shown=mobile&&pairs.length?(pairs[pairIndex]??pairs[0]):items;
 const rows=COMPARE_ROWS.filter(row=>!diffOnly||new Set(shown.map(item=>comparisonValue(item,row.key))).size>1);
 const coreRows=rows.filter(row=>COMPARE_ROWS.slice(0,7).some(r=>r.key===row.key));
 const factRows=rows.filter(row=>COMPARE_ROWS.slice(7).some(r=>r.key===row.key));
 function table(selectedRows:typeof rows,caption:string){return <div className="s29-table-wrap"><table className="s29-table" style={{'--s29-columns':shown.length} as React.CSSProperties}><caption className="s20-announcement">{caption}</caption><thead><tr><th scope="col" className="s29-metric"><span className="s20-announcement">Figure</span></th>{shown.map(item=><th key={item.id} scope="col"><Link className="s29-title-link" to={comparisonDetailPath(item.id,ids,sp.get('ret')??'')}>{item.name}</Link></th>)}</tr></thead><tbody>{selectedRows.map(row=><tr key={row.key}><th scope="row">{row.label}</th>{shown.map(item=>{const value=comparisonValue(item,row.key);return <td key={item.id}>{value==='Not provided'?<i className="s29-na">{value}</i>:value}</td>;})}</tr>)}</tbody></table></div>;}
 function provenance(item:ComparisonSchool){return <li key={item.id}><b>{item.name}</b>{item.facts.length?<ul>{item.facts.map(f=>{const source=safeSource(f.sourceUrl);return <li key={f.key}>{FACT_LABELS[f.key]??f.key} from {source?<a href={source.url} target="_blank" rel="noopener noreferrer" aria-label={`${f.sourceName||source.host} (${source.host}, opens in a new tab)`}>{f.sourceName||source.host}</a>:f.sourceName||'Source not provided'}, {retrieved(f.retrievedAt)}</li>;})}</ul>:<p>No published fact sources provided.</p>}</li>;}
 return <div ref={root} className="v321-internships s29-comparison" data-screen="S-29" data-v34-screen="S-29" onFocusCapture={event=>{first.current=false;const action=continuation.current.focus;if(action&&event.target!==action.trigger&&event.target!==action.anchor)continuation.current.focus=null;}}>
  <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Compare</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={()=>nav('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={()=>nav('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={()=>nav('/s-17')}><span><Icon name="person"/></span></button></header>
  <div className="s20-layout"><main id="main-content">
   <Link className="s20-btn s29-back" to={back}><span className="s20-action-icon"><Icon name="back" size={18}/></span>Find a law school</Link>
   <div><h1 tabIndex={-1}><span className="s20-heading-icon"><CompareIcon/></span>Compare schools.</h1><p className="s20-sub">Aligned figure by figure, using only what each institution has published.</p></div>
   {waiting&&<div className="s20-skeletons" role="status" aria-label="Loading comparison" aria-busy="true">{[1,2].map(i=><div key={i}/>)}</div>}
   {initialFailure&&!waiting&&<section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name="warn"/></span><h2>{title}</h2><p key={attempt}>{description}</p>{http!==null&&<div className="s20-code">HTTP {http}</div>}{typed&&<div className="s29-error-code">{typed.code}{Object.keys(typed.extra).length>0&&<pre>{JSON.stringify(typed.extra,null,2)}</pre>}</div>}<div className="s20-actions">{expired?<Link className="s20-btn s20-primary" to="/s-03">Sign in</Link>:tooFew||!validIds?<Link className="s20-btn s20-primary" to={back}>Add another school</Link>:selectionError?<Link className="s20-btn s20-primary" to={back}>Change schools</Link>:<button className="s20-btn s20-primary" aria-disabled={query.isFetching} aria-busy={query.isFetching||undefined} onClick={e=>void retry(e.currentTarget)}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>Retry</button>}</div>{selectionError&&<ol className="s29-correction" aria-label="Selected school IDs">{ids.map((id,index)=><li key={id}><span>School {index+1}: <code>{id}</code></span><button className="s20-btn" aria-label={`Remove school ${index+1} from comparison`} aria-disabled={query.isFetching} onClick={e=>remove(id,e.currentTarget)}>Remove school {index+1}</button></li>)}</ol>}</section>}
   {data&&<>
    <p className="s29-count">{items.length} of {data.compareMax} schools</p>
    {missing&&<section className="s20-note"><DetailIcon name="info"/><div><b>Some figures are missing.</b><p>Blanks show Not provided, never zero.</p></div></section>}
    {mobile&&pairs.length>0&&<fieldset className="s29-pairs"><legend>{items.length===3?'Show two of the three schools':`Show two of the ${items.length} schools`}</legend>{pairs.map((choices,index)=><label key={choices.map(item=>item.id).join(',')} className={index===pairIndex?'s29-pair is-selected':'s29-pair'}><input type="radio" name="s29-mobile-pair" checked={index===pairIndex} onChange={()=>setPair({selection:selectionKey,index})}/><span><b>{choices.map(item=>item.name).join(' and ')}</b></span></label>)}</fieldset>}
    <h2 className="s20-announcement">Figures compared</h2>
    <div className="s29-diff"><div><b id="s29-diff-label">Differences only</b><p id="s29-diff-help">Hides figures that are the same for every school shown. The comparison data is unchanged.</p></div><button type="button" className="s29-switch" role="switch" aria-checked={diffOnly} aria-labelledby="s29-diff-label" aria-describedby="s29-diff-help" onClick={()=>setDiffOnly(v=>!v)}><span aria-hidden="true"/></button>{diffOnly&&<p role="status">Showing {rows.length} of 13 figures that differ.</p>}</div>
    {coreRows.length?table(coreRows,shown.map(item=>item.name).join(' compared with ')):<p>No core figures differ for the schools shown.</p>}
    <details className="s29-disclosure" open={missing||undefined}><summary><span>Published facts</span><small>{diffOnly?`${factRows.length} differing ${factRows.length===1?'figure':'figures'}`:'6 more figures'}</small><span className="s29-chevron" aria-hidden="true"><Icon name="back" size={18}/></span></summary><div>{factRows.length?table(factRows,'Published facts'):<p>No published facts differ for the schools shown.</p>}</div></details>
    <details className="s29-disclosure"><summary><span>Where these figures come from</span><span className="s29-chevron" aria-hidden="true"><Icon name="back" size={18}/></span></summary><div><ul className="s29-sources">{shown.map(provenance)}</ul></div></details>
    {diffOnly&&rows.length===0&&<p role="status">Every compared figure is the same for the schools shown.</p>}
    <div className={`s20-actions s29-remove${items.length>3?' s29-many-remove':''}`}>{shown.map(item=><button key={item.id} className="s20-btn" aria-label={`Remove ${item.name} from comparison`} aria-disabled={query.isFetching} onClick={e=>remove(item.id,e.currentTarget)}><span className="s20-risk"><span className="s20-action-icon" aria-hidden="true"><DetailIcon name="trash"/></span></span>Remove {items.length>3?item.name:item.name.split(' ')[0]}</button>)}</div>
    <Link className="s20-btn s29-add" to={back} aria-disabled={items.length>=data.compareMax} onClick={e=>{if(items.length>=data.compareMax)e.preventDefault();}}><span className="s20-indigo"><span className="s20-action-icon" aria-hidden="true"><DetailIcon name="school"/></span></span>Add another school</Link>
   </>}
  </main><aside aria-label="Comparison context"><section className="s20-card"><h2 className="s20-eyebrow">This comparison</h2><p>{data?<>Comparison <span className="s29-comparison-id">{data.comparisonId}</span>, up to {data.compareMax} schools. </>:'The comparison identity and limit appear after the server responds. '}Blanks mean the institution published nothing for that item.</p></section></aside></div>
  <footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
 </div>;
}

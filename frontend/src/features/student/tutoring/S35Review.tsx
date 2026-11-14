import {Ic} from './TutoringPrimitives';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../../../app/authContext';
import {useStudentMutation,isStudentMutationCancellation} from '../lib/useStudentMutation';
import {createReview,editReview,deleteReview,TutoringApiError,type TutorReview,type TutoringSession} from '../lib/tutoringApi';
import {validateReview} from '../lib/tutoringRules';

/** Frozen continuation artwork, local to S-35; decorative, never an action label. */
function ReviewActionIcon({name}:{name:'send'|'trash'}){
 return <svg className="tt-ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{name==='send'?<><path d="M4 11 20 4l-4.5 16-4-6.5z" fill="currentColor" opacity=".16"/><path d="M4 11 20 4l-4.5 16-4-6.5zM11.5 13.5 20 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>:<><path d="M6 7h12l-1 13H7z" fill="currentColor" opacity=".14"/><path d="M6 7h12l-1 13H7zM4 7h16M9 7V4.5h6V7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/></>}</svg>;
}

type Action='create'|'edit'|'delete';
/** Only records actually returned to this actor/session are editable. No review-read endpoint is invented. */
export function S35Review({session}:{session:TutoringSession}){
 const auth=useAuth(),cache=useQueryClient(),key=['s35-review',auth.userId,session.id];
 const [record,setRecord]=useState<TutorReview|undefined>(()=>cache.getQueryData(key));
 const [rating,setRating]=useState(record?.rating??0),[body,setBody]=useState(record?.body??'');
 const [editing,setEditing]=useState(false),[confirmDelete,setConfirmDelete]=useState(false),[error,setError]=useState('');
 const [now,setNow]=useState(Date.now),[busy,setBusy]=useState(false);
 const root=useRef<HTMLElement>(null),trigger=useRef<HTMLElement|null>(null),lock=useRef(false),mounted=useRef(true);
 const eligible=['confirmed','resolved'].includes(session.attendanceState??'');
 const deadline=record?.editDeadlineAt?Date.parse(record.editDeadlineAt):NaN;
 const closed=!!record&&(!Number.isFinite(deadline)||now>deadline);
 const validation=validateReview(rating||undefined,body);
 const unchanged=!!record&&rating===record.rating&&(body.trim()||null)===(record.body??null);
 useEffect(()=>{mounted.current=true;const timer=setInterval(()=>setNow(Date.now()),500);return()=>{mounted.current=false;clearInterval(timer);};},[]);
 useLayoutEffect(()=>{if(busy||!trigger.current)return;const active=document.activeElement;
  if(active===trigger.current||active===document.body){(root.current?.querySelector<HTMLElement>('[role="alert"]')??root.current?.querySelector<HTMLElement>('[data-result]'))?.focus({preventScroll:true});}
  trigger.current=null;
 },[busy,error,record,confirmDelete]);
 const mutation=useStudentMutation({retry:false,mutationFn:async(action:Action)=>{
  const r=action==='create'?await createReview({sessionId:session.id,rating,body:body.trim()||null}):action==='edit'?await editReview({reviewId:record!.id,rating,body:body.trim()||null}):await deleteReview(record!.id);
  if(!r.id||r.sessionId!==session.id||r.tutorId!==session.tutorId||!Number.isInteger(r.rating)||r.rating<1||r.rating>5||typeof r.deleted!=='boolean'||typeof r.published!=='boolean'||(action!=='create'&&r.id!==record?.id)||(action==='delete'&&!r.deleted))throw new Error('The review response could not be verified. Reload before another change.');
  return r;
 }});
 async function submit(action:Action,button:HTMLElement){
  if(lock.current||record?.deleted||(action!=='delete'&&!eligible)||action==='edit'&&(closed||unchanged)||action!=='delete'&&!validation.ok)return;
  lock.current=true;trigger.current=button;button.focus({preventScroll:true});setBusy(true);setError('');
  try{const r=await mutation.mutateAsync(action);if(!mounted.current)return;cache.setQueryData(key,r);setRecord(r);setEditing(false);setConfirmDelete(false);setRating(r.rating);setBody(r.body??'');
   // Do not claim the public rating changed; subsequent discovery/profile reads fetch the server aggregate.
   void cache.invalidateQueries({queryKey:['s31-tutors']});void cache.invalidateQueries({queryKey:['s32-profile']});
  }catch(e){if(!mounted.current||isStudentMutationCancellation(e))return;setError(e instanceof TutoringApiError?`The server refused this review change (${e.code}). No success is assumed.`:e instanceof Error?e.message:'The review change could not be confirmed.');}
  finally{lock.current=false;if(mounted.current)setBusy(false);}
 }
 const form=!record||editing;
 return <section className="s35-review" ref={root} onFocusCapture={e=>{if(trigger.current&&e.target!==trigger.current)trigger.current=null;}}>
  <h2><span className="s35-heading-icon s35-heading-icon--review"><Ic name="star" /></span>{record?'Your review':'Write a review'}</h2>
  {!eligible&&<p role="alert" tabIndex={-1}>Reviewing is locked until attendance is confirmed or resolved. <code>REVIEW_BLOCKED</code></p>}
  {error&&<p role="alert" tabIndex={-1}>{error}</p>}
  {record&&<section data-result tabIndex={-1} aria-label="Server review record"><p>{record.deleted?'Review deleted':record.published?'Published':`Not published · ${record.moderationState??'moderation status not provided'}`}</p><p>{record.rating} of 5 stars</p>{record.body&&<p>{record.body}</p>}{record.editDeadlineAt&&<p>Edit deadline: <time dateTime={record.editDeadlineAt}>{record.editDeadlineAt}</time></p>}{record.deleted&&<p>The deleted record remains associated with this session. A second review cannot be created.</p>}</section>}
  {!record?.deleted&&<>
   {form&&<><fieldset disabled={!eligible||busy}><legend>Rating</legend><div className="s35-rating">{[1,2,3,4,5].map(n=><label key={n}><input type="radio" name="s35-rating" aria-label={`${n} star${n===1?'':'s'}`} checked={rating===n} onChange={()=>setRating(n)}/><Ic name="star" /></label>)}</div></fieldset><label htmlFor="s35-review-body">What was useful? Optional text, 10–1,000 characters.</label><textarea id="s35-review-body" className="tt-in" value={body} onChange={e=>setBody(e.target.value)} maxLength={1000} disabled={!eligible||busy}/><p className="s35-review-help">{body.trim().length} / 1,000 characters</p>{closed&&<p>The edit window has closed or could not be verified. You can still delete your review.</p>}<button className="tt-btn tt-btn--jade" aria-disabled={busy||!eligible||!validation.ok||!!record&&(closed||unchanged)} onClick={e=>void submit(record?'edit':'create',e.currentTarget)}><ReviewActionIcon name="send" />{busy?'Saving review':record?'Save changes':'Submit review'}</button>{editing&&<button className="tt-btn" aria-disabled={busy} onClick={()=>{if(!busy){setEditing(false);setRating(record!.rating);setBody(record!.body??'');}}}><Ic name="back" />Discard changes</button>}</>}
   {record&&!editing&&!confirmDelete&&<><button className="tt-btn" disabled={closed||busy} onClick={()=>setEditing(true)}><Ic name="star" />Edit review</button><button className="tt-btn" aria-disabled={busy} onClick={()=>{if(!busy)setConfirmDelete(true);}}><ReviewActionIcon name="trash" />Delete review</button></>}
   {confirmDelete&&<section aria-label="Delete review confirmation"><h3 className="s35-section-heading"><span className="s35-heading-icon s35-heading-icon--risk"><ReviewActionIcon name="trash" /></span>Delete this review?</h3><p>The server removes it from the public aggregate only after confirming deletion.</p><button className="tt-btn tt-btn--terra" aria-disabled={busy} onClick={e=>void submit('delete',e.currentTarget)}><ReviewActionIcon name="trash" />Confirm delete review</button><button className="tt-btn" aria-disabled={busy} onClick={()=>{if(!busy)setConfirmDelete(false);}}><Ic name="star" />Keep review</button></section>}
  </>}
  {busy&&<p role="status">Waiting for server confirmation.</p>}
  {!record&&<p>Your existing review is not supplied by the session read endpoint. Only a review returned in this signed-in session can be edited here; a duplicate create remains subject to server refusal.</p>}
 </section>;
}

import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Link,useNavigate,useSearchParams} from 'react-router-dom';
import {useAuth,useStudentSession} from '../../../app/authContext';
import {NyayOneRevLLockup} from '../auth/NyayOneRevLIcon';
import {Icon} from '../internships/S20BrowseView';
import {newIdempotencyKey,TutoringApiError} from '../lib/tutoringApi';
import {captureStudentContextFence,isStudentContextFenceCurrent} from '../lib/studentBrowserContext';
import {canonicalMentorId,readMentorDetail,readMentorAvailability,type MentorDetail,type MentorSlot} from './s32Api';
import {createHold,readHold,createOrder,confirmSession,type Hold,type Order,type ConfirmedSession} from './s33Api';
import './S33Booking.css';
type Operation='hold'|'order'|'read'|'session';
class Offline extends Error {}
class SelectionUnavailable extends Error {}
const money=(n:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',minimumFractionDigits:n%100?2:0,maximumFractionDigits:2}).format(n/100);
// Frozen Revision L primitives kept local so other screens' icons do not change.
function BookingIcon({name,size=18}:{name:'card'|'calendar'|'clock'|'check'|'info';size?:number}){
 return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
  {name==='card'?<><rect x="3" y="6" width="18" height="12" rx="2.5" fill="currentColor" opacity=".14"/><rect x="3" y="6" width="18" height="12" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M3 10.5h18" stroke="currentColor" strokeWidth="1.9"/><path d="M7 14.5h4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>
   :name==='calendar'?<><rect x="4" y="5.5" width="16" height="15" rx="2.5" fill="currentColor" opacity=".14"/><rect x="4" y="5.5" width="16" height="15" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M4 10h16M8 3.5v4M16 3.5v4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>
   :name==='check'?<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="m8 12.3 2.7 2.7 5.3-5.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>
   :<><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/>{name==='clock'?<path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>:<path d="M12 11v5M12 8v.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>}</>}
 </svg>;
}
export function S33Booking(){const auth=useAuth(),[sp]=useSearchParams();return <Booking key={`${auth.userId}:${auth.roles.join(',')}:${sp.get('tutor')}:${sp.get('slot')}`}/>;}
function Booking(){
 const auth=useAuth(),session=useStudentSession(),navigate=useNavigate(),[sp]=useSearchParams();
 const tutorId=canonicalMentorId(sp.get('tutor')?.trim()??''),slotId=canonicalMentorId(sp.get('slot')?.trim()??'');
 const authorized=session.phase==='authenticated'&&auth.isAuthenticated&&auth.roles.includes('student');
 const [hold,setHold]=useState<Hold|null>(null),[order,setOrder]=useState<Order|null>(null),[confirmed,setConfirmed]=useState<ConfirmedSession|null>(null),[selection,setSelection]=useState<{mentor:MentorDetail;slot:MentorSlot}|null>(null);
 const [pending,setPending]=useState<Operation|null>(null),[failure,setFailure]=useState<{error:unknown;operation:Operation;at:number}|null>(null),[now,setNow]=useState(Date.now()),[revision,setRevision]=useState(0);
 const keys=useRef({hold:newIdempotencyKey('hold'),order:newIdempotencyKey('order')}),lock=useRef(false),started=useRef(false),mounted=useRef(false),root=useRef<HTMLDivElement>(null),action=useRef<{trigger:HTMLElement|null;handoff:HTMLElement|null;owned:boolean}|null>(null),first=useRef(true);
 const error=failure?.error,api=error instanceof TutoringApiError?error:null;
 const wait=api?.status===429&&Number.isFinite(api.retryAfterSeconds)?Math.max(0,api.retryAfterSeconds!):0;
 const remaining=wait>0?Math.max(0,Math.ceil(((failure?.at??0)+wait*1000-now)/1000)):0;
 const ended=hold?.status==='expired'||hold?.status==='released'||hold?.status==='active'&&hold.expired===true;
 // A genuine hold read's expired flag is authoritative; a skewed device clock
 // must not override it. The order endpoint still enforces expiry on every write.
 const clockZero=hold?.status==='active'&&hold.expired!==false&&hold.expires_at!==null&&Date.parse(hold.expires_at)<=now;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
 // Transfer focus only for the initiating action. Background clock renders and
 // a user who moved elsewhere never regain this action's focus ownership.
 useLayoutEffect(()=>{
  const a=action.current,active=document.activeElement;
  if(a?.owned&&(active===a.trigger||active===a.handoff||active===document.body||active===null)){
   const target=root.current?.querySelector<HTMLElement>('[role="alert"]')??root.current?.querySelector<HTMLElement>('[data-outcome]')??root.current?.querySelector<HTMLElement>('h1');
   if(target){a.handoff=target;target.focus({preventScroll:true});}
  }
  if(!pending)action.current=null;
  if(first.current&&root.current){first.current=false;if(document.activeElement===document.body)root.current.querySelector<HTMLElement>('h1')?.focus({preventScroll:true});}
 },[pending,revision]);
 useEffect(()=>{const moved=(e:FocusEvent)=>{const a=action.current;if(a&&e.target!==a.trigger&&e.target!==a.handoff)a.owned=false;};document.addEventListener('focusin',moved);return()=>document.removeEventListener('focusin',moved);},[]);
 async function run(operation:Operation,trigger:HTMLElement|null=null){
  if(lock.current||!authorized||!slotId||!tutorId||remaining>0)return;
  lock.current=true;const fence=captureStudentContextFence();const current=()=>mounted.current&&isStudentContextFenceCurrent(fence);
  action.current={trigger,handoff:document.activeElement instanceof HTMLElement?document.activeElement:null,owned:trigger!==null||document.activeElement===document.body||document.activeElement===root.current?.querySelector('h1')};
  setPending(operation);setFailure(null);
  try{
   if(!navigator.onLine)throw new Offline();
   if(operation==='hold'){
    let picked=selection;
    if(!picked){
     const mentor=await readMentorDetail(tutorId);if(!current())return;
     let found:MentorSlot|undefined;let offset=0;
     // The public endpoint supports pagination, not slot-id filtering. Search
     // available pages without fabricating a GET-by-slot or trusting URL facts.
     while(!found){
      const page=await readMentorAvailability(tutorId,new URLSearchParams({timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',limit:'100',offset:String(offset)}));if(!current())return;
      if(page.offset!==offset||page.limit!==100)throw new SelectionUnavailable();
      found=page.slots.find(s=>s.slot_id===slotId&&s.status==='available');
      if(found||page.slots.length<page.limit)break;
      offset+=page.limit;if(offset>=10000)throw new SelectionUnavailable();
     }
     if(!found)throw new SelectionUnavailable();picked={mentor,slot:found};setSelection(picked);
    }
    if(!current())return;const result=await createHold(slotId,keys.current.hold);if(current())setHold(result);
   }else if(hold){
    if(operation==='order'){if(ended||clockZero||hold.status!=='active')return;const result=await createOrder(hold,keys.current.order);if(current())setOrder(result);}
    if(operation==='read'){const result=await readHold(hold);if(current())setHold(result);}
    if(operation==='session'){const result=await confirmSession(hold,tutorId,auth.userId!,order?.id);if(current())setConfirmed(result);}
   }
  }catch(e){if(current())setFailure({error:e,operation,at:Date.now()});}
  finally{lock.current=false;if(current()){setPending(null);setRevision(n=>n+1);}}
 }
 useEffect(()=>{if(authorized&&slotId&&tutorId&&!started.current){started.current=true;void run('hold');}},[authorized,slotId,tutorId]); // One attempt per actor + route; retries reuse its keys.
 const back=`/s-32?tutor=${encodeURIComponent(tutorId)}`;
 const button=(name:string,op:Operation,primary=false)=><button type="button" className={`s20-btn${primary?' s20-primary':''}`} data-action={name==='Retry'?'retry':op} aria-disabled={!!pending||remaining>0} aria-busy={pending===op||undefined} onClick={e=>void run(op,e.currentTarget)}><span className="s20-action-icon">{op==='order'?<BookingIcon name="card"/>:<Icon name="refresh" size={18}/>}</span>{name}</button>;
 const choose=<Link className="s20-btn" to={back}><span className="s20-action-icon"><BookingIcon name="calendar"/></span>Choose another time</Link>;
 function errorView(){
  const code=api?.code,unverified=code==='PAYMENT_UNVERIFIED',expired=code==='HOLD_EXPIRED',conflict=code==='SLOT_UNAVAILABLE'||code==='HOLD_CONFLICT',selectionBad=error instanceof SelectionUnavailable,invalid=code==='invalid_response',rate=api?.status===429,mentorMissing=api?.status===404&&!selection,providerUnavailable=code==='PROVIDER_UNAVAILABLE'&&api?.retryable===false,nonretryable=api?.retryable===false&&!unverified&&!expired&&!invalid&&!conflict&&![401,403,422,429].includes(api.status);
  const title=mentorMissing?'This mentor is unavailable.':providerUnavailable?'The payment provider is unavailable.':nonretryable?'This booking request is unavailable.':unverified?'Payment not confirmed yet.':expired?'The hold expired.':conflict?'That time was just taken.':selectionBad?'This time could not be verified.':rate?'Too many attempts in a short time.':api?.status===401?'Your session ended.':api?.status===403?'Booking is not available for this account.':api?.status===422?'Check the booking link.':invalid?'The response could not be verified.':'Could not reach NyayOne.';
  const detail=mentorMissing?'This mentor could not be found or is not publicly available. No hold request was sent.':providerUnavailable?'The server cannot create a payment order with this provider. No payment or confirmed session is assumed.':nonretryable?'The server does not permit retrying this request. Return to the mentor to review the available options.':error instanceof Offline?'No request was sent. Reconnect and retry.':unverified?'The server has not verified a payment for this hold. No confirmed session was returned.':expired?'If you started a payment, check its status before booking again.':selectionBad?'This slot is not in the available list. If you already started booking on this device, a previous hold may still be active until its server deadline. Reloading or going Back does not release it. No new hold request was sent.':rate?(remaining>0?`Wait ${remaining} seconds before retrying.`:'You can retry now.'):conflict?'Choose an available time on the mentor profile.':api?.status===422?'Choose a time again from the mentor profile.':invalid?'No successful booking or payment is assumed. Retry uses the same request key.':'We could not confirm the request outcome. Retrying uses the same request key.';
  return <section className={`s33-notice ${unverified||expired||rate?'s33-warn':'s33-risk'}`} role="alert" tabIndex={-1}>{unverified?<BookingIcon name="info"/>:expired||rate?<BookingIcon name="clock"/>:<Icon name={title==='Could not reach NyayOne.'?'offline':'warning'} size={18}/>}<div><h2>{title}</h2><p>{detail}</p>{api&&api.status>=400&&<div className="s20-code">HTTP {api.status} · <code data-error-code>{api.code}</code></div>}<div className="s20-actions">{mentorMissing?<Link className="s20-btn" to="/s-31">Find a mentor</Link>:nonretryable||selectionBad||conflict||api?.status===422||api?.status===403?choose:unverified?<>{button('Check again','session')}{hold&&button('Check hold','read')}{choose}</>:expired?<>{hold&&button('Check payment','session')}{choose}</>:button(unverified?'Check again':'Retry',failure!.operation)}</div></div></section>;
 }
 const paymentInfo=<p>Payment checkout is currently unavailable here. Creating an order does not prove payment. Use Check payment to ask NyayOne to verify an existing payment and confirm your session.</p>;
 return <div className="v321-internships s33-booking" data-screen="S-33" data-v34-screen="S-33" ref={root}>
  <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Booking</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={()=>navigate('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={()=>navigate('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={()=>navigate('/s-17')}><Icon name="person"/></button></header>
  <div className="s20-layout"><main id="main-content"><Link className="s20-btn s33-back" to={tutorId?back:'/s-31'}><span className="s20-action-icon"><Icon name="back" size={18}/></span>Mentor</Link><h1 tabIndex={-1}><span className="s20-heading-icon"><BookingIcon name="card" size={20}/></span>Hold and pay.</h1>
   {!tutorId||!slotId?<section className="s20-empty" role="alert" tabIndex={-1}><h2>Choose a time first.</h2><Link className="s20-btn s20-primary" to="/s-31">Find a mentor</Link></section>:<>
    {confirmed&&<section className="s33-notice s33-success" role="status" data-outcome tabIndex={-1}><BookingIcon name="check"/><div><h2>Booking confirmed.</h2><p>The server returned your confirmed session after verifying payment.</p></div></section>}
    <section className="s20-card s33-summary" aria-labelledby="s33-summary"><h2 className="s20-eyebrow" id="s33-summary">Your booking</h2><p className="s20-code">{hold?`Hold ${hold.id}`:'Hold not confirmed'} · slot {slotId}{order?` · order ${order.id}`:''}</p><dl><div><dt>Mentor</dt><dd>{selection?.mentor.display_name??'Not yet verified'}</dd></div><div><dt>When</dt><dd>{selection?`${new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:selection.slot.iana_timezone}).format(new Date(selection.slot.start_utc))} · ${selection.slot.iana_timezone}`:'Not yet verified'}</dd></div><div><dt>Length</dt><dd>{selection?`${selection.slot.duration_minutes} min`:'Not yet verified'}</dd></div><div><dt>Amount</dt><dd className="s33-amount">{hold?money(hold.price_paise):'Not yet confirmed'}</dd></div></dl></section>
    {session.phase==='authenticated'&&!auth.roles.includes('student')?<section className="s33-notice s33-risk" role="alert" tabIndex={-1}><div><h2>Booking is not available for this account.</h2><p>A student account is required to book a mentor. No booking request was sent.</p><Link className="s20-btn" to="/s-31">Find a mentor</Link></div></section>:session.phase==='unavailable'?<section className="s33-notice s33-risk" role="alert" tabIndex={-1}><div><h2>Your session could not be checked.</h2><p>No booking request was sent.</p><button className="s20-btn" onClick={()=>window.location.reload()}>Reload</button></div></section>:failure?errorView():null}
    {pending&&<section className="s33-notice" role="status" data-outcome tabIndex={-1}>{pending==='hold'?<BookingIcon name="clock"/>:<Icon name="refresh" size={18}/>}<div><h2>{pending==='hold'?'Holding this time for you.':pending==='order'?'Creating your payment order.':pending==='session'?'Checking your payment.':'Checking the hold.'}</h2><p>{pending==='session'?'Asking the server to confirm the booking.':'Waiting for server confirmation.'}</p></div></section>}
    {!failure&&!pending&&!confirmed&&hold&&(ended?<section className="s33-notice s33-warn" role="alert" tabIndex={-1}><BookingIcon name="clock"/><div><h2>{hold.status==='released'?'The hold was released.':'The hold expired.'}</h2><p>If you started a payment, check it before booking again.</p><div className="s20-actions">{button('Check payment','session')}{choose}</div></div></section>:order?.status==='failed'||order?.status==='expired'?<section className="s33-notice s33-risk" role="alert" tabIndex={-1}><Icon name="warning" size={18}/><div><h2>The payment did not complete.</h2><p>The server reports order status {order.status}. Check the hold before choosing another time.</p><div className="s20-actions">{button('Check hold','read')}{button('Check payment','session')}{choose}</div></div></section>:order||hold.status==='consumed'?<section className="s33-notice" role="status" data-outcome tabIndex={-1}><Icon name="refresh" size={18}/><div><h2>{hold.status==='consumed'||order?.status==='paid'?'Check your confirmed session.':'Waiting for the payment provider.'}</h2>{order&&<p className="s20-code">Order {order.id} · {order.status}</p>}{paymentInfo}<div className="s20-actions">{button('Check payment','session')}</div></div></section>:clockZero?<section className="s33-notice s33-warn" role="status" data-outcome tabIndex={-1}><BookingIcon name="clock"/><div><h2>The hold deadline has passed on this device.</h2><p>Check the server before continuing. Your device clock does not decide payment status.</p><div className="s20-actions">{button('Check hold','read')}{choose}</div></div></section>:<span className="s20-chip s33-held" data-outcome tabIndex={-1}><span className="s33-held-dot" aria-hidden="true"/><span>Held until {new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'medium'}).format(new Date(hold.expires_at!))} · device time</span></span>)}
    {!confirmed&&<section className="s20-card s33-policy"><h2 className="s20-eyebrow" id="s33-policy">Cancellation and rescheduling</h2><p>Cancellation and rescheduling terms are not supplied with this booking response. No refund entitlement is assumed. Leaving this page does not cancel a payment or immediately release a hold.</p></section>}
    {confirmed?<Link className="s20-btn s20-primary" to={`/s-34?session=${encodeURIComponent(confirmed.id)}`}><span className="s20-action-icon"><BookingIcon name="calendar"/></span>View session</Link>:!failure&&hold&&!order&&hold.status==='active'&&!ended&&!clockZero?<div className="s20-actions s33-payment-action">{button('Create payment order','order',true)}</div>:null}
   </>}
  </main><aside aria-label="Payment"><section className="s20-card"><h2 className="s20-eyebrow" id="s33-payment">Payment</h2>{paymentInfo}<p>NyayOne does not collect card numbers, security codes, UPI credentials or payment OTPs on this screen.</p></section></aside></div><footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
 </div>;
}

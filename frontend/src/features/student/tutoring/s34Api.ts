import {studentApiFetch} from '../lib/studentApiClient';
import {TutoringApiError} from '../lib/tutoringApi';
export interface SessionDetail {
 id:string;slot_id:string;tutor_id:string;student_user_id:string;order_id:string|null;
 status:'confirmed'|'pending_provider'|'rescheduled'|'cancelled'|'completed'|'disputed';version:number;
 start_utc:string;end_utc:string;iana_timezone:string;start_local:string;end_local:string;
 attendance_state:'pending'|'recorded'|'confirmed'|'disputed'|'resolved'|null;attendance_version:number|null;
}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const text=(v:unknown):v is string=>typeof v==='string'&&!!v.trim();
const instant=(v:unknown):v is string=>typeof v==='string'&&/(Z|[+-]\d{2}:\d{2})$/i.test(v)&&Number.isFinite(Date.parse(v));
const positive=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>0;
export const canonicalSessionId=(id:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)?id.toLowerCase():id;
function zone(v:unknown):v is string{if(!text(v))return false;try{new Intl.DateTimeFormat('en',{timeZone:v});return true;}catch{return false;}}
// The endpoint contains session/attendance facts, not payment or room authority.
// This adapter is scoped to the existing student route; backend participant access
// and the other tutoring adapters remain unchanged.
export async function readSessionDetail(id:string,actorId:string,signal?:AbortSignal):Promise<SessionDetail>{
 id=canonicalSessionId(id);
 const response=await studentApiFetch(`/api/v1/tutoring/sessions/${encodeURIComponent(id)}`,{method:'GET',signal});
 const v:unknown=await response.json().catch(()=>null);
 if(!response.ok){const d=record(v)&&record(v.detail)?v.detail:{};throw new TutoringApiError(response.status,text(d.code)?d.code:`http_${response.status}`,'',typeof d.retryable==='boolean'?d.retryable:undefined,d);}
 if(!record(v)||v.id!==id||v.student_user_id!==actorId||!text(v.tutor_id)||!text(v.slot_id)||!(v.order_id===null||text(v.order_id))||!positive(v.version)
  ||!['confirmed','pending_provider','rescheduled','cancelled','completed','disputed'].includes(String(v.status))
  ||!instant(v.start_utc)||!instant(v.end_utc)||Date.parse(v.end_utc)<=Date.parse(v.start_utc)||!zone(v.iana_timezone)
  ||!instant(v.start_local)||!instant(v.end_local)||Date.parse(v.start_local)!==Date.parse(v.start_utc)||Date.parse(v.end_local)!==Date.parse(v.end_utc)
  ||!(v.attendance_state===null||['pending','recorded','confirmed','disputed','resolved'].includes(String(v.attendance_state)))
  ||!(v.attendance_version===null||positive(v.attendance_version)))throw new TutoringApiError(response.status,'invalid_response','',false);
 return v as unknown as SessionDetail;
}

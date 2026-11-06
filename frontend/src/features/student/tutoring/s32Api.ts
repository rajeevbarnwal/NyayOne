import {studentApiFetch} from '../lib/studentApiClient';
import {TutoringApiError} from '../lib/tutoringApi';
import type {MentorSummary} from './s31Api';
export interface MentorDetail extends MentorSummary {
 source:string|null;source_url:string|null;retrieved_at:string|null;subjects:{subject:string;level:string}[];
 rating_aggregate:{tutor_id:string;rating_count:number;rating_avg:string|null;distribution:Record<string,number>};
}
export interface MentorSlot {slot_id:string;tutor_id:string;start_utc:string;end_utc:string;iana_timezone:string;status:string;start_local:string;end_local:string;duration_minutes:number;price_paise:number;currency:string}
export interface LocalResolution {requested_local:string;resolved_local:string;instant_utc:string;classification:string;dst_adjusted:boolean}
export interface MentorAvailability {tutor_id:string;iana_timezone:string;window:{from_utc:string|null;to_utc:string|null};local_resolution:Record<string,LocalResolution>;slots:MentorSlot[];limit:number;offset:number}
const rec=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const str=(v:unknown):v is string=>typeof v==='string'&&!!v.trim();
const nullable=(v:unknown)=>v===null||typeof v==='string';
const count=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>=0;
const price=(v:unknown):v is number=>count(v)&&v>0;
// PostgreSQL UUIDs are case-insensitive; keep opaque fixture identities exact.
export const canonicalMentorId=(id:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)?id.toLowerCase():id;
const instant=(v:unknown):v is string=>typeof v==='string'&&/(Z|[+-]\d{2}:\d{2})$/i.test(v)&&Number.isFinite(Date.parse(v));
const currency=(v:unknown):v is string=>typeof v==='string'&&/^[A-Z]{3}$/.test(v);
const rating=(v:unknown)=>v===null||typeof v==='string'&&/^\d+(\.\d+)?$/.test(v)&&Number(v)>=0&&Number(v)<=5;
function zone(v:unknown):v is string {if(!str(v))return false;try{new Intl.DateTimeFormat('en',{timeZone:v});return true;}catch{return false;}}
function invalid():never{throw new TutoringApiError(200,'invalid_response','',false);}
async function get(path:string,signal?:AbortSignal):Promise<unknown>{
 const response=await studentApiFetch(path,{method:'GET',signal}),body:unknown=await response.json().catch(()=>null);
 if(!response.ok){const detail=rec(body)&&rec(body.detail)?body.detail:{};throw new TutoringApiError(response.status,str(detail.code)?detail.code:`http_${response.status}`,'',typeof detail.retryable==='boolean'?detail.retryable:undefined,detail);}return body;
}
export function availabilityQuery(sp:URLSearchParams,deviceZone:string):URLSearchParams {
 const q=new URLSearchParams({timezone:sp.get('tz')||deviceZone});
 for(const key of ['date','from_local','to_local','from_utc','to_utc']){const v=sp.get(key);if(v)q.set(key,v);}
 q.set('limit','50');q.set('offset',sp.get('offset')??'0');return q;
}
export async function readMentorDetail(id:string,signal?:AbortSignal):Promise<MentorDetail>{
 id=canonicalMentorId(id);
 const v=await get(`/api/v1/tutors/${encodeURIComponent(id)}`,signal);
 if(!rec(v)||v.id!==id||!str(v.display_name)||!nullable(v.headline)||!count(v.experience_years)||!count(v.rating_count)||!rating(v.rating_avg)||typeof v.verified_identity!=='boolean'||typeof v.verified_credentials!=='boolean'||!str(v.status)||!price(v.session_price_paise)||!currency(v.currency)||!nullable(v.source)||!nullable(v.source_url)||!(v.retrieved_at===null||instant(v.retrieved_at))||!Array.isArray(v.subjects)||!v.subjects.every(s=>rec(s)&&str(s.subject)&&str(s.level)))invalid();
 const a=v.rating_aggregate;if(!rec(a)||a.tutor_id!==id||!count(a.rating_count)||!rating(a.rating_avg)||!rec(a.distribution)||!Object.entries(a.distribution).every(([k,n])=>/^[1-5]$/.test(k)&&count(n)))invalid();
 return v as unknown as MentorDetail;
}
export async function readMentorAvailability(id:string,q:URLSearchParams,signal?:AbortSignal):Promise<MentorAvailability>{
 id=canonicalMentorId(id);
 const v=await get(`/api/v1/tutors/${encodeURIComponent(id)}/availability?${q}`,signal);
 if(!rec(v)||v.tutor_id!==id||!zone(v.iana_timezone)||!rec(v.window)||![v.window.from_utc,v.window.to_utc].every(x=>x===null||instant(x))||!count(v.limit)||v.limit<1||v.limit>100||!count(v.offset)||!Array.isArray(v.slots)||v.slots.length>v.limit||!rec(v.local_resolution))invalid();
 if(!Object.entries(v.local_resolution).every(([k,r])=>['from_local','to_local'].includes(k)&&rec(r)&&str(r.requested_local)&&str(r.resolved_local)&&instant(r.instant_utc)&&['unique','ambiguous','nonexistent'].includes(String(r.classification))&&typeof r.dst_adjusted==='boolean'))invalid();
 if(!v.slots.every(s=>rec(s)&&str(s.slot_id)&&s.tutor_id===id&&instant(s.start_utc)&&instant(s.end_utc)&&Date.parse(s.end_utc)>Date.parse(s.start_utc)&&zone(s.iana_timezone)&&['available','held','booked','cancelled'].includes(String(s.status))&&instant(s.start_local)&&instant(s.end_local)&&count(s.duration_minutes)&&s.duration_minutes>0&&s.duration_minutes===Math.floor((Date.parse(s.end_utc)-Date.parse(s.start_utc))/60000)&&price(s.price_paise)&&currency(s.currency))||new Set(v.slots.map(s=>s.slot_id)).size!==v.slots.length)invalid();
 return v as unknown as MentorAvailability;
}

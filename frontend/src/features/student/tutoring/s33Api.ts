import {studentApiFetch} from '../lib/studentApiClient';
import {TutoringApiError} from '../lib/tutoringApi';
export interface Hold {id:string;slot_id:string;status:'active'|'consumed'|'expired'|'released';expires_at:string|null;hold_minutes:number;price_paise:number;currency:string;replayed:boolean;expired?:boolean}
export interface Order {id:string;hold_id:string;provider:string;provider_order_ref:string;amount_paise:number;currency:string;status:'created'|'pending'|'paid'|'failed'|'expired';brand:string|null;masked_last4:string|null;replayed:boolean}
export interface ConfirmedSession {id:string;slot_id:string;tutor_id:string;student_user_id:string;order_id:string;status:'confirmed';version:number;start_utc:string;end_utc:string;iana_timezone:string;replayed:boolean}
const rec=(x:unknown):x is Record<string,unknown>=>!!x&&typeof x==='object'&&!Array.isArray(x);
const text=(x:unknown):x is string=>typeof x==='string'&&!!x.trim();
const positive=(x:unknown):x is number=>Number.isSafeInteger(x)&&Number(x)>0;
const instant=(x:unknown):x is string=>typeof x==='string'&&/(Z|[+-]\d{2}:\d{2})$/i.test(x)&&Number.isFinite(Date.parse(x));
function invalid(status:number):never{throw new TutoringApiError(status,'invalid_response','',false);}
async function request(path:string,body?:Record<string,unknown>){
 const response=await studentApiFetch('/api/v1'+path,{method:body?'POST':'GET',...(body?{body:JSON.stringify(body)}:{})});
 const value:unknown=await response.json().catch(()=>null);
 if(!response.ok){const detail=rec(value)&&rec(value.detail)?value.detail:{};throw new TutoringApiError(response.status,text(detail.code)?detail.code:`http_${response.status}`,'',typeof detail.retryable==='boolean'?detail.retryable:undefined,detail);}
 return {value,status:response.status};
}
function holdValue(v:unknown,status:number,slot:string):Hold{
 if(!rec(v)||!text(v.id)||v.slot_id!==slot||!['active','consumed','expired','released'].includes(String(v.status))||!(v.expires_at===null||instant(v.expires_at))||(v.status==='active'&&!instant(v.expires_at))||!positive(v.hold_minutes)||!positive(v.price_paise)||v.currency!=='INR'||typeof v.replayed!=='boolean')invalid(status);
 return v as unknown as Hold;
}
export async function createHold(slot:string,key:string){const r=await request('/tutoring/booking-holds',{slot_id:slot,idempotency_key:key});return holdValue(r.value,r.status,slot);}
export async function readHold(old:Hold){const r=await request(`/tutoring/booking-holds/${encodeURIComponent(old.id)}`),v=holdValue(r.value,r.status,old.slot_id);if(v.id!==old.id||v.price_paise!==old.price_paise||v.currency!==old.currency||typeof v.expired!=='boolean')invalid(r.status);return v;}
export async function createOrder(hold:Hold,key:string):Promise<Order>{
 const r=await request('/payments/orders',{hold_id:hold.id,idempotency_key:key}),v=r.value;
 if(!rec(v)||!text(v.id)||v.hold_id!==hold.id||!text(v.provider)||!text(v.provider_order_ref)||v.amount_paise!==hold.price_paise||v.currency!==hold.currency||!['created','pending','paid','failed','expired'].includes(String(v.status))||!(v.brand===null||text(v.brand))||!(v.masked_last4===null||typeof v.masked_last4==='string'&&/^\d{4}$/.test(v.masked_last4))||typeof v.replayed!=='boolean')invalid(r.status);
 return v as unknown as Order;
}
export async function confirmSession(hold:Hold,tutor:string,actor:string,order?:string):Promise<ConfirmedSession>{
 const r=await request('/tutoring/sessions',{hold_id:hold.id}),v=r.value;
 if(!rec(v)||!text(v.id)||v.slot_id!==hold.slot_id||v.tutor_id!==tutor||v.student_user_id!==actor||!text(v.order_id)||(order!==undefined&&v.order_id!==order)||v.status!=='confirmed'||!positive(v.version)||!instant(v.start_utc)||!instant(v.end_utc)||Date.parse(v.end_utc)<=Date.parse(v.start_utc)||!text(v.iana_timezone)||typeof v.replayed!=='boolean')invalid(r.status);
 try{new Intl.DateTimeFormat('en',{timeZone:v.iana_timezone});}catch{invalid(r.status);}
 return v as unknown as ConfirmedSession;
}

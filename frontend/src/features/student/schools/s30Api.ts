import type { QueryClient } from '@tanstack/react-query';
import { studentApiFetch } from '../lib/studentApiClient';
import { LawSchoolsApiError } from '../lib/lawSchoolsApi';
import { writeSchoolSaved, writeSchoolFollow } from './s28Api';
import type { S27SchoolSummary } from './s27Api';
export type SchoolListKind = 'saved' | 'followed';
export type PrivateSchool = S27SchoolSummary & { notifyOptIn: boolean | null };
const object = (v:unknown):v is Record<string,unknown> => !!v && typeof v==='object' && !Array.isArray(v);
const text=(v:unknown):v is string=>typeof v==='string';
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const invalid=()=>new LawSchoolsApiError(200,'invalid_response');
export async function readPrivateSchools(kind:SchoolListKind,signal?:AbortSignal):Promise<PrivateSchool[]> {
 const response=await studentApiFetch(`/api/v1/student/law-schools/${kind}`,{method:'GET',signal});
 const body:unknown=await response.json().catch(()=>null);
 if(!response.ok)throw new LawSchoolsApiError(response.status,object(body)&&object(body.detail)&&text(body.detail.code)?body.detail.code:`http_${response.status}`);
 if(!object(body)||!Array.isArray(body.items))throw invalid();
 const items=body.items.map(v=>{
  if(!object(v)||!['id','name','slug','state','institution_type'].every(k=>text(v[k])&&(v[k] as string).trim())
   ||!['accreditation','entrance_exam'].every(k=>v[k]===null||text(v[k]))||!['fees_min','fees_max'].every(k=>v[k]===null||integer(v[k]))
   ||(typeof v.fees_min==='number'&&typeof v.fees_max==='number'&&v.fees_min>v.fees_max)
   ||!(v.nirf_rank===null||(integer(v.nirf_rank)&&v.nirf_rank>0))||(kind==='followed'&&typeof v.notify_opt_in!=='boolean'))throw invalid();
  return {id:v.id as string,name:v.name as string,slug:v.slug as string,state:v.state as string,institutionType:v.institution_type as string,accreditation:v.accreditation as string|null,entranceExam:v.entrance_exam as string|null,feesMin:v.fees_min as number|null,feesMax:v.fees_max as number|null,nirfRank:v.nirf_rank as number|null,notifyOptIn:kind==='followed'?v.notify_opt_in as boolean:null};
 });
 if(new Set(items.map(i=>i.id)).size!==items.length)throw invalid();return items;
}
export async function removePrivateSchool(kind:SchoolListKind,id:string):Promise<void> {
 if(kind==='saved')await writeSchoolSaved(id,false);else await writeSchoolFollow(id,false,false);
}
/** Cancel pre-write reads before changing membership; invalidate both legacy and
 * current detail consumers. No private result may cross an actor generation. */
export async function reconcileSchoolRemoval(client:QueryClient,actor:string,kind:SchoolListKind,id:string,confirmed:boolean,current:()=>boolean):Promise<void> {
 if(!current())return;
 const key=[`law-schools-${kind}`,actor],filters=[{queryKey:key},{queryKey:['law-school',id]},{queryKey:['s28-detail',actor,id]}];
 for(const filter of filters)await client.cancelQueries(filter);
 if(!current())return;
 if(confirmed)client.setQueryData<PrivateSchool[]>(key,items=>items?.filter(s=>s.id!==id));
 for(const filter of filters)void client.invalidateQueries({...filter,refetchType:'none'});
}

// S-29-only projection. Existing school/search/detail adapters remain unchanged.
import { studentApiFetch } from '../lib/studentApiClient';
import { inrAmount } from './lawschoolFormat.mjs';
import type { S28Detail } from './s28Api';
export type ComparisonSchool = Omit<S28Detail, 'saved'|'followed'|'notifyOptIn'>;
export interface Comparison { comparisonId: string; compareMax: number; items: ComparisonSchool[] }
export class ComparisonError extends Error {
  constructor(readonly status: number, readonly code: string, readonly extra: Record<string,unknown> = {}) { super(code); }
}
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const text=(v:unknown):v is string=>typeof v==='string';
const nullableText=(v:unknown):v is string|null=>v===null||text(v);
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const invalid=()=>new ComparisonError(200,'invalid_response');
export async function readComparison(ids: string[], signal?: AbortSignal): Promise<Comparison> {
  const response=await studentApiFetch('/api/v1/law-schools/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({school_ids:ids}),signal});
  const v:unknown=await response.json().catch(()=>null);
  if(!response.ok){const detail=object(v)&&object(v.detail)?v.detail:{};const {code,...extra}=detail;throw new ComparisonError(response.status,text(code)?code:`http_${response.status}`,extra);}
  if(!object(v)||!text(v.comparison_id)||!v.comparison_id.trim()||!integer(v.compare_max)||v.compare_max<2||!Array.isArray(v.items)||v.items.length!==ids.length||v.items.length>v.compare_max||new Set(ids).size!==ids.length)throw invalid();
  const items=v.items.map((s,i):ComparisonSchool=>{
    if(!object(s)||s.id!==ids[i]||!['id','name','slug','state','institution_type'].every(k=>text(s[k])&&(s[k] as string).trim())||!['accreditation','entrance_exam'].every(k=>nullableText(s[k]))||!['fees_min','fees_max'].every(k=>s[k]===null||integer(s[k]))||(typeof s.fees_min==='number'&&typeof s.fees_max==='number'&&s.fees_min>s.fees_max)||!(s.nirf_rank===null||(integer(s.nirf_rank)&&s.nirf_rank>0))||!Array.isArray(s.programmes)||!Array.isArray(s.facts))throw invalid();
    const programmes=s.programmes.map(p=>{if(!object(p)||!text(p.degree)||!p.degree.trim()||!integer(p.duration_years)||p.duration_years<1)throw invalid();return {degree:p.degree,durationYears:p.duration_years};});
    const facts=s.facts.map(f=>{if(!object(f)||!text(f.key)||!f.key.trim()||!text(f.value)||!['source_name','source_url','retrieved_at'].every(k=>nullableText(f[k])))throw invalid();return {key:f.key,value:f.value,sourceName:f.source_name as string|null,sourceUrl:f.source_url as string|null,retrievedAt:f.retrieved_at as string|null};});
    if(new Set(facts.map(f=>f.key)).size!==facts.length)throw invalid();
    return {id:s.id as string,name:s.name as string,slug:s.slug as string,state:s.state as string,institutionType:s.institution_type as string,accreditation:s.accreditation as string|null,entranceExam:s.entrance_exam as string|null,feesMin:s.fees_min as number|null,feesMax:s.fees_max as number|null,nirfRank:s.nirf_rank as number|null,programmes,facts};
  });
  return {comparisonId:v.comparison_id,compareMax:v.compare_max,items};
}
export function comparisonIds(value:string|null,tray:readonly {id:string;name?:string}[]):string[]{return [...new Set(value===null?tray.map(s=>s.id):value.split(',').filter(Boolean))];}
export function comparisonDetailPath(id:string,ids:readonly string[]):string{return `/s-28?${new URLSearchParams({id,from:'s29',ids:ids.join(',')})}`;}
export function comparisonValue(s:ComparisonSchool,key:string):string {
  const absent='Not provided';
  switch(key){
    case 'state':return s.state;
    case 'institution_type':return s.institutionType;
    case 'accreditation':return s.accreditation||absent;
    case 'entrance_exam':return s.entranceExam||absent;
    case 'nirf_rank':return s.nirfRank===null?absent:String(s.nirfRank);
    case 'programmes':return s.programmes.length?s.programmes.map(p=>p.degree).join(', '):absent;
    case 'fees':if(s.feesMin===null&&s.feesMax===null)return absent;if(s.feesMin===null)return `Up to ${inrAmount(s.feesMax!)} per year`;if(s.feesMax===null)return `From ${inrAmount(s.feesMin)} per year`;return `${inrAmount(s.feesMin)}${s.feesMin===s.feesMax?'':` to ${inrAmount(s.feesMax)}`} per year`;
    default:return s.facts.find(f=>f.key===key)?.value||absent;
  }
}

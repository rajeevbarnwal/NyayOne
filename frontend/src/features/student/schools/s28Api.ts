// S-28-only wire validation. Legacy S-29/S-30 adapters are unchanged.
import { studentApiFetch } from '../lib/studentApiClient';
import { LawSchoolsApiError, type LawSchoolProgramme } from '../lib/lawSchoolsApi';
import type { S27SchoolSummary } from './s27Api';
export interface S28Detail extends S27SchoolSummary { programmes: LawSchoolProgramme[]; facts: { key: string; value: string; sourceName: string | null; sourceUrl: string | null; retrievedAt: string | null }[]; saved: boolean; followed: boolean; notifyOptIn: boolean | null }
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const nullableText = (v: unknown): v is string | null => v === null || text(v);
const integer = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const invalid = () => new LawSchoolsApiError(200, 'invalid_response');
async function request(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<Record<string, unknown>> {
 const response = await studentApiFetch(path, { method, signal, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
 const result: unknown = await response.json().catch(() => null);
 if (!response.ok) throw new LawSchoolsApiError(response.status, object(result) && object(result.detail) && text(result.detail.code) ? result.detail.code : `http_${response.status}`);
 if (!object(result)) throw invalid(); return result;
}
export async function readSchoolDetail(id: string, signal?: AbortSignal): Promise<S28Detail> {
 const v = await request(`/api/v1/law-schools/${encodeURIComponent(id)}`, 'GET', undefined, signal);
 if (v.id !== id || !['id','name','slug','state','institution_type'].every(k => text(v[k]) && (v[k] as string).trim())
  || !['accreditation','entrance_exam'].every(k => nullableText(v[k])) || !['fees_min','fees_max'].every(k => v[k] === null || integer(v[k]))
  || (typeof v.fees_min === 'number' && typeof v.fees_max === 'number' && v.fees_max < v.fees_min)
  || !(v.nirf_rank === null || (integer(v.nirf_rank) && v.nirf_rank > 0)) || !Array.isArray(v.programmes) || !Array.isArray(v.facts)
  || typeof v.saved !== 'boolean' || typeof v.followed !== 'boolean') throw invalid();
 const programmes = v.programmes.map(p => { if (!object(p) || !text(p.degree) || !p.degree.trim() || !integer(p.duration_years) || p.duration_years < 1) throw invalid(); return { degree:p.degree, durationYears:p.duration_years }; });
 const facts = v.facts.map(f => { if (!object(f) || !text(f.key) || !f.key.trim() || !text(f.value) || !['source_name','source_url','retrieved_at'].every(k => nullableText(f[k]))) throw invalid(); return { key:f.key, value:f.value, sourceName:f.source_name as string|null, sourceUrl:f.source_url as string|null, retrievedAt:f.retrieved_at as string|null }; });
 return { id, name:v.name as string, slug:v.slug as string, state:v.state as string, institutionType:v.institution_type as string,
  accreditation:v.accreditation as string|null, entranceExam:v.entrance_exam as string|null, feesMin:v.fees_min as number|null, feesMax:v.fees_max as number|null, nirfRank:v.nirf_rank as number|null,
  programmes, facts, saved:v.saved, followed:v.followed, notifyOptIn:null };
}
export async function writeSchoolSaved(id:string, saved:boolean): Promise<{saved:boolean}> {
 const v = await request(`/api/v1/student/law-schools/${encodeURIComponent(id)}/saved`, saved ? 'PUT':'DELETE');
 if (v.saved !== saved) throw invalid(); return { saved };
}
export async function writeSchoolFollow(id:string, followed:boolean, notifyOptIn:boolean): Promise<{followed:boolean;notifyOptIn:boolean}> {
 const v = await request(`/api/v1/student/law-schools/${encodeURIComponent(id)}/follow`, followed ? 'PUT':'DELETE', followed ? { notify_opt_in:notifyOptIn }:undefined);
 if (v.followed !== followed || v.notify_opt_in !== (followed && notifyOptIn)) throw invalid();
 return { followed, notifyOptIn: v.notify_opt_in as boolean };
}
export function safeSource(value:string|null): {url:string;host:string}|null {
 if (!value) return null;
 try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) && !url.username && !url.password ? {url:url.href,host:url.host}:null; } catch { return null; }
}
export function schoolReturn(sp:URLSearchParams): {label:string;path:string} {
 const from = sp.get('from');
 if(from === 's30') return {label:'Saved and followed',path:'/s-30'};
 if(from === 's29') { const ids = sp.get('ids'); return {label:'Comparison',path:'/s-29'+(ids ? `?${new URLSearchParams({ids})}`:'')}; }
 const input = new URLSearchParams(sp.get('ret') ?? ''), query = new URLSearchParams();
 for(const key of ['q','state','institution_type','degree','accreditation','entrance_exam','fees_max','sort','page','page_size']) if(input.has(key))query.set(key,input.get(key)!);
 return {label:'Find a law school',path:'/s-27'+(query.size ? `?${query}`:'')};
}

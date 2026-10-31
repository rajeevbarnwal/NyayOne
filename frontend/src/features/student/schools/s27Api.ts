// S-27 only. Detail, comparison and private-list adapters retain their contracts.
import { studentApiFetch } from '../lib/studentApiClient';
import { LawSchoolsApiError, type LawSchoolSearchResult, type LawSchoolSummary } from '../lib/lawSchoolsApi';

// The S-27 summary preserves backend nulls; legacy detail/compare adapters are unchanged.
export type S27SchoolSummary = Omit<LawSchoolSummary, 'accreditation' | 'entranceExam' | 'feesMin' | 'feesMax'> & {
  accreditation: string | null; entranceExam: string | null; feesMin: number | null; feesMax: number | null;
};
export type S27SearchResult = Omit<LawSchoolSearchResult, 'items'> & { items: S27SchoolSummary[] };

const KEYS = ['q', 'state', 'institution_type', 'degree', 'accreditation', 'entrance_exam', 'fees_max', 'sort', 'page', 'page_size'];
export function schoolSearchQuery(input: URLSearchParams): URLSearchParams {
  const query = new URLSearchParams();
  for (const key of KEYS) { const value = input.get(key); if (value) query.set(key, value); }
  for (const [key, value] of [['sort', 'name'], ['page', '1'], ['page_size', '20']]) if (!query.has(key)) query.set(key, value);
  return query;
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const integer = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const invalid = () => new LawSchoolsApiError(200, 'invalid_response');
function summary(value: unknown): S27SchoolSummary {
  if (!object(value) || !['id', 'name', 'slug', 'state', 'institution_type'].every(k => text(value[k]))
    || !['accreditation', 'entrance_exam'].every(k => value[k] === null || text(value[k]))
    || !(value.id as string).trim() || !(value.name as string).trim()
    || !(value.fees_min === null || integer(value.fees_min)) || !(value.fees_max === null || integer(value.fees_max))
    || (value.fees_min !== null && value.fees_max !== null && value.fees_max < value.fees_min) || !(value.nirf_rank === null || (integer(value.nirf_rank) && value.nirf_rank > 0))) throw invalid();
  return { id: value.id as string, name: value.name as string, slug: value.slug as string, state: value.state as string,
    institutionType: value.institution_type as string, accreditation: value.accreditation as string | null, entranceExam: value.entrance_exam as string | null,
    feesMin: value.fees_min, feesMax: value.fees_max, nirfRank: value.nirf_rank as number | null };
}
export async function readSchoolSearch(input: URLSearchParams, signal?: AbortSignal): Promise<S27SearchResult> {
  const query = schoolSearchQuery(input);
  const response = await studentApiFetch(`/api/v1/law-schools?${query}`, { method: 'GET', signal });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const code = object(body) && object(body.detail) && text(body.detail.code) ? body.detail.code : `http_${response.status}`;
    throw new LawSchoolsApiError(response.status, code);
  }
  if (!object(body) || !Array.isArray(body.items) || !integer(body.total) || !integer(body.page) || body.page < 1
    || !integer(body.page_size) || body.page_size < 1 || body.page_size > 50 || !integer(body.compare_max) || body.compare_max < 2
    || body.page !== Number(query.get('page')) || body.page_size !== Number(query.get('page_size'))) throw invalid();
  const items = body.items.map(summary), offset = (body.page - 1) * body.page_size;
  if (new Set(items.map(i => i.id)).size !== items.length || items.length > body.page_size
    || items.length > Math.max(0, body.total - offset) || (!items.length && body.total > offset)) throw invalid();
  return { items, total: body.total, page: body.page, pageSize: body.page_size, compareMax: body.compare_max };
}

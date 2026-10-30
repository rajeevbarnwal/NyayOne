// S-27 only. Detail, comparison and private-list adapters retain their contracts.
import { studentApiFetch } from '../lib/studentApiClient';
import { LawSchoolsApiError, type LawSchoolSearchResult, type LawSchoolSummary } from '../lib/lawSchoolsApi';

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
function summary(value: unknown): LawSchoolSummary {
  if (!object(value) || !['id', 'name', 'slug', 'state', 'institution_type', 'accreditation', 'entrance_exam'].every(k => text(value[k]))
    || !(value.id as string).trim() || !(value.name as string).trim() || !integer(value.fees_min) || !integer(value.fees_max)
    || value.fees_max < value.fees_min || !(value.nirf_rank === null || (integer(value.nirf_rank) && value.nirf_rank > 0))) throw invalid();
  return { id: value.id as string, name: value.name as string, slug: value.slug as string, state: value.state as string,
    institutionType: value.institution_type as string, accreditation: value.accreditation as string, entranceExam: value.entrance_exam as string,
    feesMin: value.fees_min, feesMax: value.fees_max, nirfRank: value.nirf_rank as number | null };
}
export async function readSchoolSearch(input: URLSearchParams, signal?: AbortSignal): Promise<LawSchoolSearchResult> {
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

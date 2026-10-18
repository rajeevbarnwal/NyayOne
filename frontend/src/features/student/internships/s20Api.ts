// S-20 adapter. The legacy detail/saved screens keep their existing adapter.
import { studentApiFetch } from '../lib/studentApiClient';
import { InternshipsApiError } from '../lib/internshipsApi';
import type { InternshipListing, StipendFilter } from '../lib/internships';

export const S20_PAGE_SIZE = 20;
export interface BrowsePage { items: InternshipListing[]; total: number; page: number; pageSize: number }
const invalid = () => new InternshipsApiError(200, 'invalid_response', 'The service returned incomplete data. Reload before trying again.');
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const nullableText = (v: unknown) => v === null || text(v);
const integer = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;

async function request(path: string, method = 'GET', signal?: AbortSignal): Promise<Record<string, unknown>> {
  const response = await studentApiFetch(path, { method, signal });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const code = object(body) && object(body.detail) && text(body.detail.code) ? body.detail.code : `http_${response.status}`;
    throw new InternshipsApiError(response.status, code, 'The internship service could not complete this request.');
  }
  if (!object(body)) throw invalid();
  return body;
}
function listing(v: unknown): InternshipListing {
  if (!object(v) || !['id', 'organisation_id', 'role', 'organisation', 'location', 'application_deadline', 'eligibility', 'description'].every(k => text(v[k]))
    || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(v.id as string) || !(v.role as string).trim() || !(v.organisation as string).trim()
    || !(v.stipend_monthly_paise === null || integer(v.stipend_monthly_paise))
    || !['verified', 'unverified'].includes(v.verification_status as string)
    || !Array.isArray(v.tags) || !v.tags.every(text) || !object(v.source) || !text(v.source.name)
    || !['url', 'retrieved_at', 'verified_at'].every(k => nullableText((v.source as Record<string, unknown>)[k]))) throw invalid();
  const iso = v.application_deadline as string;
  const date = new Date(`${iso}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== iso) throw invalid();
  return { id: v.id as string, organisationId: v.organisation_id as string, role: v.role as string, org: v.organisation as string,
    location: v.location as string, stipendMonthlyPaise: v.stipend_monthly_paise as number | null,
    verificationStatus: v.verification_status as InternshipListing['verificationStatus'],
    deadline: date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }),
    eligibility: v.eligibility as string, description: v.description as string, tags: v.tags as string[],
    source: { name: v.source.name, url: v.source.url as string | null, retrievedAt: v.source.retrieved_at as string | null, verifiedAt: v.source.verified_at as string | null } };
}
function listings(value: unknown): InternshipListing[] {
  if (!Array.isArray(value)) throw invalid();
  const items = value.map(listing);
  if (new Set(items.map(i => i.id)).size !== items.length) throw invalid();
  return items;
}
export async function browseInternships(options: { page: number; verifiedOnly: boolean }, signal?: AbortSignal): Promise<BrowsePage> {
  if (!integer(options.page) || options.page < 1) throw new Error('Invalid catalogue page');
  const query = new URLSearchParams({ page: String(options.page), page_size: String(S20_PAGE_SIZE), verified_only: String(options.verifiedOnly) });
  const wire = await request(`/api/v1/internships?${query}`, 'GET', signal);
  const items = listings(wire.items);
  if (!integer(wire.total) || wire.page !== options.page || wire.page_size !== S20_PAGE_SIZE || items.length > S20_PAGE_SIZE
    || items.length > wire.total || (items.length === 0 && wire.total > (options.page - 1) * S20_PAGE_SIZE)
    || (options.verifiedOnly && items.some(i => i.verificationStatus !== 'verified'))) throw invalid();
  return { items, total: wire.total, page: options.page, pageSize: S20_PAGE_SIZE };
}
export async function readBrowseSaved(signal?: AbortSignal): Promise<InternshipListing[]> {
  return listings((await request('/api/v1/student/internships/saved', 'GET', signal)).items);
}
export async function changeBrowseSaved(id: string, saved: boolean): Promise<boolean> {
  const wire = await request(`/api/v1/student/internships/${encodeURIComponent(id)}/saved`, saved ? 'PUT' : 'DELETE');
  if (wire.listing_id !== id || wire.saved !== saved) throw invalid();
  return wire.saved as boolean;
}
export function filterBrowsePage(items: readonly InternshipListing[], query: string, stipend: StipendFilter): InternshipListing[] {
  const q = query.trim().toLocaleLowerCase('en');
  return items.filter(i => {
    const paid = i.stipendMonthlyPaise !== null && i.stipendMonthlyPaise > 0;
    if ((stipend === 'paid' && !paid) || (stipend === 'unpaid' && paid)) return false;
    const amount = i.stipendMonthlyPaise === null ? '' : String(i.stipendMonthlyPaise / 100);
    return !q || `${i.role} ${i.org} ${i.location} ${amount} ${amount ? Number(amount).toLocaleString('en-IN') : ''}`.toLocaleLowerCase('en').includes(q);
  });
}

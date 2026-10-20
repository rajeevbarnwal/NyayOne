import { studentApiFetch } from '../lib/studentApiClient';
import { InternshipsApiError } from '../lib/internshipsApi';
import type { InternshipListing } from '../lib/internships';

export function validDetailId(id: string) { return id.length <= 64 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id); }
// Match the backend's offset-aware timestamps, including microseconds. Date's
// permissive rollover (e.g. February 30) must not imply verified provenance.
export function validSourceTimestamp(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const parts = /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  if (!parts || !Number.isFinite(Date.parse(value))) return false;
  const day = new Date(`${parts[1]}T00:00:00Z`);
  return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === parts[1];
}
export async function readInternshipDetail(id: string, signal?: AbortSignal): Promise<InternshipListing> {
  if (!validDetailId(id)) throw new InternshipsApiError(422, 'invalid_listing', 'This listing link is incomplete.');
  const response = await studentApiFetch(`/api/v1/internships/${encodeURIComponent(id)}`, { signal });
  const v = await response.json().catch(() => null);
  if (!response.ok) throw new InternshipsApiError(response.status, v?.detail?.code ?? `http_${response.status}`, 'The listing did not load.');
  const invalid = () => new InternshipsApiError(200, 'invalid_response', 'The listing response was incomplete.');
  if (!v || v.id !== id || !['role', 'organisation', 'organisation_id', 'location', 'application_deadline', 'eligibility', 'description'].every(k => typeof v[k] === 'string')
    || !v.role.trim() || !v.organisation.trim() || !['verified', 'unverified'].includes(v.verification_status)
    || !(v.stipend_monthly_paise === null || (Number.isSafeInteger(v.stipend_monthly_paise) && v.stipend_monthly_paise >= 0))
    || !Array.isArray(v.tags) || !v.tags.every((t: unknown) => typeof t === 'string') || !v.source || typeof v.source.name !== 'string'
    || !(v.source.url === null || typeof v.source.url === 'string')
    || !['retrieved_at', 'verified_at'].every(k => v.source[k] === null || validSourceTimestamp(v.source[k]))) throw invalid();
  const date = new Date(`${v.application_deadline}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v.application_deadline) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== v.application_deadline) throw invalid();
  return { id, organisationId: v.organisation_id, role: v.role, org: v.organisation, location: v.location,
    stipendMonthlyPaise: v.stipend_monthly_paise, verificationStatus: v.verification_status,
    deadline: date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }),
    eligibility: v.eligibility, tags: v.tags, description: v.description,
    source: { name: v.source.name, url: v.source.url, retrievedAt: v.source.retrieved_at, verifiedAt: v.source.verified_at } };
}
export function safeSourceUrl(value: string | null): string | null {
  if (!value) return null;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}

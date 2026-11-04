import { studentApiFetch } from '../lib/studentApiClient';
import { TutoringApiError, TUTOR_SORTS } from '../lib/tutoringApi';

export interface MentorSummary {
  id: string; display_name: string; headline: string | null; experience_years: number;
  rating_avg: string | null; rating_count: number; verified_identity: boolean;
  verified_credentials: boolean; status: string; session_price_paise: number; currency: string;
}
export interface MentorPage {
  items: MentorSummary[]; total: number; limit: number; offset: number; has_more: boolean;
  sort: string; allowed_sorts: string[];
}
/** S-31 only: no price/availability filters and no local result re-ranking. */
export function mentorQuery(sp: URLSearchParams): URLSearchParams {
  const q = new URLSearchParams();
  for (const key of ['q', 'subject', 'level', 'min_rating', 'min_experience_years']) {
    const value = sp.get(key)?.trim(); if (value) q.set(key, value);
  }
  const verified = sp.get('verified_only');
  if (verified) q.set('verified_only', verified === '1' ? 'true' : verified);
  for (const [key, fallback] of [['sort', 'rating_desc'], ['limit', '10'], ['offset', '0']]) q.set(key, sp.get(key) ?? fallback);
  return q;
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim();
const count = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
function validTutor(v: unknown): v is MentorSummary {
  return record(v) && text(v.id) && text(v.display_name) && (v.headline === null || typeof v.headline === 'string')
    && count(v.experience_years) && count(v.rating_count)
    && (v.rating_avg === null || typeof v.rating_avg === 'string' && /^\d+(\.\d+)?$/.test(v.rating_avg) && Number(v.rating_avg) >= 0 && Number(v.rating_avg) <= 5)
    && typeof v.verified_identity === 'boolean' && typeof v.verified_credentials === 'boolean' && text(v.status)
    && count(v.session_price_paise) && typeof v.currency === 'string' && /^[A-Z]{3}$/.test(v.currency);
}
export async function readMentors(sp: URLSearchParams, signal?: AbortSignal): Promise<MentorPage> {
  const response = await studentApiFetch(`/api/v1/tutors?${mentorQuery(sp)}`, { method: 'GET', signal });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = record(body) && record(body.detail) ? body.detail : {};
    throw new TutoringApiError(response.status, text(detail.code) ? detail.code : `http_${response.status}`, '',
      typeof detail.retryable === 'boolean' ? detail.retryable : undefined, detail);
  }
  if (!record(body) || !Array.isArray(body.items) || !body.items.every(validTutor)
    || new Set(body.items.map(t => t.id)).size !== body.items.length || !count(body.total)
    || !count(body.limit) || body.limit < 1 || body.limit > 100 || !count(body.offset)
    || body.items.length > body.limit || body.items.length > body.total || typeof body.has_more !== 'boolean'
    || !text(body.sort) || !Array.isArray(body.allowed_sorts) || !body.allowed_sorts.length
    || !body.allowed_sorts.every(s => TUTOR_SORTS.includes(s)) || !body.allowed_sorts.includes(body.sort)) {
    throw new TutoringApiError(response.status, 'invalid_response', '', false);
  }
  return body as unknown as MentorPage;
}

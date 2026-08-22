/**
 * Law-school directory adapter (SAATHI-63 / S-27..S-30): search, detail,
 * compare, save & follow. Same typed-adapter + error-class pattern as
 * registrationApi.ts. Compare limits are server-authoritative (compare_max in
 * responses; typed 422 codes) — the pure selection helpers below mirror the
 * rules so the UI can prevent invalid selections before the request.
 */
import { studentApiFetch } from './studentApiClient';

/** Dev-stub actor claims (see settingsApi.ts) for student-scoped endpoints. */
const DEV_ACTOR_CLAIMS_HEADER = 'X-Actor-Claims';
const DEV_ACTOR_CLAIMS = JSON.stringify({ sub: '00000000-0000-4000-8000-0000000000de', roles: ['student'] });

export interface LawSchoolSummary {
  id: string;
  name: string;
  slug: string;
  state: string;
  institutionType: string;
  accreditation: string;
  entranceExam: string;
  feesMin: number;
  feesMax: number;
  nirfRank: number | null;
}

export interface LawSchoolProgramme {
  degree: string;
  durationYears: number;
}

export interface LawSchoolFact {
  key: string;
  value: string;
  sourceName: string;
  sourceUrl: string;
  retrievedAt: string;
}

export interface LawSchoolDetail extends LawSchoolSummary {
  programmes: LawSchoolProgramme[];
  facts: LawSchoolFact[];
  saved: boolean;
  followed: boolean;
}

export type LawSchoolSort = 'name' | 'fees' | 'nirf_rank';

export interface LawSchoolSearchParams {
  q?: string;
  state?: string;
  institutionType?: string;
  degree?: string;
  accreditation?: string;
  entranceExam?: string;
  feesMax?: number;
  sort?: LawSchoolSort;
  page?: number;
  pageSize?: number;
}

export interface LawSchoolSearchResult {
  items: LawSchoolSummary[];
  total: number;
  page: number;
  pageSize: number;
  compareMax: number;
}

export interface LawSchoolCompareItem extends LawSchoolSummary {
  programmes: LawSchoolProgramme[];
  facts: LawSchoolFact[];
}

export interface LawSchoolCompareResult {
  compareMax: number;
  items: LawSchoolCompareItem[];
}

export interface FollowState {
  followed: boolean;
  notifyOptIn: boolean;
}

/** Typed error codes surfaced by the compare endpoint. */
export const COMPARE_LIMIT_EXCEEDED = 'COMPARE_LIMIT_EXCEEDED';
export const COMPARE_MIN_NOT_MET = 'COMPARE_MIN_NOT_MET';
export const DUPLICATE_SCHOOL = 'DUPLICATE_SCHOOL';
export const SCHOOL_NOT_FOUND = 'school_not_found';

export class LawSchoolsApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly maxAllowed?: number,
    readonly minRequired?: number,
  ) {
    super(code);
  }
}

/**
 * Retry predicate for law-school queries (SAATHI-118/120 F4). Typed 4xx
 * responses (422 unsupported_* / 404 school_not_found / 401 ...) are
 * deterministic server verdicts — retrying re-issues an identical request and
 * doubles the observable error, so they must never be retried. Network
 * failures (TypeError) and 5xx remain retryable (React Query default cap of
 * one retry is applied at the call site: `failureCount < 1`).
 */
export function isRetryableLawSchoolsError(error: unknown): boolean {
  return !(error instanceof LawSchoolsApiError && error.status >= 400 && error.status < 500);
}

async function jsonRequest<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  if (!headers.has(DEV_ACTOR_CLAIMS_HEADER)) {
    headers.set(DEV_ACTOR_CLAIMS_HEADER, DEV_ACTOR_CLAIMS);
  }
  const response = await studentApiFetch(path, { ...init, headers });
  const body = (await response.json().catch(() => ({}))) as {
    detail?: {
      code?: string;
      max_allowed?: number;
      min_required?: number;
    } | string;
  } & T;
  if (!response.ok) {
    const detail = typeof body.detail === 'object' ? body.detail : undefined;
    throw new LawSchoolsApiError(
      response.status,
      detail?.code ?? `http_${response.status}`,
      detail?.max_allowed,
      detail?.min_required,
    );
  }
  return body;
}

/* ------------------------------- wire shapes ------------------------------ */

interface SummaryWire {
  id: string;
  name: string;
  slug: string;
  state: string;
  institution_type: string;
  accreditation: string;
  entrance_exam: string;
  fees_min: number;
  fees_max: number;
  nirf_rank: number | null;
}

interface ProgrammeWire {
  degree: string;
  duration_years: number;
}

interface FactWire {
  key: string;
  value: string;
  source_name: string;
  source_url: string;
  retrieved_at: string;
}

function mapSummary(wire: SummaryWire): LawSchoolSummary {
  return {
    id: wire.id,
    name: wire.name,
    slug: wire.slug,
    state: wire.state,
    institutionType: wire.institution_type,
    accreditation: wire.accreditation,
    entranceExam: wire.entrance_exam,
    feesMin: wire.fees_min,
    feesMax: wire.fees_max,
    nirfRank: wire.nirf_rank,
  };
}

function mapProgrammes(wires: ProgrammeWire[] | undefined): LawSchoolProgramme[] {
  return (wires ?? []).map((p) => ({ degree: p.degree, durationYears: p.duration_years }));
}

function mapFacts(wires: FactWire[] | undefined): LawSchoolFact[] {
  return (wires ?? []).map((f) => ({
    key: f.key,
    value: f.value,
    sourceName: f.source_name,
    sourceUrl: f.source_url,
    retrievedAt: f.retrieved_at,
  }));
}

/* --------------------------------- search --------------------------------- */

export function buildSearchQuery(params: LawSchoolSearchParams): string {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.state) qs.set('state', params.state);
  if (params.institutionType) qs.set('institution_type', params.institutionType);
  if (params.degree) qs.set('degree', params.degree);
  if (params.accreditation) qs.set('accreditation', params.accreditation);
  if (params.entranceExam) qs.set('entrance_exam', params.entranceExam);
  if (params.feesMax !== undefined) qs.set('fees_max', String(params.feesMax));
  if (params.sort) qs.set('sort', params.sort);
  qs.set('page', String(params.page ?? 1));
  qs.set('page_size', String(params.pageSize ?? 20));
  return qs.toString();
}

export async function searchLawSchools(
  params: LawSchoolSearchParams = {},
): Promise<LawSchoolSearchResult> {
  const wire = await jsonRequest<{
    items: SummaryWire[];
    total: number;
    page: number;
    page_size: number;
    compare_max: number;
  }>(`/api/v1/law-schools?${buildSearchQuery(params)}`, { method: 'GET' });
  return {
    items: wire.items.map(mapSummary),
    total: wire.total,
    page: wire.page,
    pageSize: wire.page_size,
    compareMax: wire.compare_max,
  };
}

/* --------------------------------- detail --------------------------------- */

export async function getLawSchoolDetail(id: string): Promise<LawSchoolDetail> {
  const wire = await jsonRequest<SummaryWire & {
    programmes: ProgrammeWire[];
    facts: FactWire[];
    saved: boolean;
    followed: boolean;
  }>(`/api/v1/law-schools/${encodeURIComponent(id)}`, { method: 'GET' });
  return {
    ...mapSummary(wire),
    programmes: mapProgrammes(wire.programmes),
    facts: mapFacts(wire.facts),
    saved: wire.saved,
    followed: wire.followed,
  };
}

/* --------------------------------- compare -------------------------------- */

export async function compareLawSchools(schoolIds: string[]): Promise<LawSchoolCompareResult> {
  const wire = await jsonRequest<{
    compare_max: number;
    items: Array<SummaryWire & { programmes?: ProgrammeWire[]; facts?: FactWire[] }>;
  }>('/api/v1/law-schools/compare', {
    method: 'POST',
    body: JSON.stringify({ school_ids: schoolIds }),
  });
  return {
    compareMax: wire.compare_max,
    items: wire.items.map((item) => ({
      ...mapSummary(item),
      programmes: mapProgrammes(item.programmes),
      facts: mapFacts(item.facts),
    })),
  };
}

/* ------------------------------ save & follow ------------------------------ */

export async function saveLawSchool(id: string): Promise<{ saved: boolean }> {
  return jsonRequest<{ saved: boolean }>(
    `/api/v1/student/law-schools/${encodeURIComponent(id)}/saved`,
    { method: 'PUT' },
  );
}

export async function unsaveLawSchool(id: string): Promise<{ saved: boolean }> {
  return jsonRequest<{ saved: boolean }>(
    `/api/v1/student/law-schools/${encodeURIComponent(id)}/saved`,
    { method: 'DELETE' },
  );
}

export async function followLawSchool(
  id: string,
  notifyOptIn?: boolean,
): Promise<FollowState> {
  const wire = await jsonRequest<{ followed: boolean; notify_opt_in: boolean }>(
    `/api/v1/student/law-schools/${encodeURIComponent(id)}/follow`,
    {
      method: 'PUT',
      body: JSON.stringify(
        notifyOptIn === undefined ? {} : { notify_opt_in: notifyOptIn },
      ),
    },
  );
  return { followed: wire.followed, notifyOptIn: wire.notify_opt_in };
}

export async function unfollowLawSchool(id: string): Promise<FollowState> {
  const wire = await jsonRequest<{ followed: boolean; notify_opt_in: boolean }>(
    `/api/v1/student/law-schools/${encodeURIComponent(id)}/follow`,
    { method: 'DELETE' },
  );
  return { followed: wire.followed, notifyOptIn: wire.notify_opt_in };
}

/**
 * Saved / followed list endpoints for S-30.
 * ASSUMED CONTRACT (not in the fixed SAATHI-63 endpoint list, which only fixes
 * PUT/DELETE per-school): GET /api/v1/student/law-schools/saved and
 * GET /api/v1/student/law-schools/followed each return { items: [...] } of
 * LawSchoolSummary (followed items additionally carry notify_opt_in).
 */
export async function listSavedLawSchools(): Promise<LawSchoolSummary[]> {
  const wire = await jsonRequest<{ items: SummaryWire[] }>(
    '/api/v1/student/law-schools/saved',
    { method: 'GET' },
  );
  return wire.items.map(mapSummary);
}

export interface FollowedLawSchool extends LawSchoolSummary {
  notifyOptIn: boolean;
}

export async function listFollowedLawSchools(): Promise<FollowedLawSchool[]> {
  const wire = await jsonRequest<{ items: Array<SummaryWire & { notify_opt_in: boolean }> }>(
    '/api/v1/student/law-schools/followed',
    { method: 'GET' },
  );
  return wire.items.map((item) => ({ ...mapSummary(item), notifyOptIn: item.notify_opt_in }));
}

/* ----------------------- pure compare-selection rules ---------------------- */
/* UI-side mirror of the server rules: min 2, max = server compare_max        */
/* (default 4), no duplicates. The backend stays authoritative.               */

export const COMPARE_MIN = 2;
export const DEFAULT_COMPARE_MAX = 4;

export type CompareSelectionResult =
  | { ok: true; selection: string[] }
  | { ok: false; reason: 'duplicate' | 'limit_reached'; maxAllowed: number };

/** Add a school to the compare tray, enforcing duplicate + limit rules. */
export function addToCompareSelection(
  selection: readonly string[],
  id: string,
  compareMax: number = DEFAULT_COMPARE_MAX,
): CompareSelectionResult {
  if (selection.includes(id)) {
    return { ok: false, reason: 'duplicate', maxAllowed: compareMax };
  }
  if (selection.length >= compareMax) {
    return { ok: false, reason: 'limit_reached', maxAllowed: compareMax };
  }
  return { ok: true, selection: [...selection, id] };
}

export function removeFromCompareSelection(
  selection: readonly string[],
  id: string,
): string[] {
  return selection.filter((s) => s !== id);
}

export interface CompareSelectionState {
  /** True when the selection satisfies the minimum of COMPARE_MIN schools. */
  canCompare: boolean;
  /** How many more schools are needed to reach the minimum. */
  missingForMin: number;
  /** True when the selection has reached the effective server limit. */
  atLimit: boolean;
}

export function compareSelectionState(
  selection: readonly string[],
  compareMax: number = DEFAULT_COMPARE_MAX,
): CompareSelectionState {
  return {
    canCompare: selection.length >= COMPARE_MIN && selection.length <= compareMax,
    missingForMin: Math.max(0, COMPARE_MIN - selection.length),
    atLimit: selection.length >= compareMax,
  };
}

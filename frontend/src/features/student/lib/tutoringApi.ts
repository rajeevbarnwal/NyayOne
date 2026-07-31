/**
 * Wave 2 tutoring adapter (SAATHI-65 / SAATHI-66, P4) — S-31 … S-35.
 *
 * Binds to the routes committed in P3 (`backend/app/api/v1/tutoring.py`) mounted
 * under `/api/v1`. Same typed-adapter shape as `registrationApi.ts` /
 * `lawSchoolsApi.ts`: one `jsonRequest`, one error class carrying the STABLE
 * machine code, one retry predicate. There is no second HTTP layer and no
 * component issues a fetch of its own.
 *
 * Error envelope (frozen by P3's `_typed`):
 *   `{"detail": {"code", "message", "retryable", ...extra}}` at the domain
 *   error's own status. `retryable` is part of the contract, so the predicate
 *   below honours it instead of guessing from the status alone.
 *
 * Privacy (matrix J1 / D-05). This module:
 *   * never sends a PAN, CVV, expiry or payment OTP — the only payment secret
 *     the surface may carry is a provider TOKEN matching `tok_[A-Za-z0-9_]{3,60}`,
 *     which is validated here, forwarded once and never retained;
 *   * never writes ANY value to localStorage, sessionStorage, a cookie or the
 *     URL — there is not one storage call in this file;
 *   * returns the raw join credential inside a value the caller must keep in
 *     component memory only. `redactJoinCredential` exists so any diagnostic
 *     rendering of that object cannot leak the token.
 */
import { apiFetch, newRequestId } from '../../../lib/apiClient';

/**
 * Dev-stub actor claims (backend auth contract: `X-Actor-Claims` JSON header).
 * Identical convention to settingsApi.ts / lawSchoolsApi.ts — the student
 * surfaces have no real login token yet. Replaced by real auth middleware in a
 * later ticket; a caller may override the header per request.
 */
export const DEV_ACTOR_CLAIMS_HEADER = 'X-Actor-Claims';
const DEV_ACTOR_CLAIMS = JSON.stringify({
  sub: '00000000-0000-4000-8000-0000000000de',
  roles: ['student'],
});

/**
 * The AUTHORISED actor a mentor-side call is made as.
 *
 * `role` is deliberately narrowed to the two roles the server's
 * `attendance.RECORDER_ROLES` accepts. There is no `'student'` member, so a
 * student screen cannot construct one of these, and every call below that
 * demands a `TutoringActor` is therefore unreachable from the student surface —
 * the authority rule is expressed in the type system, not in a runtime flag a
 * screen could forget. The subject is the opaque signed-in id supplied by the
 * mentor surface's own guard (see `features/mentor/lib/mentorAuth.ts`); the
 * server re-checks role AND ownership on every call and remains authoritative.
 */
export interface TutoringActor {
  /** Opaque subject id of the signed-in mentor/administrator. */
  readonly userId: string;
  readonly role: 'tutor' | 'admin';
}

/** The dev-stub claims header for an authorised mentor/admin call. */
export function actorClaimsHeaders(actor: TutoringActor): Record<string, string> {
  return {
    [DEV_ACTOR_CLAIMS_HEADER]: JSON.stringify({
      sub: actor.userId,
      roles: [actor.role],
    }),
  };
}

/* ========================================================================== *
 * Typed error codes — copied from backend/app/services/tutoring/errors.py.
 * These are contract. A screen branches on the code, never on the message.
 * ========================================================================== */

export const SLOT_UNAVAILABLE = 'SLOT_UNAVAILABLE';
export const HOLD_EXPIRED = 'HOLD_EXPIRED';
export const HOLD_CONFLICT = 'HOLD_CONFLICT';
export const PAYMENT_UNVERIFIED = 'PAYMENT_UNVERIFIED';
export const AMOUNT_MISMATCH = 'AMOUNT_MISMATCH';
/** The client proposed an amount that is not the server's published price. */
export const PAYMENT_AMOUNT_MISMATCH = 'PAYMENT_AMOUNT_MISMATCH';
export const SESSION_PRICE_INVALID = 'SESSION_PRICE_INVALID';
export const DUPLICATE_EVENT = 'DUPLICATE_EVENT';
export const REFUND_DUPLICATE = 'REFUND_DUPLICATE';
export const REFUND_NOT_ALLOWED = 'REFUND_NOT_ALLOWED';
export const IDEMPOTENCY_KEY_REUSE = 'IDEMPOTENCY_KEY_REUSE';
export const SESSION_STATE_INVALID = 'SESSION_STATE_INVALID';
export const SESSION_NOT_ENDED = 'SESSION_NOT_ENDED';
export const SESSION_STALE_VERSION = 'SESSION_STALE_VERSION';
export const RESCHEDULE_WINDOW_CLOSED = 'RESCHEDULE_WINDOW_CLOSED';
export const ATTENDANCE_TOO_EARLY = 'ATTENDANCE_TOO_EARLY';
export const ATTENDANCE_STALE_VERSION = 'ATTENDANCE_STALE_VERSION';
export const ATTENDANCE_STATE_INVALID = 'ATTENDANCE_STATE_INVALID';
export const REVIEW_BLOCKED = 'REVIEW_BLOCKED';
export const REVIEW_DUPLICATE = 'REVIEW_DUPLICATE';
export const REVIEW_EDIT_WINDOW_CLOSED = 'REVIEW_EDIT_WINDOW_CLOSED';
export const REVIEW_NOT_MODERATABLE = 'REVIEW_NOT_MODERATABLE';
export const GRANT_EXPIRED = 'GRANT_EXPIRED';
export const GRANT_REVOKED = 'GRANT_REVOKED';
export const PROVIDER_UNAVAILABLE = 'PROVIDER_UNAVAILABLE';
export const ADMIN_EXCEPTION_UNAUTHORISED = 'ADMIN_EXCEPTION_UNAUTHORISED';
export const NOT_FOUND = 'NOT_FOUND';
export const FORBIDDEN = 'FORBIDDEN';
export const VALIDATION_ERROR = 'VALIDATION_ERROR';
/** P3 boundary codes that are not `TutoringError` subclasses. */
export const RATE_LIMIT_EXCEEDED = 'rate_limit_exceeded';
export const AUTHENTICATION_REQUIRED = 'authentication_required';
export const HTTP_FORBIDDEN = 'forbidden';

/** Every code a Wave 2 tutoring screen may have to render. */
export const TUTORING_ERROR_CODES = [
  SLOT_UNAVAILABLE, HOLD_EXPIRED, HOLD_CONFLICT, PAYMENT_UNVERIFIED, AMOUNT_MISMATCH,
  PAYMENT_AMOUNT_MISMATCH, SESSION_PRICE_INVALID,
  DUPLICATE_EVENT, REFUND_DUPLICATE, REFUND_NOT_ALLOWED, IDEMPOTENCY_KEY_REUSE,
  SESSION_STATE_INVALID, SESSION_NOT_ENDED, SESSION_STALE_VERSION, RESCHEDULE_WINDOW_CLOSED,
  ATTENDANCE_TOO_EARLY, ATTENDANCE_STALE_VERSION, ATTENDANCE_STATE_INVALID,
  REVIEW_BLOCKED, REVIEW_DUPLICATE, REVIEW_EDIT_WINDOW_CLOSED, REVIEW_NOT_MODERATABLE,
  GRANT_EXPIRED, GRANT_REVOKED, PROVIDER_UNAVAILABLE, ADMIN_EXCEPTION_UNAUTHORISED,
  NOT_FOUND, FORBIDDEN, VALIDATION_ERROR, RATE_LIMIT_EXCEEDED, AUTHENTICATION_REQUIRED,
  HTTP_FORBIDDEN,
] as const;

/* ========================================================================== *
 * Error class
 * ========================================================================== */

export class TutoringApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    /** Server message. Safe to log: P3 guarantees ids/codes/counts only. */
    readonly serverMessage: string,
    /**
     * The contract's own retry hint. `undefined` when the envelope omitted it
     * (a boundary error such as 429 or a FastAPI 422 shape).
     */
    readonly retryable: boolean | undefined,
    /** Remaining typed detail keys: `field`, `hours_before_start`, `limit`, … */
    readonly extra: Readonly<Record<string, unknown>> = {},
  ) {
    super(code);
    this.name = 'TutoringApiError';
  }

  /** `detail.field` when the refusal names one (VALIDATION_ERROR). */
  get field(): string | undefined {
    return typeof this.extra.field === 'string' ? this.extra.field : undefined;
  }

  /** 429 `retry_after_seconds`. */
  get retryAfterSeconds(): number | undefined {
    const value = this.extra.retry_after_seconds;
    return typeof value === 'number' ? value : undefined;
  }

  /** The policy window the server applied, when it reported one. */
  get policyWindowHours(): number | undefined {
    const value = this.extra.policy_window_hours;
    return typeof value === 'number' ? value : undefined;
  }
}

/**
 * Retry predicate for every tutoring query and mutation.
 *
 * A 4xx is a DETERMINISTIC verdict: an expired hold, a lost slot race, a
 * refused review, a closed reschedule window. Re-issuing the identical request
 * cannot change the answer and only doubles the observable error, so 4xx is
 * never retried — 429 included, because the limiter's window has not moved.
 * A 5xx and a transport failure (`TypeError` from fetch) stay retryable, and an
 * explicit `retryable: false` on a 5xx (a non-retryable PROVIDER_UNAVAILABLE)
 * is honoured over the status.
 */
export function isRetryableTutoringError(error: unknown): boolean {
  if (!(error instanceof TutoringApiError)) return true;
  if (error.status >= 400 && error.status < 500) return false;
  if (error.retryable === false) return false;
  return true;
}

/** React Query `retry` for tutoring calls: at most one retry, 4xx never. */
export const tutoringRetry = (failureCount: number, error: unknown): boolean =>
  isRetryableTutoringError(error) && failureCount < 1;

/* ========================================================================== *
 * Transport
 * ========================================================================== */

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
  retryable?: unknown;
  [key: string]: unknown;
}

function parseErrorBody(status: number, body: unknown): TutoringApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    // FastAPI request-shape rejection. `extra="forbid"` lands here, which is
    // how a PAN/CVV/OTP field would be refused — the loc is kept, never a value
    // (the backend already strips `input` from validation errors).
    const first = detail[0] as { loc?: unknown[]; msg?: unknown } | undefined;
    const loc = Array.isArray(first?.loc) ? first?.loc : [];
    const field = loc.length ? String(loc[loc.length - 1]) : undefined;
    return new TutoringApiError(
      status,
      VALIDATION_ERROR,
      typeof first?.msg === 'string' ? first.msg : 'request shape rejected',
      false,
      field ? { field } : {},
    );
  }
  if (detail && typeof detail === 'object') {
    const { code, message, retryable, ...rest } = detail as ErrorDetail;
    return new TutoringApiError(
      status,
      typeof code === 'string' ? code : `http_${status}`,
      typeof message === 'string' ? message : `http_${status}`,
      typeof retryable === 'boolean' ? retryable : undefined,
      rest,
    );
  }
  return new TutoringApiError(
    status,
    typeof detail === 'string' && detail ? detail : `http_${status}`,
    `http_${status}`,
    undefined,
  );
}

interface RequestOptions extends RequestInit {
  /** Sent as `Idempotency-Key` alongside the body key where P3 accepts one. */
  idempotencyKey?: string;
}

async function jsonRequest<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { idempotencyKey, ...rest } = init;
  const headers = new Headers(rest.headers);
  headers.set('Content-Type', 'application/json');
  if (!headers.has(DEV_ACTOR_CLAIMS_HEADER)) {
    headers.set(DEV_ACTOR_CLAIMS_HEADER, DEV_ACTOR_CLAIMS);
  }
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey);
  const response = await apiFetch(path, { ...rest, headers });
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) throw parseErrorBody(response.status, body);
  return body as T;
}

/**
 * A fresh idempotency key. Reused deliberately across retries of the SAME
 * logical booking or payment so a repeat submit replays instead of charging
 * twice; a new booking attempt asks for a new key.
 */
export function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${newRequestId()}`;
}

/* ========================================================================== *
 * A1/A2/A3 — discovery (GET /tutors, /tutors/{id}, /tutors/{id}/availability)
 * ========================================================================== */

/** `availability.SORTS`. The response also echoes `allowed_sorts`. */
export const TUTOR_SORTS = [
  'rating_desc', 'rating_asc', 'experience_desc', 'experience_asc', 'name_asc', 'newest',
] as const;
export type TutorSort = (typeof TUTOR_SORTS)[number];

export interface TutorSummary {
  id: string;
  displayName: string;
  headline: string | null;
  experienceYears: number;
  /** Server-computed average as a STRING (Numeric(3,2)); never re-averaged here. */
  ratingAvg: string | null;
  ratingCount: number;
  verifiedIdentity: boolean;
  verifiedCredentials: boolean;
  status: string;
  /**
   * The SERVER's published price for one session with this tutor, in INTEGER
   * PAISE. This — never a build-time env var — is what a screen renders, and it
   * is read-only: no request this module makes can set or influence it.
   */
  sessionPricePaise: number;
  currency: string;
}

export interface TutorSubject {
  subject: string;
  level: string;
}

export interface RatingAggregate {
  tutorId: string;
  ratingCount: number;
  ratingAvg: string | null;
  /** Published-only distribution keyed "1".."5". */
  distribution: Record<string, number>;
}

export interface TutorDetail extends TutorSummary {
  /** Provenance (A2): where the claim came from and when it was pulled. */
  source: string;
  sourceUrl: string | null;
  retrievedAt: string | null;
  subjects: TutorSubject[];
  ratingAggregate: RatingAggregate;
}

export interface TutorSearchParams {
  q?: string;
  subject?: string;
  level?: string;
  minRating?: number;
  minExperienceYears?: number;
  verifiedOnly?: boolean;
  sort?: TutorSort;
  limit?: number;
  offset?: number;
}

export interface TutorSearchResult {
  items: TutorSummary[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
  sort: string;
  allowedSorts: string[];
}

interface TutorSummaryWire {
  id: string;
  display_name: string;
  headline: string | null;
  experience_years: number;
  rating_avg: string | null;
  rating_count: number;
  verified_identity: boolean;
  verified_credentials: boolean;
  status: string;
  session_price_paise: number;
  currency: string;
}

interface AggregateWire {
  tutor_id: string;
  rating_count: number;
  rating_avg: string | null;
  distribution: Record<string, number>;
}

function mapTutorSummary(wire: TutorSummaryWire): TutorSummary {
  return {
    id: wire.id,
    displayName: wire.display_name,
    headline: wire.headline,
    experienceYears: wire.experience_years,
    ratingAvg: wire.rating_avg,
    ratingCount: wire.rating_count,
    verifiedIdentity: wire.verified_identity,
    verifiedCredentials: wire.verified_credentials,
    status: wire.status,
    // Integer paise, never divided or re-rounded here.
    sessionPricePaise: wire.session_price_paise ?? 0,
    currency: wire.currency ?? 'INR',
  };
}

function mapAggregate(wire: AggregateWire | undefined, tutorId: string): RatingAggregate {
  return {
    tutorId: wire?.tutor_id ?? tutorId,
    ratingCount: wire?.rating_count ?? 0,
    ratingAvg: wire?.rating_avg ?? null,
    distribution: wire?.distribution ?? {},
  };
}

export function buildTutorSearchQuery(params: TutorSearchParams): string {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.subject) qs.set('subject', params.subject);
  if (params.level) qs.set('level', params.level);
  if (params.minRating !== undefined) qs.set('min_rating', String(params.minRating));
  if (params.minExperienceYears !== undefined) {
    qs.set('min_experience_years', String(params.minExperienceYears));
  }
  if (params.verifiedOnly) qs.set('verified_only', 'true');
  qs.set('sort', params.sort ?? 'rating_desc');
  qs.set('limit', String(params.limit ?? 20));
  qs.set('offset', String(params.offset ?? 0));
  return qs.toString();
}

export async function searchTutors(
  params: TutorSearchParams = {},
): Promise<TutorSearchResult> {
  const wire = await jsonRequest<{
    items: TutorSummaryWire[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
    sort: string;
    allowed_sorts: string[];
  }>(`/api/v1/tutors?${buildTutorSearchQuery(params)}`, { method: 'GET' });
  return {
    items: (wire.items ?? []).map(mapTutorSummary),
    total: wire.total,
    limit: wire.limit,
    offset: wire.offset,
    hasMore: wire.has_more,
    sort: wire.sort,
    allowedSorts: wire.allowed_sorts ?? [],
  };
}

export async function getTutor(tutorId: string): Promise<TutorDetail> {
  const wire = await jsonRequest<TutorSummaryWire & {
    source: string;
    source_url: string | null;
    retrieved_at: string | null;
    subjects: TutorSubject[];
    rating_aggregate: AggregateWire;
  }>(`/api/v1/tutors/${encodeURIComponent(tutorId)}`, { method: 'GET' });
  return {
    ...mapTutorSummary(wire),
    source: wire.source,
    sourceUrl: wire.source_url,
    retrievedAt: wire.retrieved_at,
    subjects: wire.subjects ?? [],
    ratingAggregate: mapAggregate(wire.rating_aggregate, wire.id),
  };
}

export type SlotStatus = 'available' | 'held' | 'booked' | string;

export interface AvailabilitySlot {
  slotId: string;
  tutorId: string;
  startUtc: string;
  endUtc: string;
  /** The slot's RETAINED IANA zone (or the requested display zone). */
  ianaTimezone: string;
  status: SlotStatus;
  startLocal: string;
  endLocal: string;
  durationMinutes: number;
  /** The server's price for booking this slot, in INTEGER PAISE. Read-only. */
  pricePaise: number;
  currency: string;
}

/** A3: the DST verdict the server applied to a naive local window bound. */
export interface LocalResolution {
  requestedLocal: string;
  resolvedLocal: string;
  instantUtc: string;
  classification: 'unique' | 'ambiguous' | 'nonexistent' | string;
  dstAdjusted: boolean;
}

export interface AvailabilityResult {
  tutorId: string;
  ianaTimezone: string;
  window: { fromUtc: string | null; toUtc: string | null };
  /** Present only for the bounds given as local wall times. */
  localResolution: Partial<Record<'from_local' | 'to_local', LocalResolution>>;
  slots: AvailabilitySlot[];
  limit: number;
  offset: number;
}

interface SlotWire {
  slot_id: string;
  tutor_id: string;
  start_utc: string;
  end_utc: string;
  iana_timezone: string;
  status: string;
  start_local: string;
  end_local: string;
  duration_minutes: number;
  price_paise: number;
  currency: string;
}

interface ResolutionWire {
  requested_local: string;
  resolved_local: string;
  instant_utc: string;
  classification: string;
  dst_adjusted: boolean;
}

function mapSlot(wire: SlotWire): AvailabilitySlot {
  return {
    slotId: wire.slot_id,
    tutorId: wire.tutor_id,
    startUtc: wire.start_utc,
    endUtc: wire.end_utc,
    ianaTimezone: wire.iana_timezone,
    status: wire.status,
    startLocal: wire.start_local,
    endLocal: wire.end_local,
    durationMinutes: wire.duration_minutes,
    pricePaise: wire.price_paise ?? 0,
    currency: wire.currency ?? 'INR',
  };
}

function mapResolution(wire: ResolutionWire): LocalResolution {
  return {
    requestedLocal: wire.requested_local,
    resolvedLocal: wire.resolved_local,
    instantUtc: wire.instant_utc,
    classification: wire.classification,
    dstAdjusted: wire.dst_adjusted,
  };
}

export interface AvailabilityParams {
  /** Display zone; the server rejects an unknown IANA name with a typed 422. */
  timezone?: string;
  /** A local CALENDAR date. Mutually exclusive with the local/UTC windows. */
  date?: string;
  fromLocal?: string;
  toLocal?: string;
  fromUtc?: string;
  toUtc?: string;
  limit?: number;
  offset?: number;
}

export async function getAvailability(
  tutorId: string,
  params: AvailabilityParams = {},
): Promise<AvailabilityResult> {
  const qs = new URLSearchParams();
  if (params.timezone) qs.set('timezone', params.timezone);
  if (params.date) qs.set('date', params.date);
  if (params.fromLocal) qs.set('from_local', params.fromLocal);
  if (params.toLocal) qs.set('to_local', params.toLocal);
  if (params.fromUtc) qs.set('from_utc', params.fromUtc);
  if (params.toUtc) qs.set('to_utc', params.toUtc);
  qs.set('limit', String(params.limit ?? 50));
  qs.set('offset', String(params.offset ?? 0));
  const wire = await jsonRequest<{
    tutor_id: string;
    iana_timezone: string;
    window: { from_utc: string | null; to_utc: string | null };
    local_resolution: Record<string, ResolutionWire>;
    slots: SlotWire[];
    limit: number;
    offset: number;
  }>(`/api/v1/tutors/${encodeURIComponent(tutorId)}/availability?${qs.toString()}`, {
    method: 'GET',
  });
  const localResolution: AvailabilityResult['localResolution'] = {};
  for (const key of ['from_local', 'to_local'] as const) {
    const raw = wire.local_resolution?.[key];
    if (raw) localResolution[key] = mapResolution(raw);
  }
  return {
    tutorId: wire.tutor_id,
    ianaTimezone: wire.iana_timezone,
    window: {
      fromUtc: wire.window?.from_utc ?? null,
      toUtc: wire.window?.to_utc ?? null,
    },
    localResolution,
    slots: (wire.slots ?? []).map(mapSlot),
    limit: wire.limit,
    offset: wire.offset,
  };
}

/* ========================================================================== *
 * B1/B2 — booking holds
 * ========================================================================== */

export interface BookingHold {
  id: string;
  slotId: string;
  status: string;
  /** Server-issued deadline. The countdown subtracts from THIS, never invents it. */
  expiresAt: string | null;
  /** `settings.booking_hold_minutes` — configurable, so it is read, not assumed. */
  holdMinutes: number;
  /**
   * The IMMUTABLE price this hold was taken at, in INTEGER PAISE — i.e. exactly
   * what `createPaymentOrder` will charge. Server-authoritative: the checkout
   * screen RENDERS this and never computes, configures or proposes an amount.
   */
  pricePaise: number;
  currency: string;
  /** True when an identical idempotency key replayed an existing hold. */
  replayed: boolean;
  /** Only the GET reports this; the server remains authoritative on expiry. */
  expired?: boolean;
}

interface HoldWire {
  id: string;
  slot_id: string;
  status: string;
  expires_at: string | null;
  hold_minutes: number;
  price_paise: number;
  currency: string;
  replayed?: boolean;
  expired?: boolean;
}

function mapHold(wire: HoldWire): BookingHold {
  return {
    id: wire.id,
    slotId: wire.slot_id,
    status: wire.status,
    expiresAt: wire.expires_at,
    holdMinutes: wire.hold_minutes,
    pricePaise: wire.price_paise ?? 0,
    currency: wire.currency ?? 'INR',
    replayed: Boolean(wire.replayed),
    ...(wire.expired === undefined ? {} : { expired: wire.expired }),
  };
}

export async function createBookingHold(input: {
  slotId: string;
  idempotencyKey: string;
}): Promise<BookingHold> {
  const wire = await jsonRequest<HoldWire>('/api/v1/tutoring/booking-holds', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: JSON.stringify({
      slot_id: input.slotId,
      idempotency_key: input.idempotencyKey,
    }),
  });
  return mapHold(wire);
}

export async function getBookingHold(holdId: string): Promise<BookingHold> {
  const wire = await jsonRequest<HoldWire>(
    `/api/v1/tutoring/booking-holds/${encodeURIComponent(holdId)}`,
    { method: 'GET' },
  );
  return mapHold(wire);
}

/* ========================================================================== *
 * C1/C3 — tokenised payment order and session creation
 * ========================================================================== */

export interface PaymentOrder {
  id: string;
  holdId: string;
  provider: string;
  providerOrderRef: string;
  /** Integer paise. Never divided in this layer. */
  amountPaise: number;
  currency: string;
  status: string;
  /** Issuer display crumbs only — never a PAN and never a token. */
  brand: string | null;
  maskedLast4: string | null;
  replayed: boolean;
}

interface OrderWire {
  id: string;
  hold_id: string;
  provider: string;
  provider_order_ref: string;
  amount_paise: number;
  currency: string;
  status: string;
  brand: string | null;
  masked_last4: string | null;
  replayed?: boolean;
}

/**
 * The ONLY payment secret shape this client may carry. A PAN pasted into the
 * token field fails this pattern locally and never reaches the network; the
 * server enforces the identical pattern.
 */
export const PAYMENT_TOKEN_PATTERN = /^tok_[A-Za-z0-9_]{3,60}$/;

export class ForbiddenPaymentFieldError extends Error {
  readonly code = 'FORBIDDEN_PAYMENT_FIELD';
  constructor(readonly field: string) {
    // No value is interpolated: the message may reach a log.
    super('FORBIDDEN_PAYMENT_FIELD');
    this.name = 'ForbiddenPaymentFieldError';
  }
}

/**
 * Create a payment order against a live hold.
 *
 * **The amount is NOT this client's to decide.** The server charges the price
 * it snapshotted onto the hold (`BookingHold.pricePaise`). `amountPaise` is an
 * OPTIONAL optimistic confirmation — "this is the figure the screen showed" —
 * and a disagreement comes back as the typed `PAYMENT_AMOUNT_MISMATCH`, which
 * carries the authoritative `expected_paise` so a stale screen can re-render
 * rather than guess. Omitting it is the preferred call.
 *
 * `paymentToken` is optional and, when given, must be a provider token. There
 * is deliberately no parameter for a card number, expiry, security code or
 * authentication code: those fields live inside the provider's hosted frame and
 * this function could not accept one if a caller tried.
 */
export async function createPaymentOrder(input: {
  holdId: string;
  /** Optimistic confirmation only. Never authoritative. Prefer omitting it. */
  amountPaise?: number;
  idempotencyKey: string;
  currency?: 'INR';
  paymentToken?: string;
}): Promise<PaymentOrder> {
  if (input.amountPaise !== undefined && !Number.isInteger(input.amountPaise)) {
    throw new ForbiddenPaymentFieldError('amount_paise');
  }
  if (input.paymentToken !== undefined && !PAYMENT_TOKEN_PATTERN.test(input.paymentToken)) {
    // Refused before any transport so a mistyped PAN cannot be sent anywhere.
    throw new ForbiddenPaymentFieldError('payment_token');
  }
  const wire = await jsonRequest<OrderWire>('/api/v1/payments/orders', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: JSON.stringify({
      hold_id: input.holdId,
      ...(input.amountPaise === undefined ? {} : { amount_paise: input.amountPaise }),
      idempotency_key: input.idempotencyKey,
      currency: input.currency ?? 'INR',
      ...(input.paymentToken ? { payment_token: input.paymentToken } : {}),
    }),
  });
  return {
    id: wire.id,
    holdId: wire.hold_id,
    provider: wire.provider,
    providerOrderRef: wire.provider_order_ref,
    amountPaise: wire.amount_paise,
    currency: wire.currency,
    status: wire.status,
    brand: wire.brand,
    maskedLast4: wire.masked_last4,
    replayed: Boolean(wire.replayed),
  };
}

/* ========================================================================== *
 * D1..D5 — sessions
 * ========================================================================== */

/**
 * The server's own vocabulary (`ATTENDANCE_STATES` in
 * backend/app/models/wave2.py). The state a tutor's completion writes is
 * `recorded`; there is no `marked`.
 */
export type AttendanceState =
  | 'pending' | 'recorded' | 'confirmed' | 'disputed' | 'resolved' | string;

export interface TutoringSession {
  id: string;
  slotId: string;
  tutorId: string;
  studentUserId: string;
  orderId: string | null;
  status: string;
  /** Optimistic-concurrency token; sent back as `expected_version`. */
  version: number;
  startUtc: string;
  endUtc: string;
  /** The session's RETAINED IANA zone. Rendered alongside the reader's zone. */
  ianaTimezone: string;
  startLocal: string;
  endLocal: string;
  attendanceState: AttendanceState | null;
  attendanceVersion: number | null;
}

interface SessionWire {
  id: string;
  slot_id: string;
  tutor_id: string;
  student_user_id: string;
  order_id: string | null;
  status: string;
  version: number;
  start_utc: string;
  end_utc: string;
  iana_timezone: string;
  start_local: string;
  end_local: string;
  attendance_state: string | null;
  attendance_version: number | null;
}

function mapSession(wire: SessionWire): TutoringSession {
  return {
    id: wire.id,
    slotId: wire.slot_id,
    tutorId: wire.tutor_id,
    studentUserId: wire.student_user_id,
    orderId: wire.order_id,
    status: wire.status,
    version: wire.version,
    startUtc: wire.start_utc,
    endUtc: wire.end_utc,
    ianaTimezone: wire.iana_timezone,
    startLocal: wire.start_local,
    endLocal: wire.end_local,
    attendanceState: wire.attendance_state,
    attendanceVersion: wire.attendance_version,
  };
}

export interface SessionCreated extends TutoringSession {
  replayed: boolean;
  reminderJobs: number;
}

/**
 * C3. Normally a REPLAY: the verified `paid` webhook already created the
 * session. An unpaid or unverified hold is refused with `PAYMENT_UNVERIFIED`
 * and nothing is written.
 */
export async function createTutoringSession(holdId: string): Promise<SessionCreated> {
  const wire = await jsonRequest<SessionWire & { replayed: boolean; reminder_jobs: number }>(
    '/api/v1/tutoring/sessions',
    { method: 'POST', body: JSON.stringify({ hold_id: holdId }) },
  );
  return {
    ...mapSession(wire),
    replayed: Boolean(wire.replayed),
    reminderJobs: wire.reminder_jobs ?? 0,
  };
}

export interface SessionListResult {
  items: TutoringSession[];
  role: string;
  limit: number;
  offset: number;
}

/**
 * D1. Scoped BY THE SERVER to the caller: a student sees their own sessions, a
 * tutor sees the ones on their calendar, an admin sees both. Passing an `actor`
 * makes the call as that authorised mentor/admin; omitting it keeps the student
 * dev-stub claims.
 */
export async function listTutoringSessions(params: {
  status?: string[];
  fromUtc?: string;
  toUtc?: string;
  limit?: number;
  offset?: number;
} = {}, actor?: TutoringActor): Promise<SessionListResult> {
  const qs = new URLSearchParams();
  for (const status of params.status ?? []) qs.append('status', status);
  if (params.fromUtc) qs.set('from_utc', params.fromUtc);
  if (params.toUtc) qs.set('to_utc', params.toUtc);
  qs.set('limit', String(params.limit ?? 50));
  qs.set('offset', String(params.offset ?? 0));
  const wire = await jsonRequest<{
    items: SessionWire[];
    role: string;
    limit: number;
    offset: number;
  }>(`/api/v1/tutoring/sessions?${qs.toString()}`, {
    method: 'GET',
    ...(actor ? { headers: actorClaimsHeaders(actor) } : {}),
  });
  return {
    items: (wire.items ?? []).map(mapSession),
    role: wire.role,
    limit: wire.limit,
    offset: wire.offset,
  };
}

export async function getTutoringSession(
  sessionId: string,
  actor?: TutoringActor,
): Promise<TutoringSession> {
  const wire = await jsonRequest<SessionWire>(
    `/api/v1/tutoring/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'GET', ...(actor ? { headers: actorClaimsHeaders(actor) } : {}) },
  );
  return mapSession(wire);
}

export interface RescheduleResult extends TutoringSession {
  remindersRevoked: number;
}

/** D2. Free at or after the notice window; `RESCHEDULE_WINDOW_CLOSED` inside it. */
export async function rescheduleSession(input: {
  sessionId: string;
  newSlotId: string;
  expectedVersion?: number;
  reason?: string;
}): Promise<RescheduleResult> {
  const wire = await jsonRequest<SessionWire & { reminders_revoked: number }>(
    `/api/v1/tutoring/sessions/${encodeURIComponent(input.sessionId)}/reschedule`,
    {
      method: 'POST',
      body: JSON.stringify({
        new_slot_id: input.newSlotId,
        ...(input.expectedVersion === undefined ? {} : { expected_version: input.expectedVersion }),
        ...(input.reason ? { reason: input.reason } : {}),
      }),
    },
  );
  return { ...mapSession(wire), remindersRevoked: wire.reminders_revoked ?? 0 };
}

export interface RefundAssessment {
  decision: 'full_refund' | 'no_auto_refund' | 'admin_exception' | string;
  /** Integer paise. */
  amountPaise: number;
  reason: string | null;
  /** Decimal string, e.g. "24.00" — kept as a string, never parsed into money. */
  hoursBeforeStart: string;
  policyWindowHours: number;
}

export interface CancelResult extends TutoringSession {
  refund: RefundAssessment | null;
  refundId: string | null;
  remindersRevoked: number;
}

/** D3. The frozen refund policy is the server's; this maps its verdict. */
export async function cancelSession(input: {
  sessionId: string;
  expectedVersion?: number;
  reason?: string;
}): Promise<CancelResult> {
  const wire = await jsonRequest<SessionWire & {
    refund: {
      decision: string;
      amount_paise: number;
      reason: string | null;
      hours_before_start: string;
      policy_window_hours: number;
    } | null;
    refund_id: string | null;
    reminders_revoked: number;
  }>(`/api/v1/tutoring/sessions/${encodeURIComponent(input.sessionId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({
      ...(input.expectedVersion === undefined ? {} : { expected_version: input.expectedVersion }),
      ...(input.reason ? { reason: input.reason } : {}),
    }),
  });
  return {
    ...mapSession(wire),
    refund: wire.refund
      ? {
        decision: wire.refund.decision,
        amountPaise: wire.refund.amount_paise,
        reason: wire.refund.reason,
        hoursBeforeStart: wire.refund.hours_before_start,
        policyWindowHours: wire.refund.policy_window_hours,
      }
      : null,
    refundId: wire.refund_id,
    remindersRevoked: wire.reminders_revoked ?? 0,
  };
}

export interface AttendanceRecord {
  sessionId: string;
  state: AttendanceState;
  version: number;
  recordedByRole: string | null;
  recordedAt: string | null;
  confirmedAt: string | null;
  disputedAt: string | null;
  resolvedAt: string | null;
  resolution: string | null;
  sessionStatus: string;
}

interface AttendanceWire {
  session_id: string;
  state: string;
  version: number;
  recorded_by_role: string | null;
  recorded_at: string | null;
  confirmed_at: string | null;
  disputed_at: string | null;
  resolved_at: string | null;
  resolution: string | null;
  session_status: string;
}

function mapAttendance(wire: AttendanceWire): AttendanceRecord {
  return {
    sessionId: wire.session_id,
    state: wire.state,
    version: wire.version,
    recordedByRole: wire.recorded_by_role,
    recordedAt: wire.recorded_at,
    confirmedAt: wire.confirmed_at,
    disputedAt: wire.disputed_at,
    resolvedAt: wire.resolved_at,
    resolution: wire.resolution,
    sessionStatus: wire.session_status,
  };
}

/**
 * D4. Recording completion is a TUTOR/ADMIN action, and only after the
 * scheduled end.
 *
 * The authorised `actor` is a REQUIRED argument, not an option: a caller that
 * has no mentor/admin identity cannot form this call at all. That is what stops
 * the student surface from firing a request the server is bound to refuse — the
 * server still answers a forged attempt with the typed `FORBIDDEN` (role) or
 * `NOT_FOUND` (a tutor who does not own the session), with zero mutation.
 */
export async function completeSession(
  sessionId: string,
  actor: TutoringActor,
): Promise<AttendanceRecord> {
  return mapAttendance(await jsonRequest<AttendanceWire>(
    `/api/v1/tutoring/sessions/${encodeURIComponent(sessionId)}/complete`,
    { method: 'POST', headers: actorClaimsHeaders(actor) },
  ));
}

/** D5. The student confirms what the tutor recorded. */
export async function confirmAttendance(input: {
  sessionId: string;
  expectedVersion?: number;
}): Promise<AttendanceRecord> {
  return mapAttendance(await jsonRequest<AttendanceWire>(
    `/api/v1/tutoring/sessions/${encodeURIComponent(input.sessionId)}/attendance/confirm`,
    {
      method: 'POST',
      body: JSON.stringify(
        input.expectedVersion === undefined ? {} : { expected_version: input.expectedVersion },
      ),
    },
  ));
}

/**
 * D5. The student disputes it. `reasonCode` is a CODE, never a narrative — it
 * reaches operators and audit, so the server enforces `^[a-z0-9_]+$`.
 */
export const ATTENDANCE_DISPUTE_REASON_CODES = [
  'tutor_absent',
  'session_cut_short',
  'wrong_session',
  'technical_failure',
  'other',
] as const;
export type AttendanceDisputeReasonCode = (typeof ATTENDANCE_DISPUTE_REASON_CODES)[number];

export async function disputeAttendance(input: {
  sessionId: string;
  expectedVersion?: number;
  reasonCode?: AttendanceDisputeReasonCode;
}): Promise<AttendanceRecord> {
  return mapAttendance(await jsonRequest<AttendanceWire>(
    `/api/v1/tutoring/sessions/${encodeURIComponent(input.sessionId)}/attendance/dispute`,
    {
      method: 'POST',
      body: JSON.stringify({
        ...(input.expectedVersion === undefined ? {} : { expected_version: input.expectedVersion }),
        ...(input.reasonCode ? { reason_code: input.reasonCode } : {}),
      }),
    },
  ));
}

/* ========================================================================== *
 * E1 — join credentials (in-memory only, one response, never stored)
 * ========================================================================== */

/**
 * The issued join credential.
 *
 * `joinToken` is the ONLY place a raw token exists client-side. The caller must
 * keep this object in component memory for the lifetime of the room and drop
 * it on leave: it may not be written to storage, a cookie, the URL, a query
 * key, a log or React Query's cache. `redactJoinCredential` is what any
 * diagnostic path renders instead.
 */
export interface JoinCredential {
  sessionId: string;
  grantId: string;
  roomRef: string;
  participantRef: string;
  permissions: string[];
  /** RAW SECRET. In-memory only, for the lifetime of the room. */
  joinToken: string;
  issuedAt: string | null;
  expiresAt: string | null;
  ttlSeconds: number;
  /** True when issuing revoked the caller's previous grant. */
  superseded: boolean;
  /** Browser-facing signalling URL; never the backend's internal Twirp URL. */
  videoRoomUrl: string | null;
}

/** A credential with the secret removed, safe to render or log. */
export type RedactedJoinCredential = Omit<JoinCredential, 'joinToken'> & {
  joinToken: '[redacted]';
};

export function redactJoinCredential(credential: JoinCredential): RedactedJoinCredential {
  return { ...credential, joinToken: '[redacted]' };
}

/**
 * E1. Issuing SUPERSEDES the caller's previous grant, so a stale token stops
 * working. An unauthorised or ineligible request is refused with the typed
 * `FORBIDDEN` / `NOT_FOUND` / `SESSION_STATE_INVALID` / `GRANT_*` codes and no
 * credential is returned at all.
 */
export async function issueJoinCredentials(sessionId: string): Promise<JoinCredential> {
  const wire = await jsonRequest<{
    session_id: string;
    grant_id: string;
    room_ref: string;
    participant_ref: string;
    permissions: string[];
    join_token: string;
    issued_at: string | null;
    expires_at: string | null;
    ttl_seconds: number;
    superseded: boolean;
    video_room_url: string | null;
  }>(`/api/v1/tutoring/sessions/${encodeURIComponent(sessionId)}/join-credentials`, {
    method: 'POST',
  });
  return {
    sessionId: wire.session_id,
    grantId: wire.grant_id,
    roomRef: wire.room_ref,
    participantRef: wire.participant_ref,
    permissions: wire.permissions ?? [],
    joinToken: wire.join_token,
    issuedAt: wire.issued_at,
    expiresAt: wire.expires_at,
    ttlSeconds: wire.ttl_seconds,
    superseded: Boolean(wire.superseded),
    videoRoomUrl: wire.video_room_url ?? null,
  };
}

/** Secret-free operational switches read at runtime, not baked into the build. */
export interface TutoringCapabilities {
  videoCallsEnabled: boolean;
  videoTransport: 'none' | 'deterministic' | 'livekit' | string;
  videoRoomUrl: string | null;
  joinCredentialTtlSeconds: number;
  recordingEnabled: boolean;
}

export async function getTutoringCapabilities(): Promise<TutoringCapabilities> {
  const wire = await jsonRequest<{
    video_calls_enabled: boolean;
    video_transport: string;
    video_room_url: string | null;
    join_credential_ttl_seconds: number;
    recording_enabled: boolean;
  }>('/api/v1/tutoring/capabilities', { method: 'GET' });
  return {
    videoCallsEnabled: Boolean(wire.video_calls_enabled),
    videoTransport: wire.video_transport,
    videoRoomUrl: wire.video_room_url ?? null,
    joinCredentialTtlSeconds: wire.join_credential_ttl_seconds,
    recordingEnabled: Boolean(wire.recording_enabled),
  };
}

/* ========================================================================== *
 * F1/F2/F3 — reviews
 * ========================================================================== */

export interface TutorReview {
  id: string;
  sessionId: string;
  tutorId: string;
  rating: number;
  body: string | null;
  published: boolean;
  editDeadlineAt: string | null;
  deleted: boolean;
  moderationState: string | null;
  ratingAggregate: RatingAggregate | null;
}

interface ReviewWire {
  id: string;
  session_id: string;
  tutor_id: string;
  rating: number;
  body: string | null;
  published: boolean;
  edit_deadline_at: string | null;
  deleted: boolean;
  moderation_state: string | null;
  rating_aggregate: AggregateWire | null;
}

function mapReview(wire: ReviewWire): TutorReview {
  return {
    id: wire.id,
    sessionId: wire.session_id,
    tutorId: wire.tutor_id,
    rating: wire.rating,
    body: wire.body,
    published: wire.published,
    editDeadlineAt: wire.edit_deadline_at,
    deleted: wire.deleted,
    moderationState: wire.moderation_state,
    ratingAggregate: wire.rating_aggregate
      ? mapAggregate(wire.rating_aggregate, wire.tutor_id)
      : null,
  };
}

/** F1/F2. One review per session, gated on CONFIRMED attendance. */
export async function createReview(input: {
  sessionId: string;
  rating: number;
  body?: string | null;
}): Promise<TutorReview> {
  return mapReview(await jsonRequest<ReviewWire>(
    `/api/v1/tutoring/sessions/${encodeURIComponent(input.sessionId)}/review`,
    {
      method: 'POST',
      body: JSON.stringify({
        rating: input.rating,
        ...(input.body === undefined ? {} : { body: input.body }),
      }),
    },
  ));
}

/**
 * F1. Author-only, inside the edit window. `body` is forwarded ONLY when the
 * caller passed the key, so `{ rating: 5 }` leaves existing text alone while
 * `{ body: null }` deliberately removes it.
 */
export async function editReview(input: {
  reviewId: string;
  rating?: number;
  body?: string | null;
}): Promise<TutorReview> {
  const payload: Record<string, unknown> = {};
  if (input.rating !== undefined) payload.rating = input.rating;
  if ('body' in input) payload.body = input.body;
  return mapReview(await jsonRequest<ReviewWire>(
    `/api/v1/tutoring/reviews/${encodeURIComponent(input.reviewId)}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  ));
}

/** F1. Author-only soft delete; drops out of the public aggregate at once. */
export async function deleteReview(reviewId: string): Promise<TutorReview> {
  return mapReview(await jsonRequest<ReviewWire>(
    `/api/v1/tutoring/reviews/${encodeURIComponent(reviewId)}`,
    { method: 'DELETE' },
  ));
}

/* ========================================================================== *
 * Query keys — one namespace, no secret ever part of a key
 * ========================================================================== */

export const tutoringKeys = {
  capabilities: ['tutoring', 'capabilities'] as const,
  tutors: (params: TutorSearchParams) => ['tutoring', 'tutors', params] as const,
  tutor: (id: string) => ['tutoring', 'tutor', id] as const,
  availability: (id: string, params: AvailabilityParams) =>
    ['tutoring', 'availability', id, params] as const,
  hold: (id: string) => ['tutoring', 'hold', id] as const,
  sessions: (params: { status?: string[] }) => ['tutoring', 'sessions', params] as const,
  session: (id: string) => ['tutoring', 'session', id] as const,
  /**
   * The mentor/admin's own session list. Keyed by the opaque subject so one
   * actor's cache can never be served to another; no secret is ever part of a key.
   */
  mentorSessions: (actor: TutoringActor) =>
    ['tutoring', 'mentor', 'sessions', actor.role, actor.userId] as const,
};

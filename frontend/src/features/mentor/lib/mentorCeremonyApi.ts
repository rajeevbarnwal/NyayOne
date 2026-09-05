import { apiFetch } from '../../../lib/apiClient';
import { withStudentAuthTransition } from '../../student/lib/registrationApi';
import {
  type StudentAuthTransition,
  withStudentAuthRequestLease,
} from '../../student/lib/studentBrowserContext';

/**
 * NYAY-22 browser seam for the server-issued mentor ceremony.
 *
 * The browser never owns mentor authority. Every projection below is display
 * data obtained from a fresh server response; the only authority is an
 * HttpOnly, host-only cookie. Cookie-changing responses are linearized by the
 * existing global student/mentor Web Locks barrier so a second realm cannot
 * mount private content while a cookie generation is changing.
 */

export const MENTOR_ENDPOINTS = Object.freeze({
  entry: '/api/v1/auth/mentor/entry',
  initiate: '/api/v1/auth/mentor/ceremony/initiate',
  verify: '/api/v1/auth/mentor/ceremony/verify',
  exchange: '/api/v1/auth/mentor/ceremony/exchange',
  session: '/api/v1/auth/mentor/session',
  rotate: '/api/v1/auth/mentor/session/rotate',
  revoke: '/api/v1/auth/mentor/session/revoke',
  logout: '/api/v1/auth/mentor/session/logout',
  recover: '/api/v1/auth/mentor/ceremony/recover',
  authority: '/api/v1/auth/mentor/authority',
} as const);

export type MentorRole = 'tutor' | 'lawyer_tutor';
export type MentorPurposeCode =
  | 'student_guidance'
  | 'legal_education'
  | 'document_review'
  | 'case_discussion';

export type MentorScope =
  | 'engagement:read'
  | 'engagement:respond'
  | 'profile-slice:read'
  | 'consent:read'
  | 'session:rotate'
  | 'session:end';

export type MentorProfileSlice =
  | 'display_name'
  | 'preferred_language'
  | 'city'
  | 'college'
  | 'year_of_study'
  | 'interests'
  | 'goals';

export type MentorDisclosureClass =
  | 'display_identity'
  | 'preferred_language'
  | 'city'
  | 'education_context'
  | 'interests'
  | 'goals';

export type MentorFailureCode =
  | 'INVALID_REQUEST'
  | 'INVALID_IDEMPOTENCY_KEY'
  | 'ORIGIN_REJECTED'
  | 'AUTHENTICATION_REQUIRED'
  | 'AUTHORIZATION_DENIED'
  | 'RESOURCE_UNAVAILABLE'
  | 'IDEMPOTENCY_CONFLICT'
  | 'CONCURRENT_STATE_CHANGED'
  | 'CEREMONY_REPLAYED'
  | 'SESSION_CONFLICT'
  | 'SESSION_STALE'
  | 'SESSION_EXPIRED'
  | 'AUTHORITY_TERMINAL'
  | 'STEP_UP_REQUIRED'
  | 'STEP_UP_EXPIRED'
  | 'RATE_LIMITED'
  | 'PROVIDER_UNAVAILABLE';

export type MentorClientFailureCode = MentorFailureCode
  | 'MENTOR_RESPONSE_INVALID'
  | 'MENTOR_SESSION_POSTCONDITION_FAILED'
  | 'MENTOR_SESSION_REQUIRED'
  | 'MENTOR_BROWSER_ORIGIN_UNAVAILABLE';

export class MentorCeremonyApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: MentorClientFailureCode,
    readonly retryable = false,
    readonly field: 'Idempotency-Key' | 'Origin' | 'request' | null = null,
  ) {
    super(code);
    this.name = 'MentorCeremonyApiError';
  }
}

export interface MentorBootstrapProjection {
  schemaVersion: 'mentor-ceremony.v1';
  status: 'accepted';
  next: 'ceremony_initiate';
  expiresInSeconds: number;
}

export interface MentorCeremonyChallenge {
  schemaVersion: 'mentor-ceremony.v1';
  status: 'accepted';
  ceremonyState: 'challenge_issued';
  next: 'external_identity';
  intent: 'mentor_session' | 'authority_deletion_step_up';
  expiresInSeconds: number;
}

export interface MentorVerificationProvenance {
  result: 'current_positive';
  provenanceClass: 'nyayone_reviewed_identity' | 'approved_federated_attestation';
  policyVersion: string;
  verifiedAt: string;
  currentAt: string;
  ownershipBinding: 'tutor_profile_user_equals_actor';
}

export interface MentorPurposeAcceptanceProjection {
  schemaVersion: 'mentor-acceptance.v1';
  status: 'acceptance_required';
  ceremonyState: 'proof_verified';
  intent: 'mentor_session';
  serverDerivedMentorRole: MentorRole;
  purposeCode: MentorPurposeCode;
  consentReceiptVersion: string;
  disclosureClasses: MentorDisclosureClass[];
  acceptanceTextVersion: string;
  verification: MentorVerificationProvenance;
  expiresInSeconds: number;
}

export interface MentorDeletionStepUpAcceptanceProjection {
  schemaVersion: 'mentor-acceptance.v1';
  status: 'acceptance_required';
  ceremonyState: 'proof_verified';
  intent: 'authority_deletion_step_up';
  deletionScope: 'global_mentor_authority';
  acceptanceTextVersion: string;
  verification: MentorVerificationProvenance;
  expiresInSeconds: number;
}

export type MentorAcceptanceProjection =
  | MentorPurposeAcceptanceProjection
  | MentorDeletionStepUpAcceptanceProjection;

export interface MentorConsentProjection {
  purposeCode: MentorPurposeCode;
  version: string;
  status: 'granted';
  recordedAt: string;
}

export interface MentorSessionProjection {
  schemaVersion: 'mentor-session.v1';
  sessionClass: 'mentor';
  mentorRole: MentorRole;
  state: 'active';
  purposeCode: MentorPurposeCode;
  scopes: MentorScope[];
  permittedProfileSlices: MentorProfileSlice[];
  sameActorVerified: true;
  tutorProfileStatus: 'active';
  verification: MentorVerificationProvenance;
  subjectSharingEligibility: 'allowed';
  consent: MentorConsentProjection;
  absoluteLifetimeSeconds: number;
  idleTimeoutSeconds: number;
  issuedAt: string;
  expiresAt: string;
}

export interface MentorAuthorityStepUpProjection {
  schemaVersion: 'mentor-authority-step-up.v1';
  status: 'step_up_ready';
  intent: 'authority_deletion_step_up';
  deletionScope: 'global_mentor_authority';
  sameActorVerified: true;
  verification: MentorVerificationProvenance;
  expiresInSeconds: number;
}

export interface MentorLifecycleOutcome {
  schemaVersion: 'mentor-lifecycle.v1';
  action: 'revoked' | 'logged_out' | 'authority_deletion_scheduled';
  state: 'revoked' | 'logged_out' | 'deletion_pending';
  sessionAuthorityPresent: false;
  stepUpAuthorityPresent?: false;
  auditEventRecorded: true;
  effectiveAt: string;
}

export interface MentorCeremonyInitiateRequest {
  intent: 'mentor_session';
  requestedMentorRole: MentorRole;
  purposeCode: MentorPurposeCode;
  privacyNoticeVersion: string;
}

export interface MentorIdentityProofRequest {
  expectedCeremonyState: 'challenge_issued';
}

export interface MentorSessionExchangeRequest {
  intent: 'mentor_session';
  expectedCeremonyState: 'proof_verified';
  acceptPurpose: true;
  purposeCode: MentorPurposeCode;
  consentReceiptVersion: string;
  acceptanceTextVersion: string;
}

export interface MentorAuthorityStepUpExchangeRequest {
  intent: 'authority_deletion_step_up';
  expectedCeremonyState: 'proof_verified';
  acceptAuthorityDeletionStepUp: true;
  acceptanceTextVersion: string;
}

export interface MentorLifecycleRequest {
  expectedSessionState: 'active';
  purposeCode: MentorPurposeCode;
  reasonCode:
    | 'routine_rotation'
    | 'mentor_requested'
    | 'purpose_complete'
    | 'suspected_compromise';
}

export type MentorRecoveryRequest = {
  intent: 'mentor_session';
  requestedMentorRole: MentorRole;
  purposeCode: MentorPurposeCode;
  recoveryMethod: 'fresh_external_identity';
  privacyNoticeVersion: string;
} | {
  intent: 'authority_deletion_step_up';
  recoveryMethod: 'fresh_external_identity';
  stepUpNoticeVersion: string;
};

export interface MentorAuthorityDeletionRequest {
  expectedSessionState: 'active';
  expectedStepUpIntent: 'authority_deletion_step_up';
  confirmation: 'delete_mentor_authority';
  retentionNoticeVersion: string;
}

export interface MentorTransitionResult<T> {
  value: T;
  session: MentorSessionProjection | null;
}

type MentorPostcondition = 'active' | 'absent' | 'either';
type MentorParser<T> = (value: unknown) => T;

const FAILURE_CODES = new Set<MentorFailureCode>([
  'INVALID_REQUEST', 'INVALID_IDEMPOTENCY_KEY', 'ORIGIN_REJECTED',
  'AUTHENTICATION_REQUIRED', 'AUTHORIZATION_DENIED', 'RESOURCE_UNAVAILABLE',
  'IDEMPOTENCY_CONFLICT', 'CONCURRENT_STATE_CHANGED', 'CEREMONY_REPLAYED',
  'SESSION_CONFLICT', 'SESSION_STALE', 'SESSION_EXPIRED', 'AUTHORITY_TERMINAL',
  'STEP_UP_REQUIRED', 'STEP_UP_EXPIRED', 'RATE_LIMITED', 'PROVIDER_UNAVAILABLE',
]);
const ROLES = new Set<MentorRole>(['tutor', 'lawyer_tutor']);
const PURPOSES = new Set<MentorPurposeCode>([
  'student_guidance', 'legal_education', 'document_review', 'case_discussion',
]);
const SCOPES = new Set<MentorScope>([
  'engagement:read', 'engagement:respond', 'profile-slice:read', 'consent:read',
  'session:rotate', 'session:end',
]);
const PROFILE_SLICES = new Set<MentorProfileSlice>([
  'display_name', 'preferred_language', 'city', 'college', 'year_of_study',
  'interests', 'goals',
]);
const DISCLOSURES = new Set<MentorDisclosureClass>([
  'display_identity', 'preferred_language', 'city', 'education_context',
  'interests', 'goals',
]);
const IDEMPOTENCY_KEY = /^[A-Za-z0-9._~-]{16,200}$/u;
const CONTRACT_VERSION = /^[a-z0-9][a-z0-9._-]{0,63}$/u;

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalidResponse();
  return value as Record<string, unknown>;
}

function requireExactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    invalidResponse();
  }
}

function invalidResponse(): never {
  throw new MentorCeremonyApiError(502, 'MENTOR_RESPONSE_INVALID');
}

function positiveBoundedInteger(value: unknown, ceiling: number): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0 && Number(value) <= ceiling;
}

function version(value: unknown): value is string {
  return typeof value === 'string' && CONTRACT_VERSION.test(value);
}

function instant(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function exactEnumArray<T extends string>(
  value: unknown,
  allowed: ReadonlySet<T>,
  maximum: number,
  allowEmpty = true,
): value is T[] {
  return Array.isArray(value)
    && (allowEmpty || value.length > 0)
    && value.length <= maximum
    && new Set(value).size === value.length
    && value.every((item) => typeof item === 'string' && allowed.has(item as T));
}

function parseVerification(value: unknown): MentorVerificationProvenance {
  const item = record(value);
  requireExactKeys(item, [
    'result', 'provenanceClass', 'policyVersion', 'verifiedAt', 'currentAt',
    'ownershipBinding',
  ]);
  if (item.result !== 'current_positive'
    || !['nyayone_reviewed_identity', 'approved_federated_attestation']
      .includes(String(item.provenanceClass))
    || !version(item.policyVersion)
    || !instant(item.verifiedAt)
    || !instant(item.currentAt)
    || item.ownershipBinding !== 'tutor_profile_user_equals_actor') invalidResponse();
  return item as unknown as MentorVerificationProvenance;
}

function parseBootstrap(value: unknown): MentorBootstrapProjection {
  const item = record(value);
  requireExactKeys(item, ['schemaVersion', 'status', 'next', 'expiresInSeconds']);
  if (item.schemaVersion !== 'mentor-ceremony.v1' || item.status !== 'accepted'
    || item.next !== 'ceremony_initiate'
    || !positiveBoundedInteger(item.expiresInSeconds, 900)) invalidResponse();
  return item as unknown as MentorBootstrapProjection;
}

function parseChallenge(value: unknown): MentorCeremonyChallenge {
  const item = record(value);
  requireExactKeys(item, [
    'schemaVersion', 'status', 'ceremonyState', 'next', 'intent', 'expiresInSeconds',
  ]);
  if (item.schemaVersion !== 'mentor-ceremony.v1' || item.status !== 'accepted'
    || item.ceremonyState !== 'challenge_issued' || item.next !== 'external_identity'
    || !['mentor_session', 'authority_deletion_step_up'].includes(String(item.intent))
    || !positiveBoundedInteger(item.expiresInSeconds, 900)) invalidResponse();
  return item as unknown as MentorCeremonyChallenge;
}

function parseAcceptance(value: unknown): MentorAcceptanceProjection {
  const item = record(value);
  if (item.intent === 'mentor_session') {
    requireExactKeys(item, [
      'schemaVersion', 'status', 'ceremonyState', 'intent', 'serverDerivedMentorRole',
      'purposeCode', 'consentReceiptVersion', 'disclosureClasses',
      'acceptanceTextVersion', 'verification', 'expiresInSeconds',
    ]);
    if (item.schemaVersion !== 'mentor-acceptance.v1'
      || item.status !== 'acceptance_required' || item.ceremonyState !== 'proof_verified'
      || !ROLES.has(item.serverDerivedMentorRole as MentorRole)
      || !PURPOSES.has(item.purposeCode as MentorPurposeCode)
      || !version(item.consentReceiptVersion) || !version(item.acceptanceTextVersion)
      || !exactEnumArray(item.disclosureClasses, DISCLOSURES, 7)
      || !positiveBoundedInteger(item.expiresInSeconds, 900)) invalidResponse();
    parseVerification(item.verification);
    return item as unknown as MentorPurposeAcceptanceProjection;
  }
  requireExactKeys(item, [
    'schemaVersion', 'status', 'ceremonyState', 'intent', 'deletionScope',
    'acceptanceTextVersion', 'verification', 'expiresInSeconds',
  ]);
  if (item.schemaVersion !== 'mentor-acceptance.v1'
    || item.status !== 'acceptance_required' || item.ceremonyState !== 'proof_verified'
    || item.intent !== 'authority_deletion_step_up'
    || item.deletionScope !== 'global_mentor_authority'
    || !version(item.acceptanceTextVersion)
    || !positiveBoundedInteger(item.expiresInSeconds, 300)) invalidResponse();
  parseVerification(item.verification);
  return item as unknown as MentorDeletionStepUpAcceptanceProjection;
}

export function parseMentorSessionProjection(value: unknown): MentorSessionProjection {
  const item = record(value);
  requireExactKeys(item, [
    'schemaVersion', 'sessionClass', 'mentorRole', 'state', 'purposeCode', 'scopes',
    'permittedProfileSlices', 'sameActorVerified', 'tutorProfileStatus', 'verification',
    'subjectSharingEligibility', 'consent', 'absoluteLifetimeSeconds',
    'idleTimeoutSeconds', 'issuedAt', 'expiresAt',
  ]);
  const consent = record(item.consent);
  requireExactKeys(consent, ['purposeCode', 'version', 'status', 'recordedAt']);
  if (item.schemaVersion !== 'mentor-session.v1' || item.sessionClass !== 'mentor'
    || !ROLES.has(item.mentorRole as MentorRole) || item.state !== 'active'
    || !PURPOSES.has(item.purposeCode as MentorPurposeCode)
    || !exactEnumArray(item.scopes, SCOPES, 8, false)
    || !exactEnumArray(item.permittedProfileSlices, PROFILE_SLICES, 7)
    || item.sameActorVerified !== true || item.tutorProfileStatus !== 'active'
    || item.subjectSharingEligibility !== 'allowed'
    || !positiveBoundedInteger(item.absoluteLifetimeSeconds, 28_800)
    || !positiveBoundedInteger(item.idleTimeoutSeconds, 1_800)
    || !instant(item.issuedAt) || !instant(item.expiresAt)
    || consent.purposeCode !== item.purposeCode || !version(consent.version)
    || consent.status !== 'granted' || !instant(consent.recordedAt)) invalidResponse();
  parseVerification(item.verification);
  return item as unknown as MentorSessionProjection;
}

function parseStepUp(value: unknown): MentorAuthorityStepUpProjection {
  const item = record(value);
  requireExactKeys(item, [
    'schemaVersion', 'status', 'intent', 'deletionScope', 'sameActorVerified',
    'verification', 'expiresInSeconds',
  ]);
  if (item.schemaVersion !== 'mentor-authority-step-up.v1' || item.status !== 'step_up_ready'
    || item.intent !== 'authority_deletion_step_up'
    || item.deletionScope !== 'global_mentor_authority'
    || item.sameActorVerified !== true
    || !positiveBoundedInteger(item.expiresInSeconds, 300)) invalidResponse();
  parseVerification(item.verification);
  return item as unknown as MentorAuthorityStepUpProjection;
}

function parseExchange(
  value: unknown,
): MentorSessionProjection | MentorAuthorityStepUpProjection {
  const item = record(value);
  return item.schemaVersion === 'mentor-session.v1'
    ? parseMentorSessionProjection(item)
    : parseStepUp(item);
}

function parseLifecycle(value: unknown): MentorLifecycleOutcome {
  const item = record(value);
  const deletion = item.action === 'authority_deletion_scheduled';
  requireExactKeys(item, deletion
    ? [
      'schemaVersion', 'action', 'state', 'sessionAuthorityPresent',
      'stepUpAuthorityPresent', 'auditEventRecorded', 'effectiveAt',
    ]
    : [
      'schemaVersion', 'action', 'state', 'sessionAuthorityPresent',
      'auditEventRecorded', 'effectiveAt',
    ]);
  const pair = `${String(item.action)}:${String(item.state)}`;
  if (item.schemaVersion !== 'mentor-lifecycle.v1'
    || !['revoked:revoked', 'logged_out:logged_out',
      'authority_deletion_scheduled:deletion_pending'].includes(pair)
    || item.sessionAuthorityPresent !== false || item.auditEventRecorded !== true
    || (deletion && item.stepUpAuthorityPresent !== false)
    || !instant(item.effectiveAt)) invalidResponse();
  return item as unknown as MentorLifecycleOutcome;
}

function parseFailure(response: Response, value: unknown): MentorCeremonyApiError {
  const envelope = record(value);
  requireExactKeys(envelope, ['detail']);
  const detail = record(envelope.detail);
  const keys = Object.keys(detail).sort();
  const permitted = ['code', 'field', 'message', 'retryAfterSeconds', 'retryable'];
  if (keys.some((key) => !permitted.includes(key))
    || !keys.includes('code') || !keys.includes('message') || !keys.includes('retryable')
    || !FAILURE_CODES.has(detail.code as MentorFailureCode)
    || detail.message !== 'Request failed' || typeof detail.retryable !== 'boolean'
    || (detail.field !== undefined
      && !['Idempotency-Key', 'Origin', 'request'].includes(String(detail.field)))
    || (detail.retryAfterSeconds !== undefined
      && !positiveBoundedInteger(detail.retryAfterSeconds, 900))) invalidResponse();
  return new MentorCeremonyApiError(
    response.status,
    detail.code as MentorFailureCode,
    detail.retryable,
    (detail.field as MentorCeremonyApiError['field'] | undefined) ?? null,
  );
}

async function settledJson<T>(
  path: string,
  init: RequestInit,
  parser: MentorParser<T>,
  authTransition?: StudentAuthTransition,
): Promise<T> {
  if (!Object.values(MENTOR_ENDPOINTS).includes(path as never)
    || path.includes('?') || path.includes('#')) {
    throw new MentorCeremonyApiError(400, 'MENTOR_RESPONSE_INVALID');
  }
  return withStudentAuthRequestLease(async () => {
    const response = await apiFetch(path, init);
    await response.clone().arrayBuffer();
    const body: unknown = await response.json().catch(() => invalidResponse());
    if (!response.ok) throw parseFailure(response, body);
    return parser(body);
  }, authTransition);
}

function requireBrowserOrigin(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  try {
    const current = new URL(globalThis.location.origin);
    if (!['http:', 'https:'].includes(current.protocol)
      || current.username || current.password || current.origin !== globalThis.location.origin) {
      throw new Error('invalid');
    }
  } catch {
    throw new MentorCeremonyApiError(0, 'MENTOR_BROWSER_ORIGIN_UNAVAILABLE');
  }
}

function mutationInit(
  method: 'POST' | 'DELETE',
  idempotencyKey: string,
  body: object,
): RequestInit {
  requireBrowserOrigin();
  if (!IDEMPOTENCY_KEY.test(idempotencyKey)) {
    throw new MentorCeremonyApiError(
      400,
      'INVALID_IDEMPOTENCY_KEY',
      false,
      'Idempotency-Key',
    );
  }
  return {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify(body),
  };
}

export async function getMentorSession(
  lifecycle: { authTransition?: StudentAuthTransition } = {},
): Promise<MentorSessionProjection | null> {
  try {
    return await settledJson(
      MENTOR_ENDPOINTS.session,
      { method: 'GET' },
      parseMentorSessionProjection,
      lifecycle.authTransition,
    );
  } catch (error) {
    if (error instanceof MentorCeremonyApiError
      && ((error.status === 401 && error.code === 'AUTHENTICATION_REQUIRED')
        || (error.status === 410
          && ['SESSION_EXPIRED', 'AUTHORITY_TERMINAL'].includes(error.code)))) return null;
    throw error;
  }
}

async function runMentorCookieTransition<T>(
  operation: (transition: StudentAuthTransition) => Promise<T>,
  postcondition: MentorPostcondition,
): Promise<MentorTransitionResult<T>> {
  return withStudentAuthTransition(async (transition) => {
    const value = await operation(transition);
    const session = await getMentorSession({ authTransition: transition });
    if ((postcondition === 'active' && session === null)
      || (postcondition === 'absent' && session !== null)) {
      throw new MentorCeremonyApiError(503, 'MENTOR_SESSION_POSTCONDITION_FAILED');
    }
    return { value, session };
  });
}

export async function enterMentorCeremony(): Promise<MentorTransitionResult<MentorBootstrapProjection>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.entry,
      { method: 'GET' },
      parseBootstrap,
      transition,
    ),
    'absent',
  );
}

export async function initiateMentorCeremony(
  body: MentorCeremonyInitiateRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorCeremonyChallenge>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.initiate,
      mutationInit('POST', idempotencyKey, body),
      parseChallenge,
      transition,
    ),
    'absent',
  );
}

export async function verifyMentorIdentity(
  body: MentorIdentityProofRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorAcceptanceProjection>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.verify,
      mutationInit('POST', idempotencyKey, body),
      parseAcceptance,
      transition,
    ),
    'either',
  );
}

export async function exchangeMentorCeremony(
  body: MentorSessionExchangeRequest | MentorAuthorityStepUpExchangeRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorSessionProjection | MentorAuthorityStepUpProjection>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.exchange,
      mutationInit('POST', idempotencyKey, body),
      parseExchange,
      transition,
    ),
    'active',
  );
}

export async function rotateMentorSession(
  body: MentorLifecycleRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorSessionProjection>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.rotate,
      mutationInit('POST', idempotencyKey, body),
      parseMentorSessionProjection,
      transition,
    ),
    'active',
  );
}

export async function revokeMentorSession(
  body: MentorLifecycleRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorLifecycleOutcome>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.revoke,
      mutationInit('POST', idempotencyKey, body),
      parseLifecycle,
      transition,
    ),
    'absent',
  );
}

export async function logoutMentorSession(
  body: MentorLifecycleRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorLifecycleOutcome>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.logout,
      mutationInit('POST', idempotencyKey, body),
      parseLifecycle,
      transition,
    ),
    'absent',
  );
}

export async function recoverMentorCeremony(
  body: MentorRecoveryRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorCeremonyChallenge>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.recover,
      mutationInit('POST', idempotencyKey, body),
      parseChallenge,
      transition,
    ),
    'either',
  );
}

export async function deleteMentorAuthority(
  body: MentorAuthorityDeletionRequest,
  idempotencyKey: string,
): Promise<MentorTransitionResult<MentorLifecycleOutcome>> {
  return runMentorCookieTransition(
    (transition) => settledJson(
      MENTOR_ENDPOINTS.authority,
      mutationInit('DELETE', idempotencyKey, body),
      parseLifecycle,
      transition,
    ),
    'absent',
  );
}

/**
 * Reusable guard for a future mentor-private route. M-01 remains admin-only;
 * this helper intentionally is not wired to that surface in NYAY-22.
 */
export async function withServerProvenMentorSession<T>(
  mount: (session: MentorSessionProjection) => T | Promise<T>,
): Promise<T> {
  const session = await getMentorSession();
  if (!session) throw new MentorCeremonyApiError(401, 'MENTOR_SESSION_REQUIRED');
  return mount(session);
}

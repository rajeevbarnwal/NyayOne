import { studentApiFetch } from './studentApiClient';
import { normalizeLegalName, validateLegalName } from './legalName';
import { institutionalEmailError } from './profile';
import { captureStudentContextFence, type StudentContextFence } from './studentBrowserContext';
import { runStudentMutationStep } from './useStudentMutation';

export { normalizeLegalName, validateLegalName } from './legalName';

const PROFILE_ROOT = '/api/v1/student/profile';
export const PROFILE_WRITE_TIMEOUT_MS = 10_000;
const PROJECTION_KEYS = [
  'access_mode',
  'completed_sections',
  'completion_percent',
  'completion_version',
  'disabled_capabilities',
  'guardian',
  'institutional_email_status',
  'is_complete',
  'missing_requirements',
  'next_incomplete_section',
  'profile',
  'profile_prompt',
  'profile_version',
] as const;

export type ProfileSection = 'personal' | 'academic' | 'interests';
export type ProfileRequirement =
  | 'personal.preferred_language'
  | 'personal.city'
  | 'academic.college'
  | 'academic.year_of_study'
  | 'academic.enrolment_number'
  | 'interests.interests'
  | 'interests.goals';
export type InstitutionalEmailStatus =
  | 'not_provided'
  | 'pending'
  | 'verified'
  | 'rejected'
  | 'expired'
  | 'revoked';
export type GuardianStatus =
  | 'not_required'
  | 'required_pending'
  | 'verified'
  | 'rejected'
  | 'revoked';
export type ProfileAccessMode = 'full' | 'limited';
export type DisabledProfileCapability = 'community' | 'sharing';

export interface PersonalProfile {
  firstName: string;
  middleName: string | null;
  lastName: string;
  dateOfBirth: string;
  preferredLanguage: 'en' | 'hi' | null;
  city: string | null;
  pronouns: string | null;
}

export interface AcademicProfile {
  college: string | null;
  yearOfStudy: string | null;
  enrolmentNumber: string | null;
  institutionalEmail: string | null;
  barEnrolmentNumber: string | null;
}

export interface InterestsProfile {
  interests: string[];
  goals: string[];
}

export interface StudentProfileProjection {
  profileVersion: number;
  completionVersion: 'v1';
  completionPercent: 0 | 34 | 67 | 100;
  completedSections: ProfileSection[];
  missingRequirements: ProfileRequirement[];
  nextIncompleteSection: ProfileSection | null;
  isComplete: boolean;
  institutionalEmailStatus: InstitutionalEmailStatus;
  guardian: { required: boolean; status: GuardianStatus };
  accessMode: ProfileAccessMode;
  disabledCapabilities: DisabledProfileCapability[];
  profilePrompt: { shouldShow: boolean; dismissedForSession: boolean };
  profile: {
    personal: PersonalProfile;
    academic: AcademicProfile;
    interests: InterestsProfile;
  };
}

interface PersonalProfileWire {
  first_name: string;
  middle_name: string | null;
  last_name: string;
  date_of_birth: string;
  preferred_language: 'en' | 'hi' | null;
  city: string | null;
  pronouns: string | null;
}

interface AcademicProfileWire {
  college: string | null;
  year_of_study: string | null;
  enrolment_number: string | null;
  institutional_email: string | null;
  bar_enrolment_number: string | null;
}

interface StudentProfileProjectionWire {
  profile_version: number;
  completion_version: 'v1';
  completion_percent: 0 | 34 | 67 | 100;
  completed_sections: ProfileSection[];
  missing_requirements: ProfileRequirement[];
  next_incomplete_section: ProfileSection | null;
  is_complete: boolean;
  institutional_email_status: InstitutionalEmailStatus;
  guardian: { required: boolean; status: GuardianStatus };
  access_mode: ProfileAccessMode;
  disabled_capabilities: DisabledProfileCapability[];
  profile_prompt: { should_show: boolean; dismissed_for_session: boolean };
  profile: {
    personal: PersonalProfileWire;
    academic: AcademicProfileWire;
    interests: { interests: string[]; goals: string[] };
  };
}

export interface PersonalProfileInput extends PersonalProfile {
  expectedProfileVersion: number;
}

export interface AcademicProfileInput extends AcademicProfile {
  expectedProfileVersion: number;
}

export interface InterestsProfileInput extends InterestsProfile {
  expectedProfileVersion: number;
}

export interface ProfileMutationResult {
  projection: StudentProfileProjection;
  certainty: 'confirmed' | 'reconciled';
}

export class ProfileApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly field?: string,
    readonly currentProfileVersion?: number,
    readonly currentProjection?: StudentProfileProjection,
    readonly latestProjection?: StudentProfileProjection,
    readonly retryAfterSeconds?: number,
  ) {
    super(code);
    this.name = 'ProfileApiError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function normalizedOptionalText(value: unknown, maximum: number): value is string | null {
  if (value === null) return true;
  if (typeof value !== 'string' || [...value].length < 1 || [...value].length > maximum) return false;
  return value === value.normalize('NFC').trim().replace(/\s+/gu, ' ');
}

function codePointCompare(left: string, right: string): number {
  const a = [...left]; const b = [...right];
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const difference = Number(a[index].codePointAt(0)) - Number(b[index].codePointAt(0));
    if (difference !== 0) return difference;
  }
  return a.length - b.length;
}

function isProfileValueArray(value: unknown): value is string[] {
  if (!Array.isArray(value) || value.length > 20) return false;
  if (!value.every((item) => normalizedOptionalText(item, 80) && item !== null)) return false;
  if (new Set(value).size !== value.length) return false;
  return value.every((item, index) => index === 0 || codePointCompare(value[index - 1], item) < 0);
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function isPersonalWire(value: unknown): value is PersonalProfileWire {
  if (!isRecord(value) || !hasExactKeys(value, [
    'city', 'date_of_birth', 'first_name', 'last_name', 'middle_name', 'preferred_language', 'pronouns',
  ])) return false;
  return typeof value.first_name === 'string'
    && validateLegalName(value.first_name)
    && normalizeLegalName(value.first_name) === value.first_name
    && (value.middle_name === null
      || (typeof value.middle_name === 'string'
        && validateLegalName(value.middle_name)
        && normalizeLegalName(value.middle_name) === value.middle_name))
    && typeof value.last_name === 'string'
    && validateLegalName(value.last_name)
    && normalizeLegalName(value.last_name) === value.last_name
    && isIsoDate(value.date_of_birth)
    && (value.preferred_language === null
      || value.preferred_language === 'en'
      || value.preferred_language === 'hi')
    && normalizedOptionalText(value.city, 120)
    && normalizedOptionalText(value.pronouns, 60);
}

function isAcademicWire(value: unknown): value is AcademicProfileWire {
  if (!isRecord(value) || !hasExactKeys(value, [
    'bar_enrolment_number', 'college', 'enrolment_number', 'institutional_email', 'year_of_study',
  ])) return false;
  return normalizedOptionalText(value.college, 160)
    && normalizedOptionalText(value.year_of_study, 40)
    && normalizedOptionalText(value.enrolment_number, 120)
    && (value.enrolment_number === null || /^[A-Za-z]{2}\/\d+\/\d{4}$/u.test(value.enrolment_number))
    && normalizedOptionalText(value.institutional_email, 254)
    && (value.institutional_email === null
      || (institutionalEmailError(value.institutional_email) === undefined
        && value.institutional_email === value.institutional_email.toLowerCase()))
    && normalizedOptionalText(value.bar_enrolment_number, 120);
}

function isInterestsWire(value: unknown): value is { interests: string[]; goals: string[] } {
  return isRecord(value)
    && hasExactKeys(value, ['goals', 'interests'])
    && isProfileValueArray(value.interests)
    && isProfileValueArray(value.goals);
}

function isProjectionWire(value: unknown): value is StudentProfileProjectionWire {
  if (!isRecord(value) || !hasExactKeys(value, PROJECTION_KEYS)) return false;
  if (!Number.isSafeInteger(value.profile_version) || Number(value.profile_version) < 1) return false;
  if (value.completion_version !== 'v1') return false;

  const completionRows = [
    { percent: 0, sections: [], next: 'personal', complete: false },
    { percent: 34, sections: ['personal'], next: 'academic', complete: false },
    { percent: 67, sections: ['personal', 'academic'], next: 'interests', complete: false },
    { percent: 100, sections: ['personal', 'academic', 'interests'], next: null, complete: true },
  ] as const;
  const completion = completionRows.find((row) => row.percent === value.completion_percent);
  if (!completion
    || !Array.isArray(value.completed_sections)
    || value.completed_sections.length !== completion.sections.length
    || !value.completed_sections.every((section, index) => section === completion.sections[index])
    || value.next_incomplete_section !== completion.next
    || value.is_complete !== completion.complete
  ) return false;

  if (!['not_provided', 'pending', 'verified', 'rejected', 'expired', 'revoked']
    .includes(String(value.institutional_email_status))) return false;
  if (!isRecord(value.guardian)
    || !hasExactKeys(value.guardian, ['required', 'status'])
    || typeof value.guardian.required !== 'boolean'
    || !['not_required', 'required_pending', 'verified', 'rejected', 'revoked']
      .includes(String(value.guardian.status))) return false;
  if (!['full', 'limited'].includes(String(value.access_mode))) return false;
  if (!Array.isArray(value.disabled_capabilities)
    || !value.disabled_capabilities.every((item) => item === 'community' || item === 'sharing')
    || new Set(value.disabled_capabilities).size !== value.disabled_capabilities.length) return false;
  if (!isRecord(value.profile_prompt)
    || !hasExactKeys(value.profile_prompt, ['dismissed_for_session', 'should_show'])
    || typeof value.profile_prompt.should_show !== 'boolean'
    || typeof value.profile_prompt.dismissed_for_session !== 'boolean') return false;
  if (!isRecord(value.profile)
    || !hasExactKeys(value.profile, ['academic', 'interests', 'personal'])
    || !isPersonalWire(value.profile.personal)
    || !isAcademicWire(value.profile.academic)
    || !isInterestsWire(value.profile.interests)) return false;

  const expectedMissing: ProfileRequirement[] = [];
  if (value.profile.personal.preferred_language === null) {
    expectedMissing.push('personal.preferred_language');
  }
  if (!value.profile.personal.city) expectedMissing.push('personal.city');
  if (!value.profile.academic.college) expectedMissing.push('academic.college');
  if (!value.profile.academic.year_of_study) expectedMissing.push('academic.year_of_study');
  if (!value.profile.academic.enrolment_number) {
    expectedMissing.push('academic.enrolment_number');
  }
  if (value.profile.interests.interests.length === 0) {
    expectedMissing.push('interests.interests');
  }
  if (value.profile.interests.goals.length === 0) {
    expectedMissing.push('interests.goals');
  }
  if (!Array.isArray(value.missing_requirements)
    || value.missing_requirements.length !== expectedMissing.length
    || !value.missing_requirements.every(
      (requirement, index) => requirement === expectedMissing[index],
    )) return false;

  const guardianConsistent = value.guardian.required
    ? value.guardian.status !== 'not_required'
    : value.guardian.status === 'not_required';
  if (!guardianConsistent) return false;
  const expectedLimited = value.guardian.required && value.guardian.status !== 'verified';
  if (value.access_mode !== (expectedLimited ? 'limited' : 'full')) return false;
  const expectedDisabled = expectedLimited ? ['community', 'sharing'] : [];
  if (value.disabled_capabilities.length !== expectedDisabled.length
    || !value.disabled_capabilities.every((item, index) => item === expectedDisabled[index])) return false;
  if (value.profile_prompt.should_show
    !== (!value.is_complete && !value.profile_prompt.dismissed_for_session)) return false;
  const personalComplete = value.profile.personal.preferred_language !== null
    && Boolean(value.profile.personal.city);
  const academicComplete = Boolean(
    value.profile.academic.college
    && value.profile.academic.year_of_study
    && value.profile.academic.enrolment_number,
  );
  const interestsComplete = value.profile.interests.interests.length > 0
    && value.profile.interests.goals.length > 0;
  const computedSectionCount = personalComplete
    ? academicComplete ? interestsComplete ? 3 : 2 : 1
    : 0;
  if (value.completed_sections.length !== computedSectionCount) return false;
  if (value.profile.academic.institutional_email === null
    ? value.institutional_email_status !== 'not_provided'
    : value.institutional_email_status === 'not_provided') return false;
  return true;
}

function mapProjection(wire: StudentProfileProjectionWire): StudentProfileProjection {
  return {
    profileVersion: wire.profile_version,
    completionVersion: wire.completion_version,
    completionPercent: wire.completion_percent,
    completedSections: [...wire.completed_sections],
    missingRequirements: [...wire.missing_requirements],
    nextIncompleteSection: wire.next_incomplete_section,
    isComplete: wire.is_complete,
    institutionalEmailStatus: wire.institutional_email_status,
    guardian: { ...wire.guardian },
    accessMode: wire.access_mode,
    disabledCapabilities: [...wire.disabled_capabilities],
    profilePrompt: {
      shouldShow: wire.profile_prompt.should_show,
      dismissedForSession: wire.profile_prompt.dismissed_for_session,
    },
    profile: {
      personal: {
        firstName: wire.profile.personal.first_name,
        middleName: wire.profile.personal.middle_name,
        lastName: wire.profile.personal.last_name,
        dateOfBirth: wire.profile.personal.date_of_birth,
        preferredLanguage: wire.profile.personal.preferred_language,
        city: wire.profile.personal.city,
        pronouns: wire.profile.personal.pronouns,
      },
      academic: {
        college: wire.profile.academic.college,
        yearOfStudy: wire.profile.academic.year_of_study,
        enrolmentNumber: wire.profile.academic.enrolment_number,
        institutionalEmail: wire.profile.academic.institutional_email,
        barEnrolmentNumber: wire.profile.academic.bar_enrolment_number,
      },
      interests: {
        interests: [...wire.profile.interests.interests],
        goals: [...wire.profile.interests.goals],
      },
    },
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ProfileApiError(502, 'invalid_profile_response');
  }
}

function projectionFromUnknown(value: unknown): StudentProfileProjection {
  if (!isProjectionWire(value)) {
    throw new ProfileApiError(502, 'invalid_profile_projection');
  }
  return mapProjection(value);
}

/** Strict parser shared by profile reads and atomic authentication responses. */
export function parseStudentProfileProjection(value: unknown): StudentProfileProjection {
  return projectionFromUnknown(value);
}

async function profileRequest(path: string, init: RequestInit): Promise<StudentProfileProjection> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const response = await studentApiFetch(path, { ...init, headers });
  const body = await readJson(response);
  if (response.ok) return projectionFromUnknown(body);

  const detail = isRecord(body) && isRecord(body.detail) ? body.detail : undefined;
  const code = typeof detail?.code === 'string' ? detail.code : `http_${response.status}`;
  const field = typeof detail?.field === 'string' ? detail.field : undefined;
  let currentProjection: StudentProfileProjection | undefined;
  if (detail?.current_projection !== undefined) {
    currentProjection = projectionFromUnknown(detail.current_projection);
  }
  const currentProfileVersion = Number.isSafeInteger(detail?.current_profile_version)
    ? Number(detail?.current_profile_version)
    : undefined;
  throw new ProfileApiError(
    response.status,
    code,
    field,
    currentProfileVersion,
    currentProjection,
  );
}

async function boundedProfileRequest(
  path: string,
  init: RequestInit,
  timeoutCode?: string,
): Promise<StudentProfileProjection> {
  const controller = new AbortController();
  const sourceSignal = init.signal;
  let timedOut = false;
  const forwardAbort = () => controller.abort(sourceSignal?.reason);
  if (sourceSignal?.aborted) forwardAbort();
  else sourceSignal?.addEventListener('abort', forwardAbort, { once: true });
  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort('profile_request_timeout');
  }, PROFILE_WRITE_TIMEOUT_MS);
  try {
    return await profileRequest(path, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut && timeoutCode) throw new ProfileApiError(0, timeoutCode);
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
    sourceSignal?.removeEventListener('abort', forwardAbort);
  }
}

export function getStudentProfileProjection(signal?: AbortSignal): Promise<StudentProfileProjection> {
  return boundedProfileRequest(PROFILE_ROOT, { method: 'GET', signal }, 'profile_request_timeout');
}

function nullableTrimmed(value: string | null): string | null {
  if (value === null) return null;
  const trimmed = value.normalize('NFC').trim().replace(/\s+/gu, ' ');
  return trimmed || null;
}

function normalizedPersonal(input: PersonalProfileInput): PersonalProfile {
  return {
    firstName: normalizeLegalName(input.firstName),
    middleName: input.middleName === null ? null : normalizeLegalName(input.middleName),
    lastName: normalizeLegalName(input.lastName),
    dateOfBirth: input.dateOfBirth,
    preferredLanguage: input.preferredLanguage,
    city: nullableTrimmed(input.city),
    pronouns: nullableTrimmed(input.pronouns),
  };
}

function normalizedAcademic(input: AcademicProfileInput): AcademicProfile {
  return {
    college: nullableTrimmed(input.college),
    yearOfStudy: nullableTrimmed(input.yearOfStudy),
    enrolmentNumber: nullableTrimmed(input.enrolmentNumber),
    institutionalEmail: nullableTrimmed(input.institutionalEmail)?.toLowerCase() ?? null,
    barEnrolmentNumber: nullableTrimmed(input.barEnrolmentNumber),
  };
}

function normalizedList(values: string[]): string[] {
  return [...new Set(values
    .map((item) => item.normalize('NFC').trim().replace(/\s+/gu, ' '))
    .filter(Boolean))];
}

function normalizedInterests(input: InterestsProfileInput): InterestsProfile {
  return { interests: normalizedList(input.interests), goals: normalizedList(input.goals) };
}

function samePersonal(a: PersonalProfile, b: PersonalProfile): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function sameAcademic(a: AcademicProfile, b: AcademicProfile): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function sameInterests(a: InterestsProfile, b: InterestsProfile): boolean {
  const sameValues = (left: string[], right: string[]) => {
    const sortedLeft = [...left].sort(codePointCompare);
    const sortedRight = [...right].sort(codePointCompare);
    return sortedLeft.length === sortedRight.length
      && sortedLeft.every((value, index) => value === sortedRight[index]);
  };
  return sameValues(a.interests, b.interests) && sameValues(a.goals, b.goals);
}

async function reconcileAfterUnknown(
  expectedProfileVersion: number,
  matches: (projection: StudentProfileProjection) => boolean,
  fence: StudentContextFence,
): Promise<ProfileMutationResult> {
  let latest: StudentProfileProjection | undefined;
  try {
    latest = await runStudentMutationStep(
      fence,
      (signal) => boundedProfileRequest(PROFILE_ROOT, { method: 'GET', signal }),
    );
  } catch {
    throw new ProfileApiError(0, 'profile_write_uncertain');
  }
  if (latest.profileVersion === expectedProfileVersion + 1 && matches(latest)) {
    return { projection: latest, certainty: 'reconciled' };
  }
  throw new ProfileApiError(
    0,
    'profile_write_uncertain',
    undefined,
    undefined,
    undefined,
    latest,
  );
}

function requiresWriteReconciliation(error: unknown): boolean {
  return !(error instanceof ProfileApiError)
    || (error.status >= 500 && error.status <= 599);
}

async function sectionMutation(
  path: string,
  expectedProfileVersion: number,
  body: Record<string, unknown>,
  matches: (projection: StudentProfileProjection) => boolean,
): Promise<ProfileMutationResult> {
  const fence = captureStudentContextFence();
  const idempotencyKey = newProfileMutationIdempotencyKey();
  if (!Number.isSafeInteger(expectedProfileVersion) || expectedProfileVersion < 1) {
    throw new ProfileApiError(422, 'invalid_expected_profile_version', 'expected_profile_version');
  }
  try {
    const projection = await runStudentMutationStep(
      fence,
      (signal) => boundedProfileRequest(path, {
        method: 'PATCH',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ expected_profile_version: expectedProfileVersion, ...body }),
        signal,
      }),
    );
    if (projection.profileVersion === expectedProfileVersion + 1 && matches(projection)) {
      return { projection, certainty: 'confirmed' };
    }
    // A valid 2xx shape is not sufficient proof if a later writer contaminated
    // the response or the returned section differs from the submitted values.
    // Re-read once and preserve the caller's draft unless authority is proven.
    return reconcileAfterUnknown(expectedProfileVersion, matches, fence);
  } catch (error) {
    if (error instanceof ProfileApiError) {
      if (!requiresWriteReconciliation(error)) throw error;
    }
    return reconcileAfterUnknown(expectedProfileVersion, matches, fence);
  }
}

/** One memory-only opaque key per profile mutation attempt. */
export function newProfileMutationIdempotencyKey(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) return randomUuid;
  const bytes = new Uint8Array(24);
  if (!globalThis.crypto?.getRandomValues) {
    throw new ProfileApiError(0, 'secure_idempotency_unavailable');
  }
  globalThis.crypto.getRandomValues(bytes);
  return `profile-${[...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}

export function updatePersonalProfile(input: PersonalProfileInput): Promise<ProfileMutationResult> {
  const personal = normalizedPersonal(input);
  if (!validateLegalName(personal.firstName)
    || !validateLegalName(personal.lastName)
    || (personal.middleName !== null && !validateLegalName(personal.middleName))) {
    throw new ProfileApiError(422, 'invalid_legal_name', 'first_name');
  }
  if (personal.pronouns !== null && [...personal.pronouns].length > 60) {
    throw new ProfileApiError(422, 'invalid_pronouns', 'pronouns');
  }
  return sectionMutation(
    `${PROFILE_ROOT}/personal`,
    input.expectedProfileVersion,
    {
      first_name: personal.firstName,
      middle_name: personal.middleName,
      last_name: personal.lastName,
      date_of_birth: personal.dateOfBirth,
      preferred_language: personal.preferredLanguage,
      city: personal.city,
      pronouns: personal.pronouns,
    },
    (projection) => samePersonal(projection.profile.personal, personal),
  );
}

export function updateAcademicProfile(input: AcademicProfileInput): Promise<ProfileMutationResult> {
  const academic = normalizedAcademic(input);
  return sectionMutation(
    `${PROFILE_ROOT}/academic`,
    input.expectedProfileVersion,
    {
      college: academic.college,
      year_of_study: academic.yearOfStudy,
      enrolment_number: academic.enrolmentNumber,
      institutional_email: academic.institutionalEmail,
      bar_enrolment_number: academic.barEnrolmentNumber,
    },
    (projection) => sameAcademic(projection.profile.academic, academic),
  );
}

export function updateInterestsProfile(input: InterestsProfileInput): Promise<ProfileMutationResult> {
  const interests = normalizedInterests(input);
  return sectionMutation(
    `${PROFILE_ROOT}/interests`,
    input.expectedProfileVersion,
    { interests: interests.interests, goals: interests.goals },
    (projection) => sameInterests(projection.profile.interests, interests),
  );
}

export async function dismissProfilePrompt(): Promise<ProfileMutationResult> {
  const fence = captureStudentContextFence();
  try {
    const projection = await runStudentMutationStep(
      fence,
      (signal) => boundedProfileRequest(`${PROFILE_ROOT}/prompt-dismiss`, {
        method: 'POST',
        body: JSON.stringify({}),
        signal,
      }),
    );
    return { projection, certainty: 'confirmed' };
  } catch (error) {
    if (!requiresWriteReconciliation(error)) throw error;
    let projection: StudentProfileProjection;
    try {
      projection = await runStudentMutationStep(
        fence,
        (signal) => boundedProfileRequest(PROFILE_ROOT, { method: 'GET', signal }),
      );
    } catch {
      throw new ProfileApiError(0, 'profile_write_uncertain');
    }
    if (projection.profilePrompt.dismissedForSession && !projection.profilePrompt.shouldShow) {
      return { projection, certainty: 'reconciled' };
    }
    throw new ProfileApiError(0, 'profile_write_uncertain', undefined, undefined, undefined, projection);
  }
}

export async function requestInstitutionalEmailVerification(): Promise<ProfileMutationResult> {
  const fence = captureStudentContextFence();
  try {
    const projection = await runStudentMutationStep(
      fence,
      (signal) => boundedProfileRequest(
        '/api/v1/auth/student/verification/email/request',
        { method: 'POST', body: JSON.stringify({}), signal },
      ),
    );
    return { projection, certainty: 'confirmed' };
  } catch (error) {
    if (!requiresWriteReconciliation(error)) throw error;
    let projection: StudentProfileProjection;
    try {
      projection = await runStudentMutationStep(
        fence,
        (signal) => boundedProfileRequest(PROFILE_ROOT, { method: 'GET', signal }),
      );
    } catch {
      throw new ProfileApiError(0, 'profile_write_uncertain');
    }
    // A saved-but-unrequested email already projects as `pending`. Therefore a
    // pending refetch cannot prove that an uncertain POST reached the server.
    // Only a concurrently completed authorized review is conclusive here.
    if (projection.institutionalEmailStatus === 'verified') {
      return { projection, certainty: 'reconciled' };
    }
    throw new ProfileApiError(
      0,
      'profile_write_uncertain',
      undefined,
      undefined,
      undefined,
      projection,
    );
  }
}

export function profileSectionRoute(section: ProfileSection | null): string {
  if (section === 'personal' || section === 'academic') return `/s-10?section=${section}`;
  if (section === 'interests') return '/s-11';
  return '/s-12';
}

export function profileErrorMessage(error: unknown): string {
  if (!(error instanceof ProfileApiError)) {
    return 'Your profile could not be saved. Check your connection and try again.';
  }
  if (error.status === 401) return 'Your session ended. Sign in again before saving.';
  if (error.code === 'dob_step_up_required') {
    return 'Changing this verified date of birth needs an additional identity check.';
  }
  if (error.code === 'profile_version_conflict') {
    return 'This profile changed in another tab. Review the latest values before saving again.';
  }
  if (error.code === 'profile_write_uncertain') {
    return 'We could not confirm whether your changes were saved. Your page is unchanged; retry after checking the latest profile.';
  }
  if (error.status === 429) return 'Too many requests. Wait a moment, then try again.';
  if (error.status === 422) return 'Review the highlighted fields and try again.';
  if (error.status === 403) return 'This account is not permitted to change that profile section.';
  return 'Your profile could not be saved. Check your connection and try again.';
}


/* -------------------------------------------------------------------------- */
/* NYAY-12 verified-email identities (owner-scoped, server-authoritative)      */
/* -------------------------------------------------------------------------- */
const EMAIL_IDENTITY_ROOT = '/api/v1/auth/student/email-identities';
const EMAIL_IDENTITY_KEY_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-';
const EMAIL_MASK_RE = /^[^\s@•]•{5}@[^\s@]+\.[^\s@]+$/u;
const IDENTITY_STATES = ['pending', 'verified', 'removed'] as const;
const VERIFICATION_STATUSES = ['none', 'pending_delivery', 'active', 'failed', 'expired'] as const;

export type EmailIdentityState = (typeof IDENTITY_STATES)[number];
export type EmailIdentityVerificationStatus = (typeof VERIFICATION_STATUSES)[number];

export interface EmailIdentity {
  id: string;
  emailMasked: string;
  state: EmailIdentityState;
  isPrimary: boolean;
  verification: {
    status: EmailIdentityVerificationStatus;
    expiresInSeconds: number | null;
    resendInSeconds: number | null;
    attemptsLeft: number | null;
  };
}

export interface EmailIdentityListing {
  loginChannelEnabled: boolean;
  maxIdentities: number;
  identities: EmailIdentity[];
}

export interface EmailIdentityMutationResult {
  status: 'accepted' | 'verified' | 'removed' | 'primary';
  identity: EmailIdentity;
}

interface EmailIdentityWire {
  id: string;
  email_masked: string;
  state: EmailIdentityState;
  is_primary: boolean;
  verification: {
    status: EmailIdentityVerificationStatus;
    expires_in_seconds: number | null;
    resend_in_seconds: number | null;
    attempts_left: number | null;
  };
}

function relativeOrNull(value: unknown): value is number | null {
  return value === null || (Number.isSafeInteger(value) && Number(value) >= 0);
}

function isEmailIdentityWire(value: unknown): value is EmailIdentityWire {
  if (!isRecord(value) || !hasExactKeys(value, ['email_masked', 'id', 'is_primary', 'state', 'verification'])) return false;
  if (typeof value.id !== 'string' || !/^[0-9a-f-]{36}$/u.test(value.id)) return false;
  if (typeof value.email_masked !== 'string' || !EMAIL_MASK_RE.test(value.email_masked)) return false;
  if (!IDENTITY_STATES.includes(value.state as EmailIdentityState)) return false;
  if (typeof value.is_primary !== 'boolean') return false;
  if (value.is_primary && value.state !== 'verified') return false;
  const verification = value.verification;
  if (!isRecord(verification) || !hasExactKeys(verification, ['attempts_left', 'expires_in_seconds', 'resend_in_seconds', 'status'])) return false;
  return VERIFICATION_STATUSES.includes(verification.status as EmailIdentityVerificationStatus)
    && relativeOrNull(verification.expires_in_seconds)
    && relativeOrNull(verification.resend_in_seconds)
    && relativeOrNull(verification.attempts_left);
}

function mapEmailIdentity(wire: EmailIdentityWire): EmailIdentity {
  return {
    id: wire.id,
    emailMasked: wire.email_masked,
    state: wire.state,
    isPrimary: wire.is_primary,
    verification: {
      status: wire.verification.status,
      expiresInSeconds: wire.verification.expires_in_seconds,
      resendInSeconds: wire.verification.resend_in_seconds,
      attemptsLeft: wire.verification.attempts_left,
    },
  };
}

function invalidIdentityProjection(): ProfileApiError {
  return new ProfileApiError(502, 'invalid_email_identity_projection');
}

export function newEmailIdentityIdempotencyKey(): string {
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  return `ei-${Array.from(bytes, (byte) => EMAIL_IDENTITY_KEY_ALPHABET[byte % EMAIL_IDENTITY_KEY_ALPHABET.length]).join('')}`;
}

export interface EmailIdentityRequestOptions {
  /** Reuse across retries of the *same* operation; generated once when absent. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

const EMAIL_IDENTITY_KEY_RE = /^[A-Za-z0-9._~-]{16,200}$/u;

function resolvedIdempotencyKey(supplied: string | undefined): string {
  if (supplied === undefined) return newEmailIdentityIdempotencyKey();
  if (!EMAIL_IDENTITY_KEY_RE.test(supplied)) {
    throw new ProfileApiError(422, 'invalid_idempotency_key', 'Idempotency-Key');
  }
  return supplied;
}

async function identityRequest(
  path: string,
  init: RequestInit,
  idempotent: boolean,
  options: EmailIdentityRequestOptions = {},
): Promise<unknown> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  // A caller-supplied key is preserved verbatim so the same operation can be
  // retried safely; a key is generated only when none is present.
  if (idempotent && !headers.has('Idempotency-Key')) {
    headers.set('Idempotency-Key', resolvedIdempotencyKey(options.idempotencyKey));
  }
  const response = await studentApiFetch(path, { ...init, headers, signal: options.signal ?? init.signal });
  const body = await readJson(response);
  if (response.ok) return body;
  const detail = isRecord(body) && isRecord(body.detail) ? body.detail : undefined;
  const code = typeof detail?.code === 'string' ? detail.code : `http_${response.status}`;
  const field = typeof detail?.field === 'string' ? detail.field : undefined;
  const retryAfter = response.headers.get('Retry-After');
  const retryAfterSeconds = retryAfter !== null && /^\d+$/u.test(retryAfter.trim()) ? Number(retryAfter.trim()) : undefined;
  throw new ProfileApiError(response.status, code, field, undefined, undefined, undefined, retryAfterSeconds);
}

function listingFromUnknown(value: unknown): EmailIdentityListing {
  if (!isRecord(value) || !hasExactKeys(value, ['identities', 'login_channel_enabled', 'max_identities'])) throw invalidIdentityProjection();
  if (typeof value.login_channel_enabled !== 'boolean' || !Number.isSafeInteger(value.max_identities) || Number(value.max_identities) < 1) throw invalidIdentityProjection();
  if (!Array.isArray(value.identities) || !value.identities.every(isEmailIdentityWire)) throw invalidIdentityProjection();
  return {
    loginChannelEnabled: value.login_channel_enabled,
    maxIdentities: Number(value.max_identities),
    identities: (value.identities as EmailIdentityWire[]).map(mapEmailIdentity),
  };
}

function mutationFromUnknown(value: unknown, expected: EmailIdentityMutationResult['status']): EmailIdentityMutationResult {
  if (!isRecord(value) || !hasExactKeys(value, ['identity', 'status']) || value.status !== expected || !isEmailIdentityWire(value.identity)) {
    throw invalidIdentityProjection();
  }
  return { status: expected, identity: mapEmailIdentity(value.identity) };
}

export async function listEmailIdentities(signal?: AbortSignal): Promise<EmailIdentityListing> {
  return listingFromUnknown(await identityRequest(EMAIL_IDENTITY_ROOT, { method: 'GET', signal }, false, { signal }));
}

export async function addEmailIdentity(email: string, options: EmailIdentityRequestOptions = {}): Promise<EmailIdentityMutationResult> {
  return mutationFromUnknown(await identityRequest(EMAIL_IDENTITY_ROOT, { method: 'POST', body: JSON.stringify({ email }) }, true, options), 'accepted');
}

export async function verifyEmailIdentity(identityId: string, code: string, options: EmailIdentityRequestOptions = {}): Promise<EmailIdentityMutationResult> {
  return mutationFromUnknown(await identityRequest(`${EMAIL_IDENTITY_ROOT}/${identityId}/verify`, { method: 'POST', body: JSON.stringify({ code }) }, true, options), 'verified');
}

export async function resendEmailIdentity(identityId: string, options: EmailIdentityRequestOptions = {}): Promise<EmailIdentityMutationResult> {
  return mutationFromUnknown(await identityRequest(`${EMAIL_IDENTITY_ROOT}/${identityId}/resend`, { method: 'POST', body: JSON.stringify({}) }, true, options), 'accepted');
}

export async function removeEmailIdentity(identityId: string, options: EmailIdentityRequestOptions = {}): Promise<EmailIdentityMutationResult> {
  return mutationFromUnknown(await identityRequest(`${EMAIL_IDENTITY_ROOT}/${identityId}`, { method: 'DELETE' }, true, options), 'removed');
}

export async function setPrimaryEmailIdentity(identityId: string, options: EmailIdentityRequestOptions = {}): Promise<EmailIdentityMutationResult> {
  return mutationFromUnknown(await identityRequest(`${EMAIL_IDENTITY_ROOT}/${identityId}/primary`, { method: 'POST', body: JSON.stringify({}) }, true, options), 'primary');
}

export function emailIdentityErrorMessage(error: unknown): string {
  if (!(error instanceof ProfileApiError)) {
    return 'That change could not be saved. Check your connection and try again.';
  }
  switch (error.code) {
    case 'authentication_required': return 'Your session ended. Sign in again before changing sign-in emails.';
    case 'email_identity_capability_disabled': return 'Sign-in emails are unavailable until your account prerequisites are complete.';
    case 'email_identity_conflict': return 'This address cannot be used for sign-in on this account. It is already the verified sign-in email of another account; support review has been recorded.';
    case 'email_identity_verification_failed': return 'That code was not accepted. Check the latest code or request a new one.';
    case 'email_identity_rate_limited': return error.retryAfterSeconds
      ? `Please wait ${error.retryAfterSeconds} seconds before trying again.`
      : 'Please wait before trying again.';
    case 'email_delivery_unavailable': return 'The code could not be delivered right now. Try resending in a moment.';
    case 'email_identity_limit_reached': return 'You have reached the maximum number of sign-in emails. Remove one to add another.';
    case 'email_identity_state_conflict': return 'That action is not available for this address right now. Refresh and try again.';
    case 'email_identity_not_found': return 'That sign-in email is no longer on your account.';
    case 'validation_error': return error.field === 'code' ? 'Enter all six digits.' : 'Enter a valid email address.';
    default: return 'That change could not be saved. Please retry.';
  }
}

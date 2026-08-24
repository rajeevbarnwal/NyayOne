/**
 * Shared student-registration validation contract (SAATHI-388 / SAATHI-421).
 *
 * Single source of truth for the S-05 registration defects confirmed by the
 * Product Owner (26 Jul 2026):
 *   - Mobile must be EXACTLY 10 ASCII digits (reject shorter AND longer; never
 *     strip arbitrary non-digits then accept the remainder).
 *   - Date of birth must be a real calendar date, not in the (local) future.
 *   - Legal name is split into First (required) / Middle (optional) / Last
 *     (required), Unicode-aware, with a compatibility mapping to legacy fullName.
 *
 * Pure and framework-free so it is unit-testable and reused by the UI, the
 * profile draft, and any payload boundary.
 */
import { isValidDateOfBirth } from './consent';
import {
  LEGAL_NAME_MAX_CODE_POINTS,
  normalizeLegalName,
  validateLegalName,
} from './legalName';

// ---- Mobile ---------------------------------------------------------------
export const MOBILE_RE = /^\d{10}$/;
export const MOBILE_ERROR = 'Mobile number must be exactly 10 digits.';

/** Exactly 10 ASCII digits on the RAW value — no stripping, no coercion. */
export function isValidMobile(value: unknown): value is string {
  return typeof value === 'string' && MOBILE_RE.test(value);
}

// ---- Date of birth --------------------------------------------------------
export const DOB_ERROR = 'Enter a valid date of birth that is not in the future.';

/** Local calendar date as YYYY-MM-DD (never a UTC slice that shifts near midnight). */
export function todayLocalISO(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * A registrable DOB: real YYYY-MM-DD calendar date (rejects impossible dates
 * such as 2026-02-31) that is not after the user's LOCAL current date.
 */
export function isRegistrableDob(dobISO: string, now: Date = new Date()): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dobISO)) return false;
  const d = new Date(`${dobISO}T00:00:00.000Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== dobISO) return false; // impossible date
  // Lexicographic compare of YYYY-MM-DD is a correct local-date comparison.
  return dobISO <= todayLocalISO(now);
}

/** Retained UTC-based validator (used elsewhere) is still honoured for impossible dates. */
export function isRealCalendarDate(dobISO: string): boolean {
  return isValidDateOfBirth(dobISO, new Date().toISOString()) || (/^\d{4}-\d{2}-\d{2}$/.test(dobISO) && isRegistrableDob(dobISO));
}

// ---- Split legal name -----------------------------------------------------
export const NAME_MAX = LEGAL_NAME_MAX_CODE_POINTS; // per sub-field
export type NameField = 'firstName' | 'middleName' | 'lastName';
export type NamePartError = 'required' | 'too_long' | 'invalid';

export interface NameParts {
  readonly firstName: string;
  readonly middleName: string;
  readonly lastName: string;
}
export interface NamePayload {
  readonly firstName: string;
  readonly middleName: string | null;
  readonly lastName: string;
}

/** Validate one name sub-field; returns null when valid or a typed reason. */
export function validateNamePart(value: string, opts: { required: boolean; max?: number }): NamePartError | null {
  const max = opts.max ?? NAME_MAX;
  const normalized = normalizeLegalName(value ?? '');
  if (!normalized) return opts.required ? 'required' : null;
  if ([...normalized].length > max) return 'too_long';
  if (!validateLegalName(value)) return 'invalid';
  return null;
}

/** Field-specific errors for the whole name group (empty object when valid). */
export function validateNameParts(p: NameParts, max: number = NAME_MAX): Partial<Record<NameField, NamePartError>> {
  const e: Partial<Record<NameField, NamePartError>> = {};
  const f = validateNamePart(p.firstName, { required: true, max });
  if (f) e.firstName = f;
  const m = validateNamePart(p.middleName, { required: false, max });
  if (m) e.middleName = m;
  const l = validateNamePart(p.lastName, { required: true, max });
  if (l) e.lastName = l;
  return e;
}

/** Human message for a field error (used by the UI). */
export function nameErrorMessage(field: NameField, reason: NamePartError): string {
  const label = field === 'firstName' ? 'First name' : field === 'middleName' ? 'Middle name' : 'Last name';
  if (reason === 'required') return `Enter your ${label.toLowerCase()}.`;
  if (reason === 'too_long') return `${label} must be ${NAME_MAX} characters or fewer.`;
  return `${label} contains characters that aren't allowed.`;
}

/** Canonical payload: firstName, middleName (normalized string | null), lastName. */
export function namePartsToPayload(p: NameParts): NamePayload {
  const mid = normalizeLegalName(p.middleName);
  return {
    firstName: normalizeLegalName(p.firstName),
    middleName: mid ? mid : null,
    lastName: normalizeLegalName(p.lastName),
  };
}

/** Compatibility display name — no double spaces when Middle Name is absent. */
export function composeDisplayName(p: NameParts): string {
  return [p.firstName, p.middleName, p.lastName]
    .map((s) => normalizeLegalName(s ?? ''))
    .filter(Boolean)
    .join(' ')
    .trim();
}

// ---- Student registration command (explicit typed payload boundary) -------
export interface StudentRegistrationCommand {
  readonly firstName: string;
  readonly middleName: string | null;
  readonly lastName: string;
  readonly fullName: string;
  readonly mobile: string;
}
export type BuildCommandResult =
  | { ok: true; command: StudentRegistrationCommand }
  | { ok: false; errors: Partial<Record<NameField | 'mobile', string>> };

/**
 * Build the canonical student-registration command from raw UI fields. Validates
 * name parts + mobile; on success returns a typed payload (firstName,
 * middleName|null, lastName, derived fullName and raw 10-digit mobile). A
 * rejected validation returns typed errors and NO command — callers
 * must not progress OTP or persist on `ok: false`.
 */
export function buildStudentRegistrationCommand(input: {
  firstName: string; middleName: string; lastName: string; mobile: string;
}): BuildCommandResult {
  const errors: Partial<Record<NameField | 'mobile', string>> = {};
  const ne = validateNameParts({ firstName: input.firstName, middleName: input.middleName, lastName: input.lastName });
  if (ne.firstName) errors.firstName = nameErrorMessage('firstName', ne.firstName);
  if (ne.middleName) errors.middleName = nameErrorMessage('middleName', ne.middleName);
  if (ne.lastName) errors.lastName = nameErrorMessage('lastName', ne.lastName);
  if (!isValidMobile(input.mobile)) errors.mobile = MOBILE_ERROR;
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  const parts = { firstName: input.firstName, middleName: input.middleName, lastName: input.lastName };
  const payload = namePartsToPayload(parts);
  return {
    ok: true,
    command: {
      firstName: payload.firstName,
      middleName: payload.middleName,
      lastName: payload.lastName,
      fullName: composeDisplayName(parts),
      mobile: input.mobile,
    },
  };
}

/** Mask a 10-digit mobile for a persisted/redacted snapshot (no full number stored). */
export function maskMobile(mobile: string): string {
  return isValidMobile(mobile) ? `••••••${mobile.slice(6)}` : '';
}

/** Migrate a legacy record that only has fullName into First/Middle/Last parts. */
export function fullNameToParts(fullName: string): NameParts {
  const tokens = normalizeLegalName(fullName ?? '').split(' ').filter(Boolean);
  if (tokens.length === 0) return { firstName: '', middleName: '', lastName: '' };
  if (tokens.length === 1) return { firstName: tokens[0], middleName: '', lastName: '' };
  return { firstName: tokens[0], middleName: tokens.slice(1, -1).join(' '), lastName: tokens[tokens.length - 1] };
}

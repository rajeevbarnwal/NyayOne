/**
 * Canonical value/label catalogs (SAATHI-58 D1/D2 remediation).
 *
 * WIRE VALUES are canonical API codes shared with the backend; LABELS are
 * display-only and must never be sent to the server. `toCanonical*` safely maps
 * legacy stored values (old display labels, abbreviations) onto canonical
 * codes so returning users hydrate correctly.
 */
export interface Option {
  value: string;
  label: string;
}

// D2 — language enum. Wire: 'en' | 'hi'. Labels rendered separately.
export type LanguageCode = 'en' | 'hi';
export const LANGUAGE_OPTIONS: readonly Option[] = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी (Hindi)' },
];

// D1 — college canonical values = official names (server seed/system of record).
export const COLLEGE_OPTIONS: readonly Option[] = [
  { value: 'National Law School of India University', label: 'National Law School of India University (NLSIU)' },
  { value: 'NALSAR University of Law', label: 'NALSAR University of Law' },
  { value: 'The West Bengal National University of Juridical Sciences', label: 'The West Bengal NUJS' },
  { value: 'Other', label: 'Other' },
];

// D1 — year canonical codes.
export const YEAR_OPTIONS: readonly Option[] = [
  { value: '1st', label: '1st year' },
  { value: '2nd', label: '2nd year' },
  { value: '3rd', label: '3rd year' },
  { value: '4th', label: '4th year · B.A. LL.B. (Hons.)' },
  { value: '5th', label: '5th year' },
  { value: 'llm', label: 'LL.M.' },
];

const LEGACY_COLLEGE: Record<string, string> = {
  'NLSIU': 'National Law School of India University',
  'National Law School of India University (NLSIU)': 'National Law School of India University',
  'NALSAR': 'NALSAR University of Law',
  'The West Bengal NUJS': 'The West Bengal National University of Juridical Sciences',
  'WBNUJS': 'The West Bengal National University of Juridical Sciences',
};

const LEGACY_YEAR: Record<string, string> = {
  '1st year': '1st', '2nd year': '2nd', '3rd year': '3rd',
  '4th year · B.A. LL.B. (Hons.)': '4th', '4th year': '4th', '5th year': '5th',
  'LL.M.': 'llm', 'LLM': 'llm',
};

/** Map any stored/legacy college value onto its canonical wire value. */
export function toCanonicalCollege(v: string | null | undefined): string | null {
  if (!v) return null;
  if (COLLEGE_OPTIONS.some((o) => o.value === v)) return v;
  return LEGACY_COLLEGE[v] ?? v;
}

/** Map any stored/legacy year value onto its canonical wire value. */
export function toCanonicalYear(v: string | null | undefined): string | null {
  if (!v) return null;
  if (YEAR_OPTIONS.some((o) => o.value === v)) return v;
  return LEGACY_YEAR[v] ?? v;
}

export function labelFor(options: readonly Option[], value: string | null | undefined): string {
  if (!value) return '';
  return options.find((o) => o.value === value)?.label ?? value;
}

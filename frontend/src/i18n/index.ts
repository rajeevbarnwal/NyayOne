import en from './locales/en.json';
import hi from './locales/hi.json';

/**
 * Lightweight i18n foundation (SAATHI-346). Strings are externalised into
 * per-locale JSON with EN as the base and HI ready. Fallback chain:
 * requested locale → English → the key itself. ICU-style {var} interpolation.
 *
 * This is a dependency-free core with a clear upgrade path to i18next/react-i18next
 * (same JSON namespaces) when the full runtime is adopted; kept pure so it is
 * unit-testable without a DOM.
 */
export type Locale = 'en-IN' | 'hi-IN';
export const DEFAULT_LOCALE: Locale = 'en-IN';
export const SUPPORTED_LOCALES: Locale[] = ['en-IN', 'hi-IN'];
export const LOCALE_STORAGE_KEY = 'nyayone.locale.v1';

type Dict = Record<string, string>;
const catalogs: Record<Locale, Dict> = { 'en-IN': en as Dict, 'hi-IN': hi as Dict };

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_m, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

/** Translate `key` for `locale`, falling back to English then the raw key. */
export function translate(
  key: string,
  vars?: Record<string, string | number>,
  locale: Locale = DEFAULT_LOCALE
): string {
  const primary = catalogs[locale]?.[key];
  const fallback = catalogs['en-IN']?.[key];
  return interpolate(primary ?? fallback ?? key, vars);
}

export function resolveInitialLocale(stored: string | null): Locale {
  return (SUPPORTED_LOCALES as string[]).includes(stored ?? '') ? (stored as Locale) : DEFAULT_LOCALE;
}

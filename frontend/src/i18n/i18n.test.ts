import { describe, expect, it } from 'vitest';
import { translate, resolveInitialLocale, DEFAULT_LOCALE, SUPPORTED_LOCALES } from './index';

describe('i18n foundation (SAATHI-346)', () => {
  it('translates EN and HI', () => {
    expect(translate('nav.home', undefined, 'en-IN')).toBe('Home');
    expect(translate('nav.home', undefined, 'hi-IN')).toBe('होम');
  });

  it('falls back HI→EN when a key is missing in HI, then to the key', () => {
    // 'privacy.minimisation' exists only in EN.
    expect(translate('privacy.minimisation', undefined, 'hi-IN')).toBe(
      translate('privacy.minimisation', undefined, 'en-IN')
    );
    // Unknown key falls back to the key itself.
    expect(translate('does.not.exist', undefined, 'hi-IN')).toBe('does.not.exist');
  });

  it('interpolates variables', () => {
    expect(translate('greeting.namaste', { name: 'Aarav' }, 'en-IN')).toBe('Namaste, Aarav');
    expect(translate('greeting.namaste', { name: 'आरव' }, 'hi-IN')).toContain('आरव');
  });

  it('resolves initial locale with fallback', () => {
    expect(resolveInitialLocale('hi-IN')).toBe('hi-IN');
    expect(resolveInitialLocale(null)).toBe(DEFAULT_LOCALE);
    expect(resolveInitialLocale('fr-FR')).toBe(DEFAULT_LOCALE);
    expect(SUPPORTED_LOCALES).toContain('en-IN');
  });
});

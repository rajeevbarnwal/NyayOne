import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { settingsDisclosuresOpen } from './SettingsScreens';

describe('S-19 responsive disclosure accessibility', () => {
  it('keeps desktop-hidden disclosure summaries semantically open for their visible controls', () => {
    let observedQuery = '';
    expect(settingsDisclosuresOpen(undefined)).toBe(false);
    expect(settingsDisclosuresOpen((query) => {
      observedQuery = query;
      return { matches: false };
    })).toBe(false);
    expect(settingsDisclosuresOpen(() => ({ matches: true }))).toBe(true);
    expect(observedQuery).toBe('(min-width: 821px)');

    const source = readFileSync(
      join(process.cwd(), 'src/features/student/settings/SettingsScreens.tsx'),
      'utf8',
    );
    const privacy = source.slice(source.indexOf('export function PrivacySettings()'));

    expect(source).toContain("const SETTINGS_WIDE_LAYOUT_QUERY = '(min-width: 821px)';");
    expect(source).toContain("media.addEventListener('change', update)");
    expect(privacy).toContain('const wideLayout = useWideSettingsLayout();');
    expect([...privacy.matchAll(/<details open=\{wideLayout\} className="v34c-mobile-disclosure">/gu)])
      .toHaveLength(2);
    expect(privacy).not.toContain('<details open className="v34c-mobile-disclosure">');
  });
});

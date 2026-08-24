import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('NYAY-18 shipped NyayOne identity contract', () => {
  it('uses the NyayOne identity in web, package, PWA and mobile metadata', () => {
    expect(read('index.html')).toContain('<title>NyayOne</title>');
    expect(JSON.parse(read('package.json')).name).toBe('nyayone-frontend');
    expect(JSON.parse(read('package-lock.json')).name).toBe('nyayone-frontend');
    expect(JSON.parse(read('package-lock.json')).packages[''].name).toBe('nyayone-frontend');
    expect(read('capacitor.config.ts')).toContain("appId: 'com.nyayone.app'");
    expect(read('capacitor.config.ts')).toContain("appName: 'NyayOne'");
    expect(JSON.parse(read('src/i18n/locales/en.json'))['app.name']).toBe('NyayOne');
    expect(JSON.parse(read('src/i18n/locales/hi.json'))['app.name']).toBe('NyayOne');
    expect(read('public/sw.js')).toContain("const CACHE = 'nyayone-shell-v1'");
    expect(read('../docs/release/mobile-store-readiness.md')).not.toMatch(/LegalSaathi|Legal Saathi/u);
  });

  it('contains no inherited brand in user-visible shipped source', () => {
    const visibleSources = [
      'src/components/shell/AppShell.tsx',
      'src/features/ScreenPlaceholder.tsx',
      'src/features/TokenShowcase.tsx',
      'src/features/auth/AuthScreens.tsx',
      'src/features/student/auth/AuthScreens.tsx',
      'src/features/student/calendar/CalendarScreens.tsx',
      'src/features/student/clinical/ClinicalScreens.tsx',
      'src/features/student/internships/InternshipScreens.tsx',
      'src/features/student/lib/calendar.ts',
      'src/features/student/lib/clinical.ts',
      'src/features/student/lib/internships.ts',
      'src/features/student/lib/riskLabelsApi.ts',
      'src/features/student/reporting/ReportingScreens.tsx',
      'src/features/student/reporting/RiskLabelScreens.tsx',
      'src/features/student/schools/SchoolScreens.tsx',
      'src/features/student/settings/SettingsScreens.tsx',
      'src/features/student/tutoring/BookingScreens.tsx',
      'src/features/student/tutoring/SessionScreens.tsx',
      'src/features/student/tutoring/TutoringPrimitives.tsx',
    ];
    for (const path of visibleSources) {
      expect(read(path), path).not.toMatch(/LegalSaathi|Legal Saathi/u);
    }
  });

  it('uses only NyayOne names for shipped browser globals and downloads', () => {
    const transport = read('src/features/student/tutoring/media/videoRoomClient.ts');
    const driver = read('src/features/student/tutoring/media/fakeVideoRoomClient.ts');
    const credentials = read('src/features/student/credentials/CredentialScreens.tsx');
    expect(transport).toContain('__nyayoneVideoTransport');
    expect(transport).not.toContain('__legalsaathiVideoTransport');
    expect(driver).toContain('__nyayoneVideoRoom');
    expect(driver).not.toContain('__legalsaathiVideoRoom');
    expect(credentials).toContain('download="nyayone-credential-qr.png"');
    expect(credentials).not.toContain('legalsaathi-credential-qr.png');
  });

  it('uses NyayOne prefixes for visible case and invoice references', () => {
    const sources = [
      'src/features/lawyer/lib/caseWorkspace.ts',
      'src/features/lawyer/lib/billing.ts',
      'src/features/lawyer/lib/drafting.ts',
      'src/features/lawyer/CaseScreens.tsx',
    ].map(read).join('\n');
    expect(sources).toContain('NYAY-CASE-');
    expect(sources).toContain('NYAY-INV-');
    expect(sources).not.toMatch(/LS-(?:CASE|INV)-/u);
  });

  it('uses a NyayOne prefix for visible internship application references', () => {
    const internships = read('src/features/student/lib/internships.ts');
    expect(internships).toContain('NYAY-INT-');
    expect(internships).not.toContain('LS-INT-');
  });

  it('retires obsolete onboarding/reviewer state and namespaces device preferences', () => {
    const onboarding = read('src/features/student/auth/V34Screens.tsx');
    const theme = read('src/hooks/useTheme.ts');
    const browserNamespace = read('src/lib/browserNamespace.ts');
    const locale = read('src/i18n/index.ts');
    const reviewer = read('src/components/shell/TraceabilityBanner.tsx');
    expect(onboarding).not.toContain('ls-onboarding-seen');
    expect(onboarding).not.toContain('ONBOARDING_SEEN_KEY');
    expect(browserNamespace).toContain("NYAYONE_THEME_STORAGE_KEY = 'nyayone.theme.v1'");
    expect(theme).toContain('THEME_STORAGE_KEY = NYAYONE_THEME_STORAGE_KEY');
    expect(locale).toContain("LOCALE_STORAGE_KEY = 'nyayone.locale.v1'");
    expect(reviewer).not.toContain('ls-reviewer');
    expect(reviewer).not.toMatch(/localStorage\.getItem/u);
  });
});

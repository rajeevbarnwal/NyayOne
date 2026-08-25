import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const FRONTEND_ROOT = process.cwd();
const AUTHORITY_SOURCES = [
  'src/features/student/lib/registrationApi.ts',
  'src/features/student/lib/useOtpFlowState.ts',
  'src/features/student/auth/AuthScreens.tsx',
  'src/features/student/auth/V34Screens.tsx',
  'src/features/student/settings/SettingsScreens.tsx',
  'src/features/student/lib/settingsApi.ts',
  'src/features/auth/screens.tsx',
  'src/features/auth/lib/authPersistence.ts',
] as const;

const PRODUCTION_AUTH_ENTRY_SOURCES = [
  'src/features/auth/screens.tsx',
  'src/features/student/auth/AuthScreens.tsx',
  'src/features/student/auth/V34Screens.tsx',
] as const;

const POLICIES = [
  ['local-attempt-default', /useState\s*\(\s*3\s*\)|set\w*Attempts\w*\s*\(\s*3\s*\)/],
  ['local-cooldown-policy', /Math\.max\s*\(\s*0\s*,\s*30\s*-/],
  ['local-five-minute-policy', /Math\.max\s*\(\s*0\s*,\s*300\s*-/],
  ['local-ten-minute-policy', /Math\.max\s*\(\s*0\s*,\s*600\s*-/],
  ['client-registration-handle', /\b(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))\b/],
  ['retired-session-helper', /\b(?:save|load)RegistrationSession\b/],
  ['absolute-security-time-wire', /\b(?:expires_at|locked_until|cooldown_until|issued_at)\b/],
  [
    'browser-security-state-write',
    /(?:localStorage|sessionStorage)\.setItem\s*\([^)]*(?:otp|attempt|expire|lock|cooldown|registration)/i,
  ],
] as const;

function violations(source: string): string[] {
  return POLICIES
    .filter(([, pattern]) => pattern.test(source))
    .map(([name]) => name);
}

describe('NYAY-4 frontend authority source contract', () => {
  it('contains no client-owned OTP policy, handle, absolute time or browser persistence', () => {
    const findings = AUTHORITY_SOURCES.flatMap((relativePath) => {
      const source = readFileSync(join(FRONTEND_ROOT, relativePath), 'utf8');
      return violations(source).map((policy) => ({ relativePath, policy }));
    });
    expect(findings).toEqual([]);
  });

  it.each([
    ['attempt reset', 'const [attempts, setAttempts] = useState(3);', 'local-attempt-default'],
    ['resend cooldown', 'Math.max(0, 30 - elapsed);', 'local-cooldown-policy'],
    ['five minute expiry', 'Math.max(0, 300 - elapsed);', 'local-five-minute-policy'],
    ['ten minute expiry', 'Math.max(0, 600 - elapsed);', 'local-ten-minute-policy'],
    ['retired storage helper', 'saveRegistrationSession(value);', 'retired-session-helper'],
    ['absolute expiry', 'const expires_at = payload.expires_at;', 'absolute-security-time-wire'],
    ['storage counter', "sessionStorage.setItem('otp-attempts', String(attempts));", 'browser-security-state-write'],
  ])('detects the planted %s mutant', (_label, mutant, expectedPolicy) => {
    expect(violations(mutant)).toContain(expectedPolicy);
  });

  it.each([
    'registration_id', 'registration_token', 'registrationId', 'registrationToken',
    'login_id', 'login_token', 'loginId', 'loginToken',
    'recovery_id', 'recovery_token', 'recoveryId', 'recoveryToken',
  ])('detects the planted %s handle mutant', (handle) => {
    expect(violations(`const payload = { ${handle}: selected };`))
      .toContain('client-registration-handle');
  });

  it('invalidates a previously accepted snapshot when a later state refresh fails', () => {
    const hookSource = readFileSync(
      join(FRONTEND_ROOT, 'src/features/student/lib/useOtpFlowState.ts'),
      'utf8',
    );
    const refreshFailure = hookSource.slice(
      hookSource.indexOf('catch (error)'),
      hookSource.indexOf('throw error;', hookSource.indexOf('catch (error)')),
    );
    expect(refreshFailure).toMatch(/setSnapshot\(null\)[\s\S]*setLoadError\(true\)/);
  });

  it('keeps OTP reads and snapshots disabled until the owning session boundary explicitly enables them', () => {
    const hookSource = readFileSync(
      join(FRONTEND_ROOT, 'src/features/student/lib/useOtpFlowState.ts'),
      'utf8',
    );

    expect(hookSource).toContain('export interface OtpFlowStateOptions');
    expect(hookSource).toContain('const enabled = options.enabled ?? true;');
    expect(hookSource).toMatch(
      /if \(!enabled\) \{[\s\S]*mutationRevision\.current \+= 1;[\s\S]*setSnapshot\(null\);[\s\S]*setLoading\(true\);[\s\S]*return;/u,
    );
    expect(hookSource).toMatch(
      /if \(!enabled\) return undefined;[\s\S]*setInterval\(\(\) => \{[\s\S]*refresh\(\)/u,
    );
    expect(hookSource).toContain('state: enabled ? state : null');
  });

  it('detects a planted stale-snapshot-on-refresh-failure source mutant', () => {
    const hookSource = readFileSync(
      join(FRONTEND_ROOT, 'src/features/student/lib/useOtpFlowState.ts'),
      'utf8',
    );
    const refreshFailure = hookSource.slice(
      hookSource.indexOf('catch (error)'),
      hookSource.indexOf('throw error;', hookSource.indexOf('catch (error)')),
    );
    const mutant = refreshFailure.replace(
      'setSnapshot(null);',
      '/* planted stale snapshot */',
    );
    expect(mutant).not.toMatch(/setSnapshot\(null\)[\s\S]*setLoadError\(true\)/);
  });

  it('keeps production auth entries disconnected from every local OTP authority and fixed code', () => {
    const findings = PRODUCTION_AUTH_ENTRY_SOURCES.flatMap((relativePath) => {
      const source = readFileSync(join(FRONTEND_ROOT, relativePath), 'utf8');
      return [
        ['fixed-code', /STUB_OTP_CODE|['"]429016['"]/],
        ['local-challenge', /\b(?:createChallenge|verifyChallenge|otpVerify|otpResend)\s*\(/],
        ['local-authority-import', /from\s+['"][^'"]*\/(?:authFlow|otp)['"]/],
        ['legacy-workbench-import', /from\s+['"]\.\/AuthScreens['"]/],
      ].filter(([, pattern]) => (pattern as RegExp).test(source))
        .map(([policy]) => ({ relativePath, policy }));
    });
    expect(findings).toEqual([]);
  });

  it('uses one neutral signup failure surface regardless of account existence', () => {
    const findings = PRODUCTION_AUTH_ENTRY_SOURCES.flatMap((relativePath) => {
      const source = readFileSync(join(FRONTEND_ROOT, relativePath), 'utf8');
      return /mobile_already_registered|already registered/i.test(source) ? [relativePath] : [];
    });
    expect(findings).toEqual([]);
  });
});

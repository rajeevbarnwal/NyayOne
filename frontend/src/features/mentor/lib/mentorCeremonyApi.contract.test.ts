import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const FRONTEND = resolve(import.meta.dirname, '../../../..');
const CLIENT_PATH = resolve(import.meta.dirname, 'mentorCeremonyApi.ts');
const RUNNER_PATH = resolve(FRONTEND, 'scripts/nyay22-mentor-ceremony-browser.mjs');
const RUNNER_CONTRACT_PATH = resolve(
  FRONTEND,
  'scripts/lib/nyay22-mentor-ceremony-browser-contract.mjs',
);

function source(path: string): string {
  return existsSync(path) ? readFileSync(path, 'utf8') : '';
}

function requireSource(path: string): string {
  const value = source(path);
  expect(value, `${path} must exist before NYAY-22 can ship`).not.toBe('');
  return value;
}

describe('NYAY-22 frontend mentor-authority seam source contract', () => {
  it('uses the existing cross-tab Web Locks transition boundary', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).toMatch(/withStudentAuthTransition/);
    expect(value).toMatch(/withStudentAuthRequestLease/);
    expect(value).toMatch(/StudentAuthTransition/);
  });

  it('pins the exact non-authorizing entry and nine sealed API operations', () => {
    const value = requireSource(CLIENT_PATH);
    for (const path of [
      '/api/v1/auth/mentor/entry',
      '/api/v1/auth/mentor/ceremony/initiate',
      '/api/v1/auth/mentor/ceremony/verify',
      '/api/v1/auth/mentor/ceremony/exchange',
      '/api/v1/auth/mentor/session',
      '/api/v1/auth/mentor/session/rotate',
      '/api/v1/auth/mentor/session/revoke',
      '/api/v1/auth/mentor/session/logout',
      '/api/v1/auth/mentor/ceremony/recover',
      '/api/v1/auth/mentor/authority',
    ]) expect(value).toContain(`'${path}'`);
  });

  it('runs every cookie-changing operation under one exclusive transition', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).toMatch(/runMentorCookieTransition/);
    for (const operation of [
      'enterMentorCeremony',
      'initiateMentorCeremony',
      'verifyMentorIdentity',
      'exchangeMentorCeremony',
      'rotateMentorSession',
      'revokeMentorSession',
      'logoutMentorSession',
      'recoverMentorCeremony',
      'deleteMentorAuthority',
    ]) {
      expect(value).toMatch(new RegExp(
        `export async function ${operation}[\\s\\S]*runMentorCookieTransition`,
      ));
    }
  });

  it('requires browser-generated Origin plus a mandatory opaque idempotency key', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).toMatch(/Idempotency-Key/);
    expect(value).toMatch(/requireBrowserOrigin/);
    expect(value).toMatch(/location\.origin/);
    expect(value).not.toMatch(/headers\s*:\s*\{[\s\S]{0,160}['"]Origin['"]\s*:/);
    expect(value).not.toMatch(/[?&#](?:actor|owner|mentor|profile|session|token)=/i);
  });

  it('settles complete mutation responses before the canonical session probe', () => {
    const value = requireSource(CLIENT_PATH);
    const transition = value.slice(
      value.indexOf('async function runMentorCookieTransition'),
      value.indexOf('export async function enterMentorCeremony'),
    );
    expect(transition).toMatch(/await operation\(transition\)/);
    expect(transition).toMatch(/await getMentorSession\(\{ authTransition: transition \}\)/);
    expect(transition.indexOf('await operation(transition)'))
      .toBeLessThan(transition.indexOf('await getMentorSession({ authTransition: transition })'));
    expect(value).toMatch(/clone\(\)\.arrayBuffer\(\)/);
  });

  it('holds a shared lease around canonical GET session observation', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).toMatch(/export async function getMentorSession/);
    expect(value).toMatch(/withStudentAuthRequestLease\(async \(\) =>/);
    expect(value).toMatch(/MENTOR_ENDPOINTS\.session/);
  });

  it('makes active and absent post-transition expectations explicit', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).toContain("type MentorPostcondition = 'active' | 'absent' | 'either';");
    expect(value).toMatch(/MENTOR_SESSION_POSTCONDITION_FAILED/);
    expect(value).toMatch(/revokeMentorSession[\s\S]*'absent'/);
    expect(value).toMatch(/logoutMentorSession[\s\S]*'absent'/);
    expect(value).toMatch(/deleteMentorAuthority[\s\S]*'absent'/);
  });

  it('never invokes a private mount until a fresh canonical session succeeds', () => {
    const value = requireSource(CLIENT_PATH);
    const guard = value.slice(value.indexOf('export async function withServerProvenMentorSession'));
    expect(guard).toMatch(/const session = await getMentorSession\(\)/);
    expect(guard).toMatch(/if \(!session\) throw/);
    expect(guard).toMatch(/return mount\(session\)/);
    expect(guard.indexOf('if (!session) throw')).toBeLessThan(guard.indexOf('return mount(session)'));
  });

  it('uses strict closed projections and rejects unknown response fields', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).toMatch(/requireExactKeys/);
    expect(value).toMatch(/mentor-session\.v1/);
    expect(value).toMatch(/absoluteLifetimeSeconds[\s\S]*28_800/);
    expect(value).toMatch(/idleTimeoutSeconds[\s\S]*1_800/);
    expect(value).toMatch(/MENTOR_RESPONSE_INVALID/);
  });

  it('stores no mentor authority and accepts no message, URL, or client-key authority', () => {
    const value = requireSource(CLIENT_PATH);
    expect(value).not.toMatch(/localStorage|sessionStorage|indexedDB|window\.name/);
    expect(value).not.toMatch(/postMessage|addEventListener\(['"]message/);
    expect(value).not.toMatch(/privateKey|secretKey|crypto\.subtle/);
    expect(value).not.toMatch(/searchParams|location\.(?:search|hash)/);
  });

  it('declares an exact fail-closed Chromium assertion inventory', () => {
    const contract = requireSource(RUNNER_CONTRACT_PATH);
    const runner = requireSource(RUNNER_PATH);
    expect(contract).toMatch(/NYAY22_BROWSER_ASSERTION_INVENTORY/);
    expect(contract).toMatch(/assertExactNyay22BrowserInventory/);
    expect(runner).toMatch(/assertExactNyay22BrowserInventory\(rows\)/);
    expect(runner).toMatch(/if \(summary\.failed > 0\) process\.exitCode = 1/);
  });

  it('exercises multi-tab exchange, rotation, revocation, and private mounting in Chromium', () => {
    const runner = requireSource(RUNNER_PATH);
    for (const marker of [
      'cross-tab-exchange-linearized',
      'cross-tab-rotation-linearized',
      'cross-tab-revocation-linearized',
      'private-mount-after-canonical-session',
    ]) expect(runner).toContain(`'${marker}'`);
    expect(runner).toMatch(/const peerPage = await context\.newPage\(\)/);
    expect(runner).toMatch(/withServerProvenMentorSession/);
  });

  it('treats both harness-ready markers as attached state, never visual content', () => {
    const runner = requireSource(RUNNER_PATH);
    const waits = runner.match(
      /waitForSelector\('body\[data-harness-ready=\\?"true\\?"\]'[\s\S]{0,80}?state:\s*'attached'/gu,
    ) ?? [];
    expect(waits).toHaveLength(2);
    expect(runner).not.toMatch(
      /waitForSelector\('body\[data-harness-ready=\\?"true\\?"\]'\s*\)/u,
    );
  });

  it('proves unsupported Web Locks or BroadcastChannel deny every private mount', () => {
    const runner = requireSource(RUNNER_PATH);
    expect(runner).toContain("'unsupported-web-locks-denies-private-mount'");
    expect(runner).toContain("'unsupported-broadcast-channel-denies-private-mount'");
    expect(runner).toMatch(/navigator[\s\S]*locks/);
    expect(runner).toMatch(/BroadcastChannel/);
  });

  it('keeps Chromium evidence privacy-safe and authority-free', () => {
    const contract = requireSource(RUNNER_CONTRACT_PATH);
    const runner = requireSource(RUNNER_PATH);
    expect(contract).toMatch(/scanNyay22BrowserEvidence/);
    expect(runner).toMatch(/scanNyay22BrowserEvidence/);
    expect(runner).not.toMatch(/\.value\s*[),]/);
    expect(runner).not.toMatch(/page\.url\(\)[\s\S]*(?:query|fragment|search|hash)/i);
  });
});

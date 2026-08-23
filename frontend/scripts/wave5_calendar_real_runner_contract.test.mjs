import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

const RUNNER_SOURCE = readFileSync(
  new URL('./wave5-calendar-real-e2e.mjs', import.meta.url),
  'utf8',
);

function directApiHeaders(source) {
  const context = source.match(
    /const api = await playwrightRequest\.newContext\(\{([\s\S]*?)\n\}\);/,
  );
  if (!context) return '';
  return context[1].match(/extraHTTPHeaders:\s*\{([^}]*)\}/)?.[1] ?? '';
}

function hasExactTrustedOrigin(source) {
  const headers = directApiHeaders(source);
  const origins = [...headers.matchAll(/(?:^|,)\s*Origin\s*:\s*([^,}\n]+)/g)]
    .map((match) => match[1].trim());
  return origins.length === 1 && origins[0] === 'WEB.origin';
}

describe('Wave 5 real runner cookie-authority boundary', () => {
  it('binds the direct API request context to the exact browser Origin', () => {
    expect(hasExactTrustedOrigin(RUNNER_SOURCE)).toBe(true);
  });

  it.each([
    ['removed Origin', (source) => source.replace(
      /^[ \t]*Origin:\s*WEB\.origin,?[ \t]*$/m,
      '',
    )],
    ['API Origin substituted for browser Origin', (source) => source.replace(
      /(^[ \t]*Origin:\s*)WEB\.origin/m,
      'Origin: API.origin',
    )],
  ])('kills the %s mutant', (_name, mutate) => {
    const mutant = mutate(RUNNER_SOURCE);
    expect(mutant).not.toBe(RUNNER_SOURCE);
    expect(hasExactTrustedOrigin(mutant)).toBe(false);
  });

  it('trusts the fixture certificate only behind the explicit self-signed opt-in', () => {
    expect(RUNNER_SOURCE).toContain(
      "const IGNORE_LOOPBACK_TLS = process.env.WAVE5_E2E_ALLOW_SELF_SIGNED_TLS === 'true';",
    );
    expect(RUNNER_SOURCE).toContain(
      "const CHROMIUM_LAUNCH_ARGS = IGNORE_LOOPBACK_TLS\n  ? ['--ignore-certificate-errors']\n  : [];",
    );
    expect(RUNNER_SOURCE).toContain('args: CHROMIUM_LAUNCH_ARGS');
    expect(RUNNER_SOURCE.match(/--ignore-certificate-errors/gu)).toHaveLength(1);
  });

  it('proves the shipped service worker owns the production page without filtering runtime errors', () => {
    expect(RUNNER_SOURCE).toContain('async function waitForServiceWorkerControl(page)');
    expect(RUNNER_SOURCE).toContain('navigator.serviceWorker.getRegistrations()');
    expect(RUNNER_SOURCE).toContain('navigator.serviceWorker.controller');
    expect(RUNNER_SOURCE).toContain("registration.active?.scriptURL).pathname === '/sw.js'");
    const navigation = RUNNER_SOURCE.indexOf(
      "await page.goto(new URL('/s-91', WEB).href, { waitUntil: 'domcontentloaded' });",
    );
    const worker = RUNNER_SOURCE.indexOf('await waitForServiceWorkerControl(page);', navigation);
    const readiness = RUNNER_SOURCE.indexOf('await waitReady(page);', navigation);
    expect(navigation).toBeGreaterThan(-1);
    expect(worker).toBeGreaterThan(navigation);
    expect(worker).toBeLessThan(readiness);
    expect(RUNNER_SOURCE).not.toContain('An SSL certificate error occurred when fetching the script.');
  });
});

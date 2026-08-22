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
});

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('Wave4 risk-label authenticated client boundary', () => {
  it('uses the enabled web origin for cookie-backed API requests', () => {
    const source = readFileSync(resolve('scripts/wave4-risk-labels-e2e.mjs'), 'utf8');
    expect(source).toContain('extraHTTPHeaders: { Origin: new URL(ENABLED_WEB).origin }');
    expect(source).not.toMatch(/secure:\s*false[\s\S]{0,160}Origin:\s*new URL\(baseUrl\)/);
  });
});

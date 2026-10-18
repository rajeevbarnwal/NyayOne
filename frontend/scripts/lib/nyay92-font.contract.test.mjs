import { readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, it } from 'vitest';
import { loadS20Source } from './nyay66-s20-reference.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const fontPath = new URL('../../public/fonts/s20/PublicSans-v32108-latin-ext.woff2', import.meta.url);
const cssPath = new URL('../../src/features/student/internships/S20Browse.css', import.meta.url);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const expected = '1c8a26c0ed4312dacc36670714794c9f4b4a0972ccb45f2936646bd8d444d5f8';
let source;
beforeAll(async () => {
  const html = (await loadS20Source(root)).html.toString();
  const marker = '<script type="text/plain" id="src-cont">', start = html.indexOf(marker) + marker.length;
  source = html.slice(start, html.indexOf('</script>', start));
});

describe('S-20 frozen rupee font provenance and isolation', () => {
  it('ships the exact approved continuation subset, without modifying font bytes', () => {
    const css = [...source.matchAll(/@font-face\s*\{([^}]+)\}/g)].map(([, body]) => body)
      .find(body => body.includes("'Public Sans'") && body.includes('U+20AD-20C0') && /font-weight:\s*400/.test(body));
    const frozen = Buffer.from(css.match(/base64,([^)'"\s]+)/)[1], 'base64');
    expect(sha(frozen)).toBe(expected);
    expect(readFileSync(fontPath).equals(frozen)).toBe(true);
  });
  it('registers only the rupee codepoint under an isolated alias and uses it only in S-20 metadata', () => {
    const css = readFileSync(cssPath, 'utf8');
    const face = css.match(/@font-face\s*\{[^}]*font-family:\s*'NyayOne S20 Rupee'[^}]*\}/)?.[0];
    expect(face).toBeTruthy();
    expect(face).toMatch(/unicode-range:\s*U\+20B9\s*;/);
    expect(face).toContain("url('/fonts/s20/PublicSans-v32108-latin-ext.woff2')");
    expect(css).toMatch(/\.s20-meta\{[^}]*font-family:'Public Sans','NyayOne S20 Rupee',system-ui,sans-serif/);
    const global = readFileSync(new URL('../../src/styles/fonts.css', import.meta.url), 'utf8');
    expect(global).not.toContain('NyayOne S20 Rupee');
    expect(global).not.toContain('PublicSans-v32108-latin-ext.woff2');
  });
  it('keeps the existing Public Sans Latin asset byte-identical', () => {
    expect(sha(readFileSync(new URL('../../public/fonts/PublicSans-latin.woff2', import.meta.url))))
      .toBe('c1b6da516e0062e9c2f341b3a51dd2d621d946da72f06c6cfe05fd9d2dd8622d');
  });
  it('preserves every existing top-level font pin; the protected supplement is separate', () => {
    const policy = JSON.parse(readFileSync(new URL('../nyay66-policy.json', import.meta.url)));
    const manifest = JSON.parse(readFileSync(new URL(`../../test-baselines/nyay66/${policy.cache}/manifest.json`, import.meta.url)));
    const fonts = new URL('../../public/fonts/', import.meta.url);
    const names = readdirSync(fonts).filter(name => name.endsWith('.woff2')).sort();
    expect(names).toEqual(Object.keys(manifest.fonts).sort());
    for (const name of names) expect(sha(readFileSync(new URL(name, fonts)))).toBe(manifest.fonts[name]);
    expect(sha(readFileSync(fontPath))).toBe(expected);
  });
});

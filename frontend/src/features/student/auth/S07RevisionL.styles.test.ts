import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync('src/styles/student-v34.css', 'utf8');
const start = css.indexOf('/* NYAY-49 S-07 Revision L');
const scoped = start === -1 ? '' : css.slice(start);

describe('S-07 Revision L presentation scope', () => {
  it('centers the mobile popup with rounded corners and scroll-safe viewport insets', () => {
    expect(scoped).toMatch(/\.v34-s07-backdrop\s*\{[^}]*align-items:\s*center[^}]*padding:\s*16px/su);
    expect(scoped).toMatch(/\.v34-s07-dialog\s*\{[^}]*width:\s*min\(420px, 100%\)[^}]*max-height:\s*calc\(100dvh - 32px\)[^}]*border-radius:\s*20px/su);
    expect(scoped).toMatch(/\.v34-s07-dialog\s*\{[^}]*padding:\s*18px 16px/su);
  });

  it('adopts the approved local typography and surfaces only within the S-07 layer', () => {
    expect(start).toBeGreaterThan(-1);
    expect(scoped).toContain('font-family: var(--nyayone-font-body)');
    expect(scoped).toContain('font-family: var(--nyayone-font-heading)');
    expect(scoped).toContain('background: var(--nyayone-color-paper)');
    expect(scoped).not.toContain('S-14');
  });

  it('keeps both primary choices equally reachable and logout as a separate 44px utility', () => {
    expect(scoped).toMatch(/\.v34-s07-actions\s*\{[^}]*display:\s*flex/su);
    expect(scoped).toMatch(/\.v34-s07-actions > button\s*\{[^}]*min-height:\s*48px/su);
    expect(scoped).toMatch(/\.v34-s07-session-actions > button\s*\{[^}]*min-height:\s*44px/su);
    expect(scoped).toMatch(/\.v34-s07-actions > button:first-child\s*\{[^}]*background:\s*var\(--nyayone-color-indigo\)/su);
    expect(scoped).toContain('outline: var(--nyayone-focus-width) solid var(--nyayone-color-focus)');
  });

  it('keeps the real percentage visible and the reference backdrop separate from dialog content', () => {
    expect(scoped).toMatch(/\.v34-s07-progress\s*\{[^}]*height:\s*8px/su);
    expect(scoped).toMatch(/\.v34-s07-background\s*\{[^}]*filter:\s*blur\(9px\)/su);
    expect(scoped).not.toMatch(/\.v34-s07-dialog\s*\{[^}]*filter:/su);
    expect(scoped).toMatch(/\.v34-s07-dialog\s*\{[^}]*overflow:\s*auto/su);
  });

  it('uses the reference notice card and actual aside caption selector', () => {
    expect(scoped).toMatch(/\.v34-s07-note\s*\{[^}]*border:\s*1\.5px solid var\(--nyayone-color-line\)[^}]*border-radius:\s*12px/su);
    expect(scoped).toMatch(/\.v34-s07-note button\s*\{[^}]*border:\s*1\.5px solid var\(--nyayone-color-indigo\)/su);
    expect(scoped).toMatch(/\.v34-s07-aside \.v34-s07-eyebrow\s*\{[^}]*margin:\s*0 0 8px/su);
  });

  it('preserves the reference home-heading spacing and secondary action icon color', () => {
    expect(scoped).toMatch(/\.v34-s07-title\s*\{[^}]*margin:\s*2px 0 \.83em/su);
    expect(scoped).toMatch(/\.v34-s07-actions > button:nth-child\(2\) > \.v321-revl-icon\s*\{[^}]*color:\s*var\(--nyayone-color-indigo\)/su);
  });

  it('preserves the reference heading bottom margin instead of collapsing paragraph spacing', () => {
    expect(scoped).toMatch(/\.v34-s07 \.v34-s07-dialog h2\s*\{[^}]*margin:\s*6px 36px \.83em 0/su);
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthProvider, type StudentSessionPhase } from '../../../app/authContext';
import { V34Splash, splashDestination } from './V34Screens';
import { readR2OnboardingSeen } from './S01R2';
import { readFileSync } from 'node:fs';

function markup(phase: StudentSessionPhase) {
  return renderToStaticMarkup(<AuthProvider studentSession={{ phase, refresh: async () => undefined }}><MemoryRouter><V34Splash /></MemoryRouter></AuthProvider>);
}

describe('NYAY-77 S-01 approved R2 light states', () => {
  it('isolates the mobile R2 raster layer without a visible shadow', () => {
    const css = readFileSync(new URL('./S01R2.css', import.meta.url), 'utf8');
    expect(css).toMatch(/@media\s*\(max-width:\s*899px\)\s*\{\s*\.s01-r2\s*\{\s*filter:\s*drop-shadow\(0 0 0 transparent\)/);
  });
  it('isolates desktop error rasterization without changing checking or resolved states', () => {
    const css = readFileSync(new URL('./S01R2.css', import.meta.url), 'utf8');
    expect(css).toMatch(/@media\s*\(min-width:\s*900px\)\s*\{\s*\.s01-r2:has\(\.s01-r2__tile--error\)\s*\{\s*filter:\s*drop-shadow\(0 0 0 transparent\)/);
    expect(markup('unavailable')).toContain('s01-r2__tile--error');
    expect(markup('pending')).not.toContain('s01-r2__tile--error');
    expect(markup('authenticated')).not.toContain('s01-r2__tile--error');
  });
  it('keeps the unavailable heading on R2 ink rather than the legacy global heading color', () => {
    const css = readFileSync(new URL('./S01R2.css', import.meta.url), 'utf8');
    expect(css).toMatch(/\.s01-r2 h1\s*\{[^}]*color:\s*inherit/);
  });
  it('renders the R2 lockup and exact checking copy without invented percentage', () => {
    const html = markup('pending');
    expect(html).toContain('data-nyayone-design="3.2.1-r2"');
    expect(html).toContain('NyayOne — Legal, on the record');
    expect(html).toContain('Checking your session…');
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toContain('aria-valuenow');
    expect(html).not.toContain('INTERNSHIPS');
  });
  it('offers only manual retry with neutral R2 failure copy', () => {
    const html = markup('unavailable');
    expect(html).toContain('We could not reach NyayOne.');
    expect(html).toContain('Check your connection and try again. Nothing on your account has changed.');
    expect(html).toContain('Try again');
    expect(html).not.toContain('role="progressbar"');
    expect(html).not.toContain('Continue');
  });
  it('renders the resolved state from authenticated authority, never from a failure', () => {
    expect(markup('authenticated')).toContain('Session confirmed. Opening your workspace…');
    expect(markup('unavailable')).not.toContain('Session confirmed');
    expect(markup('anonymous')).not.toContain('Session confirmed');
  });
  it('retains automatic routing and fail-closed session authority', () => {
    expect(splashDestination('pending')).toBeNull();
    expect(splashDestination('unavailable')).toBeNull();
    expect(splashDestination('authenticated')).toBe('/s-07');
    expect(splashDestination('anonymous')).toBe('/s-02');
    expect(splashDestination('anonymous', true)).toBe('/s-03');
    expect(splashDestination('pending', true)).toBeNull();
    expect(splashDestination('unavailable', true)).toBeNull();
  });
  it('accepts only the versioned non-sensitive R2 preference; storage failure means unseen', () => {
    expect(readR2OnboardingSeen({ getItem: key => key === 'nyayone.r2.onboarding-seen' ? 'true' : null })).toBe(true);
    for (const value of [null, '', 'false', '1', '{"id":"synthetic"}']) {
      expect(readR2OnboardingSeen({ getItem: () => value })).toBe(false);
    }
    expect(readR2OnboardingSeen({ getItem: () => { throw Error('storage unavailable'); } })).toBe(false);
  });
});

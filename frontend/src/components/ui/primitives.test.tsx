import { describe, expect, it } from 'vitest';
import * as UI from './primitives';
import { bottomNavItems, railItems, splitBottomNav } from '../shell/navItems';

describe('UI primitives (SAATHI-345)', () => {
  it('exports all 12 required primitives as components', () => {
    const expected = [
      'EmptyState', 'LoadingState', 'ErrorState', 'ValidationState', 'RestrictedState',
      'PendingVerificationState', 'ModerationBanner', 'StatusBadge', 'PrivacyNotice',
      'GuardrailNotice', 'CitationList', 'SourceVersionPill',
    ] as const;
    for (const name of expected) {
      expect(typeof (UI as Record<string, unknown>)[name]).toBe('function');
    }
  });
});

describe('shell nav config (SAATHI-343)', () => {
  it('bottom nav has exactly 5 primaries with routes', () => {
    expect(bottomNavItems).toHaveLength(5);
    for (const it of bottomNavItems) expect(it.to.startsWith('/s-')).toBe(true);
  });
  it('rail routes all target canonical S-xx screens', () => {
    expect(railItems.length).toBeGreaterThan(5);
    for (const it of railItems) expect(it.to).toMatch(/^\/s-\d{2}$/);
  });

  it('splitBottomNav renders every configured item — none dropped (SAATHI-374)', () => {
    const { left, right } = splitBottomNav();
    // Every bottom-nav item appears exactly once across left+right.
    expect(left.length + right.length).toBe(bottomNavItems.length);
    const renderedIds = [...left, ...right].map((i) => i.id).sort();
    const configuredIds = bottomNavItems.map((i) => i.id).sort();
    expect(renderedIds).toEqual(configuredIds);
    // Profile (the previously-dropped index 4) must be present.
    expect(renderedIds).toContain('profile');
  });
});

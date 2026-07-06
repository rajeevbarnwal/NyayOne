import { describe, expect, it } from 'vitest';
import { nextTheme, resolveInitialTheme } from './useTheme';

describe('theme resolution (ls-theme)', () => {
  it('uses a stored value when present', () => {
    expect(resolveInitialTheme('dark', false)).toBe('dark');
    expect(resolveInitialTheme('light', true)).toBe('light');
  });

  it('falls back to system preference when nothing is stored', () => {
    expect(resolveInitialTheme(null, true)).toBe('dark');
    expect(resolveInitialTheme(null, false)).toBe('light');
  });

  it('ignores invalid stored values and uses system preference', () => {
    expect(resolveInitialTheme('purple', true)).toBe('dark');
  });

  it('toggles to the opposite theme', () => {
    expect(nextTheme('light')).toBe('dark');
    expect(nextTheme('dark')).toBe('light');
  });
});

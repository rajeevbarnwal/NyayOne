import { useCallback, useEffect, useState } from 'react';
import {
  migrateLegacyBrowserNamespace,
  NYAYONE_THEME_STORAGE_KEY,
} from '../lib/browserNamespace';

export type ThemeMode = 'light' | 'dark';

export const THEME_STORAGE_KEY = NYAYONE_THEME_STORAGE_KEY;

/** Pure: resolve the initial theme from stored value then system preference. */
export function resolveInitialTheme(
  stored: string | null,
  prefersDark: boolean
): ThemeMode {
  if (stored === 'light' || stored === 'dark') return stored;
  return prefersDark ? 'dark' : 'light';
}

/** Pure: the opposite theme. */
export function nextTheme(mode: ThemeMode): ThemeMode {
  return mode === 'dark' ? 'light' : 'dark';
}

function readInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'light';
  let stored: string | null = null;
  try {
    stored = migrateLegacyBrowserNamespace(window.localStorage).theme;
  } catch {
    /* storage unavailable — fall through to the system preference */
  }
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  return resolveInitialTheme(stored, prefersDark);
}

/**
 * Runtime dark/light theme. Persists to the NyayOne device-preference namespace and applies
 * `data-theme` on <html> so the token CSS switches with no reload. Respects the
 * OS preference on first load (when nothing is stored).
 */
export function useTheme() {
  const [theme, setThemeState] = useState<ThemeMode>(readInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* storage unavailable — theme still applies for the session */
    }
  }, [theme]);

  const setTheme = useCallback((mode: ThemeMode) => setThemeState(mode), []);
  const toggleTheme = useCallback(() => setThemeState((prev) => nextTheme(prev)), []);

  return { theme, setTheme, toggleTheme };
}

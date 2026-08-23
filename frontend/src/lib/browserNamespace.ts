import { purgeCompleteLegacyBrowserLocalStorage } from '../features/student/lib/studentLegacyStorage';

export const LEGACY_THEME_STORAGE_KEY = 'ls-theme';
export const NYAYONE_THEME_STORAGE_KEY = 'nyayone.theme.v1';

export type BrowserThemeMode = 'light' | 'dark';

export interface BrowserNamespaceMigrationResult {
  readonly complete: boolean;
  readonly theme: BrowserThemeMode | null;
}

function validTheme(value: string | null): BrowserThemeMode | null {
  return value === 'light' || value === 'dark' ? value : null;
}

/**
 * One-shot NYAY-18 compatibility boundary.
 *
 * Only the non-sensitive theme preference may cross namespaces. All other
 * retired values are deleted by key name without being read or rewritten.
 * A false `complete` result means storage was inaccessible or the bounded
 * purge could not prove that every owned legacy key was removed.
 */
export function migrateLegacyBrowserNamespace(
  storage: Storage,
): BrowserNamespaceMigrationResult {
  let complete = true;
  let theme: BrowserThemeMode | null = null;

  try {
    theme = validTheme(storage.getItem(NYAYONE_THEME_STORAGE_KEY));
    if (theme === null) {
      const legacyTheme = validTheme(storage.getItem(LEGACY_THEME_STORAGE_KEY));
      if (legacyTheme !== null) {
        storage.setItem(NYAYONE_THEME_STORAGE_KEY, legacyTheme);
        theme = legacyTheme;
      }
    }
  } catch {
    complete = false;
  }

  const purge = purgeCompleteLegacyBrowserLocalStorage(storage);
  return { complete: complete && purge.complete, theme };
}

import { describe, expect, it, vi } from 'vitest';
import {
  LEGACY_THEME_STORAGE_KEY,
  NYAYONE_THEME_STORAGE_KEY,
  migrateLegacyBrowserNamespace,
} from './browserNamespace';

function storage(entries: Array<[string, string]>): Storage {
  const values = new Map(entries);
  return {
    get length() { return values.size; },
    clear: vi.fn(() => values.clear()),
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    key: vi.fn((index: number) => [...values.keys()][index] ?? null),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
  };
}

describe('NYAY-18 browser namespace bootstrap', () => {
  it('reads a valid legacy theme exactly once, writes the NyayOne key, then purges legacy families', () => {
    const area = storage([
      [LEGACY_THEME_STORAGE_KEY, 'dark'],
      ['ls-reviewer', '1'],
      ['ls-draftws-private', 'private'],
      ['unrelated.preference', 'keep'],
    ]);
    const result = migrateLegacyBrowserNamespace(area);
    expect(result).toEqual({ complete: true, theme: 'dark' });
    expect(area.getItem).toHaveBeenCalledWith(LEGACY_THEME_STORAGE_KEY);
    expect(area.getItem).toHaveBeenCalledTimes(2);
    expect(area.getItem(NYAYONE_THEME_STORAGE_KEY)).toBe('dark');
    expect(area.getItem(LEGACY_THEME_STORAGE_KEY)).toBeNull();
    expect(area.getItem('ls-reviewer')).toBeNull();
    expect(area.getItem('ls-draftws-private')).toBeNull();
    expect(area.getItem('unrelated.preference')).toBe('keep');
    expect(area.clear).not.toHaveBeenCalled();
  });

  it('lets an existing valid NyayOne theme win and always removes the legacy value', () => {
    const area = storage([
      [NYAYONE_THEME_STORAGE_KEY, 'light'],
      [LEGACY_THEME_STORAGE_KEY, 'dark'],
    ]);
    expect(migrateLegacyBrowserNamespace(area)).toEqual({ complete: true, theme: 'light' });
    expect(area.getItem(LEGACY_THEME_STORAGE_KEY)).toBeNull();
    expect(area.getItem(NYAYONE_THEME_STORAGE_KEY)).toBe('light');
  });

  it('does not copy an invalid legacy value into the NyayOne namespace', () => {
    const area = storage([[LEGACY_THEME_STORAGE_KEY, 'private-payload']]);
    expect(migrateLegacyBrowserNamespace(area)).toEqual({ complete: true, theme: null });
    expect(area.getItem(LEGACY_THEME_STORAGE_KEY)).toBeNull();
    expect(area.getItem(NYAYONE_THEME_STORAGE_KEY)).toBeNull();
  });
});

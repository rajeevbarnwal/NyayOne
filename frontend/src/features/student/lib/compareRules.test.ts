import { describe, expect, it } from 'vitest';
import {
  addToCompareSelection,
  removeFromCompareSelection,
  compareSelectionState,
  COMPARE_MIN,
  DEFAULT_COMPARE_MAX,
} from './lawSchoolsApi';

/**
 * UI-side compare-selection rules (SAATHI-63): min 2, max = server compare_max
 * (default 4), duplicates blocked before any request. Backend stays
 * authoritative — these helpers only prevent obviously-invalid selections.
 */
describe('compare selection rules (S-27/S-29)', () => {
  it('two selections satisfy the minimum and produce a comparable shape', () => {
    let selection: string[] = [];
    for (const id of ['a', 'b']) {
      const result = addToCompareSelection(selection, id);
      expect(result.ok).toBe(true);
      if (result.ok) selection = result.selection;
    }
    expect(selection).toEqual(['a', 'b']);
    const state = compareSelectionState(selection);
    expect(state.canCompare).toBe(true);
    expect(state.missingForMin).toBe(0);
    expect(state.atLimit).toBe(false);
  });

  it('one selection is below the minimum of 2', () => {
    const state = compareSelectionState(['a']);
    expect(COMPARE_MIN).toBe(2);
    expect(state.canCompare).toBe(false);
    expect(state.missingForMin).toBe(1);
  });

  it('four selections are allowed at the default limit', () => {
    let selection: string[] = [];
    for (const id of ['a', 'b', 'c', 'd']) {
      const result = addToCompareSelection(selection, id);
      expect(result.ok).toBe(true);
      if (result.ok) selection = result.selection;
    }
    expect(selection).toHaveLength(DEFAULT_COMPARE_MAX);
    const state = compareSelectionState(selection);
    expect(state.canCompare).toBe(true);
    expect(state.atLimit).toBe(true);
  });

  it('a fifth selection surfaces the limit error with the effective max', () => {
    const result = addToCompareSelection(['a', 'b', 'c', 'd'], 'e');
    expect(result).toEqual({ ok: false, reason: 'limit_reached', maxAllowed: 4 });
  });

  it('honours a lower server compare_max over the default', () => {
    const result = addToCompareSelection(['a', 'b', 'c'], 'd', 3);
    expect(result).toEqual({ ok: false, reason: 'limit_reached', maxAllowed: 3 });
    expect(compareSelectionState(['a', 'b', 'c'], 3).atLimit).toBe(true);
  });

  it('blocks duplicates in the UI helper', () => {
    const result = addToCompareSelection(['a', 'b'], 'a');
    expect(result).toEqual({ ok: false, reason: 'duplicate', maxAllowed: DEFAULT_COMPARE_MAX });
  });

  it('remove is a no-op for unknown ids and removes known ids', () => {
    expect(removeFromCompareSelection(['a', 'b'], 'b')).toEqual(['a']);
    expect(removeFromCompareSelection(['a'], 'zz')).toEqual(['a']);
  });
});

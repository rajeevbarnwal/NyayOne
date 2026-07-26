import { describe, expect, it } from 'vitest';
import {
  moduleAvailability,
  availableModules,
  upcomingModules,
  releaseRank,
  profileCompletionPct,
} from './dashboard';

describe('dashboard graceful degradation by release (SAATHI-57)', () => {
  it('ranks releases in order', () => {
    expect(releaseRank('R1')).toBeLessThan(releaseRank('R2'));
    expect(releaseRank('R1')).toBeLessThan(releaseRank('R1.1'));
  });

  it('marks later-tranche modules as not released in R1', () => {
    expect(moduleAvailability('R1', 'R1')).toBe('available');
    expect(moduleAvailability('R2', 'R1')).toBe('unavailable_not_released');
    expect(moduleAvailability('R3', 'R1')).toBe('unavailable_not_released');
  });

  it('splits modules into available and upcoming for R1', () => {
    const live = availableModules('R1');
    const soon = upcomingModules('R1');
    expect(live.length).toBeGreaterThan(0);
    expect(soon.length).toBeGreaterThan(0);
    expect(live.every((m) => m.release === 'R1')).toBe(true);
    // No overlap.
    expect(live.some((m) => soon.some((s) => s.id === m.id))).toBe(false);
  });
});

describe('dashboard real-data summary', () => {
  it('derives profile completion instead of using a fixed momentum score', () => {
    const empty = {
      fullName: '', dateOfBirth: '', college: '', yearOfStudy: '', enrolmentNumber: '',
      institutionalEmail: '', interests: [] as string[], careerGoal: '',
    };
    expect(profileCompletionPct(empty)).toBe(0);
    expect(profileCompletionPct({ ...empty, fullName: 'Rajeev', dateOfBirth: '2000-01-01' })).toBe(25);
  });
});

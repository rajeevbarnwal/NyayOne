import { describe, expect, it } from 'vitest';
import {
  filterListings,
  toggleSave,
  stepForStatus,
  statusChip,
  stipendText,
  newApplicationRef,
  SAMPLE_LISTINGS,
} from './internships';

describe('internships browse/filter/save (SAATHI-60)', () => {
  it('filters by query, stipend and verified-only', () => {
    expect(filterListings(SAMPLE_LISTINGS, { query: 'mumbai' }).map((l) => l.id)).toEqual(['cam']);
    expect(filterListings(SAMPLE_LISTINGS, { stipend: 'unpaid' }).map((l) => l.id)).toEqual(['vidhi']);
    expect(filterListings(SAMPLE_LISTINGS, { stipend: 'paid' }).every((l) => l.stipendMonthly !== null)).toBe(true);
    expect(filterListings(SAMPLE_LISTINGS, { verifiedOnly: true }).map((l) => l.id)).toEqual(['cam']);
  });
  it('toggles saved set', () => {
    expect(toggleSave([], 'cam')).toEqual(['cam']);
    expect(toggleSave(['cam'], 'cam')).toEqual([]);
  });
  it('renders stipend text', () => {
    expect(stipendText(SAMPLE_LISTINGS[0])).toBe('₹40,000/mo');
    expect(stipendText(SAMPLE_LISTINGS[2])).toBe('unpaid');
  });
});

describe('internships application tracker (SAATHI-61)', () => {
  it('maps status to stepper + chip', () => {
    expect(stepForStatus('interview')).toBe(3);
    expect(stepForStatus('offer')).toBe(4);
    expect(statusChip('action_needed').kind).toBe('risk');
    expect(statusChip('interview').kind).toBe('ok');
    expect(statusChip('closed').kind).toBe('warn');
  });
  it('generates unique application refs', () => {
    const a = newApplicationRef();
    const b = newApplicationRef();
    expect(a).toMatch(/^LS-INT-\d+$/);
    expect(a).not.toBe(b);
  });
});

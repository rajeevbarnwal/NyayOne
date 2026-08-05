import { describe, expect, it } from 'vitest';
import { formatDateDDMMYYYY, parseDDMMYYYYToISO, formatTime12Hour } from './dateTime';

describe('Centralized Date Utility (formatDateDDMMYYYY)', () => {
  it('formats YYYY-MM-DD strings into DD-MM-YYYY', () => {
    expect(formatDateDDMMYYYY('2004-03-14')).toBe('14-03-2004');
    expect(formatDateDDMMYYYY('1998-12-05')).toBe('05-12-1998');
  });

  it('formats ISO ISO-8601 full timestamps into DD-MM-YYYY', () => {
    expect(formatDateDDMMYYYY('2026-07-29T06:35:10.000Z')).toBe('29-07-2026');
  });

  it('handles Date objects and numeric timestamps correctly', () => {
    const d = new Date(2026, 6, 29); // Month is 0-indexed (6 = July)
    expect(formatDateDDMMYYYY(d)).toBe('29-07-2026');
  });

  it('preserves already formatted DD-MM-YYYY strings', () => {
    expect(formatDateDDMMYYYY('14-03-2004')).toBe('14-03-2004');
  });

  it('returns empty string for null, undefined, or empty inputs', () => {
    expect(formatDateDDMMYYYY(null)).toBe('');
    expect(formatDateDDMMYYYY(undefined)).toBe('');
    expect(formatDateDDMMYYYY('')).toBe('');
  });

  it('parses DD-MM-YYYY back to ISO YYYY-MM-DD format', () => {
    expect(parseDDMMYYYYToISO('14-03-2004')).toBe('2004-03-14');
    expect(parseDDMMYYYYToISO('2004-03-14')).toBe('2004-03-14');
  });

  it('formats timestamps into 12-Hour AM/PM time strings', () => {
    expect(formatTime12Hour('2026-07-20T18:30:00Z', 'UTC')).toBe('06:30 PM');
    expect(formatTime12Hour('2026-07-20T05:15:00Z', 'UTC')).toBe('05:15 AM');
  });
});

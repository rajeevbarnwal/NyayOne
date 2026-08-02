import { describe, expect, it } from 'vitest';
import {
  filterListings,
  stepForStatus,
  statusChip,
  stipendText,
  isVerifiedListing,
  listingSourceLabel,
  newApplicationRef,
  SAMPLE_LISTINGS,
  validateApplicationPdf,
  validateCoverNote,
  MAX_APPLICATION_PDF_BYTES,
} from './internships';

describe('internships browse/filter/save (SAATHI-60)', () => {
  it('filters by query, stipend and verified-only', () => {
    expect(filterListings(SAMPLE_LISTINGS, { query: 'mumbai' }).map((l) => l.id)).toEqual(['cam']);
    expect(filterListings(SAMPLE_LISTINGS, { stipend: 'unpaid' }).map((l) => l.id)).toEqual(['vidhi']);
    expect(filterListings(SAMPLE_LISTINGS, { stipend: 'paid' }).every((l) => l.stipendMonthlyPaise !== null)).toBe(true);
    expect(filterListings(SAMPLE_LISTINGS, { verifiedOnly: true }).map((listing) => listing.id)).toEqual(['cam']);
  });
  it('derives badge truth and source copy from one verification status', () => {
    expect(SAMPLE_LISTINGS.map(isVerifiedListing)).toEqual([true, false, false]);
    expect(SAMPLE_LISTINGS.map(listingSourceLabel)).toEqual([
      'Source: Cyril Amarchand Mangaldas careers · verified 28 Jun 2026 · not affiliated',
      'Source: Sample fixture · unverified · not affiliated',
      'Source: Sample fixture · unverified · not affiliated',
    ]);
    expect(listingSourceLabel(SAMPLE_LISTINGS[0])).toContain('verified');
    expect(listingSourceLabel(SAMPLE_LISTINGS[0])).not.toContain('unverified');
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
  it('requires genuine, non-empty PDFs no larger than 5 MB', () => {
    expect(validateApplicationPdf(null, 'Résumé')).toContain('required');
    expect(validateApplicationPdf({ name: 'resume.txt', type: 'text/plain', size: 12 }, 'Résumé')).toContain('PDF');
    expect(validateApplicationPdf({ name: 'resume.pdf', type: 'application/pdf', size: 0 }, 'Résumé')).toContain('empty');
    expect(validateApplicationPdf({ name: 'resume.pdf', type: 'application/pdf', size: 6 * 1024 * 1024 }, 'Résumé')).toContain('5 MB');
    expect(validateApplicationPdf({ name: 'resume.pdf', type: 'application/pdf', size: 1024 }, 'Résumé')).toBeNull();
    expect(validateApplicationPdf({ name: 'resume.pdf', type: 'application/pdf', size: MAX_APPLICATION_PDF_BYTES }, 'Résumé')).toBeNull();
    expect(validateApplicationPdf({ name: 'resume.pdf', type: 'application/pdf', size: MAX_APPLICATION_PDF_BYTES + 1 }, 'Résumé')).toContain('5 MB');
  });
  it('enforces the 50–250 character cover-note boundary and rejects control bytes', () => {
    expect(validateCoverNote('')).toContain('at least 50');
    expect(validateCoverNote(' '.repeat(60))).toContain('at least 50');
    expect(validateCoverNote('A'.repeat(49))).toContain('at least 50');
    expect(validateCoverNote('A'.repeat(50))).toBeNull();
    expect(validateCoverNote('A'.repeat(250))).toBeNull();
    expect(validateCoverNote('A'.repeat(251))).toContain('250');
    expect(validateCoverNote(`${'A'.repeat(60)}\u0000`)).toContain('control');
  });
});

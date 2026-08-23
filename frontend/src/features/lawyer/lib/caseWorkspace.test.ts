import { describe, expect, it } from 'vitest';
import { initCase, sendWelcome, CASE_TABS } from './caseWorkspace';

describe('case workspace init (SAATHI-10 / E03)', () => {
  it('creates a case with a stable ref and five tabs', () => {
    const c = initCase('Acme v. Sunrise', '2026-07-08');
    expect(c.ref).toMatch(/^NYAY-CASE-\d+$/);
    expect(c.tabs).toHaveLength(5);
    expect(CASE_TABS.map((t) => t.id)).toEqual(['timeline', 'documents', 'notes', 'communication', 'milestones']);
    expect(CASE_TABS.every((t) => t.empty.length > 0)).toBe(true);
  });

  it('sends welcome only with logged opt-in consent', () => {
    expect(sendWelcome({ channel: 'whatsapp', optedIn: true, loggedAt: '2026-07-08' })).toEqual({ outcome: 'sent', deliveryStatus: 'queued' });
    expect(sendWelcome({ channel: 'whatsapp', optedIn: true, loggedAt: null }).outcome).toBe('skipped_no_consent');
    expect(sendWelcome({ channel: 'whatsapp', optedIn: false, loggedAt: '2026-07-08' }).deliveryStatus).toBe('not_sent');
  });
});

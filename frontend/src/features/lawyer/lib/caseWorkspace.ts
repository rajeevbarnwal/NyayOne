/**
 * Case workspace initialization logic (SAATHI-10 · Core E03).
 * On retainer-signed, create a case record with a stable reference ID and five
 * tabs; welcome communication is sent ONLY when client channel opt-in/consent
 * is logged first (DPDP). Pure + testable; notifications are a stub boundary.
 */

export type CaseTab = 'timeline' | 'documents' | 'notes' | 'communication' | 'milestones';

export const CASE_TABS: ReadonlyArray<{ id: CaseTab; label: string; empty: string }> = [
  { id: 'timeline', label: 'Timeline / Roznama', empty: 'No hearings or events yet.' },
  { id: 'documents', label: 'Documents', empty: 'No documents collected yet.' },
  { id: 'notes', label: 'Notes', empty: 'No notes yet.' },
  { id: 'communication', label: 'Client Communication', empty: 'No messages yet.' },
  { id: 'milestones', label: 'Milestone Tracker', empty: 'No milestones set yet.' },
];

let caseSeq = 2040;
/** Stable internal LegalSaathi reference id (server-authoritative in prod). */
export function newCaseRef(): string {
  caseSeq += 1;
  return `LS-CASE-${caseSeq}`;
}

export interface CaseRecord {
  readonly ref: string;
  readonly title: string;
  readonly tabs: readonly CaseTab[];
  readonly createdAt: string;
}

export function initCase(title: string, now: string): CaseRecord {
  return { ref: newCaseRef(), title, tabs: CASE_TABS.map((t) => t.id), createdAt: now };
}

export interface CommunicationConsent {
  readonly channel: 'whatsapp' | 'email';
  readonly optedIn: boolean;
  readonly loggedAt: string | null;
}

export type WelcomeOutcome = 'sent' | 'skipped_no_consent';
export interface WelcomeResult {
  readonly outcome: WelcomeOutcome;
  readonly deliveryStatus: 'queued' | 'not_sent';
}

/** Welcome message is sent only when consent is opted-in AND logged first. */
export function sendWelcome(consent: CommunicationConsent): WelcomeResult {
  if (consent.optedIn && consent.loggedAt) {
    return { outcome: 'sent', deliveryStatus: 'queued' };
  }
  return { outcome: 'skipped_no_consent', deliveryStatus: 'not_sent' };
}

export const CONSENT_NOTICE =
  'Automated client messages are sent only after DPDP notice/consent and channel opt-in are logged.';

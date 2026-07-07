/**
 * Internship browse/filter/save/apply/track logic (SAATHI-60/61 · S4).
 * Pure + testable. Scope is S4 only (browse/detail/save/apply/confirm/track);
 * S18 experience reporting is explicitly out of scope. No external integrations —
 * listings are sample/source-labelled and applications live in a local store.
 */

export type StipendFilter = 'any' | 'paid' | 'unpaid';

export interface InternshipListing {
  readonly id: string;
  readonly role: string;
  readonly org: string;
  readonly location: string;
  readonly stipendMonthly: number | null; // null = unpaid
  readonly verified: boolean;
  readonly deadline: string; // display, e.g. "9 Jul"
  readonly eligibility: string;
  readonly tags: readonly string[];
  readonly description: string;
  readonly sourceLabel: string; // provenance, always shown
}

/** Application lifecycle. `action_needed`/`closed` are terminal-ish display states. */
export type ApplicationStatus =
  | 'applied'
  | 'under_review'
  | 'interview'
  | 'offer'
  | 'action_needed'
  | 'closed';

export const APPLICATION_STAGES = ['Applied', 'Screen', 'Interview', 'Offer'] as const;

export interface Application {
  readonly id: string;
  readonly listingId: string;
  readonly org: string;
  readonly role: string;
  readonly meta: string;
  readonly status: ApplicationStatus;
  readonly note?: string;
}

/** Stepper index (1..4) reached for a status. */
export function stepForStatus(s: ApplicationStatus): number {
  switch (s) {
    case 'applied':
    case 'action_needed':
      return 1;
    case 'under_review':
      return 2;
    case 'interview':
      return 3;
    case 'offer':
      return 4;
    case 'closed':
      return 1;
    default:
      return 1;
  }
}

export type ChipKind = 'ok' | 'warn' | 'risk' | 'info';

/** Status → semantic chip (never colour-only; label carried by caller). */
export function statusChip(s: ApplicationStatus): { kind: ChipKind; label: string } {
  switch (s) {
    case 'interview':
      return { kind: 'ok', label: 'Interview' };
    case 'offer':
      return { kind: 'ok', label: 'Offer' };
    case 'under_review':
      return { kind: 'info', label: 'Under review' };
    case 'action_needed':
      return { kind: 'risk', label: 'Action needed' };
    case 'closed':
      return { kind: 'warn', label: 'Closed' };
    case 'applied':
    default:
      return { kind: 'info', label: 'Applied' };
  }
}

export function stipendText(l: InternshipListing): string {
  return l.stipendMonthly === null ? 'unpaid' : `₹${l.stipendMonthly.toLocaleString('en-IN')}/mo`;
}

/** Filter listings by free-text query, stipend, and verified-only. */
export function filterListings(
  list: readonly InternshipListing[],
  opts: { query?: string; stipend?: StipendFilter; verifiedOnly?: boolean } = {}
): InternshipListing[] {
  const q = (opts.query ?? '').trim().toLowerCase();
  const stipend = opts.stipend ?? 'any';
  return list.filter((l) => {
    if (q && ![l.role, l.org, l.location].some((f) => f.toLowerCase().includes(q))) return false;
    if (stipend === 'paid' && l.stipendMonthly === null) return false;
    if (stipend === 'unpaid' && l.stipendMonthly !== null) return false;
    if (opts.verifiedOnly && !l.verified) return false;
    return true;
  });
}

export function toggleSave(saved: readonly string[], id: string): string[] {
  return saved.includes(id) ? saved.filter((x) => x !== id) : [...saved, id];
}

let refSeq = 4820;
/** Generate an application reference id (stub; server-authoritative in prod). */
export function newApplicationRef(): string {
  refSeq += 1;
  return `LS-INT-${refSeq}`;
}

export const SAMPLE_LISTINGS: readonly InternshipListing[] = [
  {
    id: 'cam',
    role: 'Summer Associate',
    org: 'Cyril Amarchand Mangaldas',
    location: 'Mumbai',
    stipendMonthly: 40000,
    verified: true,
    deadline: '9 Jul',
    eligibility: '3rd–4th year · apply by 9 Jul · joins Dec 2026',
    tags: ['Disputes', 'Mumbai', '6 weeks'],
    description:
      '6-week summer internship with the disputes team, Mumbai. Research, drafting and hearing support. Stipend ₹40,000/month.',
    sourceLabel: 'Source: firm career pages · unverified · not affiliated',
  },
  {
    id: 'menon',
    role: 'Judicial research',
    org: 'Chambers of Sr. Adv. R. Menon',
    location: 'Delhi HC',
    stipendMonthly: 15000,
    verified: false,
    deadline: '8 Jul',
    eligibility: '2nd year+ · rolling',
    tags: ['Research', 'Delhi'],
    description: 'Judicial research support with a senior advocate’s chambers at the Delhi High Court.',
    sourceLabel: 'Source: firm career pages · unverified · not affiliated',
  },
  {
    id: 'vidhi',
    role: 'Policy intern',
    org: 'Vidhi Centre for Legal Policy',
    location: 'New Delhi',
    stipendMonthly: null,
    verified: false,
    deadline: '15 Jul',
    eligibility: 'All years · certificate',
    tags: ['Policy', 'Research'],
    description: 'Legal-policy research internship; certificate on completion. Unpaid.',
    sourceLabel: 'Source: firm career pages · unverified · not affiliated',
  },
];

export const SAMPLE_APPLICATIONS: readonly Application[] = [
  { id: 'a1', listingId: 'cam', org: 'Cyril Amarchand Mangaldas', role: 'Summer Associate', meta: 'Mumbai · ₹40,000/mo', status: 'interview', note: 'Interview Wed 9' },
  { id: 'a2', listingId: 'azb', org: 'AZB & Partners', role: 'Pre-Placement', meta: 'Bengaluru · ₹35,000/mo', status: 'under_review' },
  { id: 'a3', listingId: 'menon', org: 'Chambers of Sr. Adv. R. Menon', role: 'Judicial research', meta: 'Delhi HC · ₹15,000/mo', status: 'action_needed', note: 'Upload transcript by 8 Jul' },
  { id: 'a4', listingId: 'trilegal', org: 'Trilegal', role: 'Corporate', meta: 'Bengaluru · ₹30,000/mo', status: 'applied', note: 'Applied 2 Jul' },
  { id: 'a5', listingId: 'vidhi', org: 'Vidhi Centre for Legal Policy', role: 'Research fellowship', meta: 'not selected · recorded 28 Jun', status: 'closed' },
];

export const APPLY_DPDP = 'Documents leave LegalSaathi only when you submit';
export const TRACKER_SOURCE = 'Source: firm career pages · external listings, unverified · not affiliated. Applications leave only when you submit';

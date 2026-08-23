/**
 * Internship browse/filter/save/apply/track logic (SAATHI-60/61 · S4).
 * Pure + testable. Scope is S4 only (browse/detail/save/apply/confirm/track);
 * S18 experience reporting is explicitly out of scope. No external integrations —
 * listings are sample/source-labelled and transitional application state is
 * tab-memory-only until a server persistence contract exists.
 */

export type StipendFilter = 'any' | 'paid' | 'unpaid';

export interface InternshipListing {
  readonly id: string;
  /** Stable opaque identity used only by the gated aggregate projection. */
  readonly organisationId?: string;
  readonly role: string;
  readonly org: string;
  readonly location: string;
  readonly stipendMonthlyPaise: number | null; // null = unpaid; integer paise, never float money
  readonly verificationStatus: 'verified' | 'unverified';
  readonly deadline: string; // display, e.g. "9 Jul"
  readonly eligibility: string;
  readonly tags: readonly string[];
  readonly description: string;
  readonly source: {
    readonly name: string;
    readonly url: string | null;
    readonly retrievedAt: string | null;
    readonly verifiedAt: string | null;
  };
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
  return l.stipendMonthlyPaise === null
    ? 'unpaid'
    : `${(l.stipendMonthlyPaise / 100).toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })}/mo`;
}

export function isVerifiedListing(listing: InternshipListing): boolean {
  return listing.verificationStatus === 'verified';
}

/** A single structured status owns both the badge and the provenance sentence. */
export function listingSourceLabel(listing: InternshipListing): string {
  if (listing.verificationStatus === 'verified') {
    const checked = listing.source.verifiedAt ?? listing.source.retrievedAt;
    return `Source: ${listing.source.name} · verified${checked ? ` ${new Date(checked).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })}` : ''} · not affiliated`;
  }
  return `Source: ${listing.source.name} · unverified · not affiliated`;
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
    if (stipend === 'paid' && l.stipendMonthlyPaise === null) return false;
    if (stipend === 'unpaid' && l.stipendMonthlyPaise !== null) return false;
    if (opts.verifiedOnly && !isVerifiedListing(l)) return false;
    return true;
  });
}

let refSeq = 4820;
/** Generate an application reference id (stub; server-authoritative in prod). */
export function newApplicationRef(): string {
  refSeq += 1;
  return `LS-INT-${refSeq}`;
}

export const MAX_APPLICATION_PDF_BYTES = 5 * 1024 * 1024;
export const MIN_COVER_NOTE_LENGTH = 50;
export const MAX_COVER_NOTE_LENGTH = 250;

/** Design-approved S-22 boundary: meaningful note, bounded storage and no control bytes. */
export function validateCoverNote(value: string): string | null {
  const trimmed = value.trim();
  const hasControlCharacter = Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return (
      codePoint <= 8 ||
      codePoint === 11 ||
      codePoint === 12 ||
      (codePoint >= 14 && codePoint <= 31) ||
      codePoint === 127
    );
  });
  if (hasControlCharacter) return 'Cover note contains unsupported control characters.';
  if (trimmed.length < MIN_COVER_NOTE_LENGTH) return `Cover note must be at least ${MIN_COVER_NOTE_LENGTH} characters.`;
  if (trimmed.length > MAX_COVER_NOTE_LENGTH) return `Cover note must be ${MAX_COVER_NOTE_LENGTH} characters or fewer.`;
  return null;
}

/** Validate an actual upload, not a typed file-name placeholder. */
export function validateApplicationPdf(
  file: Pick<File, 'name' | 'type' | 'size'> | null,
  label: string,
): string | null {
  if (!file) return `${label} PDF is required.`;
  const pdfType = file.type === 'application/pdf';
  const pdfName = file.name.toLowerCase().endsWith('.pdf');
  if (!pdfType || !pdfName) return `${label} must be a PDF file.`;
  if (file.size <= 0) return `${label} file is empty.`;
  if (file.size > MAX_APPLICATION_PDF_BYTES) return `${label} must be 5 MB or smaller.`;
  return null;
}

let submittedApplications: Application[] = [];

export function saveSubmittedApplication(application: Application): void {
  submittedApplications = [
    { ...application },
    ...submittedApplications.filter((candidate) => candidate.id !== application.id),
  ];
}

export function loadSubmittedApplications(): Application[] {
  return submittedApplications.map((application) => ({ ...application }));
}

export function loadLatestSubmittedApplication(): Application | null {
  return loadSubmittedApplications()[0] ?? null;
}

export function clearSubmittedApplications(): void {
  submittedApplications = [];
}

export const SAMPLE_LISTINGS: readonly InternshipListing[] = [
  {
    id: 'cam',
    role: 'Summer Associate, disputes',
    org: 'Cyril Amarchand Mangaldas',
    location: 'Mumbai',
    stipendMonthlyPaise: 4000000,
    verificationStatus: 'verified',
    deadline: '9 Jul',
    eligibility: '3rd–4th year · apply by 9 Jul · joins Dec 2026',
    tags: ['Disputes', 'Mumbai', '6 weeks'],
    description:
      '6-week summer internship with the disputes team, Mumbai. Research, drafting and hearing support. Stipend ₹40,000/month.',
    source: {
      name: 'Cyril Amarchand Mangaldas careers',
      url: 'https://www.cyrilshroff.com/careers/',
      retrievedAt: '2026-06-28T00:00:00+05:30',
      verifiedAt: '2026-06-28T00:00:00+05:30',
    },
  },
  {
    id: 'menon',
    role: 'Judicial research assistant',
    org: 'Chambers of Sr. Adv. R. Menon',
    location: 'Delhi HC',
    stipendMonthlyPaise: 1500000,
    verificationStatus: 'unverified',
    deadline: '8 Jul',
    eligibility: '2nd year+ · rolling',
    tags: ['Research', 'Delhi'],
    description: 'Judicial research support with a senior advocate’s chambers at the Delhi High Court.',
    source: { name: 'Sample fixture', url: null, retrievedAt: null, verifiedAt: null },
  },
  {
    id: 'vidhi',
    role: 'Research fellowship, policy',
    org: 'Vidhi Centre for Legal Policy',
    location: 'New Delhi',
    stipendMonthlyPaise: null,
    verificationStatus: 'unverified',
    deadline: '15 Jul',
    eligibility: 'All years · certificate',
    tags: ['Policy', 'Research'],
    description: 'Legal-policy research internship; certificate on completion. Unpaid.',
    source: { name: 'Sample fixture', url: null, retrievedAt: null, verifiedAt: null },
  },
];

export const SAMPLE_APPLICATIONS: readonly Application[] = [
  { id: 'a1', listingId: 'cam', org: 'Cyril Amarchand Mangaldas', role: 'Summer Associate, disputes', meta: 'Mumbai · ₹40,000/mo', status: 'interview', note: 'Interview Wed 9' },
  { id: 'a2', listingId: 'azb', org: 'AZB & Partners', role: 'Pre-Placement', meta: 'Bengaluru · ₹35,000/mo', status: 'under_review' },
  { id: 'a3', listingId: 'menon', org: 'Chambers of Sr. Adv. R. Menon', role: 'Judicial research assistant', meta: 'Delhi HC · ₹15,000/mo', status: 'action_needed', note: 'Upload transcript by 8 Jul' },
  { id: 'a4', listingId: 'trilegal', org: 'Trilegal', role: 'Corporate', meta: 'Bengaluru · ₹30,000/mo', status: 'applied', note: 'Applied 2 Jul' },
  { id: 'a5', listingId: 'vidhi', org: 'Vidhi Centre for Legal Policy', role: 'Research fellowship, policy', meta: 'not selected · recorded 28 Jun', status: 'closed' },
];

export const APPLY_DPDP = 'Documents leave LegalSaathi only when you submit';
export const TRACKER_SOURCE = 'Source: firm career pages · external listings, unverified · not affiliated. Applications leave only when you submit';

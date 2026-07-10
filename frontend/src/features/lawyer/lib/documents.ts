/**
 * Document collection + classification logic (SAATHI-14 · Core E05).
 * Checklist state machine; secure client links expire and carry no PII; OCR is
 * assistive only — the lawyer must confirm tags before legal reliance. DPDP
 * minimisation + access logging. Pure + testable; storage/OCR are stubs.
 */

export type DocState = 'missing' | 'received' | 'rejected' | 'needs_clarification';

export interface ChecklistItem {
  readonly key: string;
  readonly label: string;
  readonly state: DocState;
}

export const DOC_STATE_LABELS: Record<DocState, string> = {
  missing: 'Missing',
  received: 'Received',
  rejected: 'Rejected',
  needs_clarification: 'Needs clarification',
};

export interface UploadedDoc {
  readonly id: string;
  readonly filename: string;
  readonly ocrText: string;
  readonly ocrConfirmed: boolean; // lawyer confirmed tags
  readonly tags: readonly string[];
}

/** OCR output is machine-extracted and NOT reliable until a lawyer confirms. */
export function isReliableForLegalUse(d: UploadedDoc): boolean {
  return d.ocrConfirmed;
}

export function confirmTags(d: UploadedDoc, tags: readonly string[]): UploadedDoc {
  return { ...d, tags: [...tags], ocrConfirmed: true };
}

const ALLOWED_EXT = ['pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'];
export function isAllowedFile(filename: string): boolean {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  return ALLOWED_EXT.includes(ext);
}

export interface SecureLink {
  readonly token: string;
  readonly url: string;
  readonly expiresAt: number;
}

/** Build an expiring client link. The token is opaque; the URL carries NO PII. */
export function makeSecureLink(token: string, now: number, ttlMs = 24 * 60 * 60 * 1000): SecureLink {
  return { token, url: `/u/${token}`, expiresAt: now + ttlMs };
}
export function linkValid(link: SecureLink, now: number): boolean {
  return now < link.expiresAt;
}
/** Guardrail: a client link must never embed PII (name/email/phone) in the URL. */
export function urlHasNoPii(url: string): boolean {
  return !/@|\bphone\b|\bemail\b|\bname\b|\d{10}/i.test(url);
}

export function checklistProgress(items: readonly ChecklistItem[]): { received: number; total: number } {
  return { received: items.filter((i) => i.state === 'received').length, total: items.length };
}

export const SAMPLE_CHECKLIST: readonly ChecklistItem[] = [
  { key: 'id', label: 'Client ID proof', state: 'received' },
  { key: 'agreement', label: 'Disputed agreement', state: 'received' },
  { key: 'notice', label: 'Legal notice (if any)', state: 'needs_clarification' },
  { key: 'evidence', label: 'Supporting evidence', state: 'missing' },
];

export const OCR_MACHINE_LABEL = 'Machine-extracted — verify before legal reliance';
export const DPDP_ACCESS_NOTICE = 'Files are access-controlled and logged; links expire and carry no personal data.';

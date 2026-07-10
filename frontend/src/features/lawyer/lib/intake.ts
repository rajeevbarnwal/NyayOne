/**
 * Client intake + conflict check logic (SAATHI-6 · Core E01).
 * Synchronous conflict check BEFORE case creation: exact + fuzzy party-name
 * match. Possible conflict blocks creation or routes to an authorised override
 * with a recorded reason. All checks are also enforced server-side; AI cannot
 * clear conflicts. Pure + testable; local stub matcher (no external service).
 */

export interface Party {
  readonly name: string;
  readonly role: 'client' | 'opponent';
}

export interface IntakeDraft {
  clientName: string;
  opponentName: string;
  matterType: string;
  courtPreference: string;
  contact: string;
  source: string;
}

export const EMPTY_INTAKE: IntakeDraft = {
  clientName: '',
  opponentName: '',
  matterType: '',
  courtPreference: '',
  contact: '',
  source: '',
};

export type FieldErrors = Record<string, string>;

export function validateIntake(d: IntakeDraft): FieldErrors {
  const e: FieldErrors = {};
  if (!d.clientName.trim()) e.clientName = 'Enter the client name.';
  if (!d.opponentName.trim()) e.opponentName = 'Enter the opponent name.';
  if (!d.matterType.trim()) e.matterType = 'Select a matter type.';
  if (!d.contact.trim()) e.contact = 'Enter a contact.';
  return e;
}

/** Normalise a party name for matching (case/space/punct-insensitive). */
export function normaliseName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

/** Token-set similarity in [0,1] — a light fuzzy match (no external deps). */
export function nameSimilarity(a: string, b: string): number {
  const ta = new Set(normaliseName(a).split(' ').filter(Boolean));
  const tb = new Set(normaliseName(b).split(' ').filter(Boolean));
  if (ta.size === 0 || tb.size === 0) return 0;
  let inter = 0;
  for (const t of ta) if (tb.has(t)) inter += 1;
  return inter / new Set([...ta, ...tb]).size;
}

export type MatchKind = 'exact' | 'fuzzy';
export interface ConflictMatch {
  readonly party: Party;
  readonly against: string; // existing name matched
  readonly kind: MatchKind;
  readonly score: number;
}

export const FUZZY_THRESHOLD = 0.5;

/** Run the conflict check against an existing register of known parties. */
export function checkConflicts(draft: IntakeDraft, register: readonly string[]): ConflictMatch[] {
  const candidates: Party[] = [
    { name: draft.clientName, role: 'client' },
    { name: draft.opponentName, role: 'opponent' },
  ];
  const out: ConflictMatch[] = [];
  for (const p of candidates) {
    if (!p.name.trim()) continue;
    for (const existing of register) {
      if (normaliseName(p.name) === normaliseName(existing)) {
        out.push({ party: p, against: existing, kind: 'exact', score: 1 });
        continue;
      }
      const s = nameSimilarity(p.name, existing);
      if (s >= FUZZY_THRESHOLD) out.push({ party: p, against: existing, kind: 'fuzzy', score: Number(s.toFixed(2)) });
    }
  }
  return out;
}

export type ConflictDecision = 'clear' | 'blocked' | 'overridden';

export interface ConflictResult {
  readonly decision: ConflictDecision;
  readonly matches: readonly ConflictMatch[];
  readonly checker: string;
  readonly timestamp: string;
  readonly overrideReason?: string;
}

/** Decide outcome. With matches, default is BLOCKED; an authorised override
 *  requires a non-empty reason. AI/automation can never produce 'clear' when
 *  matches exist — only a human override. */
export function decideConflict(
  matches: readonly ConflictMatch[],
  now: string,
  checker: string,
  override?: { authorised: boolean; reason: string }
): ConflictResult {
  if (matches.length === 0) return { decision: 'clear', matches, checker, timestamp: now };
  if (override && override.authorised && override.reason.trim()) {
    return { decision: 'overridden', matches, checker, timestamp: now, overrideReason: override.reason.trim() };
  }
  return { decision: 'blocked', matches, checker, timestamp: now };
}

/** Case creation may proceed only when clear or authorised-override. */
export function canProceed(r: ConflictResult): boolean {
  return r.decision === 'clear' || r.decision === 'overridden';
}

/** Immutable audit event for a conflict decision (shape mirrors audit service). */
export interface ConflictAuditEvent {
  readonly type: 'conflict_check';
  readonly decision: ConflictDecision;
  readonly checker: string;
  readonly timestamp: string;
  readonly matchCount: number;
  readonly overrideReason?: string;
}
export function toAuditEvent(r: ConflictResult): ConflictAuditEvent {
  return {
    type: 'conflict_check',
    decision: r.decision,
    checker: r.checker,
    timestamp: r.timestamp,
    matchCount: r.matches.length,
    overrideReason: r.overrideReason,
  };
}

export const MATTER_TYPES = ['Civil suit', 'Writ petition', 'Arbitration', 'Consumer', 'Family', 'Other'];
export const SAMPLE_REGISTER = ['Acme Textiles Pvt Ltd', 'R. K. Traders', 'Sunrise Builders', 'Meera Nair'];
export const CONFLICT_GUARDRAIL = 'Conflict clearance is a human decision — the platform never auto-clears a possible conflict.';

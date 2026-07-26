import { describe, expect, it } from 'vitest';
import { ANONYMOUS_AUTH, type AuthState } from '../../../app/authContext';
import { filingActorFromAuth, lawyerActorFromAuth, lawyerRouteDenial, canEnterStage } from './caseAuth';
import type { FilingAction } from './filingWorkflow';

const base: AuthState = {
  isAuthenticated: true, userId: 'u1', roles: ['student'],
  studentVerification: 'verified', lawyerVerification: 'draft', filingRole: null, isMinor: false,
};
const client: AuthState = { ...base, roles: [] };
const unverifiedLawyer: AuthState = { ...base, roles: ['lawyer'], lawyerVerification: 'submitted' };
const verifiedLawyer: AuthState = { ...base, userId: 'adv-1', roles: ['lawyer'], lawyerVerification: 'verified' };
/** A verified workspace member holding functional role `filingRole`. */
const workspace = (filingRole: string, userId = `subj_${filingRole}`): AuthState =>
  ({ ...base, userId, roles: ['lawyer'], lawyerVerification: 'verified', filingRole });

// Stage action sets (mirror screens.tsx).
const FINALIZE: FilingAction[] = ['checklist', 'lock', 'edit_after_lock', 'notify_config'];
const FILING: FilingAction[] = ['filing_record', 'filing_proof', 'invoice_approve', 'filing_correct'];
const DIARY: FilingAction[] = ['diary_capture', 'diary_ack', 'diary_correct', 'diary_notify'];
const FEES: FilingAction[] = ['fee_add', 'fee_pay', 'fee_allocate', 'fee_receipt'];
const TRACKING: FilingAction[] = ['cnr_capture', 'tracking_activate', 'identifier_fetch', 'identifier_manual'];

describe('lawyerActorFromAuth / lawyerRouteDenial (session → workflow actor)', () => {
  it('denies anonymous / student / client / unverified lawyer (null actor + denial reason)', () => {
    for (const a of [ANONYMOUS_AUTH, base, client, unverifiedLawyer]) {
      expect(lawyerActorFromAuth(a)).toBeNull();
      expect(lawyerRouteDenial(a)).toBeTruthy();
    }
  });

  it('maps a verified lawyer to a finalize-capable actor bound to the session id', () => {
    const actor = lawyerActorFromAuth(verifiedLawyer);
    expect(actor).toEqual({ id: 'adv-1', role: 'lawyer' });
    expect(lawyerRouteDenial(verifiedLawyer)).toBeNull();
  });

  it('never derives the actor role from a caller-supplied string', () => {
    // the actor role comes from the auth roles + verification, not a free string
    const spoof: AuthState = { ...base, userId: 'lawyer:rao', roles: ['student'] };
    expect(lawyerActorFromAuth(spoof)).toBeNull();
  });
});

describe('role x /case route guard matrix (E01-E12 all guarded)', () => {
  const rejectedLawyer: AuthState = { ...base, roles: ['lawyer'], lawyerVerification: 'rejected' };
  const denied: Record<string, AuthState> = {
    anonymous: ANONYMOUS_AUTH,
    student: base,
    client,
    unverifiedLawyer,
    rejectedLawyer,
  };
  it('every non-verified persona is denied the lawyer routes (guard reason present)', () => {
    for (const auth of Object.values(denied)) {
      expect(lawyerRouteDenial(auth)).toBeTruthy();
      expect(lawyerActorFromAuth(auth)).toBeNull(); // no workflow actor either
    }
  });
  it('only a verified lawyer is allowed and maps to a finalize-capable actor', () => {
    expect(lawyerRouteDenial(verifiedLawyer)).toBeNull();
    expect(lawyerActorFromAuth(verifiedLawyer)).toEqual({ id: 'adv-1', role: 'lawyer' });
  });
});

describe('filingActorFromAuth persona claim → real FilingActorRole', () => {
  it('maps each verified workspace role to its actor (opaque subject id, not a role string)', () => {
    for (const role of ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'clerk', 'billing_admin']) {
      expect(filingActorFromAuth(workspace(role))).toEqual({ id: `subj_${role}`, role });
    }
  });
  it('denies unknown, student, client claims and never silently upgrades to lawyer', () => {
    expect(filingActorFromAuth(workspace('sith_lord'))).toBeNull();     // unknown role claim
    expect(filingActorFromAuth(workspace('student'))).toBeNull();
    expect(filingActorFromAuth(workspace('client'))).toBeNull();
    expect(filingActorFromAuth(workspace('unknown'))).toBeNull();
    expect(filingActorFromAuth({ ...workspace('lawyer'), userId: '' })).toBeNull(); // missing opaque subject
    expect(filingActorFromAuth(unverifiedLawyer)).toBeNull(); // unverified
  });
});

describe('canEnterStage role × route least-privilege matrix', () => {
  const cases: Array<[string, FilingAction[], string[]]> = [
    // [route, stageActions, roles that MAY enter]
    ['finalize', FINALIZE, ['lawyer', 'senior_advocate', 'firm_partner', 'associate']],
    ['filing', FILING, ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'clerk', 'billing_admin']],
    ['diary', DIARY, ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'clerk']],
    ['fees', FEES, ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'billing_admin']],
    ['tracking', TRACKING, ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'clerk']],
  ];
  const allRoles = ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'clerk', 'billing_admin'];
  it('permits only Jira-authorised personas per stage; denies the rest', () => {
    for (const [route, stage, allowed] of cases) {
      for (const role of allRoles) {
        const expected = allowed.includes(role);
        expect(canEnterStage(workspace(role), stage)).toBe(expected);
      }
      void route;
    }
  });
  it('key negative cases: clerk cannot enter finalize; billing admin cannot enter diary or tracking', () => {
    expect(canEnterStage(workspace('clerk'), FINALIZE)).toBe(false);
    expect(canEnterStage(workspace('billing_admin'), DIARY)).toBe(false);
    expect(canEnterStage(workspace('billing_admin'), TRACKING)).toBe(false);
    expect(canEnterStage(workspace('billing_admin'), FINALIZE)).toBe(false);
    expect(canEnterStage(workspace('clerk'), FEES)).toBe(false);
  });
  it('anonymous/unverified are denied every stage', () => {
    for (const stage of [FINALIZE, FILING, DIARY, FEES, TRACKING]) {
      expect(canEnterStage(ANONYMOUS_AUTH, stage)).toBe(false);
      expect(canEnterStage(unverifiedLawyer, stage)).toBe(false);
    }
  });
});

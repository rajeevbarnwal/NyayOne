import { describe, expect, it } from 'vitest';
import { ANONYMOUS_AUTH, type AuthState } from '../../../app/authContext';
import { lawyerActorFromAuth, lawyerRouteDenial } from './caseAuth';

const base: AuthState = {
  isAuthenticated: true, userId: 'u1', roles: ['student'],
  studentVerification: 'verified', lawyerVerification: 'draft', isMinor: false,
};
const client: AuthState = { ...base, roles: [] };
const unverifiedLawyer: AuthState = { ...base, roles: ['lawyer'], lawyerVerification: 'submitted' };
const verifiedLawyer: AuthState = { ...base, userId: 'adv-1', roles: ['lawyer'], lawyerVerification: 'verified' };

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

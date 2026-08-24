import { describe, expect, it } from 'vitest';
import {
  validWave4StaffSession,
  validWave4StudentSession,
} from './wave4-session-validator.mjs';

const actor = (role) => ({
  authenticated: true,
  actor: {
    sub: '00000000-0000-4000-8000-000000002740',
    roles: [role],
    student_profile_id: null,
    student_verification: 'draft',
    is_minor: false,
    consent_state: [],
  },
});

describe('Wave4 server-session role validator', () => {
  it.each(['moderator', 'admin'])('accepts an exact server-issued %s session', (role) => {
    expect(validWave4StaffSession(actor(role))).toBe(true);
  });

  it.each([
    ['empty roles', { ...actor('moderator'), actor: { ...actor('moderator').actor, roles: [] } }],
    ['unknown role', actor('owner')],
    ['student role', actor('student')],
    ['mixed forged roles', { ...actor('moderator'), actor: { ...actor('moderator').actor, roles: ['moderator', 'admin'] } }],
    ['non-string role', { ...actor('moderator'), actor: { ...actor('moderator').actor, roles: [7] } }],
    ['missing actor', { authenticated: true, actor: null }],
    ['extra claim', { ...actor('moderator'), actor: { ...actor('moderator').actor, forged: true } }],
  ])('rejects %s fail-closed', (_label, value) => {
    expect(validWave4StaffSession(value)).toBe(false);
  });
});

describe('Wave4 reporting student-session validator', () => {
  const studentId = '00000000-0000-4000-8000-0000000000de';
  const profileId = '00000000-0000-4000-8000-000000008601';
  const session = {
    authenticated: true,
    actor: {
      sub: studentId,
      roles: ['student'],
      student_profile_id: profileId,
      student_verification: 'draft',
      is_minor: false,
      consent_state: ['registration'],
    },
  };

  it('accepts the exact canonical reporter projection', () => {
    expect(validWave4StudentSession(session, studentId)).toBe(true);
  });

  it.each([
    ['wrong actor', { ...session, actor: { ...session.actor, sub: '00000000-0000-4000-8000-0000000000b2' } }],
    ['missing profile', { ...session, actor: { ...session.actor, student_profile_id: null } }],
    ['wrong role', { ...session, actor: { ...session.actor, roles: ['lawyer'] } }],
    ['extra role', { ...session, actor: { ...session.actor, roles: ['student', 'admin'] } }],
    ['minor', { ...session, actor: { ...session.actor, is_minor: true } }],
    ['missing consent', { ...session, actor: { ...session.actor, consent_state: [] } }],
    ['extra consent', { ...session, actor: { ...session.actor, consent_state: ['registration', 'marketing'] } }],
    ['extra claim', { ...session, actor: { ...session.actor, forged: true } }],
  ])('rejects %s fail-closed', (_label, candidate) => {
    expect(validWave4StudentSession(candidate, studentId)).toBe(false);
  });
});

import { describe, expect, it } from 'vitest';
import { validWave4StaffSession } from './wave4-session-validator.mjs';

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

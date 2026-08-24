const STAFF_ROLES = new Set(['moderator', 'admin']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export function validWave4StaffSession(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  if (value.authenticated !== true || value.actor === null
      || typeof value.actor !== 'object' || Array.isArray(value.actor)) return false;
  if (Object.keys(value).sort().join(',') !== 'actor,authenticated') return false;

  const actor = value.actor;
  if (Object.keys(actor).sort().join(',')
      !== 'consent_state,is_minor,roles,student_profile_id,student_verification,sub') return false;
  return typeof actor.sub === 'string'
    && UUID.test(actor.sub)
    && Array.isArray(actor.roles)
    && actor.roles.length === 1
    && typeof actor.roles[0] === 'string'
    && STAFF_ROLES.has(actor.roles[0])
    && actor.student_profile_id === null
    && actor.student_verification === 'draft'
    && actor.is_minor === false
    && Array.isArray(actor.consent_state)
    && actor.consent_state.length === 0;
}

export function validWave4StudentSession(value, expectedSub) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  if (value.authenticated !== true || value.actor === null
      || typeof value.actor !== 'object' || Array.isArray(value.actor)) return false;
  if (Object.keys(value).sort().join(',') !== 'actor,authenticated') return false;

  const actor = value.actor;
  if (Object.keys(actor).sort().join(',')
      !== 'consent_state,is_minor,roles,student_profile_id,student_verification,sub') return false;
  return typeof expectedSub === 'string'
    && UUID.test(expectedSub)
    && actor.sub === expectedSub
    && Array.isArray(actor.roles)
    && actor.roles.length === 1
    && actor.roles[0] === 'student'
    && typeof actor.student_profile_id === 'string'
    && UUID.test(actor.student_profile_id)
    && actor.student_verification === 'draft'
    && actor.is_minor === false
    && Array.isArray(actor.consent_state)
    && actor.consent_state.length === 1
    && actor.consent_state[0] === 'registration';
}

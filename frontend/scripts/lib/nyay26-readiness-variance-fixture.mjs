const SEEDED_HEADING_STACK_VARIANCE = Object.freeze({
  assertion: 'browser:redesigned_heading_stack',
  attempts: 1,
  legacyOutcome: 'FAIL_EARLY_SAMPLE',
  settledOutcome: 'PASS',
});

export function runSeededHeadingStackVariance({ attempts } = { attempts: 1 }) {
  if (attempts !== SEEDED_HEADING_STACK_VARIANCE.attempts) {
    throw new Error('NYAY26_SEEDED_VARIANCE_ATTEMPTS_INVALID');
  }
  return SEEDED_HEADING_STACK_VARIANCE;
}

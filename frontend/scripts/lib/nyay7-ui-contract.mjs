export const NYAY7_AUTHORITY_SHA256 = '338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252';

export const NYAY7_VIEWPORTS = Object.freeze([
  Object.freeze({ id: 'desktop', directory: '1440x1024', width: 1440, height: 1024 }),
  Object.freeze({ id: 'mobile-390', directory: '390x844', width: 390, height: 844 }),
  Object.freeze({ id: 'mobile-360', directory: '360x800', width: 360, height: 800 }),
]);

export const NYAY7_SCREENS = Object.freeze([
  Object.freeze({ id: 'S-03', path: '/s-03', baseline: 's03.png' }),
  Object.freeze({ id: 'S-04', path: '/s-04', baseline: 's04.png' }),
  Object.freeze({ id: 'S-05', path: '/s-05', baseline: 's05.png' }),
  Object.freeze({ id: 'S-08', path: '/s-08', baseline: 's08.png' }),
  Object.freeze({ id: 'S-09', path: '/s-09', baseline: 's09.png' }),
]);

export const NYAY7_CHECKS = Object.freeze([
  'mount',
  'axe-serious-critical',
  'horizontal-overflow',
  'mobile-touch-targets',
  'layout-shift',
  'rev-l-token-use',
  'selector-context-contract',
  'visual-baseline',
]);

// The approved native captures were produced with the same pinned Playwright
// version and DPR. One percent leaves room for platform font rasterisation,
// while still rejecting meaningful layout, palette, or component drift.
export const NYAY7_VISUAL_MAX_MISMATCH_RATIO = 0.01;
export const NYAY7_LAYOUT_SHIFT_MAX = 0.1;
export const NYAY7_MOBILE_TARGET_MIN = 44;

export const NYAY7_PERSONA_OPTIONS = Object.freeze([
  Object.freeze({ name: 'Lawyer', selected: 'false', disabled: 'true', text: 'Lawyer Coming soon' }),
  Object.freeze({ name: 'Student', selected: 'true', disabled: 'false', text: 'Student Available' }),
  Object.freeze({ name: 'Customer', selected: 'false', disabled: 'true', text: 'Customer Coming soon' }),
  Object.freeze({ name: 'University', selected: 'false', disabled: 'true', text: 'University Coming soon' }),
]);

export const NYAY7_LANGUAGE_OPTIONS = Object.freeze([
  Object.freeze({ name: 'English', selected: 'true', disabled: 'false', text: 'English Available' }),
  Object.freeze({ name: 'हिन्दी', selected: 'false', disabled: 'true', text: 'हिन्दी Coming soon' }),
  Object.freeze({ name: 'ಕನ್ನಡ', selected: 'false', disabled: 'true', text: 'ಕನ್ನಡ Coming soon' }),
]);

export const NYAY7_ASSERTION_INVENTORY = Object.freeze(
  NYAY7_VIEWPORTS.flatMap((viewport) => (
    NYAY7_SCREENS.flatMap((screen) => (
      NYAY7_CHECKS.map((check) => `${viewport.id}:${screen.id}:${check}`)
    ))
  )),
);

export function nyay7AssertionName(viewportId, screenId, check) {
  return `${viewportId}:${screenId}:${check}`;
}

export function summarizeNyay7Rows(rows) {
  const inventory = new Set(NYAY7_ASSERTION_INVENTORY);
  const seen = new Set();
  const duplicates = [];
  const unknown = [];
  const malformed = [];
  const failures = [];

  for (const row of rows) {
    if (!row || typeof row !== 'object' || Array.isArray(row)
      || typeof row.name !== 'string' || typeof row.pass !== 'boolean'
      || row.executed !== true || row.skipped !== false) {
      malformed.push(row?.name ?? null);
      continue;
    }
    if (!inventory.has(row.name)) unknown.push(row.name);
    if (seen.has(row.name)) duplicates.push(row.name);
    seen.add(row.name);
    if (!row.pass) failures.push(row.name);
  }

  const missing = NYAY7_ASSERTION_INVENTORY.filter((name) => !seen.has(name));
  const valid = malformed.length === 0
    && unknown.length === 0
    && duplicates.length === 0
    && missing.length === 0
    && rows.length === NYAY7_ASSERTION_INVENTORY.length;

  return {
    valid,
    total: NYAY7_ASSERTION_INVENTORY.length,
    observed: rows.length,
    passed: rows.filter((row) => row?.pass === true).length,
    failed: failures.length,
    failures,
    missing,
    duplicates,
    unknown,
    malformed,
  };
}

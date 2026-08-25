export const NYAY7_AUTHORITY_SHA256 = '338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252';

export const NYAY7_VIEWPORTS = Object.freeze([
  Object.freeze({ id: 'desktop', directory: '1440x1024', width: 1440, height: 1024 }),
  Object.freeze({ id: 'mobile-390', directory: '390x844', width: 390, height: 844 }),
  Object.freeze({ id: 'mobile-360', directory: '360x800', width: 360, height: 800 }),
]);

// Supplemental responsive/theme coverage. This inventory is intentionally
// separate from the sealed 3 x 5 x 8 Revision L visual contract above:
// approved visual references exist only for the canonical light captures, so
// expanded dark states must never be compared with those light PNGs.
export const NYAY7_EXPANDED_VIEWPORTS = Object.freeze([
  Object.freeze({ id: 'width-390', directory: '390x844', width: 390, height: 844, mobile: true }),
  Object.freeze({ id: 'width-430', directory: '430x932', width: 430, height: 932, mobile: true }),
  Object.freeze({ id: 'width-768', directory: '768x1024', width: 768, height: 1024, mobile: false }),
  Object.freeze({ id: 'width-1024', directory: '1024x768', width: 1024, height: 768, mobile: false }),
  Object.freeze({ id: 'width-1440', directory: '1440x1024', width: 1440, height: 1024, mobile: false }),
]);

export const NYAY7_COLOR_SCHEMES = Object.freeze(['light', 'dark']);

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

// These observations are meaningful without a theme-specific reference PNG.
// Token-palette and pixel-baseline assertions remain in the canonical light
// gate; the expanded gate covers behavior, a11y and responsive geometry.
export const NYAY7_EXPANDED_CHECKS = Object.freeze([
  'mount',
  'axe-serious-critical',
  'horizontal-overflow',
  'mobile-touch-targets',
  'layout-shift',
  'theme-activation',
  'selector-context-contract',
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

export const NYAY7_EXPANDED_ASSERTION_INVENTORY = Object.freeze(
  NYAY7_COLOR_SCHEMES.flatMap((colorScheme) => (
    NYAY7_EXPANDED_VIEWPORTS.flatMap((viewport) => (
      NYAY7_SCREENS.flatMap((screen) => (
        NYAY7_EXPANDED_CHECKS.map((check) => (
          `expanded:${colorScheme}:${viewport.id}:${screen.id}:${check}`
        ))
      ))
    ))
  )),
);

export function nyay7AssertionName(viewportId, screenId, check) {
  return `${viewportId}:${screenId}:${check}`;
}

export function nyay7ExpandedAssertionName(colorScheme, viewportId, screenId, check) {
  return `expanded:${colorScheme}:${viewportId}:${screenId}:${check}`;
}

function summarizeRowsAgainstInventory(rows, assertionInventory) {
  const inventory = new Set(assertionInventory);
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

  const missing = assertionInventory.filter((name) => !seen.has(name));
  const valid = malformed.length === 0
    && unknown.length === 0
    && duplicates.length === 0
    && missing.length === 0
    && rows.length === assertionInventory.length;

  return {
    valid,
    total: assertionInventory.length,
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

export function summarizeNyay7Rows(rows) {
  return summarizeRowsAgainstInventory(rows, NYAY7_ASSERTION_INVENTORY);
}

export function summarizeNyay7ExpandedRows(rows) {
  return summarizeRowsAgainstInventory(rows, NYAY7_EXPANDED_ASSERTION_INVENTORY);
}

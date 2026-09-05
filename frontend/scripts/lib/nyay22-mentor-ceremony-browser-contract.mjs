export const NYAY22_BROWSER_ASSERTION_INVENTORY = Object.freeze([
  'runtime-chromium',
  'live-backend-positive-lifecycle',
  'canonical-request-trace',
  'mentor-cookie-attributes',
  'cross-tab-exchange-linearized',
  'private-mount-after-canonical-session',
  'cross-tab-rotation-linearized',
  'cross-tab-revocation-linearized',
  'unsupported-web-locks-denies-private-mount',
  'unsupported-broadcast-channel-denies-private-mount',
  'postmessage-no-authority',
  'browser-storage-authority-free',
  'm01-admin-only-preserved',
  'evidence-privacy',
]);

const PRIVATE_TEXT = [
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/iu,
  /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/iu,
  /(?<!\d)[6-9]\d{9}(?!\d)/u,
  /\b\d{6}\b/u,
  /(?:bearer\s+|eyJ)[A-Za-z0-9._~+/-]{12,}/iu,
  /(?:cookie|token|secret|otp|mobile|email|actor|profile|subject)[=:][^\s,}\]]+/iu,
];

const CANONICAL_FAILURE_CODES = new Set([
  'NYAY22_BROWSER_FAILURE',
  'NYAY22_EVIDENCE_PRIVATE',
  'NYAY22_FINAL_EVIDENCE_PRIVATE',
  'NYAY22_FIXTURE_ADDRESS_INVALID',
  'NYAY22_LIVE_BACKEND_ORIGIN_INVALID',
  'NYAY22_LIVE_FIXTURE_INVALID',
  'NYAY22_LIVE_FIXTURE_REQUIRED',
  'NYAY22_PRODUCTION_PREVIEW_START_FAILED',
]);

const CANONICAL_SYSTEM_CODES = new Set([
  'EACCES',
  'EADDRINUSE',
  'ECONNREFUSED',
  'ENOENT',
  'EPERM',
  'ETIMEDOUT',
]);

export function canonicalNyay22BrowserFailureCode(error) {
  const systemCode = error && typeof error === 'object' && 'code' in error
    ? String(error.code)
    : '';
  if (CANONICAL_SYSTEM_CODES.has(systemCode)) return `SYSTEM_${systemCode}`;
  const message = error instanceof Error ? error.message : '';
  return CANONICAL_FAILURE_CODES.has(message) ? message : 'NYAY22_BROWSER_FAILURE';
}

export function scanNyay22BrowserEvidence(value) {
  let text;
  try {
    text = JSON.stringify(value);
  } catch {
    return { pass: false, code: 'NYAY22_EVIDENCE_UNSERIALIZABLE' };
  }
  if (typeof text !== 'string' || text.length === 0) {
    return { pass: false, code: 'NYAY22_EVIDENCE_EMPTY' };
  }
  return PRIVATE_TEXT.some((pattern) => pattern.test(text))
    ? { pass: false, code: 'NYAY22_EVIDENCE_PRIVATE' }
    : { pass: true, code: 'NYAY22_EVIDENCE_CLEAN' };
}

export function assertExactNyay22BrowserInventory(rows) {
  if (!Array.isArray(rows)
    || rows.length !== NYAY22_BROWSER_ASSERTION_INVENTORY.length
    || rows.some((row, index) => (
      !row
      || typeof row !== 'object'
      || Object.keys(row).sort().join(',') !== 'actual,expected,name,pass'
      || row.name !== NYAY22_BROWSER_ASSERTION_INVENTORY[index]
      || typeof row.expected !== 'string'
      || row.expected.length === 0
      || typeof row.pass !== 'boolean'
      || scanNyay22BrowserEvidence(row.actual).pass !== true
    ))) {
    throw new Error('NYAY22_BROWSER_ASSERTION_INVENTORY_INVALID');
  }
  return {
    total: rows.length,
    passed: rows.filter((row) => row.pass).length,
    failed: rows.filter((row) => !row.pass).length,
  };
}

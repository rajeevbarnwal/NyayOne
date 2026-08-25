export const NYAY4_ASSERTION_INVENTORY = Object.freeze([
  'signup-safe-projection',
  'otp-flow-cookie-security',
  'full-preauth-cookie-inventory',
  'reload-server-state',
  'pending-refresh-failure-invalidation',
  'pending-refresh-recovery',
  'wrong-code-server-budget',
  'real-authoritative-resend',
  'identifier-free-browser-mutations',
  'successful-cookie-owned-verify',
  'post-auth-cookie-inventory',
  'no-browser-flow-persistence',
  'known-decoy-public-contract',
  'disposable-account-login',
  'recovery-safe-verified-projection',
  'recovery-refresh-failure-invalidation',
  'recovery-refresh-recovery',
  'recovery-proof-reload',
  'deletion-proof-consumption',
  'recovery-browser-storage-privacy',
  'stale-student-snapshot-no-cookie',
  'failed-state-bootstrap',
]);

export const FLOW_HANDLE_PATTERN = /(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))/;

export function containsFlowHandle(value) {
  return FLOW_HANDLE_PATTERN.test(typeof value === 'string' ? value : JSON.stringify(value));
}

export async function hasExactSingleOrigin(request, expectedOrigin) {
  try {
    const headers = await request.headersArray();
    if (!Array.isArray(headers)) return false;
    const origins = headers.filter((header) => (
      header
      && typeof header.name === 'string'
      && header.name.toLowerCase() === 'origin'
    ));
    return origins.length === 1
      && typeof origins[0].value === 'string'
      && origins[0].value === expectedOrigin;
  } catch {
    return false;
  }
}

export async function hasExactOrderedOriginTrace(trace, expectedPaths, expectedOrigin) {
  if (!Array.isArray(trace)
      || !Array.isArray(expectedPaths)
      || trace.length !== expectedPaths.length
      || !trace.every((entry, index) => entry?.path === expectedPaths[index])) return false;
  const origins = await Promise.all(trace.map((entry) => (
    hasExactSingleOrigin(entry.request, expectedOrigin)
  )));
  return origins.every(Boolean);
}

function normalizeDomText(value) {
  return typeof value === 'string' ? value.replace(/\s+/gu, ' ').trim() : '';
}

export function inspectOtpViewSnapshot(raw, expectedAttempts, expectedDestinationMasked) {
  const typedRows = Array.isArray(raw?.rowTexts)
    && raw.rowTexts.every((value) => typeof value === 'string');
  const rows = typedRows ? raw.rowTexts.map(normalizeDomText) : [];
  const structureExact = raw?.cardCount === 1
    && raw?.ledeCount === 1
    && typedRows
    && rows.length === 3
    && typeof raw?.ledeText === 'string';
  const expectedAttemptsExact = Number.isSafeInteger(expectedAttempts)
    && expectedAttempts > 0;
  const expectedDestinationExact = typeof expectedDestinationMasked === 'string'
    && /^••••••\d{4}$/u.test(expectedDestinationMasked);
  const attemptsText = `Tries left ${expectedAttempts}`;
  const attemptsExact = structureExact
    && expectedAttemptsExact
    && rows[2] === attemptsText
    && rows.filter((row) => row === attemptsText).length === 1;
  const renderedDestination = expectedDestinationExact
    ? `+91 ••••• ••${expectedDestinationMasked.slice(-3)}`
    : null;
  const destinationExact = structureExact
    && expectedDestinationExact
    && normalizeDomText(raw.ledeText)
      === `Six digits sent to ${renderedDestination}. Your code stays valid for the time shown below. Change`;
  const countdownMatch = structureExact
    ? /^Expires in (\d{2}):([0-5]\d)$/u.exec(rows[0])
    : null;
  const countdownRowExact = countdownMatch !== null
    && rows.filter((row) => row.startsWith('Expires in ')).length === 1;
  const resendRowExact = structureExact
    && /^Resend in \d{2}:[0-5]\d$/u.test(rows[1])
    && rows.filter((row) => row.startsWith('Resend in ')).length === 1;
  const countdownSeconds = countdownMatch
    ? Number.parseInt(countdownMatch[1], 10) * 60
      + Number.parseInt(countdownMatch[2], 10)
    : null;
  const countdownValid = countdownRowExact
    && Number.isSafeInteger(countdownSeconds)
    && countdownSeconds > 0;
  return {
    structureExact,
    resendRowExact,
    attemptsExact,
    destinationExact,
    countdownValid,
    countdownSeconds: countdownValid ? countdownSeconds : null,
    pass: structureExact && resendRowExact
      && attemptsExact && destinationExact && countdownValid,
  };
}

export function hasExactOtpReload(beforeReload, afterReload) {
  return beforeReload?.pass === true
    && afterReload?.pass === true
    && Number.isSafeInteger(beforeReload.countdownSeconds)
    && Number.isSafeInteger(afterReload.countdownSeconds)
    && beforeReload.countdownSeconds > 0
    && afterReload.countdownSeconds > 0
    && afterReload.countdownSeconds <= beforeReload.countdownSeconds;
}

export function assertExactAssertionInventory(rows) {
  if (!Array.isArray(rows)) throw new Error('NYAY4_ASSERTION_INVENTORY_MISMATCH');
  const names = rows.map((row) => row?.name);
  const exact = names.length === NYAY4_ASSERTION_INVENTORY.length
    && names.every((name, index) => name === NYAY4_ASSERTION_INVENTORY[index]);
  const unique = new Set(names).size === names.length;
  const typed = rows.every((row) => row && typeof row.pass === 'boolean');
  if (!exact || !unique || !typed) {
    throw new Error('NYAY4_ASSERTION_INVENTORY_MISMATCH');
  }
}

export function summarizeNyay4Rows(rows) {
  assertExactAssertionInventory(rows);
  const passed = rows.filter((row) => row.pass).length;
  return {
    expectedTotal: NYAY4_ASSERTION_INVENTORY.length,
    total: rows.length,
    passed,
    failed: rows.length - passed,
    rows,
  };
}

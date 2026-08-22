import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  FLOW_HANDLE_PATTERN,
  NYAY4_ASSERTION_INVENTORY,
  assertExactAssertionInventory,
  containsFlowHandle,
  hasExactOrderedOriginTrace,
  hasExactOtpReload,
  hasExactSingleOrigin,
  inspectOtpViewSnapshot,
  summarizeNyay4Rows,
} from './nyay4-otp-runner-contract.mjs';

const EXPECTED_ORIGIN = 'http://127.0.0.1:1170';
const MASKED_DESTINATION = '••••••1234';

const requestWithHeaders = (headers) => ({
  headersArray: async () => headers,
});

const validOtpView = (overrides = {}) => ({
  cardCount: 1,
  rowTexts: [
    'Code expires in 09:59',
    'Resend available in 00:29',
    'Tries left\n5',
  ],
  ledeCount: 1,
  ledeText: 'Six digits, sent to ••••••1234.',
  ...overrides,
});

const validRows = () => NYAY4_ASSERTION_INVENTORY.map((name) => ({
  name, expected: 'expected', actual: { aggregate: true }, pass: true,
}));

function assertRunnerWiring(source) {
  if (!/summarizeNyay4Rows[\s\S]*from ['"]\.\/lib\/nyay4-otp-runner-contract\.mjs['"]/.test(source)) {
    throw new Error('NYAY4_RUNNER_SUMMARY_IMPORT_MISSING');
  }
  if (!/const summary = summarizeNyay4Rows\(rows\);/.test(source)) {
    throw new Error('NYAY4_RUNNER_SUMMARY_CALL_MISSING');
  }
  if (!/if \(summary\.failed > 0\) process\.exitCode = 1;/.test(source)) {
    throw new Error('NYAY4_RUNNER_FAILURE_EXIT_MISSING');
  }
  const recordedNames = [...source.matchAll(/\brecord\(\s*['"]([^'"]+)['"]/g)]
    .map((match) => match[1]);
  if (JSON.stringify(recordedNames) !== JSON.stringify(NYAY4_ASSERTION_INVENTORY)) {
    throw new Error('NYAY4_RUNNER_ASSERTION_SOURCE_MISMATCH');
  }
  for (const required of [
    /cookieInventory\.length === 1/,
    /postAuthCookies\.length === 1/,
    /postAuthAuthorityCookies\[0\]\.path === ['"]\/api\/v1['"]/,
    /postAuthAuthorityCookies\[0\]\.sameSite === ['"]Strict['"]/,
    /postAuthAuthorityCookies\[0\]\.secure === !localHttp/,
    /hasExactSingleOrigin/,
    /hasExactOrderedOriginTrace/,
    /originExact: await hasExactSingleOrigin\(request, WEB_ORIGIN\)/,
    /const wrongOriginExact = await hasExactSingleOrigin\(wrongResponse\.request\(\), WEB_ORIGIN\);/,
    /const successOriginExact = await hasExactSingleOrigin\(successResponse\.request\(\), WEB_ORIGIN\);/,
    /otpRequests\.push\(\{\s*request,\s*method: request\.method\(\)/,
    /privacyMutations\.push\(\{ path, request \}\)/,
    /const recoveryOriginTraceExact = await hasExactOrderedOriginTrace\(\s*privacyMutations,\s*\[\s*['"]\/api\/v1\/auth\/student\/recovery\/start['"],\s*['"]\/api\/v1\/auth\/student\/recovery\/verify['"],\s*\],\s*WEB_ORIGIN,\s*\);/,
    /const privacyMutationTraceExact = await hasExactOrderedOriginTrace\(\s*privacyMutations,\s*\[\s*['"]\/api\/v1\/auth\/student\/recovery\/start['"],\s*['"]\/api\/v1\/auth\/student\/recovery\/verify['"],\s*['"]\/api\/v1\/student\/privacy\/delete['"],\s*\],\s*WEB_ORIGIN,\s*\);/,
  ]) {
    if (!required.test(source)) throw new Error('NYAY4_RUNNER_REQUIRED_ORACLE_MISSING');
  }
  if (/\.headers\(\)\.origin/.test(source)) {
    throw new Error('NYAY4_PROVISIONAL_ORIGIN_ORACLE_PRESENT');
  }
  for (const required of [
    /async function readOtpViewSnapshot\(targetPage, expectedAttempts, expectedDestinationMasked\)/,
    /targetPage\.locator\('\[data-screen="S-09"\]'\)/,
    /cards\.count\(\)/,
    /cards\.locator\(['"]:scope > span['"]\)\.allTextContents\(\)/,
    /ledes\.count\(\)/,
    /ledes\.allTextContents\(\)/,
    /return inspectOtpViewSnapshot\(/,
    /const beforeReload = await readOtpViewSnapshot\(/,
    /await page\.reload\(\{ waitUntil: ['"]domcontentloaded['"] \}\);/,
    /const afterReload = await readOtpViewSnapshot\(/,
    /registrationBody\.destination_masked/,
    /hasExactOtpReload\(beforeReload, afterReload\)/,
  ]) {
    if (!required.test(source)) throw new Error('NYAY4_RELOAD_ORACLE_MISSING');
  }
  if (/\.innerText\(\)/.test(source)) {
    throw new Error('NYAY4_RENDERED_WHITESPACE_ORACLE_PRESENT');
  }
  const reloadRecordStart = source.indexOf("record(\n    'reload-server-state'");
  const reloadRecordEnd = source.indexOf('// A successful pending snapshot', reloadRecordStart);
  const reloadRecord = source.slice(reloadRecordStart, reloadRecordEnd);
  if (reloadRecordStart === -1
      || reloadRecordEnd === -1
      || /registrationBody\.destination_masked/.test(reloadRecord)) {
    throw new Error('NYAY4_RELOAD_REPORT_PRIVACY_BREACH');
  }
  for (const required of [
    /const REAUTHENTICATED_BADGE_SELECTOR = ['"]\.status\.status--ok['"];/,
    /const REAUTHENTICATED_BADGE_LABEL = ['"]Re-authenticated['"];/,
    /async function waitForReauthenticatedBadge\(targetPage\)/,
    /targetPage\.locator\(REAUTHENTICATED_BADGE_SELECTOR\)/,
    /querySelectorAll\(['"]\[aria-hidden=[\\'"]true[\\'"]\]['"]\)/,
    /querySelectorAll\(['"]\[aria-hidden=[\\'"]true[\\'"]\]['"]\)\.forEach\(\(node\) => node\.remove\(\)\);/,
    /labelOnly\.textContent\?\.trim\(\) === expectedLabel/,
    /matchingIndexes\.length > 1/,
    /matchingIndexes\.length === 1[\s\S]*badges\.nth\(matchingIndexes\[0\]\)\.isVisible\(\)/,
  ]) {
    if (!required.test(source)) throw new Error('NYAY4_REAUTHENTICATED_BADGE_ORACLE_MISSING');
  }
  if ((source.match(/await waitForReauthenticatedBadge\(privacyPage\);/g) ?? []).length !== 3
      || /getByText\(['"]Re-authenticated['"],\s*\{\s*exact:\s*true\s*\}\)/.test(source)) {
    throw new Error('NYAY4_REAUTHENTICATED_BADGE_ORACLE_MISSING');
  }
}

function exactReauthenticatedBadgeIndexes(badges) {
  return badges.flatMap((badge, index) => {
    const classes = new Set(badge.className.split(/\s+/));
    if (!classes.has('status') || !classes.has('status--ok')) return [];
    const label = badge.children
      .filter((child) => child.ariaHidden !== true)
      .map((child) => child.text)
      .join('')
      .trim();
    return label === 'Re-authenticated' ? [index] : [];
  });
}

describe('NYAY-4 browser runner exact assertion contract', () => {
  it('accepts only the exact ordered unique inventory and reports its pinned total', () => {
    const summary = summarizeNyay4Rows(validRows());
    expect(summary).toMatchObject({
      expectedTotal: NYAY4_ASSERTION_INVENTORY.length,
      total: NYAY4_ASSERTION_INVENTORY.length,
      passed: NYAY4_ASSERTION_INVENTORY.length,
      failed: 0,
    });
  });

  it.each([
    ['zero rows', () => []],
    ['missing row', () => validRows().slice(0, -1)],
    ['extra row', () => [...validRows(), { name: 'extra', pass: true }]],
    ['duplicate row', () => validRows().map((row, index, rows) => index === 1 ? rows[0] : row)],
    ['reordered rows', () => {
      const rows = validRows();
      [rows[0], rows[1]] = [rows[1], rows[0]];
      return rows;
    }],
    ['untyped verdict', () => validRows().map((row, index) => index === 0 ? { ...row, pass: 1 } : row)],
  ])('rejects the planted %s inventory mutant', (_label, mutate) => {
    expect(() => assertExactAssertionInventory(mutate())).toThrow('NYAY4_ASSERTION_INVENTORY_MISMATCH');
  });

  it.each([
    'registration_id', 'registration_token', 'registrationId', 'registrationToken',
    'login_id', 'login_token', 'loginId', 'loginToken',
    'recovery_id', 'recovery_token', 'recoveryId', 'recoveryToken',
  ])('detects the planted %s flow-handle mutant', (handle) => {
    expect(FLOW_HANDLE_PATTERN.test(handle)).toBe(true);
    expect(containsFlowHandle({ [handle]: 'planted' })).toBe(true);
  });

  it.each([
    ['canonical name', [{ name: 'Origin', value: EXPECTED_ORIGIN }]],
    ['case-insensitive name', [{ name: 'oRiGiN', value: EXPECTED_ORIGIN }]],
    ['unrelated headers retained', [
      { name: 'Accept', value: 'application/json' },
      { name: 'ORIGIN', value: EXPECTED_ORIGIN },
      { name: 'Content-Type', value: 'application/json' },
    ]],
  ])('accepts one exact raw Origin with %s', async (_label, headers) => {
    await expect(hasExactSingleOrigin(
      requestWithHeaders(headers),
      EXPECTED_ORIGIN,
    )).resolves.toBe(true);
  });

  it.each([
    ['missing header', []],
    ['wrong value', [{ name: 'Origin', value: 'http://127.0.0.1:9999' }]],
    ['trailing slash', [{ name: 'Origin', value: `${EXPECTED_ORIGIN}/` }]],
    ['leading whitespace', [{ name: 'Origin', value: ` ${EXPECTED_ORIGIN}` }]],
    ['changed value casing', [{ name: 'Origin', value: 'HTTP://127.0.0.1:1170' }]],
    ['duplicate exact values', [
      { name: 'Origin', value: EXPECTED_ORIGIN },
      { name: 'Origin', value: EXPECTED_ORIGIN },
    ]],
    ['duplicate mixed-case names', [
      { name: 'origin', value: EXPECTED_ORIGIN },
      { name: 'ORIGIN', value: EXPECTED_ORIGIN },
    ]],
    ['non-string value', [{ name: 'Origin', value: null }]],
    ['malformed header', [{ value: EXPECTED_ORIGIN }]],
    ['non-array inventory', null],
  ])('rejects the planted raw Origin mutant: %s', async (_label, headers) => {
    await expect(hasExactSingleOrigin(
      requestWithHeaders(headers),
      EXPECTED_ORIGIN,
    )).resolves.toBe(false);
  });

  it('fails closed when raw browser headers cannot be read', async () => {
    await expect(hasExactSingleOrigin({
      headersArray: async () => { throw new Error('planted raw-header failure'); },
    }, EXPECTED_ORIGIN)).resolves.toBe(false);
    await expect(hasExactSingleOrigin({}, EXPECTED_ORIGIN)).resolves.toBe(false);
  });

  it('awaits an exact ordered browser Origin trace', async () => {
    const paths = ['/recovery/start', '/recovery/verify', '/privacy/delete'];
    const trace = paths.map((path) => ({
      path,
      request: requestWithHeaders([{ name: 'Origin', value: EXPECTED_ORIGIN }]),
    }));
    await expect(hasExactOrderedOriginTrace(
      trace,
      paths,
      EXPECTED_ORIGIN,
    )).resolves.toBe(true);

    const wrongOrigin = trace.map((entry, index) => index === 1 ? {
      ...entry,
      request: requestWithHeaders([{ name: 'Origin', value: `${EXPECTED_ORIGIN}/` }]),
    } : entry);
    for (const mutant of [
      trace.slice(0, -1),
      [...trace, trace[2]],
      [trace[1], trace[0], trace[2]],
      [trace[0], trace[0], trace[2]],
      wrongOrigin,
      trace.map((entry, index) => index === 1 ? {
        ...entry,
        request: { headersArray: async () => { throw new Error('planted'); } },
      } : entry),
    ]) {
      await expect(hasExactOrderedOriginTrace(
        mutant,
        paths,
        EXPECTED_ORIGIN,
      )).resolves.toBe(false);
    }
  });

  it('normalizes rendered flex whitespace but keeps the OTP view exact', () => {
    const snapshot = inspectOtpViewSnapshot(
      validOtpView(),
      5,
      MASKED_DESTINATION,
    );
    expect(snapshot).toEqual({
      structureExact: true,
      resendRowExact: true,
      attemptsExact: true,
      destinationExact: true,
      countdownValid: true,
      countdownSeconds: 599,
      pass: true,
    });
  });

  it.each([
    ['missing card', { cardCount: 0 }],
    ['duplicate card', { cardCount: 2 }],
    ['missing direct row', { rowTexts: ['Code expires in 09:59', 'Tries left 5'] }],
    ['extra direct row', { rowTexts: [
      'Code expires in 09:59', 'Resend available in 00:29', 'Tries left 5', 'extra',
    ] }],
    ['changed attempt', { rowTexts: [
      'Code expires in 09:59', 'Resend available in 00:29', 'Tries left 4',
    ] }],
    ['attempt substring', { rowTexts: [
      'Code expires in 09:59', 'Resend available in 00:29', 'Tries left 5 extra',
    ] }],
    ['duplicate attempt row', { rowTexts: [
      'Code expires in 09:59', 'Tries left 5', 'Tries left 5',
    ] }],
    ['missing resend row', { rowTexts: [
      'Code expires in 09:59', 'something else', 'Tries left 5',
    ] }],
    ['malformed countdown width', { rowTexts: [
      'Code expires in 9:59', 'Resend available in 00:29', 'Tries left 5',
    ] }],
    ['malformed countdown seconds', { rowTexts: [
      'Code expires in 09:60', 'Resend available in 00:29', 'Tries left 5',
    ] }],
    ['zero countdown', { rowTexts: [
      'Code expires in 00:00', 'Resend available in 00:29', 'Tries left 5',
    ] }],
    ['duplicate countdown row', { rowTexts: [
      'Code expires in 09:59', 'Code expires in 09:58', 'Tries left 5',
    ] }],
    ['missing lede', { ledeCount: 0, ledeText: undefined }],
    ['duplicate lede', { ledeCount: 2 }],
    ['fallback destination', { ledeText: 'Six digits, sent to your mobile.' }],
    ['changed masked suffix', { ledeText: 'Six digits, sent to ••••••1235.' }],
    ['destination substring', { ledeText: 'Six digits, sent to ••••••1234. extra' }],
  ])('rejects the planted OTP view mutant: %s', (_label, overrides) => {
    expect(inspectOtpViewSnapshot(
      validOtpView(overrides),
      5,
      MASKED_DESTINATION,
    ).pass).toBe(false);
  });

  it('requires fresh valid snapshots and a non-increasing positive reload countdown', () => {
    const before = inspectOtpViewSnapshot(validOtpView(), 5, MASKED_DESTINATION);
    const after = inspectOtpViewSnapshot(validOtpView({
      rowTexts: [
        'Code expires in 09:57',
        'Resend available in 00:27',
        'Tries left 5',
      ],
    }), 5, MASKED_DESTINATION);
    expect(hasExactOtpReload(before, after)).toBe(true);
    expect(hasExactOtpReload(before, { ...after, countdownSeconds: 600 })).toBe(false);
    expect(hasExactOtpReload(before, { ...after, pass: false })).toBe(false);
    expect(hasExactOtpReload(before, before)).toBe(true);
  });

  it('pins the executable runner to the exact summary builder and failure exit', () => {
    const source = readFileSync(resolve('scripts/nyay4-otp-browser-negative.mjs'), 'utf8');
    expect(() => assertRunnerWiring(source)).not.toThrow();
  });

  it('matches the StatusBadge label after excluding its aria-hidden mark, exactly once', () => {
    const badge = (status, label) => ({
      className: `status status--${status}`,
      children: [
        { ariaHidden: true, text: '\u2713' },
        { ariaHidden: false, text: label },
      ],
    });
    const rendered = badge('ok', 'Re-authenticated');
    const rawText = rendered.children.map((child) => child.text).join('');
    expect(rawText).toBe('\u2713Re-authenticated');
    expect(rawText === 'Re-authenticated').toBe(false);
    expect(exactReauthenticatedBadgeIndexes([rendered])).toEqual([0]);
    expect(exactReauthenticatedBadgeIndexes([badge('warn', 'Re-authenticated')])).toEqual([]);
    for (const label of [
      'Not Re-authenticated',
      'Re-authenticated later',
      'Re-authenticated!',
    ]) {
      expect(exactReauthenticatedBadgeIndexes([badge('ok', label)])).toEqual([]);
    }
    expect(exactReauthenticatedBadgeIndexes([rendered, rendered])).toEqual([0, 1]);
  });

  it.each([
    ['ad-hoc empty summary', (source) => source.replace(
      'const summary = summarizeNyay4Rows(rows);',
      'const summary = { total: 0, passed: 0, failed: 0, rows: [] };',
    )],
    ['removed failure exit', (source) => source.replace(
      'if (summary.failed > 0) process.exitCode = 1;',
      'process.exitCode = 0;',
    )],
    ['removed contract import', (source) => source.replace(
      /import \{[\s\S]*?\} from ['"]\.\/lib\/nyay4-otp-runner-contract\.mjs['"];\n/,
      '',
    )],
    ['removed executable assertion', (source) => source.replace(
      /\s*record\(\s*['"]signup-safe-projection['"][\s\S]*?\n\s*\);/,
      '',
    )],
    ['weakened preauth inventory', (source) => source.replaceAll(
      'cookieInventory.length === 1',
      'cookieInventory.length >= 1',
    )],
    ['weakened postauth inventory', (source) => source.replace(
      'postAuthCookies.length === 1',
      'postAuthCookies.length >= 1',
    )],
    ['removed browser Origin oracle', (source) => source.replace(
      'originExact: await hasExactSingleOrigin(request, WEB_ORIGIN)',
      'originExact: true',
    )],
    ['restored provisional Origin headers', (source) => source.replace(
      'await hasExactSingleOrigin(request, WEB_ORIGIN)',
      'request.headers().origin === WEB_ORIGIN',
    )],
    ['removed wrong-verify raw Origin oracle', (source) => source.replace(
      'const wrongOriginExact = await hasExactSingleOrigin(wrongResponse.request(), WEB_ORIGIN);',
      'const wrongOriginExact = true;',
    )],
    ['removed successful-verify raw Origin oracle', (source) => source.replace(
      'const successOriginExact = await hasExactSingleOrigin(successResponse.request(), WEB_ORIGIN);',
      'const successOriginExact = true;',
    )],
    ['dropped captured OTP request object', (source) => source.replace(
      'otpRequests.push({\n      request,',
      'otpRequests.push({',
    )],
    ['dropped captured privacy request object', (source) => source.replace(
      'privacyMutations.push({ path, request });',
      'privacyMutations.push({ path });',
    )],
    ['weakened recovery trace cardinality', (source) => source.replace(
      "      '/api/v1/auth/student/recovery/verify',\n    ],\n    WEB_ORIGIN,",
      "    ],\n    WEB_ORIGIN,",
    )],
    ['reordered deletion trace', (source) => source.replaceAll(
      "      '/api/v1/auth/student/recovery/start',\n      '/api/v1/auth/student/recovery/verify',\n      '/api/v1/student/privacy/delete',",
      "      '/api/v1/auth/student/recovery/verify',\n      '/api/v1/auth/student/recovery/start',\n      '/api/v1/student/privacy/delete',",
    )],
    ['unscoped reload card', (source) => source.replace(
      "targetPage.locator('[data-screen=\"S-09\"]')",
      "targetPage.locator('body')",
    )],
    ['masked duplicate reload card', (source) => source.replace(
      'cards.count(),',
      'cards.first().count(),',
    )],
    ['restored rendered innerText reload read', (source) => source.replace(
      "cards.locator(':scope > span').allTextContents()",
      "cards.locator(':scope > span').allInnerTexts()",
    )],
    ['reused pre-reload snapshot', (source) => source.replace(
      'const afterReload = await readOtpViewSnapshot(\n    page,\n    initialAttempts,\n    registrationBody.destination_masked,\n  );',
      'const afterReload = beforeReload;',
    )],
    ['dropped exact masked destination input', (source) => source.replaceAll(
      'registrationBody.destination_masked',
      'null',
    )],
    ['removed countdown relation', (source) => source.replace(
      'hasExactOtpReload(beforeReload, afterReload)',
      'true',
    )],
    ['reported masked destination', (source) => source.replace(
      'destinationMatchAfter: afterReload.destinationExact,',
      'destinationMatchAfter: afterReload.destinationExact,\n      destination: registrationBody.destination_masked,',
    )],
    ['restored broken exact-text locator', (source) => source.replace(
      'await waitForReauthenticatedBadge(privacyPage);',
      "await privacyPage.getByText('Re-authenticated', { exact: true }).waitFor({ state: 'visible' });",
    )],
    ['unscoped re-authenticated text', (source) => source.replace(
      'targetPage.locator(REAUTHENTICATED_BADGE_SELECTOR)',
      "targetPage.getByText(/Re-authenticated/)",
    )],
    ['substring re-authenticated label', (source) => source.replace(
      'labelOnly.textContent?.trim() === expectedLabel',
      'labelOnly.textContent?.includes(expectedLabel)',
    )],
    ['retained aria-hidden badge mark', (source) => source.replace(
      ".forEach((node) => node.remove());",
      '.forEach(() => undefined);',
    )],
  ])('detects the planted %s source mutant', (_label, mutate) => {
    const source = readFileSync(resolve('scripts/nyay4-otp-browser-negative.mjs'), 'utf8');
    expect(() => assertRunnerWiring(mutate(source))).toThrow();
  });
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'vitest';

const source = readFileSync(
  new URL('../credential-e2e.mjs', import.meta.url),
  'utf8',
);

test('credential page journeys use a server session without authenticating the anonymous oracle', () => {
  const negativeMatrix = source.indexOf('await runApiNegativeMatrix(context.request);');
  const sessionLogin = source.indexOf('await authenticateStudent(context);');
  const firstPageJourney = source.indexOf('await page.goto(`${WEB}/s-82`');

  assert.ok(negativeMatrix >= 0);
  assert.ok(sessionLogin > negativeMatrix);
  assert.ok(firstPageJourney > sessionLogin);
  assert.match(source, /login\/otp\/start/);
  assert.match(source, /login\/otp\/verify/);
  assert.doesNotMatch(
    source,
    /const studentSessionCookies = await context\.cookies\(\);[\s\S]*?await context\.clearCookies\(\);[\s\S]*?await context\.addCookies\(studentSessionCookies\);/,
  );
  assert.doesNotMatch(
    source,
    /getByRole\('button', \{ name: 'Verify credential' \}\)\.click\(\)/,
  );
  assert.match(source, /const ISSUER_HEADERS = \{/);
  assert.match(source, /roles: \['lawyer'\]/);
  assert.match(source, /const studentIssuerMutationControls = await page\.getByRole/);
  assert.match(source, /request as playwrightRequest/);
  assert.match(
    source,
    /playwrightRequest\.newContext\([\s\S]*?extraHTTPHeaders: ISSUER_HEADERS/,
  );
  assert.match(
    source,
    /issuerRequest\.post\([\s\S]*?expected_version: credentialBeforeVerificationBody\?\.version/,
  );
  assert.match(
    source,
    /async function geometryMatrix\(browser, credentialId, storageState\)[\s\S]*?storageState/,
  );
  assert.match(
    source,
    /async function freshContextPersistence\(browser, credentialId, storageState\)[\s\S]*?storageState/,
  );
  assert.match(source, /publicVerificationRequestMethods\[method\]/);
  assert.match(source, /publicVerificationRequestCount === 1/);
  assert.match(source, /diagnostics\.publicVerificationRequestMethods\?\.GET === 1/);
  assert.match(
    source,
    /name: 'wallet anonymous'[\s\S]*?headers: \{\}/,
  );
});

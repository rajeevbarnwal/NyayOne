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
  assert.match(
    source,
    /const studentSessionCookies = await context\.cookies\(\);[\s\S]*?await context\.clearCookies\(\);[\s\S]*?await context\.addCookies\(studentSessionCookies\);/,
  );
  assert.match(
    source,
    /async function geometryMatrix\(browser, credentialId, storageState\)[\s\S]*?storageState/,
  );
  assert.match(
    source,
    /async function freshContextPersistence\(browser, credentialId, storageState\)[\s\S]*?storageState/,
  );
  assert.match(
    source,
    /name: 'wallet anonymous'[\s\S]*?headers: \{\}/,
  );
});

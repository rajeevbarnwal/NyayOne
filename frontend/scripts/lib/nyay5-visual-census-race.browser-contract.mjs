/** Real Chromium regression of the actual NYAY-5 census, not a canned result. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import ts from 'typescript';
import { chromium } from 'playwright';
import { waitForVisualCensusSettled } from './browser-response-readiness.mjs';

const producerPath = resolve(import.meta.dirname, '../nyay5-profile-browser.mjs');
const producer = readFileSync(producerPath, 'utf8');
const syntax = ts.createSourceFile(producerPath, producer, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
const names = new Set(['REVISION_L_VISUAL_SCREEN_IDS', 'REVISION_L_HEADING_STACK', 'LEGACY_CARLITO_HEADING_STACK']);
const constants = syntax.statements.filter((statement) => ts.isVariableStatement(statement)
  && statement.declarationList.declarations.some((declaration) => names.has(declaration.name.getText(syntax))));
const census = syntax.statements.find((statement) => ts.isFunctionDeclaration(statement)
  && statement.name?.text === 'recordVisualContract');
if (constants.length !== 3 || !census) throw new Error('NYAY5_CENSUS_SOURCE_INVENTORY_INVALID');
const compileCensus = new Function('waitForVisualCensusSettled', 'visualScreens',
  `${constants.map((statement) => statement.getText(syntax)).join('\n')}\n${census.getText(syntax)}\nreturn recordVisualContract;`);

const legacyFamily = 'Aptos, Calibri, Carlito, system-ui, sans-serif';
const revisionFamily = 'Aptos, Calibri, "NyayOne Revision L Heading", system-ui, sans-serif';
let browser;

function assertFields(actual, expected) {
  for (const [key, value] of Object.entries(expected)) assert.deepEqual(actual?.[key], value, key);
}

function markup(screenId = 'S-07', { wrongFont = false, heading = true, badIcon = false, lockup } = {}) {
  const revision = ['S-03', 'S-04', 'S-05', 'S-07', 'S-08', 'S-09', 'S-10', 'S-11', 'S-12'].includes(screenId);
  const family = wrongFont ? 'serif' : revision ? revisionFamily : legacyFamily;
  const svg = (lockup ?? revision)
    ? '<svg class="v321-lockup" role="img" aria-label="NyayOne — Legal, on the record" width="40" height="40"><rect width="30" height="30"/></svg>'
    : '<svg aria-hidden="true" width="40" height="40"><rect width="30" height="30"/></svg>';
  const invalidIcon = badIcon ? '<svg width="40" height="40"><rect width="30" height="30"/></svg>' : '';
  return `<section data-screen="${screenId}" style="display:block;min-height:40px">${heading ? `<h1 style='font-family:${family}'>Synthetic screen</h1>` : '<p role="status">Synthetic pending state</p>'}${svg}${invalidIcon}</section>`;
}

async function withPage(task) {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(2_000);
  await page.setContent('<html data-theme="light"><body></body></html>');
  try { await task(page); } finally { await context.close(); }
}

/**
 * Playwright Locator.evaluate resolves an ElementHandle then evaluates in a
 * separate browser command. Replace the real DOM in that exact command gap.
 * For the repaired page-level atomic sampler, replace immediately before its
 * command instead: it must discover the current connected root itself.
 */
function replacingPage(page, { startEmpty = false } = {}) {
  const replacement = markup();
  const events = { replacements: 0, detachedSamples: 0, atomicSamples: 0, startupMounts: 0 };
  const mount = async () => {
    await page.evaluate((html) => { document.body.innerHTML = html; }, replacement);
    events.startupMounts += 1;
  };
  const replace = async () => {
    await page.evaluate((html) => { document.querySelector('[data-screen="S-07"]').outerHTML = html; }, replacement);
    events.replacements += 1;
  };
  const locatorProxy = (locator) => new Proxy(locator, {
    get(target, property) {
      if (property === 'first') return () => locatorProxy(target.first());
      if (property === 'waitFor') return async (options) => {
        if (startEmpty && events.startupMounts === 0) await mount();
        return target.waitFor(options);
      };
      if (property === 'evaluate') return async (callback, argument) => {
        const handle = await target.elementHandle();
        if (!handle) throw new Error('NYAY5_SEEDED_ROOT_MISSING');
        try {
          await replace();
          assert.equal(await handle.evaluate((node) => node.isConnected), false);
          assert.equal(await handle.evaluate((node) => node.querySelector('h1').getClientRects().length), 0);
          events.detachedSamples += 1;
          return await handle.evaluate(callback, argument);
        } finally { await handle.dispose(); }
      };
      const value = Reflect.get(target, property);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
  return {
    events,
    page: new Proxy(page, {
      get(target, property) {
        if (property === 'locator') return (selector) => locatorProxy(target.locator(selector));
        if (property === 'waitForFunction') return async (callback, argument, options) => {
          // S-07 now requires its labelled lockup at semantic readiness, before
          // the later atomic sample. Model the pending render arriving there.
          if (argument?.lockupRequired && startEmpty && events.startupMounts === 0) await mount();
          if (argument?.screenId === 'S-07') {
            if (startEmpty && events.startupMounts === 0) await mount();
            await replace();
            events.atomicSamples += 1;
          }
          return target.waitForFunction(callback, argument, options);
        };
        const value = Reflect.get(target, property);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    }),
  };
}

describe('NYAY-5 real Chromium atomic visual census', () => {
  before(async () => { browser = await chromium.launch({ headless: true }); });
  after(async () => { await browser?.close(); });

  for (const startEmpty of [false, true]) {
    it(`samples the connected replacement once (${startEmpty ? 'pending startup' : 'already visible'} schedule)`, async () => {
      await withPage(async (page) => {
        if (!startEmpty) await page.setContent(`<html data-theme="light"><body>${markup()}</body></html>`);
        const visualScreens = new Map();
        const realCensus = compileCensus(waitForVisualCensusSettled, visualScreens);
        const replacement = replacingPage(page, { startEmpty });
        await realCensus(replacement.page, 'S-07');
        assert.equal(replacement.events.replacements, 1);
        assert.equal(replacement.events.startupMounts, startEmpty ? 1 : 0);
        assertFields(visualScreens.get('S-07'), { headingCount: 1, typographyExact: true, iconsExact: true });
      });
    });
  }

  it('records the wrong font as FAIL without polling until it becomes correct', async () => {
    await withPage(async (page) => {
      await page.setContent(`<html data-theme="light"><body>${markup('S-07', { wrongFont: true })}</body></html>`);
      const rows = new Map();
      await compileCensus(waitForVisualCensusSettled, rows)(page, 'S-07');
      assertFields(rows.get('S-07'), { headingCount: 1, typographyExact: false });
      // A later correct product state cannot erase the earlier recorded failure.
      await page.setContent(`<html data-theme="light"><body>${markup()}</body></html>`);
      await compileCensus(waitForVisualCensusSettled, rows)(page, 'S-07');
      assert.equal(rows.get('S-07').typographyExact, false);
    });
  });

  it('fails closed when a real connected screen has no visible heading', async () => {
    await withPage(async (page) => {
      page.setDefaultTimeout(250);
      await page.setContent(`<html data-theme="light"><body>${markup('S-07', { heading: false })}</body></html>`);
      const rows = new Map();
      await assert.rejects(compileCensus(waitForVisualCensusSettled, rows)(page, 'S-07'));
      assert.equal(rows.size, 0);
    });
  });

  it('retains the original rect-bearing heading census even for visibility-hidden text', async () => {
    await withPage(async (page) => {
      await page.setContent(`<html data-theme="light"><body>${markup()}</body></html>`);
      await page.evaluate(() => {
        const heading = document.createElement('h2');
        heading.style.cssText = 'visibility:hidden;font-family:serif';
        heading.textContent = 'Synthetic hidden heading';
        document.querySelector('[data-screen="S-07"]').append(heading);
      });
      const rows = new Map();
      await compileCensus(waitForVisualCensusSettled, rows)(page, 'S-07');
      assertFields(rows.get('S-07'), { headingCount: 2, typographyExact: false });
    });
  });

  it('preserves the exact nine-screen Revision L census and the legacy Carlito stack', async () => {
    await withPage(async (page) => {
      const rows = new Map();
      const actual = compileCensus(waitForVisualCensusSettled, rows);
      for (const screenId of ['S-03', 'S-04', 'S-05', 'S-07', 'S-08', 'S-09', 'S-10', 'S-11', 'S-12', 'S-13']) {
        await page.setContent(`<html data-theme="light"><body>${markup(screenId)}</body></html>`);
        await actual(page, screenId);
        assertFields(rows.get(screenId), { headingCount: 1, typographyExact: true, iconsExact: true, legacyBrandVisible: false });
      }
      assert.equal(rows.size, 10);
    });
  });

  it('does not forgive a semantically invalid SVG in an otherwise settled screen', async () => {
    await withPage(async (page) => {
      await page.setContent(`<html data-theme="light"><body>${markup('S-07', { badIcon: true })}</body></html>`);
      const rows = new Map();
      await compileCensus(waitForVisualCensusSettled, rows)(page, 'S-07');
      assertFields(rows.get('S-07'), { typographyExact: true, iconsExact: false });
    });
  });

  it('does not allow a legacy screen to acquire the Revision L-only lockup exception', async () => {
    await withPage(async (page) => {
      await page.setContent(`<html data-theme="light"><body>${markup('S-13', { lockup: true })}</body></html>`);
      const rows = new Map();
      await compileCensus(waitForVisualCensusSettled, rows)(page, 'S-13');
      assertFields(rows.get('S-13'), { typographyExact: true, iconsExact: false });
    });
  });

  for (const [name, screenId, decoration, expected] of [
    ['exact hidden nonfocusable wrapper', 'S-12', '<span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"><path d="m5 12 4 4 8-8"/></svg></span>', true],
    ['unhidden wrapper', 'S-12', '<span class="v321-profile-done__check"><svg width="42" height="42"/></span>', false],
    ['extra wrapper class', 'S-12', '<span class="v321-profile-done__check extra" aria-hidden="true"><svg width="42" height="42"/></span>', false],
    ['focusable wrapper', 'S-12', '<span class="v321-profile-done__check" aria-hidden="true" tabindex="0"><svg width="42" height="42"/></span>', false],
    ['editable wrapper', 'S-12', '<span class="v321-profile-done__check" aria-hidden="true" contenteditable="true"><svg width="42" height="42"/></span>', false],
    ['editable ancestor', 'S-12', '<div contenteditable="true"><span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"/></span></div>', false],
    ['focusable SVG', 'S-12', '<span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42" tabindex="0"/></span>', false],
    ['focusable=true SVG', 'S-12', '<span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42" focusable="true"/></span>', false],
    ['button ancestor', 'S-12', '<button><span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"/></span></button>', false],
    ['link ancestor', 'S-12', '<a href="#"><span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"/></span></a>', false],
    ['wrong wrapper element', 'S-12', '<div class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"/></div>', false],
    ['other Revision L screen', 'S-11', '<span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"/></span>', false],
    ['legacy screen', 'S-13', '<span class="v321-profile-done__check" aria-hidden="true"><svg width="42" height="42"/></span>', false],
    ['generic hidden wrapper', 'S-12', '<span aria-hidden="true"><svg width="42" height="42"/></span>', false],
  ]) {
    it(`S-12 completion check: ${name}`, async () => {
      await withPage(async page => {
        await page.setContent(`<html data-theme="light"><body>${markup(screenId).replace('</section>', decoration + '</section>')}</body></html>`);
        const rows = new Map();
        await compileCensus(waitForVisualCensusSettled, rows)(page, screenId);
        assertFields(rows.get(screenId), { headingCount: 1, typographyExact: true, iconCount: 2, iconsExact: expected });
      });
    });
  }
});

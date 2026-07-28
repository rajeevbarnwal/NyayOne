/**
 * SAATHI-121 (QA F1) — REAL boot test for the Option C+ reference bundle.
 *
 * The independent QA run proved the committed bundle could not boot: a plain
 * JSON.stringify of the template payload re-materialised literal "</script>"
 * tokens, HTML parsing terminated the outer template block early and
 * window.__opt never existed (20s waitForFunction timeout, checksum null).
 *
 * This test fails on exactly that class of defect:
 *   1. STATIC (runs everywhere): the bundler payload lines contain zero
 *      literal "</script" / "<!--" tokens and the file has exactly one close
 *      tag per outer <script> element.
 *   2. CHROMIUM BOOT (runs wherever a Playwright chromium executable is
 *      installed — Mac/CI; skipped with an explicit reason where the browser
 *      cannot exist, e.g. the network-isolated Linux sandbox): loads the
 *      bundle over file://, requires window.__opt within 20s, asserts no
 *      #__bundler_err element, zero console errors, zero page errors,
 *      window.LSKIT.FIXTURE.checksum equal to the approved contract checksum,
 *      and __opt.apply/render/setFrame/focusHeading all functions.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { contractChecksum } from './lawschool_fixture_contract.mjs';

/** Approved Option C+ oracle checksum (frozen; must equal contractChecksum()). */
const APPROVED_CHECKSUM = '49f3bce98b8ae00e7073b6899c6ec65d5dee4d3b9d2ba82f012e6172ba0c74c9';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BUNDLE = path.resolve(
  HERE, '..', '..', 'docs', 'design', 'lawschool_reference', 'option_c_plus',
  'OPTION_C_PLUS_GUIDED_CONFIDENCE.html',
);

function chromiumAvailable() {
  try { return fs.existsSync(chromium.executablePath()); } catch { return false; }
}

describe('Option C+ reference bundle boot (SAATHI-121 F1)', () => {
  it('embeds zero literal </script> or <!-- tokens inside the bundler JSON payloads', () => {
    const lines = fs.readFileSync(BUNDLE, 'utf8').split('\n');
    const manifestOpen = lines.findIndex((l) => l.includes('<script type="__bundler/manifest">'));
    const templateOpen = lines.findIndex((l) => l.includes('<script type="__bundler/template">'));
    expect(manifestOpen).toBeGreaterThan(-1);
    expect(templateOpen).toBeGreaterThan(-1);
    for (const payload of [lines[manifestOpen + 1], lines[templateOpen + 1]]) {
      expect(payload.includes('</script')).toBe(false);
      expect(payload.includes('<!--')).toBe(false);
      JSON.parse(payload); // payload must remain valid JSON after escaping
    }
    const whole = lines.join('\n');
    const closeTags = whole.split('</script').length - 1;
    const blockOpens = lines.filter((l) => /^\s*<script[\s>]/.test(l)).length;
    expect(blockOpens).toBe(5);
    expect(closeTags).toBe(5);
  });

  it('stores the LSKIT resource uncompressed (deterministic across Node/zlib versions)', () => {
    const lines = fs.readFileSync(BUNDLE, 'utf8').split('\n');
    const manifestOpen = lines.findIndex((l) => l.includes('<script type="__bundler/manifest">'));
    const manifest = JSON.parse(lines[manifestOpen + 1]);
    const jsKey = Object.keys(manifest).find((k) => manifest[k].mime === 'application/javascript');
    expect(jsKey).toBeTruthy();
    expect(manifest[jsKey].compressed).toBe(false);
    const lskit = Buffer.from(manifest[jsKey].data, 'base64').toString('utf8');
    expect(lskit).toContain(`contract checksum: ${APPROVED_CHECKSUM}`);
  });

  it.skipIf(!chromiumAvailable())(
    'boots in real chromium: window.__opt exists, checksum matches, no errors',
    async (ctx) => {
      expect(contractChecksum()).toBe(APPROVED_CHECKSUM);
      let browser;
      try {
        browser = await chromium.launch();
      } catch (err) {
        /* A launch failure can only be an incapable HOST (missing system
         * libraries, e.g. libXdamage.so.1 in the network-isolated Linux
         * sandbox) — the bundle was never reached, so the boot verdict is
         * unknowable here, not passed. Mac/CI hosts launch fine and run the
         * strict assertions below. */
        const msg = String(err?.message ?? err);
        if (/error while loading shared libraries|Executable doesn't exist|browserType.launch/.test(msg)) {
          ctx.skip(`chromium cannot launch on this host (not a bundle verdict): ${msg.split('\n')[0]}`);
          return;
        }
        throw err;
      }
      try {
        const page = await browser.newPage({ viewport: { width: 1024, height: 768 } });
        const consoleErrors = [];
        const pageErrors = [];
        page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
        page.on('pageerror', (e) => pageErrors.push(String(e)));
        await page.goto(pathToFileURL(BUNDLE).href);
        await page.waitForFunction(() => !!window.__opt, null, { timeout: 20000 });
        const probe = await page.evaluate(() => ({
          bundlerErr: document.getElementById('__bundler_err')?.textContent ?? null,
          checksum: window.LSKIT?.FIXTURE?.checksum ?? null,
          fns: ['apply', 'render', 'setFrame', 'focusHeading']
            .map((k) => [k, typeof window.__opt?.[k]]),
        }));
        expect(probe.bundlerErr).toBeNull();
        expect(probe.checksum).toBe(APPROVED_CHECKSUM);
        for (const [name, type] of probe.fns) {
          expect(`${name}:${type}`).toBe(`${name}:function`);
        }
        expect(pageErrors).toEqual([]);
        expect(consoleErrors).toEqual([]);
      } finally {
        await browser.close();
      }
    },
    60000,
  );
});

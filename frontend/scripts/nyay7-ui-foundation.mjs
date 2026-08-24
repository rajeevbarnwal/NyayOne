import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';
import {
  NYAY7_ASSERTION_INVENTORY,
  NYAY7_CHECKS,
  NYAY7_LAYOUT_SHIFT_MAX,
  NYAY7_LANGUAGE_OPTIONS,
  NYAY7_MOBILE_TARGET_MIN,
  NYAY7_PERSONA_OPTIONS,
  NYAY7_SCREENS,
  NYAY7_VIEWPORTS,
  NYAY7_VISUAL_MAX_MISMATCH_RATIO,
  nyay7AssertionName,
  summarizeNyay7Rows,
} from './lib/nyay7-ui-contract.mjs';

const require = createRequire(import.meta.url);
const axeSource = await readFile(require.resolve('axe-core/axe.min.js'), 'utf8');
const baseUrl = process.env.NYAY7_BASE_URL ?? 'http://127.0.0.1:4174';
const outputPath = resolve(
  process.env.NYAY7_EVIDENCE_PATH ?? 'test-results/nyay7-ui-foundation/results.json',
);
const evidenceDirectory = dirname(outputPath);
const baselineDirectory = resolve('test-baselines/nyay7/option-3.2.1-rev-l');
const actualDirectory = resolve(evidenceDirectory, 'actual');
const diffDirectory = resolve(evidenceDirectory, 'diff');
await Promise.all([
  mkdir(actualDirectory, { recursive: true }),
  mkdir(diffDirectory, { recursive: true }),
]);

const rows = new Map();
function record(viewport, screen, check, pass, diagnostics = {}) {
  if (!NYAY7_CHECKS.includes(check)) throw new Error(`NYAY7_UNKNOWN_CHECK:${check}`);
  const name = nyay7AssertionName(viewport, screen, check);
  if (!NYAY7_ASSERTION_INVENTORY.includes(name)) throw new Error(`NYAY7_UNKNOWN_ASSERTION:${name}`);
  if (rows.has(name)) throw new Error(`NYAY7_DUPLICATE_ASSERTION:${name}`);
  rows.set(name, {
    name,
    pass: Boolean(pass),
    executed: true,
    skipped: false,
    diagnostics,
  });
}

function recordUnobservedFailures(viewport, screen, error) {
  for (const check of NYAY7_CHECKS) {
    const name = nyay7AssertionName(viewport, screen, check);
    if (!rows.has(name)) record(viewport, screen, check, false, { error });
  }
}

const anonymousSession = { authenticated: false, actor: null };
function otpStateFor(screenId) {
  return {
    status: 'pending',
    purpose: screenId === 'S-09' ? 'signup' : 'login',
    destination_masked: '+91 ••••• ••340',
    attempts_left: 3,
    expires_in_seconds: 272,
    resend_in_seconds: 0,
    locked_for_seconds: 0,
    resend_allowed: true,
  };
}

async function installFixtures(page, screenId) {
  await page.route('**/api/v1/**', (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/v1/auth/student/session') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(anonymousSession),
      });
    }
    if (pathname === '/api/v1/auth/student/otp/state') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(otpStateFor(screenId)),
      });
    }
    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'nyay7_fixture_route_not_implemented' } }),
    });
  });
}

async function observeAxe(page) {
  await page.addScriptTag({ content: axeSource });
  return page.evaluate(async () => {
    const result = await window.axe.run(document, { resultTypes: ['violations', 'incomplete'] });
    const blockingImpacts = ['critical', 'serious'];
    const blocking = result.violations
      .filter((violation) => blockingImpacts.includes(violation.impact ?? ''))
      .map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.map((node) => ({ target: node.target, failureSummary: node.failureSummary })),
      }));
    return {
      blocking,
      allViolations: result.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodeCount: violation.nodes.length,
      })),
      incomplete: result.incomplete.map((entry) => ({
        id: entry.id,
        impact: entry.impact,
        nodeCount: entry.nodes.length,
      })),
    };
  });
}

async function observeGeometry(page, isMobile) {
  return page.evaluate(({ mobile, targetMin }) => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && style.opacity !== '0'
        && rect.width > 0
        && rect.height > 0;
    };
    const selector = [
      'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea',
      '[role="button"]', '[role="option"]', '[role="radio"]', '[tabindex]:not([tabindex="-1"])',
    ].join(',');
    const effectiveRect = (element) => {
      const own = element.getBoundingClientRect();
      if (!(element instanceof HTMLInputElement)
        || !['checkbox', 'radio'].includes(element.type)) return own;
      const label = element.closest('label')
        || (element.id ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`) : null);
      if (!label || !visible(label)) return own;
      const proxy = label.getBoundingClientRect();
      const left = Math.min(own.left, proxy.left);
      const right = Math.max(own.right, proxy.right);
      const top = Math.min(own.top, proxy.top);
      const bottom = Math.max(own.bottom, proxy.bottom);
      return { width: right - left, height: bottom - top };
    };
    const smallTargets = mobile
      ? [...document.querySelectorAll(selector)]
        .filter(visible)
        .map((element) => {
          const rect = effectiveRect(element);
          return {
            name: element.getAttribute('aria-label')
              || element.textContent?.trim().replace(/\s+/gu, ' ').slice(0, 80)
              || element.id
              || element.tagName,
            width: Number(rect.width.toFixed(2)),
            height: Number(rect.height.toFixed(2)),
          };
        })
        .filter(({ width, height }) => width < targetMin || height < targetMin)
      : [];
    const screen = document.querySelector('[data-screen]');
    return {
      documentOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      screenOverflow: screen ? Math.max(0, screen.scrollWidth - screen.clientWidth) : null,
      smallTargets,
    };
  }, { mobile: isMobile, targetMin: NYAY7_MOBILE_TARGET_MIN });
}

async function observeTokenUse(page) {
  return page.evaluate(() => {
    const screen = document.querySelector('[data-screen]');
    const heading = screen?.querySelector('h1');
    if (!screen || !heading) return { present: false };
    const screenStyle = getComputedStyle(screen);
    const headingStyle = getComputedStyle(heading);
    const values = {
      paper: screenStyle.getPropertyValue('--v34-bg').trim().toLowerCase(),
      card: screenStyle.getPropertyValue('--v34-surface').trim().toLowerCase(),
      deep: screenStyle.getPropertyValue('--v34-mark').trim().toLowerCase(),
      indigo: screenStyle.getPropertyValue('--v34-accent-text').trim().toLowerCase(),
      headingFont: headingStyle.fontFamily.toLowerCase(),
    };
    return {
      present: true,
      values,
      exact: values.paper === '#efedf6'
        && values.card === '#ffffff'
        && values.deep === '#1c2454'
        && values.indigo === '#2e3a8c'
        && values.headingFont.includes('aptos'),
    };
  });
}

async function observeSelectorContext(page, screenId) {
  const counts = await page.evaluate(() => ({
    personaTriggers: document.querySelectorAll('[data-nyayone-persona-trigger]').length,
    languageTriggers: document.querySelectorAll('[data-nyayone-language-trigger]').length,
    createContexts: document.querySelectorAll('[data-nyayone-create-context]').length,
    personaChanges: document.querySelectorAll('[data-nyayone-persona-change]').length,
  }));

  if (screenId === 'S-04' || screenId === 'S-05') {
    return {
      pass: Object.values(counts).every((count) => count === 0),
      counts,
      expected: 'no persona or locale authority on sign-in screens',
    };
  }
  if (screenId === 'S-08' || screenId === 'S-09') {
    return {
      pass: counts.createContexts === 1
        && counts.personaChanges === 1
        && counts.languageTriggers === 1
        && counts.personaTriggers === 0,
      counts,
      expected: 'one Student/English create-account context',
    };
  }

  const personaTrigger = page.locator('[data-nyayone-persona-trigger]');
  const languageTrigger = page.locator('[data-nyayone-language-trigger]');
  const triggerSemantics = counts.personaTriggers === 1
    && counts.languageTriggers === 1
    && await personaTrigger.getAttribute('aria-haspopup') === 'listbox'
    && await languageTrigger.getAttribute('aria-haspopup') === 'listbox';
  let personaOptions = [];
  let languageOptions = [];
  let disabledPersonaInert = false;
  let disabledLanguageInert = false;

  if (counts.personaTriggers === 1) {
    await personaTrigger.click();
    personaOptions = await page.locator('[role="option"][data-nyayone-persona-option]').evaluateAll((options) => (
      options.map((option) => ({
        name: option.getAttribute('data-nyayone-value'),
        selected: option.getAttribute('aria-selected'),
        disabled: option.getAttribute('aria-disabled'),
        text: option.textContent?.trim().replace(/\s+/gu, ' '),
      }))
    ));
    const before = await personaTrigger.textContent();
    const lawyer = page.locator('[role="option"][data-nyayone-persona-option][data-nyayone-value="Lawyer"]');
    if (await lawyer.count() === 1) await lawyer.click();
    disabledPersonaInert = (await personaTrigger.textContent()) === before
      && await personaTrigger.getAttribute('aria-expanded') === 'true';
    await personaTrigger.press('Escape');
  }

  if (counts.languageTriggers === 1) {
    await languageTrigger.click();
    languageOptions = await page.locator('[role="option"][data-nyayone-language-option]').evaluateAll((options) => (
      options.map((option) => ({
        name: option.getAttribute('data-nyayone-value'),
        selected: option.getAttribute('aria-selected'),
        disabled: option.getAttribute('aria-disabled'),
        text: option.textContent?.trim().replace(/\s+/gu, ' '),
      }))
    ));
    const before = await languageTrigger.textContent();
    const hindi = page.locator('[role="option"][data-nyayone-language-option][data-nyayone-value="हिन्दी"]');
    if (await hindi.count() === 1) await hindi.click();
    disabledLanguageInert = (await languageTrigger.textContent()) === before
      && await languageTrigger.getAttribute('aria-expanded') === 'true';
    await languageTrigger.press('Escape');
  }

  const personaExact = JSON.stringify(personaOptions) === JSON.stringify(NYAY7_PERSONA_OPTIONS);
  const languageExact = JSON.stringify(languageOptions) === JSON.stringify(NYAY7_LANGUAGE_OPTIONS);

  return {
    pass: triggerSemantics && personaExact && languageExact
      && disabledPersonaInert && disabledLanguageInert,
    counts,
    triggerSemantics,
    personaOptions,
    languageOptions,
    disabledPersonaInert,
    disabledLanguageInert,
  };
}

async function compareVisual(actualBytes, baselinePath, diffPath) {
  const [actual, baseline] = await Promise.all([
    Promise.resolve(PNG.sync.read(Buffer.from(actualBytes))),
    readFile(baselinePath).then((bytes) => PNG.sync.read(bytes)),
  ]);
  if (actual.width !== baseline.width || actual.height !== baseline.height) {
    return {
      pass: false,
      dimensions: {
        actual: [actual.width, actual.height],
        baseline: [baseline.width, baseline.height],
      },
      mismatchRatio: 1,
    };
  }
  const diff = new PNG({ width: actual.width, height: actual.height });
  const mismatchedPixels = pixelmatch(
    actual.data,
    baseline.data,
    diff.data,
    actual.width,
    actual.height,
    { threshold: 0.1, includeAA: false },
  );
  const mismatchRatio = mismatchedPixels / (actual.width * actual.height);
  await writeFile(diffPath, PNG.sync.write(diff));
  return {
    pass: mismatchRatio <= NYAY7_VISUAL_MAX_MISMATCH_RATIO,
    dimensions: { actual: [actual.width, actual.height], baseline: [baseline.width, baseline.height] },
    mismatchedPixels,
    mismatchRatio,
    maximum: NYAY7_VISUAL_MAX_MISMATCH_RATIO,
  };
}

const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of NYAY7_VIEWPORTS) {
    for (const screen of NYAY7_SCREENS) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: 'light',
        reducedMotion: 'reduce',
        serviceWorkers: 'block',
      });
      await context.addInitScript(() => {
        window.__nyay7LayoutShift = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (!entry.hadRecentInput) window.__nyay7LayoutShift.push(entry.value);
          }
        }).observe({ type: 'layout-shift', buffered: true });
      });
      const page = await context.newPage();
      await installFixtures(page, screen.id);
      try {
        await page.goto(`${baseUrl}${screen.path}`, { waitUntil: 'domcontentloaded' });
        const mounted = page.locator(`[data-screen="${screen.id}"]`);
        await mounted.waitFor({ state: 'visible', timeout: 10_000 });
        record(viewport.id, screen.id, 'mount', await mounted.count() === 1, {
          url: page.url(),
          count: await mounted.count(),
        });
        await page.evaluate(async () => {
          await document.fonts.ready;
          await new Promise((resolveFrame) => requestAnimationFrame(() => requestAnimationFrame(resolveFrame)));
        });

        const axe = await observeAxe(page);
        record(viewport.id, screen.id, 'axe-serious-critical', axe.blocking.length === 0, axe);

        const geometry = await observeGeometry(page, viewport.id !== 'desktop');
        record(viewport.id, screen.id, 'horizontal-overflow',
          geometry.documentOverflow === 0 && geometry.screenOverflow === 0, geometry);
        record(viewport.id, screen.id, 'mobile-touch-targets',
          viewport.id === 'desktop' || geometry.smallTargets.length === 0,
          viewport.id === 'desktop' ? { notApplicable: true } : geometry);

        const layoutShift = await page.evaluate(() => (
          window.__nyay7LayoutShift.reduce((sum, value) => sum + value, 0)
        ));
        record(viewport.id, screen.id, 'layout-shift', layoutShift <= NYAY7_LAYOUT_SHIFT_MAX, {
          observed: layoutShift,
          maximum: NYAY7_LAYOUT_SHIFT_MAX,
        });

        const tokens = await observeTokenUse(page);
        record(viewport.id, screen.id, 'rev-l-token-use', tokens.exact === true, tokens);

        const selectorContext = await observeSelectorContext(page, screen.id);
        record(viewport.id, screen.id, 'selector-context-contract', selectorContext.pass, selectorContext);

        const actualPath = resolve(actualDirectory, `${viewport.directory}-${screen.baseline}`);
        const diffPath = resolve(diffDirectory, `${viewport.directory}-${screen.baseline}`);
        const actual = await page.screenshot({ animations: 'disabled' });
        await writeFile(actualPath, actual);
        const visual = await compareVisual(
          actual,
          resolve(baselineDirectory, viewport.directory, screen.baseline),
          diffPath,
        );
        record(viewport.id, screen.id, 'visual-baseline', visual.pass, {
          ...visual,
          baseline: resolve(baselineDirectory, viewport.directory, screen.baseline),
          actual: actualPath,
          diff: diffPath,
        });
      } catch (error) {
        console.error(JSON.stringify({
          stage: 'screen-observation',
          viewport: viewport.id,
          screen: screen.id,
          error: error instanceof Error ? error.message : String(error),
        }));
        recordUnobservedFailures(
          viewport.id,
          screen.id,
          error instanceof Error ? error.message : String(error),
        );
      } finally {
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
}

const orderedRows = NYAY7_ASSERTION_INVENTORY
  .map((name) => rows.get(name))
  .filter(Boolean);
const summary = summarizeNyay7Rows(orderedRows);
const report = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  baseUrl,
  summary,
  rows: orderedRows,
};
await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ outputPath, summary }, null, 2));
if (!summary.valid || summary.failed > 0) process.exitCode = 1;

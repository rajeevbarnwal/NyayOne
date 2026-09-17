import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';

const ROOT = resolve(import.meta.dirname, '../..');
const RUNNER = resolve(ROOT, 'scripts/nyay5-profile-browser.mjs');
const CONTRACT = resolve(import.meta.dirname, 'nyay5-profile-browser-contract.mjs');
const PACKAGE = resolve(ROOT, 'package.json');
const STUDENT_V34_STYLES = resolve(ROOT, 'src/styles/student-v34.css');
const ACCEPTANCE_MATRIX = resolve(
  ROOT,
  '../docs/design/nyayone_auth_profile_option3_2_engineering_handoff_2026-08-17/ACCEPTANCE_MATRIX.md',
);

function stringArrayConstant(source, name) {
  const match = source.match(new RegExp(
    `const ${name} = Object\\.freeze\\(\\[([\\s\\S]*?)\\]\\);`,
    'u',
  ));
  expect(match, `${name} must be an explicit frozen string array`).not.toBeNull();
  return [...match[1].matchAll(/'([^']+)'/gu)].map((entry) => entry[1]);
}

// Execute the producer's actual census callback, not a second implementation
// of its predicates. The DOM double supplies only the observations it reads.
async function visualCensus({ screenId = 'S-06', family, logo = {}, decoration = false,
  decorationParent = {}, decorationIcon = {} } = {}) {
  class CensusElement {
    constructor(attributes = {}, parentElement = null) {
      this.attributes = attributes;
      this.parentElement = parentElement;
      this.isConnected = true;
      this.tabIndex = Number(attributes.tabindex ?? -1);
      this.classList = { contains: name => (attributes.class ?? '').split(' ').includes(name) };
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
    getClientRects() { return [{}]; }
    closest(selector) {
      if (selector === 'button,a') return null;
      throw new Error(`UNEXPECTED_CENSUS_SELECTOR:${selector}`);
    }
  }
  const heading = new CensusElement();
  heading.family = family ?? '"NyayOne Revision L Heading", Aptos, Calibri, Carlito, system-ui, sans-serif';
  const lockup = new CensusElement({ class: 'v321-lockup', role: 'img',
    'aria-label': 'NyayOne — Legal, on the record', ...logo });
  const icons = [lockup];
  if (decoration) icons.push(new CensusElement(decorationIcon,
    new CensusElement({ class: 's06-r2__ring', 'aria-hidden': 'true', ...decorationParent })));
  const root = new CensusElement();
  root.textContent = 'Recover your account.';
  root.querySelector = selector => {
    if (selector === '.v321-lockup') return lockup.classList.contains('v321-lockup') ? lockup : null;
    throw new Error(`UNEXPECTED_CENSUS_SELECTOR:${selector}`);
  };
  root.querySelectorAll = selector => {
    if (selector === 'h1,h2') return [heading];
    if (selector === 'svg') return icons;
    throw new Error(`UNEXPECTED_CENSUS_SELECTOR:${selector}`);
  };
  const document = {
    documentElement: { getAttribute: name => name === 'data-theme' ? 'light' : null },
    fonts: { status: 'loaded', ready: Promise.resolve() },
    querySelector: selector => {
      expect(selector).toBe(`[data-screen="${screenId}"]`);
      return root;
    },
  };
  const readiness = [];
  const locator = { first: () => locator, locator: () => locator, waitFor: async () => {} };
  const page = {
    locator: () => locator,
    evaluate: async callback => callback(),
    waitForFunction: async (callback, contract) => {
      const observation = callback(contract);
      if (!observation) throw new Error('CENSUS_NOT_READY');
      return { jsonValue: async () => observation, dispose: async () => {} };
    },
  };
  const visualScreens = new Map();
  const runner = readFileSync(RUNNER, 'utf8');
  const constants = runner.slice(runner.indexOf('const REVISION_L_VISUAL_SCREEN_IDS'),
    runner.indexOf('let authWireExact'));
  const callback = runner.slice(runner.indexOf('async function recordVisualContract'),
    runner.indexOf('async function resetOtp'));
  await runInNewContext(`${constants}\n${callback}\nrecordVisualContract(page, screenId)`, {
    page, screenId, document, Element: CensusElement, visualScreens,
    getComputedStyle: element => ({ visibility: 'visible', fontFamily: element.family ?? '' }),
    waitForVisualCensusSettled: async (_page, options) => readiness.push(options),
  });
  return { ...visualScreens.get(screenId), readiness };
}

// Execute the real responsive callback with a focused, visible city field.
async function responsiveCensus(family, viewportName = 'mobile-keyboard') {
  class ResponsiveElement {
    constructor(id, textContent = '') { this.id = id; this.textContent = textContent; }
    getClientRects() { return [{}]; }
    getBoundingClientRect() { return { top: 100, bottom: 148, width: 180, height: 48 }; }
  }
  const city = new ResponsiveElement('profile-personal-city');
  const primary = new ResponsiveElement('save', 'Save & continue');
  const heading = Object.assign(new ResponsiveElement('title'), { tagName: 'H1', className: 'v321-profile__title' });
  const runner = readFileSync(RUNNER, 'utf8');
  const start = runner.indexOf('geometries.push(await page.evaluate(');
  const callback = runner.slice(start + 'geometries.push(await page.evaluate('.length,
    runner.indexOf(', viewport.name));', start));
  return runInNewContext(`(${callback})(viewportName)`, {
    viewportName, HTMLElement: ResponsiveElement,
    getComputedStyle: () => ({ fontFamily: family }),
    window: { innerHeight: 430 },
    document: { documentElement: { scrollWidth: 390, clientWidth: 390 }, activeElement: city,
      querySelectorAll: selector => {
        if (selector === 'h1,h2') return [heading];
        if (selector === 'button') return [primary];
        if (selector === 'button,a,input,select') return [city, primary];
        throw new Error(`UNEXPECTED_RESPONSIVE_SELECTOR:${selector}`);
      } },
  });
}

const EXPECTED_ASSERTIONS = [
  'runtime_chromium',
  'pending_session_fail_closed',
  'denial_matrix_fail_closed',
  'single_authoritative_projection',
  'confirmed_success_before_navigation',
  'typed_failures_retain_route_and_values',
  'direct_step_skip_denied',
  'completion_server_derived',
  'verification_distinct_from_completion',
  'prompt_session_scoped',
  'prompt_lifecycle_teardown',
  'dialog_focus_and_inert_contract',
  'accessible_errors_and_controls',
  'responsive_targets_and_no_overflow',
  'reload_new_tab_resume',
  'cross_user_denied',
  'stale_multi_tab_conflict',
  'uncertain_write_reconciles',
  'production_actor_channel_exact',
  'browser_persistence_inventory_clean',
  'unicode_legal_name_corpus',
  'evidence_privacy_and_mutants',
];

const EXPECTED_MUTANTS = [
  'mount-private-content-while-session-pending',
  'accept-anonymous-profile-route',
  'accept-wrong-role-profile-route',
  'trust-client-owner-header',
  'trust-client-owner-query',
  'trust-client-owner-body',
  'navigate-before-server-success',
  'discard-values-on-typed-error',
  'complete-skipped-section',
  'derive-completion-in-browser',
  'derive-verification-from-completion',
  'persist-prompt-dismissal-in-web-storage',
  'retain-prompt-on-session-rotation',
  'omit-dialog-focus-wrap',
  'omit-dialog-background-inert',
  'accept-sub-44px-target',
  'allow-horizontal-overflow',
  'accept-cross-user-projection',
  'overwrite-newer-profile-version',
  'retry-uncertain-write-before-refetch',
  'persist-profile-pii',
  'persist-uuid-capability',
  'accept-control-character-name',
  'accept-61-code-point-name',
  'render-password-auth-surface',
  'omit-required-storage-surface',
  'omit-required-assertion',
  'reorder-required-assertions',
  'duplicate-required-assertion',
  'emit-private-evidence',
  'substitute-s14-for-s07-popup-host',
  'hard-code-progress-at-67',
  'accept-empty-otp',
  'accept-unchecked-consent',
  'disagree-decomposed-valid-name',
  'disagree-punctuation-only-name',
  'disagree-tabbed-name',
  'disagree-61-code-point-name',
  'disclose-registration-existence',
  'navigate-after-failed-save',
  'expose-reviewer-demo-validation-bypass',
  'allow-student-guardian-verification-mutation',
  'grant-authority-from-forged-registration-uuid',
  'persist-raw-token-or-identity',
  'zero-selector-icon-success',
  'green-aggregator-after-required-workflow-failure',
];

const VALID_EMPTY_PROJECTION = {
  profile_version: 1,
  completion_version: 'v1',
  completion_percent: 0,
  completed_sections: [],
  missing_requirements: [
    'personal.preferred_language',
    'personal.city',
    'academic.college',
    'academic.year_of_study',
    'academic.enrolment_number',
    'interests.interests',
    'interests.goals',
  ],
  next_incomplete_section: 'personal',
  is_complete: false,
  institutional_email_status: 'not_provided',
  guardian: { required: false, status: 'not_required' },
  access_mode: 'full',
  disabled_capabilities: [],
  profile_prompt: { should_show: true, dismissed_for_session: false },
  profile: {
    personal: {
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      date_of_birth: '2002-03-14',
      preferred_language: null,
      city: null,
      pronouns: null,
    },
    academic: {
      college: null,
      year_of_study: null,
      enrolment_number: null,
      institutional_email: null,
      bar_enrolment_number: null,
    },
    interests: { interests: [], goals: [] },
  },
};

describe('NYAY-5 browser release-gate source contract', () => {
  it('maps every acceptance-matrix ID to a real non-skipped execution', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const matrixIds = [...readFileSync(ACCEPTANCE_MATRIX, 'utf8').matchAll(
      /^\|\s*([A-Z0-9]+-\d{2})\s*\|/gmu,
    )].map((match) => match[1]);
    expect(matrixIds).toHaveLength(61);
    expect(contract.NYAY5_ACCEPTANCE_MATRIX_IDS).toEqual(matrixIds);
    expect(Object.keys(contract.NYAY5_ACCEPTANCE_EXECUTION_MAP)).toEqual(matrixIds);

    const executions = [...new Set(
      Object.values(contract.NYAY5_ACCEPTANCE_EXECUTION_MAP).flat(),
    )].map((id) => ({
      id,
      executed: true,
      skipped: false,
      pass: true,
      evidenceCount: 1,
      selectorCount: contract.NYAY5_SELECTOR_EXECUTION_IDS.includes(id) ? 1 : null,
    }));
    const baseline = contract.inspectAcceptanceExecutionCoverage(executions);
    expect(baseline).toMatchObject({ pass: true, mapped: 61, missing: 0, skipped: 0 });
    expect(contract.inspectAcceptanceExecutionCoverage(executions.slice(1)).pass).toBe(false);
    expect(contract.inspectAcceptanceExecutionCoverage([
      ...executions,
      { ...executions[0], skipped: true },
    ]).pass).toBe(false);
    expect(contract.inspectBrowserExecutionCoverage([
      ...executions.filter((row) => row.id.startsWith('browser:')
        && row.id !== 'browser:svg_icon_census'),
      {
        id: 'browser:svg_icon_census',
        executed: true,
        skipped: false,
        pass: true,
        evidenceCount: 1,
        selectorCount: 0,
      },
    ]).pass).toBe(false);
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain('inspectBrowserExecutionCoverage');
    expect(runner).toContain('acceptanceExecutionCoverage');
    expect(contract.inspectAcceptanceExecutionCoverage([
      ...executions.filter((row) => row.id !== 'browser:responsive_targets_and_no_overflow'),
      {
        id: 'browser:responsive_targets_and_no_overflow',
        executed: true,
        skipped: false,
        pass: true,
        selectorCount: 0,
      },
    ]).pass).toBe(false);
  });

  it('executes every exact responsive viewport including keyboard geometry', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain("{ name: 'mobile-narrow', width: 360, height: 800 }");
    expect(runner).toContain("{ name: 'mobile-keyboard', width: 390, height: 430 }");
    expect(runner).toContain("{ name: 'mobile-standard', width: 390, height: 844 }");
    expect(runner).toContain("{ name: 'desktop', width: 1440, height: 1024 }");
    expect(runner).toContain("viewport.name === 'mobile-keyboard'");
    const styles = readFileSync(STUDENT_V34_STYLES, 'utf8');
    expect(styles).toContain(
      ".ls-v34-content [data-screen='S-10'] :is(h1, h2) { font-family: Aptos, Calibri, Carlito, system-ui, sans-serif; }",
    );
    const revisionLStyles = readFileSync(resolve(ROOT, 'src/styles/student-option321.css'), 'utf8');
    expect(revisionLStyles).toContain(
      ".ls-v34-content .v321-profile[data-screen='S-10'] :is(h1, h2) { font-family: var(--nyayone-font-heading); }",
    );
  });

  it('uses the approved S-10 heading after the Wave-1 edit-profile route without dropping its waits', () => {
    const wave1 = readFileSync(resolve(ROOT, 'scripts/v34-s11-s26-e2e.mjs'), 'utf8');
    expect(wave1).toContain("page.waitForURL((url) => url.pathname === '/s-10' && url.search === '?section=personal')");
    expect(wave1).toContain("getByRole('heading', { name: 'About you.', exact: true }).waitFor({ state: 'visible' })");
    expect(wave1).not.toContain("getByRole('heading', { name: 'About you', exact: true })");
  });

  it('measures the S-10 Revision L keyboard font while retaining focus and target checks', async () => {
    expect(await responsiveCensus('Aptos, Calibri, "NyayOne Revision L Heading", system-ui, sans-serif'))
      .toMatchObject({ typographyExact: true, keyboardGeometryExact: true, selectorCount: 2, minimumTarget: 48, overflow: false });
  });

  it.each([
    'Aptos, Calibri, Carlito, system-ui, sans-serif',
    '"NyayOne Revision L Heading", Aptos, Calibri, system-ui, sans-serif',
    'Aptos, Calibri, "NyayOne Revision L Heading", system-ui, serif',
  ])('rejects the wrong S-10 keyboard heading stack: %s', async family => {
    expect((await responsiveCensus(family)).typographyExact).toBe(false);
  });

  it.each(['mobile-narrow', 'mobile-standard', 'desktop'])(
    'preserves the existing S-16 responsive font expectations for %s', async viewport => {
      expect((await responsiveCensus('Aptos, Calibri, Carlito, system-ui, sans-serif', viewport)).typographyExact).toBe(true);
      expect((await responsiveCensus('sans-serif', viewport)).typographyExact).toBe(false);
    });

  it('requires the production service worker and exact public-shell cache inventory', async () => {
    const { inspectBrowserPersistence } = await import(
      './nyay5-profile-browser-contract.mjs'
    );
    const clean = {
      origin: 'http://localhost:1190',
      localStorageKeys: [],
      localStorageEntries: [],
      sessionStorageKeys: [],
      cacheInventory: [{
        name: 'nyayone-shell-v1',
        entries: [
          {
            pathname: '/index.html', query: '', method: 'GET',
            credentials: 'same-origin', authorization: false, responseStatus: 200,
          },
          {
            pathname: '/assets/index-a1b2c3.js', query: '', method: 'GET',
            credentials: 'omit', authorization: false, responseStatus: 200,
          },
        ],
      }],
      serviceWorker: {
        supported: true,
        controlled: true,
        registrations: 1,
        scriptPathnames: ['/sw.js'],
        productionAssets: true,
        disableFlagAbsent: true,
      },
      privacyInstrumentation: {
        installed: true,
        historyCallsObserved: 2,
        transientHistoryPrivateDetected: false,
        globalsScanned: 1,
        globalPrivateDetected: false,
        windowNamePrivateDetected: false,
        historyStatePrivateDetected: false,
      },
      indexedDatabases: [],
      javascriptCookieNames: [],
      deterministicGlobalKeys: [],
      historyUrls: ['http://localhost:1190/s-14'],
    };
    expect(inspectBrowserPersistence(clean).pass).toBe(true);
    for (const mutant of [
      { ...clean, cacheInventory: [] },
      {
        ...clean,
        cacheInventory: clean.cacheInventory.map((cache) => ({
          ...cache,
          name: 'ls-shell-v1',
        })),
      },
      {
        ...clean,
        cacheInventory: [{ name: 'nyayone-shell-v1', entries: [{
          pathname: '/api/v1/student/profile', query: '', method: 'GET',
          credentials: 'omit', authorization: false, responseStatus: 200,
        }] }],
      },
      {
        ...clean,
        cacheInventory: [{ name: 'nyayone-shell-v1', entries: [{
          pathname: '/assets/index-a1b2c3.js', query: '?credential=private', method: 'GET',
          credentials: 'omit', authorization: false, responseStatus: 200,
        }] }],
      },
      { ...clean, serviceWorker: { ...clean.serviceWorker, controlled: false } },
      { ...clean, serviceWorker: { ...clean.serviceWorker, disableFlagAbsent: false } },
      {
        ...clean,
        privacyInstrumentation: {
          ...clean.privacyInstrumentation,
          transientHistoryPrivateDetected: true,
        },
      },
      {
        ...clean,
        privacyInstrumentation: {
          ...clean.privacyInstrumentation,
          globalPrivateDetected: true,
        },
      },
      {
        ...clean,
        privacyInstrumentation: {
          ...clean.privacyInstrumentation,
          windowNamePrivateDetected: true,
        },
      },
      {
        ...clean,
        privacyInstrumentation: {
          ...clean.privacyInstrumentation,
          historyStatePrivateDetected: true,
        },
      },
    ]) {
      expect(inspectBrowserPersistence(mutant).pass).toBe(false);
    }
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain("'http://localhost:1190'");
    expect(runner).toContain("fetch(`${WEB}/@vite/client`)");
    expect(runner).toContain('viteClientLooksLikeHtmlFallback');
    expect(runner).toContain("viteClientResponse.headers.get('content-type')");
    expect(runner).toContain('navigator.serviceWorker.ready');
    expect(runner).toContain("Symbol.for('nyay5.browser.privacy-probe.v1')");
    expect(runner).toContain("for (const method of ['pushState', 'replaceState'])");
    expect(runner).toContain('context.addInitScript');
    expect(runner).toContain('privacyProbe.containsPrivate(window.name)');
    expect(runner).toContain('privacyProbe.containsPrivate(history.state)');
  });

  it('executes the empty S-08 accessibility denial with zero request', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain('const registrationRequestsBeforeEmptySubmit');
    expect(runner).toContain("emptySummary.getAttribute('role') === 'alert'");
    expect(runner).toContain('registrationRequestsAfterEmptySubmit === registrationRequestsBeforeEmptySubmit');
  });

  it('provides an exact npm command with no lifecycle wrappers', () => {
    const pkg = JSON.parse(readFileSync(PACKAGE, 'utf8'));
    expect(pkg.scripts['qa:nyay5:profile-boundary']).toBe(
      'node scripts/nyay5-profile-browser.mjs',
    );
    expect(pkg.scripts['preqa:nyay5:profile-boundary']).toBeUndefined();
    expect(pkg.scripts['postqa:nyay5:profile-boundary']).toBeUndefined();
  });

  it('ships separate executable and pure assertion-contract modules', () => {
    expect(() => readFileSync(RUNNER, 'utf8')).not.toThrow();
    expect(() => readFileSync(CONTRACT, 'utf8')).not.toThrow();
  });

  it('requires the authenticated cookie to be root-scoped and SameSite Lax', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain(
      "context.cookies(`${API}/api/v1/auth/student/session`)",
    );
    expect(runner).not.toContain('context.cookies(API)');
    expect(runner).toContain("cookie.path === '/' && cookie.sameSite === 'Lax'");
    expect(runner).not.toContain("cookie.path.startsWith('/api/v1')");
  });

  it('runs expired, revoked, deleted, and wrong-role denials through real sessions', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain('NYAY5_DENIAL_FIXTURE_PATH');
    expect(runner).toContain("['expired', 'revoked', 'deleted', 'wrong_role']");
    expect(runner).toContain('await context.addCookies');
    expect(runner).toContain('privateRequestCount === 0');
    expect(runner).toContain('realDenials.every(Boolean)');
  });

  it('requires deliberate conflict review before a current-version CAS retry', async () => {
    const { inspectStaleConflictObservation } = await import(
      './nyay5-profile-browser-contract.mjs'
    );
    const baseline = {
      firstStatus: 409,
      secondStatus: 409,
      routeAndValuesRetained: true,
      patchCountBeforeReview: 1,
      conflictReviewVisible: true,
      serverWinnerVisible: true,
      retainedDraftVisible: true,
      patchCountAfterAdopt: 1,
      deliberateRetryStatus: 200,
      wrongStaleStatus: 409,
      deliberateDraftPersisted: true,
      newerVersionPreserved: true,
    };
    expect(inspectStaleConflictObservation(baseline).pass).toBe(true);
    for (const [key, value] of [
      ['patchCountBeforeReview', 2],
      ['conflictReviewVisible', false],
      ['serverWinnerVisible', false],
      ['retainedDraftVisible', false],
      ['patchCountAfterAdopt', 2],
      ['deliberateRetryStatus', 409],
      ['wrongStaleStatus', 200],
      ['deliberateDraftPersisted', false],
      ['newerVersionPreserved', false],
    ]) {
      expect(inspectStaleConflictObservation({ ...baseline, [key]: value }).pass).toBe(false);
    }
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain("getByTestId('profile-conflict-review')");
    expect(runner).toContain("name: 'Use current version and review my draft'");
    expect(runner).toContain('patchCountBeforeReview');
    expect(runner).toContain('patchCountAfterAdopt');
    expect(runner).toContain('deliberateRetryStatus');
    expect(runner).toContain('wrongStaleStatus');
  });

  it('preserves academic and interests drafts across real prerequisite conflicts', async () => {
    const { inspectCrossSectionConflictObservation } = await import(
      './nyay5-profile-browser-contract.mjs'
    );
    const exactCase = {
      section: 'academic',
      firstStatus: 409,
      reviewVisible: true,
      routeAndDraftRetained: true,
      patchCountBeforeAdopt: 1,
      patchCountAfterAdopt: 1,
      deliberateRetryStatus: 200,
      deliberateDraftPersisted: true,
    };
    const prerequisiteCase = {
      section: 'academic',
      firstStatus: 409,
      reviewVisible: true,
      routeAndDraftRetained: true,
      patchCountBeforeAdopt: 1,
      adoptRoutedToPrerequisite: true,
      browserPersistenceClean: true,
      draftRestoredAfterRepair: true,
      finalRetryStatus: 200,
      deliberateDraftPersisted: true,
    };
    const baseline = {
      completePrerequisiteChanges: [
        exactCase,
        { ...exactCase, section: 'interests' },
      ],
      prerequisiteRegressions: [
        prerequisiteCase,
        { ...prerequisiteCase, section: 'interests' },
      ],
    };
    expect(inspectCrossSectionConflictObservation(baseline).pass).toBe(true);
    for (const [group, field, value] of [
      ['completePrerequisiteChanges', 'firstStatus', 200],
      ['completePrerequisiteChanges', 'patchCountAfterAdopt', 2],
      ['completePrerequisiteChanges', 'deliberateRetryStatus', 409],
      ['prerequisiteRegressions', 'routeAndDraftRetained', false],
      ['prerequisiteRegressions', 'adoptRoutedToPrerequisite', false],
      ['prerequisiteRegressions', 'browserPersistenceClean', false],
      ['prerequisiteRegressions', 'draftRestoredAfterRepair', false],
      ['prerequisiteRegressions', 'finalRetryStatus', 409],
    ]) {
      const mutated = structuredClone(baseline);
      mutated[group][0][field] = value;
      expect(inspectCrossSectionConflictObservation(mutated).pass).toBe(false);
    }
    const duplicate = structuredClone(baseline);
    duplicate.prerequisiteRegressions[1].section = 'academic';
    expect(inspectCrossSectionConflictObservation(duplicate).pass).toBe(false);

    const runner = readFileSync(RUNNER, 'utf8');
    for (const seam of [
      'completePrerequisiteChanges',
      'prerequisiteRegressions',
      'profile-conflict-draft-restored',
      'patchCountBeforeAdopt',
      'patchCountAfterAdopt',
      'browserPersistenceClean',
      'draftRestoredAfterRepair',
    ]) {
      expect(runner).toContain(seam);
    }
  });

  it('pins the exact assertion inventory and rejects false-green inventories', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    expect(contract.NYAY5_ASSERTION_INVENTORY).toEqual(EXPECTED_ASSERTIONS);
    const passing = EXPECTED_ASSERTIONS.map((name) => ({ name, pass: true }));
    expect(contract.summarizeNyay5Rows(passing)).toMatchObject({
      total: 22,
      passed: 22,
      failed: 0,
      inventoryExact: true,
    });
    expect(contract.summarizeNyay5Rows(passing.slice(1)).inventoryExact).toBe(false);
    expect(contract.summarizeNyay5Rows([...passing].reverse()).inventoryExact).toBe(false);
    expect(contract.summarizeNyay5Rows([...passing, passing[0]]).inventoryExact).toBe(false);
  });

  it('rejects browser evidence containing identity or authority material', async () => {
    const { scanNyay5Evidence } = await import('./nyay5-profile-browser-contract.mjs');
    expect(scanNyay5Evidence({ status: 'PASS', total: 22 })).toEqual([]);
    expect(scanNyay5Evidence({ mobile: '9876543210' })).not.toEqual([]);
    expect(scanNyay5Evidence({ actor: '123e4567-e89b-42d3-a456-426614174000' })).not.toEqual([]);
    expect(scanNyay5Evidence({ session_token: 'opaque-secret-value' })).not.toEqual([]);
  });

  it('validates the exact nested projection, enums, and state consistency', async () => {
    const { inspectNyay5Projection } = await import('./nyay5-profile-browser-contract.mjs');
    expect(inspectNyay5Projection(VALID_EMPTY_PROJECTION).pass).toBe(true);
    expect(inspectNyay5Projection({
      ...VALID_EMPTY_PROJECTION,
      institutional_email_status: 'arbitrary',
    }).pass).toBe(false);
    expect(inspectNyay5Projection({
      ...VALID_EMPTY_PROJECTION,
      profile: { personal: {}, academic: {}, interests: {} },
    }).pass).toBe(false);
    expect(inspectNyay5Projection({
      ...VALID_EMPTY_PROJECTION,
      profile_prompt: { should_show: false, dismissed_for_session: false },
    }).pass).toBe(false);
    expect(inspectNyay5Projection({
      ...VALID_EMPTY_PROJECTION,
      guardian: { required: true, status: 'required_pending' },
    }).pass).toBe(false);
    expect(inspectNyay5Projection({
      ...VALID_EMPTY_PROJECTION,
      institutional_email_status: 'pending',
      profile: {
        ...VALID_EMPTY_PROJECTION.profile,
        academic: {
          ...VALID_EMPTY_PROJECTION.profile.academic,
          institutional_email: `${'a'.repeat(243)}@example.edu`,
        },
      },
    }).pass).toBe(false);
    expect(inspectNyay5Projection({
      ...VALID_EMPTY_PROJECTION,
      profile: {
        ...VALID_EMPTY_PROJECTION.profile,
        personal: {
          ...VALID_EMPTY_PROJECTION.profile.personal,
          first_name: '𐐀'.repeat(60),
        },
      },
    }).pass).toBe(true);
    for (const firstName of ['𐐀'.repeat(61), 'A-\u0301', 'A\nB']) {
      expect(inspectNyay5Projection({
        ...VALID_EMPTY_PROJECTION,
        profile: {
          ...VALID_EMPTY_PROJECTION.profile,
          personal: { ...VALID_EMPTY_PROJECTION.profile.personal, first_name: firstName },
        },
      }).pass).toBe(false);
    }
  });

  it('pins AUTH-07 to exact eight-key flow and nine-key success wires', async () => {
    const {
      inspectOtpFlowWire,
      inspectOtpVerificationWire,
      inspectRegistrationStartWire,
    } = await import('./nyay5-profile-browser-contract.mjs');
    const pending = {
      attempts_left: 5,
      destination_masked: '••••••0042',
      expires_in_seconds: 600,
      locked_for_seconds: 0,
      purpose: 'signup',
      resend_allowed: false,
      resend_in_seconds: 1,
      status: 'pending',
    };
    expect(inspectRegistrationStartWire({
      status: 'accepted',
      next: 'otp',
      expires_in_seconds: 600,
      resend_after_seconds: 1,
    }).pass).toBe(true);
    expect(inspectRegistrationStartWire({
      status: 'accepted',
      next: 'otp',
      expires_in_seconds: 600,
      resend_after_seconds: 1,
      destination_masked: '••••••0042',
    }).pass).toBe(false);
    expect(inspectOtpFlowWire(pending).pass).toBe(true);
    expect(inspectOtpFlowWire({ ...pending, onboarding: VALID_EMPTY_PROJECTION }).pass).toBe(false);
    expect(inspectOtpVerificationWire({
      attempts_left: null,
      destination_masked: null,
      expires_in_seconds: null,
      locked_for_seconds: null,
      onboarding: VALID_EMPTY_PROJECTION,
      purpose: 'signup',
      resend_allowed: false,
      resend_in_seconds: null,
      status: 'authenticated',
    }).pass).toBe(true);
    expect(inspectOtpVerificationWire({
      ...pending,
      status: 'authenticated',
      attempts_left: null,
      destination_masked: null,
      expires_in_seconds: null,
      locked_for_seconds: null,
      resend_in_seconds: null,
    }).pass).toBe(false);
  });

  it('requires real signup and login verification to land on S-07', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain('signupLanding === \'/s-07\'');
    expect(runner).toContain('loginLanding === \'/s-07\'');
    expect(runner).toContain('secondConflictStatus === 409');
    expect(runner).toContain(
      'const typedFailures = await typedFailureMatrixProbe(page, context, mobile, sessionActor)',
    );
    expect(runner).toContain('ceremonyPosts.length === 1');
    expect(runner).toContain('ceremonyStatus === 202');
    expect(runner).toContain("ceremonyBody?.institutional_email_status === 'pending'");
    expect(runner).toContain('ceremonySelectorCount === 0');
    expect(runner).toContain('ceremonyRetryStatus === 202');
    expect(runner).toContain('ceremonyRetryBody?.profile_version === ceremonyBody?.profile_version');
    const labelProbe = runner.indexOf('const interestsGoalLabelCount =');
    const interestsSubmit = runner.indexOf(
      "page.getByRole('button', { name: 'Finish setup' }).click()",
    );
    expect(labelProbe).toBeGreaterThan(-1);
    expect(labelProbe).toBeLessThan(interestsSubmit);
    expect(runner).toContain('controlsLabelled: interestsGoalLabelCount === 1');
  });

  it('requires every PROFILE-05 failure class to retain route and values', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const exactCases = [
      ['missing_context', 422],
      ['401', 401],
      ['403', 403],
      ['409', 409],
      ['422', 422],
      ['429', 429],
      ['500', 500],
      ['abort', null],
      ['timeout', null],
      ['network', null],
    ].map(([kind, status]) => ({
      kind,
      status,
      routeRetained: true,
      valuesRetained: true,
      errorRole: kind === '401' ? 'status' : 'alert',
      errorVisible: true,
      errorText: ({
        missing_context: 'Review the highlighted fields and try again.',
        401: 'Your unsaved profile draft was restored after you signed in again. Review it before saving.',
        403: 'This account is not permitted to change that profile section.',
        409: 'This profile changed in another tab. Review the latest values before saving again.',
        422: 'Review the highlighted fields and try again.',
        429: 'Too many requests. Wait a moment, then try again.',
        500: 'We could not confirm whether your changes were saved. Your page is unchanged; retry after checking the latest profile.',
        abort: 'We could not confirm whether your changes were saved. Your page is unchanged; retry after checking the latest profile.',
        timeout: 'We could not confirm whether your changes were saved. Your page is unchanged; retry after checking the latest profile.',
        network: 'We could not confirm whether your changes were saved. Your page is unchanged; retry after checking the latest profile.',
      })[kind],
      ...(kind === '401' ? {
        canonicalCode: 'authentication_required',
        pendingObserved: true,
        privateUnmounted: true,
        anonymousObserved: true,
        sameActorResolved: true,
        restoredSelectorCount: 1,
        profilePatchCount: 1,
        automaticRetryCount: 0,
        browserPersistenceClean: true,
      } : {}),
    }));
    expect(contract.inspectTypedFailureMatrix(exactCases)).toMatchObject({
      pass: true,
      exact: true,
      passed: 10,
    });
    for (let index = 0; index < exactCases.length; index += 1) {
      const mutant = exactCases.map((row) => ({ ...row }));
      mutant[index].valuesRetained = false;
      expect(contract.inspectTypedFailureMatrix(mutant).pass).toBe(false);
    }
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain("kind: 'missing_context'");
    expect(runner).toContain("kind: 'timeout'");
    expect(runner).toContain("kind: 'abort'");
    expect(runner).toContain("kind: 'network'");
    expect(runner).toContain('inspectTypedFailureMatrix');
    expect(runner).toContain("getByTestId('profile-reauth-draft-restored')");
    expect(runner).toContain('automaticRetryCount');
    expect(runner).toContain('sameActorResolved');
  });

  it('requires a real cross-realm exclusive cookie transition in Chromium', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const exact = {
      delayedPeerObserved: true,
      verifyRequestsBeforeDelayedPeer: 0,
      pendingSelectorCount: 1,
      privateMountedBeforeVerify: 0,
      verifyRequestsBeforeInflightRelease: 0,
      verifyRequests: 1,
      oldActorPatchCount: 1,
      oldActorAutomaticRetryCount: 0,
      postStartOldActorMutationRequests: 0,
      profilePostStartAttemptObserved: true,
      newPageSessionRequestsBeforeEnd: 0,
      newActorProjectionUnchanged: true,
      transitionMessagesExact: true,
      transitionMessagePrivateFindings: 0,
      missingPrimitivesUnavailable: true,
      missingPrimitivesPrivateRequests: 0,
      inaccessibleStorageUnavailable: true,
      peerNackVerifyRequests: 0,
      peerNackSessionCookieUnchanged: true,
      m01HolderCompletionControls: 2,
      m01AttackerCompletionControls: 2,
      m01ServerSettledStatus: 200,
      m01VerifyRequestsBeforeResponseRelease: 0,
      m01VerifyRequests: 1,
      m01CompletionRequests: 1,
      m01CommitExactlyOnce: true,
      m01FirstTargetCompleted: true,
      m01FirstTargetAttendanceRecorded: true,
      m01PostStartSecondTargetRequests: 0,
      m01PostStartAttemptObserved: true,
      m01PrivateControlsAfterTransitionStart: 0,
      m01PrivateUiUnmounted: true,
      m01SecondTargetUntouched: true,
    };
    expect(Object.keys(exact)).toHaveLength(33);
    expect(contract.inspectCrossRealmTransitionObservation(exact).pass).toBe(true);
    for (const field of Object.keys(exact)) {
      const mutant = structuredClone(exact);
      mutant[field] = typeof mutant[field] === 'boolean'
        ? !mutant[field] : (mutant[field] === 0 ? 1 : 0);
      expect(contract.inspectCrossRealmTransitionObservation(mutant).pass).toBe(false);
    }
    expect(contract.NYAY5_ACCEPTANCE_EXECUTION_MAP['AUTH-06']).toContain(
      'browser:cross_realm_auth_transition_barrier',
    );
    expect(contract.NYAY5_ACCEPTANCE_EXECUTION_MAP['AUTH-07']).toContain(
      'browser:cross_realm_auth_transition_barrier',
    );
    expect(contract.NYAY5_ACCEPTANCE_EXECUTION_MAP['PROFILE-05']).toContain(
      'browser:canonical_401_draft_handoff',
    );
    const runner = readFileSync(RUNNER, 'utf8');
    for (const seam of [
      'crossRealmAuthTransitionProbe',
      'canonical401DraftHandoffProbe',
      'nyayone.student.auth-transition.v2',
      'student-session-unavailable',
      'newPageSessionRequestsBeforeEnd',
      'postStartOldActorMutationRequests',
      'peerNackVerifyRequests',
      'readM01Fixture',
      'setTimeout(resolveDelay, 1_100)',
      "goto(`${WEB}/mentor/sessions`",
      "data-action=\"record-completion\"",
      'm01VerifyRequestsBeforeResponseRelease',
      'm01VerifyRequests',
      'm01PostStartSecondTargetRequests',
      'm01PostStartAttemptObserved',
      'profilePostStartAttemptObserved',
      'm01CommitExactlyOnce',
      'm01PrivateUiUnmounted',
      'm01SecondTargetUntouched',
    ]) {
      expect(runner).toContain(seam);
    }
    const crossRealmSource = runner.slice(
      runner.indexOf('async function crossRealmAuthTransitionProbe'),
      runner.indexOf('function canonical401DraftHandoffProbe'),
    );
    expect(crossRealmSource).not.toContain(
      'await context.request.post(`${API}/api/v1/auth/student/logout`',
    );
    const retireCookieIndex = crossRealmSource.indexOf(
      "await context.clearCookies({ name: 'nyayone_session' });",
    );
    const prepareLoginIndex = crossRealmSource.indexOf(
      'await prepareStudentLoginOtp(initiator, actorAMobile);',
    );
    const retireCookieOccurrences = crossRealmSource.match(
      /await context\.clearCookies\(\{ name: 'nyayone_session' \}\);/gu,
    ) ?? [];
    const secondRetireCookieIndex = crossRealmSource.indexOf(
      "await context.clearCookies({ name: 'nyayone_session' });",
      retireCookieIndex + 1,
    );
    const secondPrepareLoginIndex = crossRealmSource.indexOf(
      'await prepareStudentLoginOtp(initiator, actorBMobile);',
    );
    expect(retireCookieIndex).toBeGreaterThan(-1);
    expect(prepareLoginIndex).toBeGreaterThan(retireCookieIndex);
    expect(retireCookieOccurrences).toHaveLength(2);
    expect(secondRetireCookieIndex).toBeGreaterThan(prepareLoginIndex);
    expect(secondPrepareLoginIndex).toBeGreaterThan(secondRetireCookieIndex);

    const prepareLoginSource = runner.slice(
      runner.indexOf('async function prepareStudentLoginOtp'),
      runner.indexOf('async function installTransitionMessageProbe'),
    );
    expect(prepareLoginSource).toContain('startResponse.status() !== 202');
    expect(prepareLoginSource).toContain(
      "if (new URL(page.url()).pathname !== '/s-03')",
    );
    expect(prepareLoginSource).toContain("stateBody?.status !== 'pending'");
    expect(prepareLoginSource).toContain("stateBody?.purpose !== 'login'");
    expect(prepareLoginSource).toContain("cookie.name === 'nyayone_otp_flow'");
    expect(prepareLoginSource).toContain("cookie.name === 'nyayone_session'");
    expect(prepareLoginSource).toContain(
      "page.getByLabel('Six digit code').waitFor({ state: 'visible' })",
    );
    expect(crossRealmSource).toMatch(
      /recordBrowserExecution\(\s*'cross_realm_auth_transition_barrier',\s*inspected\.pass,\s*33,/u,
    );
  });

  it('rotates the prompt session only through the production auth ceremony', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const promptSource = runner.slice(
      runner.indexOf('async function promptAndRoutingProbe'),
      runner.indexOf('async function crossSectionConflictProbe'),
    );

    expect(promptSource).not.toContain('context.request.post(`${API}/api/v1/auth/student/logout`');
    expect(promptSource).not.toContain('loginStudent(context, mobile)');
    expect(promptSource).toContain('loginStudentThroughUi(rotatedPage, mobile)');
    const promptCookieRetirement = promptSource.indexOf(
      "await context.clearCookies({ name: 'nyayone_session' });",
    );
    expect(promptCookieRetirement).toBeGreaterThan(-1);
    expect(promptCookieRetirement)
      .toBeLessThan(promptSource.indexOf('loginStudentThroughUi(rotatedPage, mobile)'));
    expect(promptSource).toMatch(
      /await page\.waitForFunction\(\(\) => \(\s*document\.activeElement === document\.querySelector/u,
    );
    expect(promptSource).toContain('await rotatedPage.waitForURL(/\\/s-07$/u)');
    expect(promptSource).toContain("await rotatedDialog.waitFor({ state: 'visible' })");
    expect(promptSource).toMatch(
      /const dashboardCardLocator = page\.getByTestId\('profile-completion-card'\);\s*await dashboardCardLocator\.waitFor\(\{ state: 'visible' \}\);\s*const dashboardCard = await dashboardCardLocator\.count\(\) === 1;/u,
    );
    expect(promptSource).toMatch(
      /const profileCardLocator = page\.getByTestId\('profile-completion-card'\);\s*await profileCardLocator\.waitFor\(\{ state: 'visible' \}\);\s*const profileCard = await profileCardLocator\.count\(\) === 1;/u,
    );

    const minorSource = runner.slice(
      runner.indexOf('async function minorAndResponsiveProbe'),
      runner.indexOf('async function unicodeAndRegistrationProbe'),
    );
    expect(minorSource).not.toContain('context.request.post(`${API}/api/v1/auth/student/logout`');
    expect(minorSource).not.toContain('loginStudent(context, mobile)');
    expect(minorSource).toContain('loginStudentThroughUi(reloginPage, mobile)');
    const minorCookieRetirement = minorSource.indexOf(
      "await context.clearCookies({ name: 'nyayone_session' });",
    );
    expect(minorCookieRetirement).toBeGreaterThan(-1);
    expect(minorCookieRetirement)
      .toBeLessThan(minorSource.indexOf('loginStudentThroughUi(reloginPage, mobile)'));
    expect(minorSource).toMatch(
      /const reloadLimitedMessage = page\.getByText\(\s*'Disabled capabilities: community, sharing\.'[,]?\s*\);\s*await reloadLimitedMessage\.waitFor\(\{ state: 'visible' \}\);\s*const reloadLimited = await reloadLimitedMessage\.isVisible\(\);/u,
    );
    expect(minorSource).toMatch(
      /getByRole\('heading',\s*\{\s*name: 'Some features are still locked'/u,
    );

    const loginUiSource = runner.slice(
      runner.indexOf('async function loginStudentThroughUi'),
      runner.indexOf('async function prepareStudentLoginOtp'),
    );
    expect(loginUiSource).toContain(
      'const { startResponse } = await prepareStudentLoginOtp(page, mobile);',
    );
    expect(loginUiSource).toContain('const verifiedSessionResponsePromise');
    expect(loginUiSource).toContain("response.request().method() === 'GET'");
    expect(loginUiSource).toContain("url.pathname === '/api/v1/auth/student/session'");
    expect(loginUiSource).toContain('verifiedSessionResponse.finished()');
    expect(loginUiSource).toContain('verifiedSessionResponse');
  });

  it('exercises OTP normalization with a real clipboard paste event', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).not.toContain("signupOtpInput.fill('12a34 56')");
    expect(runner).toContain("clipboardData.setData('text', '12a34 56')");
    expect(runner).toContain("new ClipboardEvent('paste'");
    expect(runner).toContain("value === '123456'");
  });

  it('samples continuation typography only after authoritative headings settle', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const completeSource = runner.slice(
      runner.indexOf('async function completeProfileProbe'),
      runner.indexOf('async function promptAndRoutingProbe'),
    );
    const promptSource = runner.slice(
      runner.indexOf('async function promptAndRoutingProbe'),
      runner.indexOf('async function crossSectionConflictProbe'),
    );
    expect(completeSource).toMatch(
      /await page\.goto\(`\$\{WEB\}\/s-11`[^;]*;\s*await page\.getByRole\('heading', \{ name: 'What should find you\?', exact: true \}\)\.waitFor\(\{ state: 'visible' \}\);\s*await recordVisualContract\(page, 'S-11'\);/u,
    );
    expect(promptSource).toMatch(
      /await page\.goto\(`\$\{WEB\}\/s-17`[^;]*;\s*await page\.getByRole\('heading', \{ name: 'Your profile', exact: true \}\)\.waitFor\(\{ state: 'visible' \}\);\s*await recordVisualContract\(page, 'S-17'\);/u,
    );
  });

  it('waits for every visual screen to reach its asserted render-ready state', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const visualSource = runner.slice(
      runner.indexOf('async function recordVisualContract'),
      runner.indexOf('async function resetOtp'),
    );
    expect(visualSource).toContain(
      "await screen.locator('h1:visible,h2:visible').first().waitFor({ state: 'visible' });",
    );
    expect(visualSource).toContain('await page.evaluate(() => document.fonts.ready);');
  });

  it('scopes the Revision L heading and labelled-lockup census to the seven approved screens', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    expect(stringArrayConstant(runner, 'REVISION_L_VISUAL_SCREEN_IDS')).toEqual([
      'S-03', 'S-04', 'S-05', 'S-07', 'S-08', 'S-09', 'S-10',
    ]);
    expect(stringArrayConstant(runner, 'REVISION_L_HEADING_STACK')).toEqual([
      'aptos', 'calibri', 'nyayone revision l heading', 'system-ui', 'sans-serif',
    ]);
    expect(stringArrayConstant(runner, 'LEGACY_CARLITO_HEADING_STACK')).toEqual([
      'aptos', 'calibri', 'carlito', 'system-ui', 'sans-serif',
    ]);
    expect(stringArrayConstant(runner, 'S06_R2_HEADING_STACK')).toEqual([
      'nyayone revision l heading', 'aptos', 'calibri', 'carlito', 'system-ui', 'sans-serif',
    ]);

    const visualSource = runner.slice(
      runner.indexOf('async function recordVisualContract'),
      runner.indexOf('async function resetOtp'),
    );
    expect(visualSource).toContain(
      'revisionLExpected: REVISION_L_VISUAL_SCREEN_IDS.includes(screenId)',
    );
    expect(visualSource).toContain(
      "const isRevisionLLockup = icon.classList.contains('v321-lockup');",
    );
    expect(visualSource).toContain(
      "s06R2Expected: screenId === 'S-06'",
    );
    expect(visualSource).toMatch(
      /if \(isRevisionLLockup\) return \(contract\.revisionLExpected \|\| contract\.s06R2Expected\)\s*&& exactRevisionLLockup\(icon\);/u,
    );
    for (const exactLockupClause of [
      "icon.getAttribute('class') === 'v321-lockup'",
      "icon.getAttribute('role') === 'img'",
      "icon.getAttribute('aria-label') === 'NyayOne — Legal, on the record'",
      "!icon.hasAttribute('aria-hidden')",
      'icon.tabIndex < 0',
    ]) {
      expect(visualSource).toContain(exactLockupClause);
    }
    expect(visualSource).toMatch(
      /icon\.getAttribute\('aria-hidden'\) === 'true'[\s\S]*icon\.tabIndex < 0[\s\S]*icon\.closest\('button,a'\)/u,
    );
  });

  it('measures the approved S-06 R2 heading stack and exact labelled lockup', async () => {
    const observed = await visualCensus();
    expect(observed).toMatchObject({ headingCount: 1, typographyExact: true,
      iconCount: 1, iconsExact: true, legacyBrandVisible: false });
    expect(observed.readiness[0].requireRevisionLLockup).toBe(true);
  });

  it('measures only the exact nonfocusable S-06 decorative hidden parent', async () => {
    expect(await visualCensus({ decoration: true })).toMatchObject({
      headingCount: 1, typographyExact: true, iconCount: 2, iconsExact: true,
    });
  });

  it.each([
    'Aptos, Calibri, Carlito, system-ui, sans-serif',
    'Aptos, Calibri, "NyayOne Revision L Heading", system-ui, sans-serif',
    '"NyayOne Revision L Heading", Aptos, Calibri, system-ui, sans-serif',
    'sans-serif',
  ])('refuses an incorrect S-06 heading stack: %s', async family => {
    expect((await visualCensus({ family })).typographyExact).toBe(false);
  });

  it.each([
    { 'aria-label': 'Different logo' }, { role: 'presentation' },
    { class: 'v321-lockup other' }, { 'aria-hidden': 'true' }, { tabindex: '0' },
  ])('refuses a changed or focusable S-06 labelled lockup: %j', async logo => {
    expect((await visualCensus({ logo })).iconsExact).toBe(false);
  });

  it.each([
    [{ 'aria-hidden': 'false' }, {}], [{ 'aria-hidden': null }, {}],
    [{ class: 'different-ring' }, {}], [{ class: 's06-r2__ring extra' }, {}],
    [{ tabindex: '0' }, {}], [{}, { tabindex: '0' }],
    [{}, { focusable: 'true' }], [{}, { 'aria-hidden': 'false' }],
  ])('refuses an unhidden, changed, or focusable S-06 decoration: %j / %j',
    async (decorationParent, decorationIcon) => {
      expect((await visualCensus({ decoration: true, decorationParent, decorationIcon })).iconsExact).toBe(false);
    });

  it.each(['S-03', 'S-04', 'S-05', 'S-07', 'S-08', 'S-09', 'S-10', 'S-17'])(
    'never grants the S-06 R2 stack or inherited decoration rule to %s', async screenId => {
      const observed = await visualCensus({ screenId, decoration: true });
      expect(observed.typographyExact).toBe(false);
      expect(observed.iconsExact).toBe(false);
    });

  it.each(['S-03', 'S-04', 'S-05', 'S-07', 'S-08', 'S-09', 'S-10'])(
    'retains the exact existing Revision L stack and lockup on %s', async screenId => {
      expect(await visualCensus({ screenId,
        family: 'Aptos, Calibri, "NyayOne Revision L Heading", system-ui, sans-serif',
      })).toMatchObject({ typographyExact: true, iconsExact: true });
    });

  it('retains the legacy font rule and rejects branded lockups outside approved screens', async () => {
    expect(await visualCensus({ screenId: 'S-17',
      family: 'Aptos, Calibri, Carlito, system-ui, sans-serif',
    })).toMatchObject({ typographyExact: true, iconsExact: false });
  });

  it.each([
    'Aptos, Calibri, Carlito, system-ui, sans-serif',
    '"NyayOne Revision L Heading", Aptos, Calibri, system-ui, sans-serif',
    'sans-serif',
  ])('rejects an incorrect S-10 heading stack: %s', async family => {
    expect((await visualCensus({ screenId: 'S-10', family })).typographyExact).toBe(false);
  });

  it.each([
    { 'aria-label': 'Different logo' }, { role: 'presentation' },
    { class: 'v321-lockup other' }, { 'aria-hidden': 'true' }, { tabindex: '0' },
  ])('rejects a changed or focusable S-10 labelled lockup: %j', async logo => {
    expect((await visualCensus({ screenId: 'S-10',
      family: 'Aptos, Calibri, "NyayOne Revision L Heading", system-ui, sans-serif', logo,
    })).iconsExact).toBe(false);
  });

  it.each([
    'Aptos, Calibri, Carlito, system-ui, sans-serif',
    '"NyayOne Revision L Heading", Aptos, Calibri, system-ui, sans-serif',
    'sans-serif',
  ])('rejects an incorrect S-07 heading stack: %s', async family => {
    expect((await visualCensus({ screenId: 'S-07', family })).typographyExact).toBe(false);
  });

  it.each([
    { 'aria-label': 'Different logo' }, { role: 'presentation' },
    { class: 'v321-lockup other' }, { 'aria-hidden': 'true' }, { tabindex: '0' },
  ])('rejects a changed or focusable S-07 labelled lockup: %j', async logo => {
    expect((await visualCensus({ screenId: 'S-07',
      family: 'Aptos, Calibri, "NyayOne Revision L Heading", system-ui, sans-serif', logo,
    })).iconsExact).toBe(false);
  });

  it('observes both S-07 focus wraps and the entire approved dialog control order', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const prompt = runner.slice(runner.indexOf('async function promptAndRoutingProbe'),
      runner.indexOf('async function crossSectionConflictProbe'));
    expect(prompt).toMatch(/const shiftWrapped = await dialog\.getByRole\('button', \{ name: 'Sign out', exact: true \}\)/u);
    expect(prompt).toMatch(/const tabWrapped = await dialog\.getByRole\('button', \{ name: 'Close profile prompt', exact: true \}\)/u);
    expect(prompt).toContain("const dialogControlOrder = ['Complete Profile', 'Maybe Later', 'Sign out', 'Close profile prompt'];");
    expect(prompt).toMatch(/for \(const name of dialogControlOrder\) \{\s*await page\.keyboard\.press\('Tab'\);/u);
    expect(prompt).toContain("observe('dialog_focus_and_inert_contract', dialogObservation.pass && dialogTraversal.every(Boolean)");
    expect(prompt).toContain('focusChecks: 4 + dialogTraversal.length');
  });

  it('builds failed-run stdout diagnostics from static privacy-safe inventories only', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const diagnostics = contract.summarizeNyay5BrowserFailure({
      rows: EXPECTED_ASSERTIONS.map((name) => ({ name, pass: name !== 'runtime_chromium' })),
      executions: [],
      acceptanceExecutionCoverage: {
        mapped: 61, missing: 2, skipped: 0, unknown: 0, unique: true,
      },
      failureClass: 'TimeoutError2',
      failureStage: 'complete_profile',
      failureCode: 'RUNTIME_ASSERTION_FAILED',
      mobile: '9876543210',
      session_token: 'opaque-private-session-token',
    });

    expect(diagnostics.failedAssertions).toEqual(['runtime_chromium']);
    expect(diagnostics.invalidExecutionIds.length).toBeGreaterThan(0);
    expect(diagnostics).toMatchObject({
      failureClass: 'TimeoutError2',
      failureStage: 'complete_profile',
      failureCode: 'RUNTIME_ASSERTION_FAILED',
      coverage: { mapped: 61, missing: 2, skipped: 0, unknown: 0, unique: true },
    });
    expect(contract.scanNyay5Evidence(diagnostics)).toEqual([]);
    expect(JSON.stringify(diagnostics)).not.toContain('9876543210');
    expect(JSON.stringify(diagnostics)).not.toContain('opaque-private-session-token');

    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain('summarizeNyay5BrowserFailure');
    expect(runner).toContain("diagnostics: report.status === 'FAIL'");
  });

  it('captures selector evidence while the exact controls are still mounted', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const completeSource = runner.slice(
      runner.indexOf('async function completeProfileProbe'),
      runner.indexOf('async function promptAndRoutingProbe'),
    );
    expect(completeSource).toMatch(
      /const clientErrorAccessible = [\s\S]*?;\s*const validationSelectorCount = await errorSummary\.count\(\)\s*\+ await page\.locator\('#profile-personal-city'\)\.count\(\);\s*await fillPersonal/u,
    );
    expect(completeSource).toMatch(
      /const ceremonyButton = page\.getByRole\('button', \{ name: 'Request verification review' \}\);\s*await ceremonyButton\.waitFor\(\);\s*const ceremonyActionSelectorCount = await ceremonyButton\.count\(\);/u,
    );
    expect(completeSource.match(/const validationSelectorCount =/gu)).toHaveLength(1);
    expect(completeSource.match(/const ceremonyActionSelectorCount =/gu)).toHaveLength(1);
  });

  it('settles canonical student-session and profile responses before sampling S-10', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const completeSource = runner.slice(
      runner.indexOf('async function completeProfileProbe'),
      runner.indexOf('async function promptAndRoutingProbe'),
    );
    const sessionObserver = completeSource.indexOf('const s10SessionResponsePromise');
    const profileObserver = completeSource.indexOf('const s10ProfileResponsePromise');
    const navigation = completeSource.indexOf("page.goto(`${WEB}/s-10?section=personal`");
    const settlement = completeSource.indexOf('await Promise.all([');
    const cityMount = completeSource.indexOf("page.locator('#profile-personal-city').waitFor()");

    expect(sessionObserver).toBeGreaterThan(-1);
    expect(profileObserver).toBeGreaterThan(-1);
    expect(sessionObserver).toBeLessThan(navigation);
    expect(profileObserver).toBeLessThan(navigation);
    expect(settlement).toBeGreaterThan(navigation);
    expect(cityMount).toBeGreaterThan(settlement);
    expect(completeSource).toContain("'/api/v1/auth/student/session'");
    expect(completeSource).toContain("'/api/v1/student/profile'");
    expect(completeSource).toContain('s10SessionResponse.finished()');
    expect(completeSource).toContain('s10ProfileResponse.finished()');
    expect(completeSource).toContain('s10SessionResponse.status() !== 200');
    expect(completeSource).toContain('s10ProfileResponse.status() !== 200');
    expect(completeSource).toContain('s10SessionBody?.authenticated !== true');
    expect(completeSource).toContain("!s10SessionBody?.actor?.roles?.includes('student')");
    expect(completeSource).toContain('s10SessionBody?.actor?.sub !== sessionActor?.sub');
    for (const stage of [
      'complete_profile_s10_navigation',
      'complete_profile_s10_authority',
      'complete_profile_s10_mount',
      'complete_profile_visual_contract',
      'complete_profile_initial_projection',
      'complete_profile_client_validation',
      'complete_profile_typed_failure_matrix',
      'complete_profile_personal_write',
      'complete_profile_resume_projection',
      'complete_profile_academic_write',
      'complete_profile_verification_ceremony',
      'complete_profile_dashboard_return',
      'complete_profile_interests_write',
      'complete_profile_final_projection',
    ]) {
      expect(completeSource).toContain(`failureStage = '${stage}'`);
    }
    expect(completeSource).not.toContain('waitForTimeout');
  });

  it('requires directional, ordered traces for exactly two successful auth transitions', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const first = 'transition-first-1';
    const second = 'transition-second-2';
    const message = (kind, sender, transition) => ({
      version: 2, kind, sender, transition,
    });
    const trace = (...events) => events.map(([direction, wire], index) => ({
      direction, sequence: index + 1, message: wire,
    }));
    const ceremony = (transition, suffix, late) => {
      const initiator = `realm-init-${suffix}`;
      const peerOne = `realm-peer-${suffix}1`;
      const peerTwo = `realm-peer-${suffix}2`;
      return {
        initiator: trace(
          ['send', message('start', initiator, transition)],
          ['receive', message('ack', peerOne, transition)],
          ['receive', message('ack', peerTwo, transition)],
          ['send', message('end', initiator, transition)],
        ),
        peers: [
          trace(
            ['receive', message('start', initiator, transition)],
            ['send', message('ack', peerOne, transition)],
            ['receive', message('ack', peerTwo, transition)],
            ['receive', message('end', initiator, transition)],
          ),
          trace(
            ['receive', message('start', initiator, transition)],
            ['send', message('ack', peerTwo, transition)],
            ['receive', message('ack', peerOne, transition)],
            ['receive', message('end', initiator, transition)],
          ),
        ],
        lateRealm: late
          ? trace(['receive', message('end', initiator, transition)])
          : [],
      };
    };
    const exact = { ceremonies: [ceremony(first, '1', false), ceremony(second, '2', true)] };
    expect(contract.inspectTransitionProtocolTrace(exact).pass).toBe(true);

    const resequence = (traceRows) => {
      traceRows.forEach((row, index) => { row.sequence = index + 1; });
    };
    const mutations = [
      (value) => {
        const rows = value.ceremonies[0].initiator;
        [rows[0], rows[3]] = [rows[3], rows[0]];
        resequence(rows);
      },
      (value) => { value.ceremonies[0].initiator[1].message.transition = second; },
      (value) => {
        const rows = value.ceremonies[0].initiator;
        rows.splice(1, 0, structuredClone(rows[0]));
        resequence(rows);
      },
      (value) => { value.ceremonies[0].peers[0][1].message.kind = 'nack'; },
      (value) => {
        const rows = value.ceremonies[0].initiator;
        rows.splice(4, 0, structuredClone(rows[3]));
        resequence(rows);
      },
      (value) => {
        const rows = value.ceremonies[0].initiator;
        rows.splice(2, 0, structuredClone(rows[1]));
        resequence(rows);
      },
      (value) => { value.ceremonies[0].initiator[1].message.sender = 'realm-ghost-9'; },
      (value) => {
        const rows = value.ceremonies[0].peers[0];
        rows.splice(1, 0, structuredClone(rows[0]));
        resequence(rows);
      },
      (value) => { value.ceremonies[1] = structuredClone(value.ceremonies[0]); },
      (value) => { value.ceremonies.pop(); },
    ];
    for (const mutate of mutations) {
      const mutant = structuredClone(exact);
      mutate(mutant);
      expect(contract.inspectTransitionProtocolTrace(mutant).pass).toBe(false);
    }
  });

  it('exercises every browser-storage boundary surface with no private workflow state', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    expect(contract.NYAY5_REQUIRED_STORAGE_SURFACES).toEqual([
      'auth',
      'profile',
      'prompt',
      'rotated-session',
      'stale-tab',
      'uncertain-write',
      'limited-access',
      'registration',
      's18-settings',
      's19-privacy-export',
      's20-internship-browse',
      's21-internship-detail',
      's22-internship-apply',
      's23-internship-confirm',
      's24-internship-tracker',
      's65-clinical-export',
      's86-private-report-draft',
      's93-server-reminders',
    ]);
    const runner = readFileSync(RUNNER, 'utf8');
    const exactCalls = {
      auth: "recordStorage(page, 'auth')",
      profile: "recordStorage(page, 'profile')",
      prompt: "recordStorage(page, 'prompt')",
      'rotated-session': "recordStorage(rotatedPage, 'rotated-session')",
      'stale-tab': "recordStorage(stalePage, 'stale-tab')",
      'uncertain-write': "recordStorage(uncertainPage, 'uncertain-write')",
      'limited-access': "recordStorage(page, 'limited-access')",
      registration: "recordStorage(registrationPage, 'registration')",
      's18-settings': "recordStorage(page, 's18-settings')",
      's19-privacy-export': "recordStorage(page, 's19-privacy-export')",
      's20-internship-browse': "recordStorage(page, 's20-internship-browse')",
      's21-internship-detail': "recordStorage(page, 's21-internship-detail')",
      's22-internship-apply': "recordStorage(page, 's22-internship-apply')",
      's23-internship-confirm': "recordStorage(page, 's23-internship-confirm')",
      's24-internship-tracker': "recordStorage(page, 's24-internship-tracker')",
      's65-clinical-export': "recordStorage(page, 's65-clinical-export')",
      's86-private-report-draft': "recordStorage(page, 's86-private-report-draft')",
      's93-server-reminders': "recordStorage(page, 's93-server-reminders')",
    };
    expect(Object.keys(exactCalls)).toEqual(contract.NYAY5_REQUIRED_STORAGE_SURFACES);
    for (const sourceCall of Object.values(exactCalls)) {
      expect(runner).toContain(sourceCall);
    }
    for (const stage of [
      'storage_provision',
      'storage_s18',
      'storage_s19_export',
      'storage_s20',
      'storage_s21',
      'storage_s22',
      'storage_s23',
      'storage_s24',
      'storage_s65',
      'storage_s86',
      'storage_s93',
    ]) {
      expect(runner).toContain(`failureStage = '${stage}'`);
    }
    expect(runner).toContain(
      "locator('details.v34c-mobile-disclosure').filter({ hasText: 'Data rights' })",
    );
    expect(runner).toContain("const dataRightsSummary = dataRightsDisclosure.locator('summary');");
    expect(runner).not.toContain("getByText('Data rights', { exact: true }).click()");
    expect(runner).toContain("getByRole('button', { name: 'Export' })");
    expect(runner).toContain("getByRole('button', { name: 'Save private draft' })");
  });

  it('emits null failure diagnostics for every successful final report', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const successfulCompletionReset = [
      '    failureStage = null;',
      '  } catch (error) {',
    ].join('\n');
    const successfulReportInvariant = [
      '  const successfulReport = summary.overallPass',
      '    && failureClass === null',
      '    && failureStage === null',
      '    && failureCode === null;',
    ].join('\n');
    const reportSource = runner.slice(
      runner.indexOf('  const report = {'),
      runner.indexOf('  const finalFindings = scanNyay5Evidence(report);'),
    );

    expect(runner).toContain(successfulCompletionReset);
    expect(runner).toContain(successfulReportInvariant);
    expect(reportSource).toContain("status: successfulReport ? 'PASS' : 'FAIL'");
    expect(reportSource).toMatch(/failureClass,\s*failureStage,\s*failureCode,/u);
  });

  it('kills an unconditional S-19 disclosure toggle before the privacy export', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const storageProbeStart = runner.indexOf('async function extendedStorageBoundaryProbe');
    const storageProbe = runner.slice(
      storageProbeStart,
      runner.indexOf('async function run()', storageProbeStart),
    );
    const guardedOpen = [
      "  if ((await dataRightsDisclosure.getAttribute('open')) === null) {",
      "    await dataRightsSummary.waitFor({ state: 'visible' });",
      '    await dataRightsSummary.click();',
      '  }',
    ].join('\n');
    const guardedDisclosurePasses = (source) => (
      source.includes(guardedOpen)
      && (source.match(/await dataRightsSummary\.click\(\);/gu) ?? []).length === 1
      && !source.includes("click({ force: true })")
      && !source.includes('dataRightsDisclosure.evaluate(')
    );

    expect(guardedDisclosurePasses(storageProbe)).toBe(true);
    const unconditionalToggleMutant = storageProbe.replace(
      guardedOpen,
      '  await dataRightsSummary.click();',
    );
    expect(unconditionalToggleMutant).not.toBe(storageProbe);
    expect(guardedDisclosurePasses(unconditionalToggleMutant)).toBe(false);
  });

  it('plants an owned legacy key before each synthesized cleanup failure', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const peerFailureProbe = runner.slice(
      runner.indexOf('if (peer) {'),
      runner.indexOf('failureStage = `cross_realm_${mode}_otp`;'),
    );
    const localFailureProbe = runner.slice(
      runner.indexOf("if (mode === 'local-cleanup') {"),
      runner.indexOf('const beforeCookies ='),
    );
    const localOwnedSeed = [
      "localStorage.setItem('legalsaathi.student.profile.v1',",
      "        'synthetic-cleanup-denial-canary');",
    ].join('\n');
    const peerOwnedSeed = [
      "sessionStorage.setItem('legalsaathi.student.registration.v2',",
      "        'synthetic-peer-cleanup-denial-canary');",
    ].join('\n');
    const denial = 'Storage.prototype.removeItem = () => {';
    const exactFixture = (source, ownedSeed) => (
      source.includes(ownedSeed)
      && source.includes(denial)
      && source.indexOf(ownedSeed) < source.indexOf(denial)
      && source.indexOf(ownedSeed) === source.lastIndexOf(ownedSeed)
    );

    expect(exactFixture(localFailureProbe, localOwnedSeed)).toBe(true);
    expect(exactFixture(peerFailureProbe, peerOwnedSeed)).toBe(true);
    for (const [source, ownedSeed] of [
      [localFailureProbe, localOwnedSeed],
      [peerFailureProbe, peerOwnedSeed],
    ]) {
      const missingOwnedKeyMutant = source.replace(ownedSeed, '');
      expect(missingOwnedKeyMutant).not.toBe(source);
      expect(exactFixture(missingOwnedKeyMutant, ownedSeed)).toBe(false);
    }
  });

  it('requires failed auth-transition cleanup to leave S-05 through the safe entry route', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const cleanupProbe = runner.slice(
      runner.indexOf('async function transitionCleanupFailureProbe'),
      runner.indexOf('async function crossRealmAuthTransitionProbe'),
    );
    expect(cleanupProbe).not.toContain("getByRole('alert').filter(");
    expect(cleanupProbe).toContain('await initiator.waitForURL(/\\/s-03$/u);');
    expect(cleanupProbe).toContain("initiator.getByLabel('Six digit code').count()");
    expect(cleanupProbe).toMatch(
      /initiator\s*\.getByRole\('button', \{ name: 'Verify and continue', exact: true \}\)\.count\(\)/u,
    );
    expect(cleanupProbe).toContain("throw new Error('NYAY5_FAILED_TRANSITION_OTP_CONTROLS_PRESENT')");
  });

  it('pins the sole current device preference and rejects every retired survivor', async () => {
    const { inspectBrowserPersistence } = await import(
      './nyay5-profile-browser-contract.mjs'
    );
    const base = {
      origin: 'http://localhost:1190',
      localStorageKeys: ['nyayone.theme.v1'],
      localStorageEntries: [
        ['nyayone.theme.v1', 'dark'],
      ],
      sessionStorageKeys: [],
      cacheInventory: [{
        name: 'nyayone-shell-v1',
        entries: [{
          pathname: '/index.html', query: '', method: 'GET',
          credentials: 'same-origin', authorization: false, responseStatus: 200,
        }],
      }],
      serviceWorker: {
        supported: true, controlled: true, registrations: 1,
        scriptPathnames: ['/sw.js'], productionAssets: true, disableFlagAbsent: true,
      },
      privacyInstrumentation: {
        installed: true, historyCallsObserved: 0,
        transientHistoryPrivateDetected: false, globalsScanned: 0,
        globalPrivateDetected: false, windowNamePrivateDetected: false,
        historyStatePrivateDetected: false,
      },
      indexedDatabases: [], javascriptCookieNames: [], deterministicGlobalKeys: [],
      historyUrls: ['http://localhost:1190/s-18'],
    };
    expect(inspectBrowserPersistence(base)).toMatchObject({
      pass: true,
      localValueContractExact: true,
    });
    for (const [key, unsafe] of [
      ['nyayone.theme.v1', 'system'],
      ['nyayone.theme.v1', 'Bearer synthetic-private-credential'],
    ]) {
      const mutant = structuredClone(base);
      mutant.localStorageEntries.find((entry) => entry[0] === key)[1] = unsafe;
      expect(inspectBrowserPersistence(mutant).pass).toBe(false);
    }
    for (const [key, value] of [
      ['ls-theme', 'dark'],
      ['ls-onboarding-seen', 'seen'],
      ['ls-reviewer', '1'],
      ['ls-locale', 'en-IN'],
    ]) {
      const mutant = structuredClone(base);
      mutant.localStorageKeys.push(key);
      mutant.localStorageEntries.push([key, value]);
      expect(inspectBrowserPersistence(mutant).pass).toBe(false);
    }
    expect(inspectBrowserPersistence({
      ...base,
      cacheInventory: [
        ...base.cacheInventory,
        { name: 'ls-shell-v1', entries: [] },
      ],
    }).pass).toBe(false);
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain("localStorage.setItem('ls-theme', 'dark')");
    expect(runner).toContain("localStorage.setItem('ls-onboarding-seen', 'seen')");
    expect(runner).toContain("localStorage.setItem('ls-reviewer', '1')");
    expect(runner).toContain("localStorage.setItem('ls-locale', 'en-IN')");
    expect(runner).toContain("caches.open('ls-shell-v1')");
    expect(runner).toContain("localStorage.getItem('nyayone.theme.v1') === 'dark'");
    expect(runner).toContain("!cacheNames.includes('ls-shell-v1')");
  });

  it('executes REG-05 through both the real UI and canonical backend corpus', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const corpus = JSON.parse(readFileSync(
      resolve(ROOT, '../contracts/unicode-legal-name-v1.json'), 'utf8',
    ));
    expect(corpus.cases).toHaveLength(24);
    const rows = corpus.cases.map((testCase) => ({
      id: testCase.id,
      valid: testCase.valid,
      ui: testCase.valid
        ? {
            patchCount: 1, status: 200, normalizedExact: true,
            projectionExact: true, routeAdvanced: true,
          }
        : testCase.id === 'newline' ? {
            patchCount: 0, status: null, normalizedExact: false,
            projectionExact: false, routeRetained: true, valueRetained: false,
            errorRole: null, errorVisible: false, platformRejected: true,
          }
        : {
            patchCount: 0, status: null, normalizedExact: false,
            projectionExact: false, routeRetained: true, valueRetained: true,
            errorRole: 'alert', errorVisible: true,
          },
      backend: testCase.valid
        ? { status: 200, normalizedExact: true, projectionExact: true, zeroMutation: false }
        : { status: 422, normalizedExact: false, projectionExact: false, zeroMutation: true },
    }));
    expect(contract.inspectLegalNameCorpusObservation(rows, corpus.cases)).toMatchObject({
      pass: true, exact: true, passed: 24, uiPassed: 24, backendPassed: 24,
    });
    for (const id of [
      'decomposed_accent', 'punctuation_only', 'tab', 'newline',
      'supplementary_letter_60', 'supplementary_letter_61',
    ]) {
      const mutant = structuredClone(rows);
      const row = mutant.find((entry) => entry.id === id);
      if (row.valid) row.ui.normalizedExact = false;
      else if (id === 'newline') row.ui.platformRejected = false;
      else row.ui.patchCount = 1;
      expect(contract.inspectLegalNameCorpusObservation(mutant, corpus.cases).pass).toBe(false);
    }
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain('firstNameInput.fill(candidate)');
    expect(runner).toContain('const presentedCandidate = await firstNameInput.inputValue()');
    expect(runner).toContain('inspectLegalNameCorpusObservation(corpusRows, corpus.cases)');
    expect(runner).toContain('backendZeroMutation');
    expect(runner).toContain('platformRejected');
    expect(runner).toMatch(
      /provisionStudent\(\s*browser, \{ firstName: 'Storage', signupSessionOnly: true \}/u,
    );
    expect(runner).toContain('if (signupSessionOnly)');
  });

  it('binds ROUTE-03 to an exact real S-15 back click', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    expect(contract.NYAY5_ACCEPTANCE_EXECUTION_MAP['ROUTE-03']).toEqual([
      'browser:s15_back_to_dashboard_exact',
    ]);
    expect(contract.NYAY5_SELECTOR_EXECUTION_IDS).toContain(
      'browser:s15_back_to_dashboard_exact',
    );
    const runner = readFileSync(RUNNER, 'utf8');
    expect(runner).toContain("getByRole('button', { name: 'Back to dashboard', exact: true })");
    expect(runner).toContain("recordBrowserExecution(\n      's15_back_to_dashboard_exact'");
    expect(runner).toContain("s15BackUrl.search === ''");
    expect(runner).toContain("s15BackUrl.hash === ''");
  });

  it('compares registration enumeration with the actual safe four-key wire', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    const body = {
      status: 'accepted',
      next: 'otp',
      expires_in_seconds: 600,
      resend_after_seconds: 1,
    };
    const wire = {
      status: 202,
      body,
      headerClass: 'uniform',
      cookieClass: 'uniform',
    };
    expect(contract.inspectRegistrationEnumerationObservation({
      known: structuredClone(wire),
      unknown: structuredClone(wire),
    }).pass).toBe(true);
    expect(contract.inspectRegistrationEnumerationObservation({
      known: { ...structuredClone(wire), body: { ...body, status: 'account_exists' } },
      unknown: structuredClone(wire),
    }).pass).toBe(false);
  });

  it('gives every direct profile-mutation fixture a fresh NYAY-9 idempotency key', () => {
    const runner = readFileSync(RUNNER, 'utf8');

    expect(runner).toContain('function profileFixtureIdempotencyKey()');
    expect(runner).toContain('rememberPrivate(key);');
    expect(
      runner.match(/'Idempotency-Key': profileFixtureIdempotencyKey\(\)/gu),
    ).toHaveLength(3);
  });

  it('uses the approved S-04 Send Code and S-08 Create Account names without changing assertions', () => {
    const inventory = [
      ['nyay5-profile-browser.mjs', 2, 4],
      ['nyay18-browser-namespace.mjs', 1, 0],
      ['v34-s01-s10-e2e.mjs', 2, 2],
      ['nyay12-email-identity-browser.mjs', 2, 0],
      ['nyay19-auth-lifecycle-browser.mjs', 1, 0],
    ];
    for (const [file, signInCount, registrationCount] of inventory) {
      const source = readFileSync(resolve(ROOT, 'scripts', file), 'utf8');
      expect(source.match(/getByRole\('button', \{ name: 'Send Code', exact: true \}\)/gu) ?? [], file)
        .toHaveLength(signInCount);
      expect(source.match(/getByRole\('button', \{ name: 'Create Account'/gu) ?? [], file)
        .toHaveLength(registrationCount);
    }
  });

  it('fails closed when S-04 legal notices gain a link, button or tab stop', () => {
    const runner = readFileSync(RUNNER, 'utf8');
    const start = runner.indexOf("if (path === '/s-04')");
    const end = runner.indexOf("const bodyText = await page.locator('body').innerText();", start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const signIn = runner.slice(start, end);
    expect(signIn).toContain("['Privacy Notice', 'Terms', 'Accessibility']");
    expect(signIn).toContain("'a, button, [role=\"link\"], [role=\"button\"], [tabindex]'");
    expect(signIn).toContain('footer.querySelectorAll(interactive).length === 0');
    expect(signIn).toContain("if (!legalTextInert) throw new Error('NYAY83_S04_LEGAL_TEXT_INTERACTIVE')");
  });

  it('uses the approved mobile-field names on S-04, S-06 and S-08', () => {
    const runner = readFileSync(resolve(ROOT, 'scripts/registration-e2e.mjs'), 'utf8');
    const start = runner.indexOf("await page.waitForURL('**/s-04');");
    const end = runner.indexOf('// Responsive/theme and icon-tooltip contract matrix.', start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    expect(runner.slice(start, end)).toContain("getByLabel('Mobile Number', { exact: true }).fill('')");
    const registration = runner.slice(runner.indexOf('async function fillBase'), runner.indexOf('// Explicit negative/boundary cases.'));
    expect(registration.match(/getByLabel\('Mobile Number', \{ exact: true \}\)/gu)).toHaveLength(1);
    expect(runner.match(/getByLabel\('Registered mobile number', \{ exact: true \}\)/gu)).toHaveLength(1);
  });

  it('kills exactly one deterministic perturbation for every named mutant', async () => {
    const contract = await import('./nyay5-profile-browser-contract.mjs');
    expect(contract.NYAY5_SEEDED_MUTANT_INVENTORY).toEqual(EXPECTED_MUTANTS);
    const result = contract.seededNyay5MutantResults();
    expect(result.rows.map((row) => row.name)).toEqual(EXPECTED_MUTANTS);
    expect(result.rows.every((row) => row.killed === true)).toBe(true);
    expect(result).toMatchObject({ named: 46, killed: 46, allKilled: true });
    expect(contract.seededNyay5MutantsAreKilled()).toBe(true);
  });
});

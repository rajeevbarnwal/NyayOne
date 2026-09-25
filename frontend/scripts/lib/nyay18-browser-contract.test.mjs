import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  NYAY18_ASSERTION_INVENTORY,
  NYAY18_LEGACY_CACHE_PREFIXES,
  NYAY18_LEGACY_LOCAL_EXACT_KEYS,
  NYAY18_LEGACY_LOCAL_PREFIXES,
  NYAY18_LEGACY_SESSION_EXACT_KEYS,
  NYAY18_LEADING_CANDIDATE_KEYS,
  NYAY18_LEADING_UNRELATED_KEYS,
  NYAY18_LEADING_TARGET_KEYS,
  NYAY18_PLANTED_MUTANT_NAMES,
  NYAY18_RETIRED_CURRENT_CACHE,
  buildNyay18LeadingCandidateEntries,
  buildNyay18LeadingTargetKeys,
  inspectNyay18Evidence,
  makeValidNyay18EvidenceFixture,
  runNyay18ContractSelfTest,
} from './nyay18-browser-contract.mjs';

const FRONTEND = resolve(import.meta.dirname, '../..');
const RUNNER = resolve(FRONTEND, 'scripts/nyay18-browser-namespace.mjs');
const PREVIEW = resolve(FRONTEND, 'scripts/nyay18-preview-server.mjs');
const PACKAGE = resolve(FRONTEND, 'package.json');
const ORCHESTRATOR = resolve(FRONTEND, '../scripts/nyay18_browser_namespace_gate.sh');

const EXPECTED_ASSERTIONS = [
  'runtime_chromium',
  'required_environment_exact',
  'fresh_profiles_reload_strictmode',
  'anonymous_session_canonical',
  'legacy_local_seed_complete',
  'legacy_session_seed_complete',
  'legacy_cache_seed_complete',
  'leading_unrelated_keys_preserved',
  'storage_clear_never_called',
  'legacy_value_reads_theme_only',
  'legacy_local_purge_complete',
  'legacy_session_purge_complete',
  'legacy_cache_purge_complete',
  'theme_one_shot_migrated',
  'theme_current_precedence',
  'invalid_theme_retired',
  'inaccessible_storage_fail_closed',
  'failed_removal_fail_closed',
  'no_progress_fail_closed',
  'unsupported_locks_fail_closed',
  'lifecycle_boundaries_complete',
  'private_api_cache_excluded',
  'delete_only_privacy_sinks_clean',
  'unrelated_surfaces_preserved',
  'active_namespaces_nyayone_only',
  'service_worker_reinstalled_active',
  'runtime_identity_clean',
  's03_desktop_observed',
  's03_mobile_observed',
  'screenshots_exact',
  'inherited_nyay5_contract_integrity',
  'evidence_sanitized',
  'planted_mutants_killed',
];

const EXPECTED_MUTANTS = [
  'missing-required-row',
  'reordered-required-rows',
  'duplicate-required-row',
  'unexecuted-required-row',
  'failed-required-row',
  'bad-exact-commit',
  'bad-exact-tree',
  'bad-exact-parent',
  'bad-preview-server-source-sha',
  'dirty-worktree',
  'non-chromium-runtime',
  'noncanonical-anonymous-session',
  'pending-flow-authority-unproven',
  'pending-flow-controls-missing',
  'undersized-local-seed',
  'missing-local-family',
  'undersized-cache-seed',
  'undersized-leading-unrelated-seed',
  'leading-target-survived',
  'storage-clear-called',
  'non-theme-legacy-read',
  'retained-legacy-local',
  'retained-legacy-session',
  'retained-legacy-cache',
  'failed-theme-migration',
  'overwritten-current-theme',
  'retained-invalid-theme',
  'inaccessible-storage-mounted-private',
  'failed-removal-mounted-private',
  'no-progress-mounted-private',
  'cleanup-failure-vacuous-action',
  'cleanup-failure-pending-control-unproven',
  'cleanup-failure-mutated-cookie-authority',
  'cleanup-failure-safe-entry-missing',
  'cleanup-failure-pending-authority-unproven',
  'unsupported-locks-cookie-work',
  'unsupported-locks-vacuous-action',
  'missing-lifecycle-scenario',
  'lifecycle-bypassed-production-action',
  'lifecycle-missing-canonical-401',
  'lifecycle-missing-transition',
  'actor-rotation-unobserved',
  'cold-actor-keys-survived-private-mount',
  'profile-id-actor-key-survived-teardown',
  'cached-private-api-response',
  'unexercised-private-cache-probe',
  'unexercised-hostile-asset-probe',
  'cookie-bearing-hostile-asset-fetch',
  'cached-hostile-private-asset',
  'unexercised-hostile-shell-probe',
  'cookie-bearing-hostile-shell-fetch',
  'cached-hostile-private-shell',
  'missing-install-created-shell',
  'offline-install-shell-unserved',
  'served-unrelated-asset-poison',
  'served-unrelated-shell-poison',
  'deleted-unrelated-poison',
  'delete-only-value-in-sink',
  'transient-dom-private-write',
  'transient-cache-private-write',
  'transient-cookie-private-write',
  'transient-history-private-write',
  'transient-storage-private-write',
  'privacy-instrumentation-canary-missed',
  'single-privacy-probe-document',
  'indexeddb-private-write',
  'missing-strictmode-reload',
  'inherited-nyay5-contract-failed',
  'retained-current-brand-cache',
  'deleted-unrelated-canary',
  'active-legacy-name',
  'inactive-service-worker',
  'visible-legacy-brand',
  'brand-separator-canary-missed',
  'wrong-desktop-geometry',
  'wrong-mobile-geometry',
  'missing-screenshot',
  'private-evidence',
  'unchecked-planted-mutant',
];

function row(report, id) {
  const found = report.rows.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`fixture row missing: ${id}`);
  return found;
}

describe('NYAY-18 pure browser evidence contract', () => {
  it('locks the complete assertion and compatibility inventories', () => {
    expect(NYAY18_ASSERTION_INVENTORY).toEqual(EXPECTED_ASSERTIONS);
    expect(NYAY18_PLANTED_MUTANT_NAMES).toEqual(EXPECTED_MUTANTS);
    expect(new Set(NYAY18_ASSERTION_INVENTORY).size).toBe(EXPECTED_ASSERTIONS.length);
    expect(new Set(NYAY18_PLANTED_MUTANT_NAMES).size).toBe(EXPECTED_MUTANTS.length);
    expect(NYAY18_LEGACY_LOCAL_EXACT_KEYS).toEqual([
      'legalsaathi.student.profile.v1',
      'legalsaathi.student.onboarding.v34',
      'legalsaathi.internship.applications.v1',
      'legalsaathi.clinical.export-audit.v1',
      'legalsaathi.student.cleanup-registry.v1',
      'ls-auth-student',
      'ls-auth-lawyer',
      'ls-locale',
      'ls-reviewer',
      'ls-onboarding-seen',
      'ls-theme',
    ]);
    expect(NYAY18_LEGACY_LOCAL_PREFIXES).toEqual([
      'ls-reports-',
      'ls-reminder-prefs-',
      'ls-draftws-',
      'ls-review-',
      'ls-filing-',
    ]);
    expect(NYAY18_LEGACY_SESSION_EXACT_KEYS).toEqual([
      'legalsaathi.student.registration.v2',
      'legalsaathi.student.privacy.export.v1',
      'legalsaathi.student.privacy.delete.v1',
    ]);
    expect(NYAY18_LEGACY_CACHE_PREFIXES).toEqual(['ls-shell-', 'legalsaathi-shell-']);
    expect(NYAY18_RETIRED_CURRENT_CACHE).toBe('nyayone-shell-v0');
    expect(NYAY18_LEADING_UNRELATED_KEYS).toBe(257);
    expect(NYAY18_LEADING_CANDIDATE_KEYS).toBe(1_024);
    expect(NYAY18_LEADING_TARGET_KEYS).toBe(64);
    const candidates = buildNyay18LeadingCandidateEntries();
    const targets = buildNyay18LeadingTargetKeys();
    expect(candidates).toHaveLength(NYAY18_LEADING_CANDIDATE_KEYS);
    expect(candidates[0]).toEqual(['third-party.leading.candidate.0000', 'retain-0']);
    expect(candidates.at(-1)).toEqual(['third-party.leading.candidate.1023', 'retain-1023']);
    expect(targets).toHaveLength(NYAY18_LEADING_TARGET_KEYS);
    expect(targets[0]).toBe('ls-reports-nyay18-leading-target-00');
    expect(targets.at(-1)).toBe('ls-reports-nyay18-leading-target-63');
  });

  it('accepts only an exact clean-head, fully executed sanitized report', () => {
    const clean = makeValidNyay18EvidenceFixture();
    expect(inspectNyay18Evidence(clean)).toMatchObject({
      pass: true,
      inventoryExact: true,
      executed: EXPECTED_ASSERTIONS.length,
      failed: 0,
    });

    const dirty = structuredClone(clean);
    row(dirty, 'required_environment_exact').metrics.worktreeClean = false;
    expect(inspectNyay18Evidence(dirty).pass).toBe(false);

    const wrongTree = structuredClone(clean);
    wrongTree.exactTree = 'bad';
    expect(inspectNyay18Evidence(wrongTree).pass).toBe(false);

    const wrongParent = structuredClone(clean);
    wrongParent.exactParent = 'bad';
    expect(inspectNyay18Evidence(wrongParent).pass).toBe(false);

    const wrongPreviewSource = structuredClone(clean);
    wrongPreviewSource.previewServerSourceSha256 = 'bad';
    expect(inspectNyay18Evidence(wrongPreviewSource).pass).toBe(false);

    const missing = structuredClone(clean);
    missing.rows.pop();
    expect(inspectNyay18Evidence(missing).pass).toBe(false);

    const unexecuted = structuredClone(clean);
    row(unexecuted, 'runtime_identity_clean').executed = false;
    expect(inspectNyay18Evidence(unexecuted).pass).toBe(false);

    const raw = structuredClone(clean);
    raw.rawPrivateValue = 'Bearer nyay18-private-seed-value';
    expect(inspectNyay18Evidence(raw).pass).toBe(false);
  });

  it('kills every named planted mutant with the production inspector', () => {
    const result = runNyay18ContractSelfTest();
    expect(result.names).toEqual(EXPECTED_MUTANTS);
    expect(result).toMatchObject({
      named: EXPECTED_MUTANTS.length,
      killed: EXPECTED_MUTANTS.length,
      allKilled: true,
    });
    expect(result.results.every((entry) => entry.killed === true)).toBe(true);
  });

  it('binds screenshot dimensions, checksums, migration, and bounded purge observations', () => {
    const clean = makeValidNyay18EvidenceFixture();
    for (const [id, mutate] of [
      ['legacy_local_seed_complete', (metrics) => { metrics.seededCount = 256; }],
      ['legacy_cache_seed_complete', (metrics) => { metrics.seededCount = 256; }],
      ['storage_clear_never_called', (metrics) => { metrics.localCalls = 1; }],
      ['legacy_value_reads_theme_only', (metrics) => { metrics.nonThemeLegacyReads = 1; }],
      ['theme_one_shot_migrated', (metrics) => { metrics.oldThemeAbsent = false; }],
      ['service_worker_reinstalled_active', (metrics) => { metrics.active = false; }],
      ['runtime_identity_clean', (metrics) => { metrics.brandSeparatorCanariesDetected = 5; }],
      ['s03_desktop_observed', (metrics) => { metrics.width = 1439; }],
      ['s03_mobile_observed', (metrics) => { metrics.height = 843; }],
      ['screenshots_exact', (metrics) => { metrics.count = 1; }],
    ]) {
      const mutant = structuredClone(clean);
      mutate(row(mutant, id).metrics);
      expect(inspectNyay18Evidence(mutant).pass, id).toBe(false);
    }
  });

  it('rejects every omitted normative real-browser matrix outcome', () => {
    const clean = makeValidNyay18EvidenceFixture();
    for (const [id, mutate] of [
      ['fresh_profiles_reload_strictmode', (metrics) => { metrics.reloads = 0; }],
      ['leading_unrelated_keys_preserved', (metrics) => { metrics.targetIndexBeforeBootstrap = 256; }],
      ['leading_unrelated_keys_preserved', (metrics) => { metrics.targetRemoved = false; }],
      ['theme_current_precedence', (metrics) => { metrics.currentWon = false; }],
      ['invalid_theme_retired', (metrics) => { metrics.oldThemeAbsent = false; }],
      ['anonymous_session_canonical', (metrics) => { metrics.denialRoutesDenied = 1; }],
      ['anonymous_session_canonical', (metrics) => { metrics.denialOtpControlsAbsent = false; }],
      ['anonymous_session_canonical', (metrics) => { metrics.denialFlowAuthorityAbsent = false; }],
      ['anonymous_session_canonical', (metrics) => { metrics.denialCookieInventoryUnchanged = false; }],
      ['inaccessible_storage_fail_closed', (metrics) => { metrics.privateMounted = true; }],
      ['inaccessible_storage_fail_closed', (metrics) => { metrics.pendingAuthorityProven = false; }],
      ['inaccessible_storage_fail_closed', (metrics) => { metrics.flowAuthorityPreserved = false; }],
      ['failed_removal_fail_closed', (metrics) => { metrics.unavailableVisible = false; }],
      ['no_progress_fail_closed', (metrics) => { metrics.actionRejected = false; }],
      ['no_progress_fail_closed', (metrics) => { metrics.cookieOperations = 1; }],
      ['unsupported_locks_fail_closed', (metrics) => { metrics.sessionRequests = 1; }],
      ['lifecycle_boundaries_complete', (metrics) => { metrics.coldActorKeysPurged = 5; }],
      ['lifecycle_boundaries_complete', (metrics) => { metrics.actorIdentifiersPerScenario = 1; }],
      ['lifecycle_boundaries_complete', (metrics) => { metrics.actorRotationRediscoveryResponses = 0; }],
      ['private_api_cache_excluded', (metrics) => { metrics.privateEntries = 1; }],
      ['private_api_cache_excluded', (metrics) => { metrics.hostileShellEntries = 1; }],
      ['delete_only_privacy_sinks_clean', (metrics) => { metrics.consoleFindings = 1; }],
      ['delete_only_privacy_sinks_clean', (metrics) => { metrics.continuousHistoryWrites = 1; }],
      ['delete_only_privacy_sinks_clean', (metrics) => { metrics.instrumentationDocumentCount = 1; }],
      ['inherited_nyay5_contract_integrity', (metrics) => { metrics.failed = 1; }],
    ]) {
      const mutant = structuredClone(clean);
      mutate(row(mutant, id).metrics);
      expect(inspectNyay18Evidence(mutant).pass, id).toBe(false);
    }
  });
});

describe('NYAY-18 real Chromium runner source contract', () => {
  it('requires exact inputs, real Chromium, canonical anonymous authority and production SW activation', () => {
    const source = readFileSync(RUNNER, 'utf8');
    for (const env of [
      'NYAY18_WEB_URL', 'NYAY18_EVIDENCE_PATH', 'NYAY18_EXACT_COMMIT',
      'NYAY18_EXACT_TREE', 'NYAY18_EXACT_PARENT',
      'NYAY18_PREVIEW_SOURCE_SHA256',
    ]) {
      expect(source).toContain(`requiredEnv('${env}')`);
    }
    expect(source).toContain("execFileSync('git', ['rev-parse', 'HEAD']");
    expect(source).toContain("execFileSync('git', ['rev-parse', 'HEAD^{tree}']");
    expect(source).toContain("execFileSync('git', ['rev-list', '--parents', '-n', '1', 'HEAD']");
    expect(source).toContain("execFileSync('git', ['status', '--porcelain=v1', '--untracked-files=all']");
    expect(source).toContain('chromium.launch({ headless: true })');
    expect(source).toContain("page.route('**/api/v1/auth/student/session'");
    expect(source).toContain('JSON.stringify(state.actor === null');
    expect(source).toContain('{ authenticated: false, actor: null }');
    expect(source).toContain('navigator.serviceWorker.getRegistrations()');
    expect(source).toContain('registration.unregister()');
    expect(source).toContain('navigator.serviceWorker.ready');
    expect(source).toContain('exactTree: EXACT_TREE');
    expect(source).toContain('exactParent: EXACT_PARENT');
    expect(source).toContain('previewServerSourceSha256: PREVIEW_SOURCE_SHA256');
    expect(source).not.toMatch(/\b(?:localStorage|sessionStorage)\.clear\s*\(/u);
    expect(source).not.toContain('caches.delete(');
    expect(source).not.toContain('Reflect.apply(CacheStorage.prototype.delete');
    expect(source).toContain('await cache.delete(canaryRequest)');
  });

  it('plants every legacy family, instruments value reads/clear calls, and captures exact S03 viewports', () => {
    const source = readFileSync(RUNNER, 'utf8');
    expect(source).toContain("import { PNG } from 'pngjs'");
    expect(source).toContain('NYAY18_PREFIX_SEEDS_PER_FAMILY');
    expect(source).toContain('NYAY18_CACHE_SEEDS_PER_FAMILY');
    expect(source).toContain("Storage.prototype.getItem");
    expect(source).toContain("Storage.prototype.clear");
    expect(source).toContain("{ name: 'desktop', width: 1440, height: 1024 }");
    expect(source).toContain("{ name: 'mobile', width: 390, height: 844 }");
    expect(source).toContain("'[data-screen=\"S-03\"]'");
    expect(source).toContain('page.screenshot(');
    expect(source).toContain('PNG.sync.read');
    expect(source).toContain('observedPng.width');
    expect(source).toContain('observedPng.height');
    for (const helper of [
      'runThemeMatrix',
      'runLeadingUnrelatedMatrix',
      'runFailClosedMatrix',
      'runLifecycleMatrix',
      'inspectPrivateCacheBoundary',
      'inspectDeleteOnlyPrivacySinks',
      'runInheritedNyay5ContractIntegrity',
    ]) expect(source).toContain(`async function ${helper}`);
    expect(source).toContain('NYAY18_LEADING_UNRELATED_KEYS');
    expect(source).toContain('NYAY18_LEADING_CANDIDATE_KEYS');
    expect(source).toContain('NYAY18_LEADING_TARGET_KEYS');
    expect(source).toContain("'__nyay18-leading-bootstrap'");
    expect(source).toContain('targetIndexBeforeBootstrap');
    expect(source).toContain('React.StrictMode');
    for (const productionBoundary of [
      "'[data-screen=\"S-05\"]'",
      "'[data-screen=\"S-04\"]'",
      "name: 'Send Code'",
      "getByLabel('Six digit code')",
      "name: 'Verify and continue'",
      "'This browser cannot safely change sessions. Check browser privacy support and try again.'",
      "'/api/v1/auth/student/logout'",
      "name: 'Sign out'",
      "'/api/v1/student/privacy/delete'",
      "name: 'Delete…'",
      "name: 'Delete my account'",
      "'authentication_required'",
      "'session_authority_required'",
      "'nyayone:student-auth-transition-started'",
      "'nyayone:student-auth-changed'",
      'IDBFactory.prototype.open',
      'IDBFactory.prototype.deleteDatabase',
      'IDBDatabase.prototype.createObjectStore',
      "for (const method of ['add', 'put'])",
      'MutationObserver',
      'History.prototype.pushState',
      'Storage.prototype.setItem',
      "Object.getOwnPropertyDescriptor(Document.prototype, 'cookie')",
      'Cache.prototype.put',
      'runPrivacySinkInstrumentationCanaries',
      'migrationPrivacyInstrumentation',
      'instrumentationDocumentCount',
      'privateRouteProbeRequests',
      'apiProbeRequests',
      "const HOSTILE_ASSET_PATH = '/assets/nyay18-private-canary.js'",
      'hostileAssetCookieHeaders',
      'hostileAssetEntries',
      'hostileAssetServerRequests',
      'hostileShellCookieHeaders',
      'hostileShellEntries',
      'hostileShellServerRequests',
      'installShellEntryPresent',
      'installShellOfflineServed',
      'runUnrelatedCachePoisonProbe',
      'runInstallShellOfflineProbe',
      'context.setOffline(true)',
      'unrelatedPoisonEntriesPreserved',
      'unrelatedShellPoisonServed',
      'coldActorKeysPurged',
      'teardownActorKeysPurged',
      'actorRotationRediscoveryResponses',
    ]) expect(source).toContain(productionBoundary);
    expect(source).not.toContain(
      "'That code could not be verified. Check all six digits.'",
    );
    expect(source).not.toContain('/api/v1/student/privacy/account');
    expect(source).not.toContain("fetch('/api/v1/auth/student/logout'");
    expect(source).toContain("fetch('/__nyay18-gate/metrics'");
    expect(source).toContain("fetch('/__nyay18-gate/arm-shell'");
    expect(source).not.toContain('page.route(`**${HOSTILE_ASSET_PATH}`');
    expect(source.match(/legal\[\\s\._-\]\*saathi/gu)?.length).toBeGreaterThanOrEqual(3);
    expect(source).not.toContain('legal\\s*saathi');
    expect(source).toContain('legal[\\s._:-]*saathi');
    expect(source).not.toContain('legal[-_.:]?saathi');
  });

  it('requires server-issued pending authority before observing S05 and S09 OTP controls', () => {
    const source = readFileSync(RUNNER, 'utf8');
    const provisionStart = source.indexOf('async function provisionServerPendingFlow');
    const provisionEnd = source.indexOf('async function runServerPendingFlowMatrix', provisionStart);
    const matrixEnd = source.indexOf('async function runUnavailableChallengeDenial', provisionEnd);
    const provision = source.slice(provisionStart, provisionEnd);
    const matrix = source.slice(provisionEnd, matrixEnd);
    expect(source).toContain('async function provisionServerPendingFlow');
    expect(source).toContain('async function runServerPendingFlowMatrix');
    expect(source).toContain("context.request.post(`${WEB}/api/v1/auth/student/login/otp/start`");
    expect(source).toContain("context.request.post(`${WEB}/api/v1/auth/student/register`");
    expect(source).toContain("context.request.get(`${WEB}/api/v1/auth/student/otp/state`");
    expect(source).toContain("stateBody?.status !== 'pending'");
    expect(source).toContain('stateBody?.purpose !== purpose');
    expect(source).toContain("cookie.name === 'nyayone_otp_flow'");
    expect(source).toContain("cookie.name === 'nyayone_session'");
    expect(source).toContain("['login', '/s-05', '[data-screen=\"S-05\"]']");
    expect(source).toContain("['signup', '/s-09', '[data-screen=\"S-09\"]']");
    expect(source).toContain('otpStateRequestCount');
    expect(provision).not.toContain("page.route('**/api/v1/auth/student/otp/state'");
    expect(provision).not.toMatch(/\bcode\b/u);
    expect(matrix).not.toContain("page.route('**/api/v1/auth/student/otp/state'");
  });

  it('requires unavailable challenge navigation to prove S03 denial and zero OTP controls', () => {
    const source = readFileSync(RUNNER, 'utf8');
    expect(source).toContain('async function runUnavailableChallengeDenial');
    expect(source).toContain("await page.waitForURL(/\\/s-03$/u)");
    expect(source).toContain("page.getByLabel('Six digit code').count()");
    expect(source).toContain('cookieInventoryUnchanged');
    expect(source).toContain('flowAuthorityAbsent');
    expect(source).toContain('flowUnavailableProven');
    expect(source).toContain('otpControlsAbsent');
    const start = source.indexOf('async function runUnavailableChallengeDenial');
    const end = source.indexOf('async function runFailClosedMatrix', start);
    const denial = source.slice(start, end);
    expect(denial).not.toContain("getByLabel('Six digit code').fill(");
    expect(denial).not.toContain("name: 'Verify and continue'");
    expect(denial).toContain("stateBody.status === 'unavailable'");
  });

  it('keeps anonymous challenge denial separate from the storage-failure mutation barrier', () => {
    const source = readFileSync(RUNNER, 'utf8');
    expect(source).toContain('async function runAnonymousChallengeDenialMatrix');
    expect(source).toContain('const anonymousDenied = await runAnonymousChallengeDenialMatrix(browser);');
    const start = source.indexOf('async function runFailClosedMatrix');
    const end = source.indexOf('async function runLifecycleMatrix', start);
    const matrix = source.slice(start, end);
    expect(matrix).not.toContain('runUnavailableChallengeDenial(page, context)');
  });

  it('uses a real pending-flow authority and a logout UI mutation to prove cleanup failure blocks cookie work', () => {
    const source = readFileSync(RUNNER, 'utf8');
    const start = source.indexOf('async function runFailClosedMatrix');
    const end = source.indexOf('async function runLifecycleMatrix', start);
    const matrix = source.slice(start, end);
    expect(matrix).toContain("await provisionServerPendingFlow(browser, 'login')");
    expect(matrix).toContain('pendingAuthorityProven');
    expect(matrix).toContain('installRuntimeStorageFailure');
    expect(matrix).toContain("page.getByRole('button', { name: 'Sign out', exact: true })");
    expect(matrix).toContain('await signOut.click()');
    expect(matrix).toContain('cookieInventoryUnchanged');
    expect(matrix).toContain('flowAuthorityPreserved');
    expect(matrix).toContain('cookieOperations === 0');
    expect(matrix).toContain(
      'const pendingStateResponsePromise = page.waitForResponse(isExactPendingStateResponse);',
    );
    expect(matrix.indexOf(
      'const pendingStateResponsePromise = page.waitForResponse(isExactPendingStateResponse);',
    )).toBeLessThan(matrix.indexOf('await page.goto(`${WEB}/s-05`'));
    expect(matrix).toContain('await pendingStateResponse.finished()');
    expect(matrix).toContain("await pendingControl.waitFor({ state: 'visible' })");
    expect(matrix).toContain("await page.locator(SESSION_UNAVAILABLE).waitFor({ state: 'visible' })");
    expect(matrix.indexOf('await signOut.click()')).toBeLessThan(
      matrix.indexOf("await page.locator(SESSION_UNAVAILABLE).waitFor({ state: 'visible' })"),
    );
    expect(matrix.indexOf("await page.locator(SESSION_UNAVAILABLE).waitFor({ state: 'visible' })")).toBeLessThan(
      matrix.indexOf('const safeEntryVisible ='),
    );
    const rejection = matrix.slice(matrix.indexOf('await signOut.click()'), matrix.indexOf('const afterCookies ='));
    expect(rejection).toContain("page.getByText('Sign out could not be confirmed.'");
    expect(rejection).toContain('page.locator(S03_SELECTOR).count() === 0');
    expect(rejection).not.toContain('waitForURL');
    expect(matrix).not.toContain("getByLabel('Six digit code').fill(");
    expect(matrix).not.toContain("name: 'Verify and continue'");
  });

  it('matches storage-failure readiness only to the exact canonical OTP-state response', () => {
    const source = readFileSync(RUNNER, 'utf8');
    const start = source.indexOf('function isExactPendingStateResponse');
    const end = source.indexOf('async function runFailClosedMatrix', start);
    const matcher = source.slice(start, end);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(matcher).toContain("response.request().method() === 'GET'");
    expect(matcher).toContain("url.origin === new URL(WEB).origin");
    expect(matcher).toContain("url.pathname === '/api/v1/auth/student/otp/state'");
    expect(matcher).toContain("url.search === ''");
    expect(matcher).toContain("url.hash === ''");
  });

  it('measures the credential-omitted hostile asset fetch at the loopback server', () => {
    const source = readFileSync(PREVIEW, 'utf8');
    expect(source).toContain("'/assets/nyay18-private-canary.js'");
    expect(source).toContain("'/__nyay18-gate/metrics'");
    expect(source).toContain("'/__nyay18-gate/arm-shell'");
    expect(source).toContain("'/index.html'");
    expect(source).toContain('request.headers.cookie');
    expect(source).toContain("'Cache-Control': 'private, no-store'");
    expect(source).toContain("Vary: 'Cookie'");
    expect(source).toContain("'Cache-Control': 'public, max-age=60'");
  });

  it('requires the preview fixture to own pending flow state in an HttpOnly cookie', () => {
    const source = readFileSync(PREVIEW, 'utf8');
    expect(source).toContain("'/api/v1/auth/student/login/otp/start'");
    expect(source).toContain("'/api/v1/auth/student/register'");
    expect(source).toContain("'/api/v1/auth/student/otp/state'");
    expect(source).toContain("'/api/v1/auth/student/session'");
    expect(source).toContain("'Set-Cookie'");
    expect(source).toContain('HttpOnly');
    expect(source).toContain('SameSite=Strict');
    expect(source).toContain('flowAuthority.set(');
    expect(source).toContain('flowAuthority.get(');
    expect(source).not.toContain('otp_code');
    expect(source).not.toContain('one_time_code');
  });

  it('passes exact commit, tree and parent bindings through the isolated orchestrator', () => {
    const source = readFileSync(ORCHESTRATOR, 'utf8');
    expect(source).toContain('EXACT_TREE="$(git -C "$ROOT" rev-parse \'HEAD^{tree}\')"');
    expect(source).toContain('EXACT_PARENT=\'ROOT\'');
    expect(source).toContain('NYAY18_EXACT_TREE="$EXACT_TREE"');
    expect(source).toContain('NYAY18_EXACT_PARENT="$EXACT_PARENT"');
    expect(source).toContain('PREVIEW_SOURCE_SHA256=');
    expect(source).toContain('NYAY18_PREVIEW_SOURCE_SHA256="$PREVIEW_SOURCE_SHA256"');
    expect(source).toContain('node scripts/nyay18-preview-server.mjs');
  });

  it('exposes one package command for orchestration without weakening another gate', () => {
    const pkg = JSON.parse(readFileSync(PACKAGE, 'utf8'));
    expect(pkg.scripts['qa:nyay18:browser-namespace']).toBe(
      'node scripts/nyay18-browser-namespace.mjs',
    );
  });
});

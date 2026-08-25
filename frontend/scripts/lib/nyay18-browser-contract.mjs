import { createHash } from 'node:crypto';

export const NYAY18_ASSERTION_INVENTORY = Object.freeze([
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
]);

export const NYAY18_LEGACY_LOCAL_EXACT_KEYS = Object.freeze([
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

export const NYAY18_LEGACY_LOCAL_PREFIXES = Object.freeze([
  'ls-reports-',
  'ls-reminder-prefs-',
  'ls-draftws-',
  'ls-review-',
  'ls-filing-',
]);

export const NYAY18_LEGACY_SESSION_EXACT_KEYS = Object.freeze([
  'legalsaathi.student.registration.v2',
  'legalsaathi.student.privacy.export.v1',
  'legalsaathi.student.privacy.delete.v1',
]);

export const NYAY18_LEGACY_CACHE_PREFIXES = Object.freeze([
  'ls-shell-',
  'legalsaathi-shell-',
]);

export const NYAY18_RETIRED_CURRENT_CACHE = 'nyayone-shell-v0';

export const NYAY18_ACTIVE_RUNTIME_NAMESPACES = Object.freeze([
  '__nyayoneVideoRoom',
  '__nyayoneVideoTransport',
  'nyayone-shell-',
  'nyayone.auth.',
  'nyayone.lawyer.draft-workspace.v1.',
  'nyayone.lawyer.filing-workflow.v1.',
  'nyayone.lawyer.review-workspace.v1.',
  'nyayone.locale.v1',
  'nyayone.student.auth-session.v1',
  'nyayone.student.auth-transition.v2',
  'nyayone.student.reminder-prefs.v1.',
  'nyayone.student.reports.v1.',
  'nyayone.theme.v1',
  'nyayone:auth-change',
  'nyayone:student-auth-changed',
  'nyayone:student-auth-transition-started',
]);

export const NYAY18_PREFIX_SEEDS_PER_FAMILY = 257;
export const NYAY18_CACHE_SEEDS_PER_FAMILY = 129;
export const NYAY18_LEADING_UNRELATED_KEYS = 257;
export const NYAY18_LEADING_CANDIDATE_KEYS = 1_024;
export const NYAY18_LEADING_TARGET_KEYS = 64;

export const NYAY18_UNRELATED_CANARIES = Object.freeze({
  local: 'third-party.preferences.v1',
  session: 'third-party.flow.v1',
  cache: 'third-party-shell-v1',
});

export const NYAY18_SCREENSHOT_INVENTORY = Object.freeze([
  Object.freeze({ name: 'nyay18-s03-desktop-1440x1024.png', width: 1440, height: 1024 }),
  Object.freeze({ name: 'nyay18-s03-mobile-390x844.png', width: 390, height: 844 }),
]);

export const NYAY18_PLANTED_MUTANT_NAMES = Object.freeze([
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
]);

const SHA256 = /^[0-9a-f]{64}$/u;
const COMMIT = /^[0-9a-f]{40}$/u;
const PRIVATE_EVIDENCE_PATTERNS = Object.freeze([
  /nyay18-private-(?:local|session|cache)-value/iu,
  /bearer\s+[a-z0-9._~+/-]{12,}/iu,
  /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/iu,
  /(?<!\d)[6-9]\d{9}(?!\d)/u,
  /https?:\/\/[^\s/@]+:[^\s/@]+@/iu,
]);

function digestLines(values) {
  return createHash('sha256').update(`${values.join('\n')}\n`).digest('hex');
}

export function buildNyay18LegacyLocalSeedKeys() {
  return [
    ...NYAY18_LEGACY_LOCAL_EXACT_KEYS,
    ...NYAY18_LEGACY_LOCAL_PREFIXES.flatMap((prefix) => (
      Array.from({ length: NYAY18_PREFIX_SEEDS_PER_FAMILY }, (_, index) => (
        `${prefix}nyay18-${String(index).padStart(3, '0')}`
      ))
    )),
  ];
}

export function buildNyay18LegacyCacheSeedKeys() {
  return [
    NYAY18_RETIRED_CURRENT_CACHE,
    ...NYAY18_LEGACY_CACHE_PREFIXES.flatMap((prefix) => (
      Array.from({ length: NYAY18_CACHE_SEEDS_PER_FAMILY }, (_, index) => (
        `${prefix}nyay18-${String(index).padStart(3, '0')}`
      ))
    )),
  ];
}

export function buildNyay18LeadingCandidateEntries() {
  return Array.from({ length: NYAY18_LEADING_CANDIDATE_KEYS }, (_, index) => (
    [`third-party.leading.candidate.${String(index).padStart(4, '0')}`, `retain-${index}`]
  ));
}

export function buildNyay18LeadingTargetKeys() {
  return Array.from({ length: NYAY18_LEADING_TARGET_KEYS }, (_, index) => (
    `ls-reports-nyay18-leading-target-${String(index).padStart(2, '0')}`
  ));
}

function expectedInventory() {
  const screenshotRows = NYAY18_SCREENSHOT_INVENTORY.map(
    ({ name, width, height }) => `${name}:${width}x${height}`,
  );
  const canaries = Object.entries(NYAY18_UNRELATED_CANARIES)
    .map(([surface, name]) => `${surface}:${name}`);
  const leadingCandidates = buildNyay18LeadingCandidateEntries()
    .map(([key, value]) => `${key}\0${value}`);
  const leadingTargets = buildNyay18LeadingTargetKeys();
  return {
    assertions: {
      count: NYAY18_ASSERTION_INVENTORY.length,
      sha256: digestLines(NYAY18_ASSERTION_INVENTORY),
    },
    legacyLocalExact: {
      count: NYAY18_LEGACY_LOCAL_EXACT_KEYS.length,
      sha256: digestLines(NYAY18_LEGACY_LOCAL_EXACT_KEYS),
    },
    legacyLocalPrefixes: {
      count: NYAY18_LEGACY_LOCAL_PREFIXES.length,
      sha256: digestLines(NYAY18_LEGACY_LOCAL_PREFIXES),
    },
    legacySessionExact: {
      count: NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
      sha256: digestLines(NYAY18_LEGACY_SESSION_EXACT_KEYS),
    },
    legacyCachePrefixes: {
      count: NYAY18_LEGACY_CACHE_PREFIXES.length,
      sha256: digestLines(NYAY18_LEGACY_CACHE_PREFIXES),
    },
    retiredCurrentCache: {
      count: 1,
      sha256: digestLines([NYAY18_RETIRED_CURRENT_CACHE]),
    },
    leadingCandidates: {
      count: leadingCandidates.length,
      sha256: digestLines(leadingCandidates),
    },
    leadingTargets: {
      count: leadingTargets.length,
      sha256: digestLines(leadingTargets),
    },
    activeRuntimeNamespaces: {
      count: NYAY18_ACTIVE_RUNTIME_NAMESPACES.length,
      sha256: digestLines(NYAY18_ACTIVE_RUNTIME_NAMESPACES),
    },
    unrelatedCanaries: {
      count: canaries.length,
      sha256: digestLines(canaries),
    },
    screenshots: {
      count: screenshotRows.length,
      sha256: digestLines(screenshotRows),
    },
  };
}

export function nyay18EvidenceInventory() {
  return structuredClone(expectedInventory());
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value, keys) {
  return isObject(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}

function digest(value) {
  return typeof value === 'string' && SHA256.test(value);
}

function deepEqual(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function validRuntime(metrics) {
  return exactKeys(metrics, ['engine', 'headless', 'launches', 'versionSha256'])
    && metrics.engine === 'chromium'
    && metrics.headless === true
    && metrics.launches === 1
    && digest(metrics.versionSha256);
}

function validEnvironment(metrics) {
  return exactKeys(metrics, [
    'commitMatchesHead', 'commitRequired', 'outputAbsolute', 'outputOutsideRepository',
    'parentMatchesHead', 'parentRequired', 'previewSourceMatches',
    'treeMatchesHead', 'treeRequired',
    'webOriginLoopback', 'webRequired', 'worktreeClean',
  ])
    && Object.values(metrics).every((value) => value === true);
}

function validFreshProfiles(metrics) {
  return exactKeys(metrics, [
    'contexts', 'freshProfiles', 'reloads', 'strictModeRoot', 'strictModeSessionSettled',
  ])
    && Number.isSafeInteger(metrics.contexts)
    && metrics.contexts >= 10
    && metrics.freshProfiles === metrics.contexts
    && Number.isSafeInteger(metrics.reloads)
    && metrics.reloads >= 2
    && metrics.strictModeRoot === true
    && metrics.strictModeSessionSettled === true;
}

function validAnonymous(metrics) {
  return exactKeys(metrics, [
    'canonicalBodies', 'controls', 'flowCookies', 'flows', 'getRequests',
    'denialCookieInventoryUnchanged', 'denialFlowAuthorityAbsent',
    'denialFlowUnavailableProven', 'denialOtpControlsAbsent',
    'denialRetiredInlineErrorAbsent', 'denialRoutesDenied', 'otherRequests',
    'purposesExact', 'requestCount', 'screens', 'serverStateRequests',
    'sessionCookies', 'sessionRequests', 'startResponses', 'stateResponses',
    'verifyControls',
  ])
    && metrics.requestCount >= 1
    && metrics.getRequests === metrics.requestCount
    && metrics.canonicalBodies === metrics.requestCount
    && metrics.otherRequests === 0
    && metrics.flows === 2
    && metrics.startResponses === metrics.flows
    && metrics.stateResponses === metrics.flows
    && metrics.serverStateRequests >= metrics.flows
    && metrics.sessionRequests >= metrics.flows
    && metrics.controls === metrics.flows
    && metrics.screens === metrics.flows
    && metrics.flowCookies === metrics.flows
    && metrics.sessionCookies === 0
    && metrics.verifyControls === metrics.flows
    && metrics.purposesExact === true
    && metrics.denialCookieInventoryUnchanged === true
    && metrics.denialFlowAuthorityAbsent === true
    && metrics.denialFlowUnavailableProven === true
    && metrics.denialOtpControlsAbsent === true
    && metrics.denialRetiredInlineErrorAbsent === true
    && metrics.denialRoutesDenied === 2;
}

function validLocalSeed(metrics) {
  const keys = buildNyay18LegacyLocalSeedKeys();
  return exactKeys(metrics, [
    'exactFamilies', 'inventorySha256', 'prefixFamilies', 'seededCount',
    'themeSeeded', 'unique',
  ])
    && metrics.seededCount === keys.length
    && metrics.seededCount > 256
    && metrics.exactFamilies === NYAY18_LEGACY_LOCAL_EXACT_KEYS.length
    && metrics.prefixFamilies === NYAY18_LEGACY_LOCAL_PREFIXES.length
    && metrics.themeSeeded === true
    && metrics.unique === true
    && metrics.inventorySha256 === digestLines(keys);
}

function validSessionSeed(metrics) {
  return exactKeys(metrics, ['exactFamilies', 'inventorySha256', 'seededCount', 'unique'])
    && metrics.seededCount === NYAY18_LEGACY_SESSION_EXACT_KEYS.length
    && metrics.exactFamilies === NYAY18_LEGACY_SESSION_EXACT_KEYS.length
    && metrics.unique === true
    && metrics.inventorySha256 === digestLines(NYAY18_LEGACY_SESSION_EXACT_KEYS);
}

function validCacheSeed(metrics) {
  const keys = buildNyay18LegacyCacheSeedKeys();
  return exactKeys(metrics, [
    'inventorySha256', 'prefixFamilies', 'retiredCurrentSeeded', 'seededCount', 'unique',
  ])
    && metrics.seededCount === keys.length
    && metrics.seededCount > 256
    && metrics.prefixFamilies === NYAY18_LEGACY_CACHE_PREFIXES.length
    && metrics.retiredCurrentSeeded === true
    && metrics.unique === true
    && metrics.inventorySha256 === digestLines(keys);
}

function validLeadingUnrelated(metrics) {
  const candidates = buildNyay18LeadingCandidateEntries();
  const targets = buildNyay18LeadingTargetKeys();
  const expectedCandidateDigest = digestLines(
    candidates.map(([key, value]) => `${key}\0${value}`),
  );
  return exactKeys(metrics, [
    'afterSha256', 'beforeSha256', 'candidateCount', 'candidateInventorySha256',
    'leadingBeforeOwned', 'preservedCount', 'selectionAttempts',
    'targetCandidates', 'targetIndexBeforeBootstrap', 'targetInventorySha256',
    'targetRemoved', 'targetSurvivorsBeforeBootstrap', 'unrelatedBeforeTarget',
    'valuesExact',
  ])
    && metrics.candidateCount === NYAY18_LEADING_CANDIDATE_KEYS
    && metrics.preservedCount === NYAY18_LEADING_CANDIDATE_KEYS
    && metrics.targetCandidates === NYAY18_LEADING_TARGET_KEYS
    && Number.isSafeInteger(metrics.selectionAttempts)
    && metrics.selectionAttempts >= 1
    && metrics.selectionAttempts <= NYAY18_LEADING_TARGET_KEYS
    && Number.isSafeInteger(metrics.targetIndexBeforeBootstrap)
    && metrics.targetIndexBeforeBootstrap >= NYAY18_LEADING_UNRELATED_KEYS
    && Number.isSafeInteger(metrics.unrelatedBeforeTarget)
    && metrics.unrelatedBeforeTarget >= NYAY18_LEADING_UNRELATED_KEYS
    && metrics.candidateInventorySha256 === expectedCandidateDigest
    && metrics.targetInventorySha256 === digestLines(targets)
    && metrics.beforeSha256 === expectedCandidateDigest
    && metrics.afterSha256 === expectedCandidateDigest
    && metrics.leadingBeforeOwned === true
    && metrics.targetRemoved === true
    && metrics.targetSurvivorsBeforeBootstrap === 1
    && metrics.valuesExact === true;
}

function validClear(metrics) {
  return exactKeys(metrics, ['localCalls', 'sessionCalls'])
    && metrics.localCalls === 0
    && metrics.sessionCalls === 0;
}

function validReads(metrics) {
  return exactKeys(metrics, [
    'localLegacyReads', 'nonThemeLegacyReads', 'sessionLegacyReads', 'themeReads',
  ])
    && metrics.localLegacyReads === 1
    && metrics.themeReads === 1
    && metrics.nonThemeLegacyReads === 0
    && metrics.sessionLegacyReads === 0;
}

function validPurge(metrics, surface) {
  const keys = surface === 'local'
    ? buildNyay18LegacyLocalSeedKeys()
    : surface === 'session'
      ? NYAY18_LEGACY_SESSION_EXACT_KEYS
      : buildNyay18LegacyCacheSeedKeys();
  return exactKeys(metrics, ['inventorySha256', 'remaining', 'seededCount'])
    && metrics.seededCount === keys.length
    && metrics.remaining === 0
    && metrics.inventorySha256 === digestLines(keys);
}

function validTheme(metrics) {
  return exactKeys(metrics, [
    'migratedDark', 'newThemePresent', 'oldThemeAbsent', 'oneShotRead',
  ])
    && Object.values(metrics).every((value) => value === true);
}

function validThemePrecedence(metrics) {
  return exactKeys(metrics, [
    'currentLightPreserved', 'currentWon', 'legacyDarkSeeded',
    'legacyThemeReads', 'oldThemeAbsent',
  ])
    && metrics.currentLightPreserved === true
    && metrics.currentWon === true
    && metrics.legacyDarkSeeded === true
    && metrics.legacyThemeReads === 0
    && metrics.oldThemeAbsent === true;
}

function validInvalidTheme(metrics) {
  return exactKeys(metrics, [
    'invalidLegacySeeded', 'invalidReadOnce', 'oldThemeAbsent', 'resolvedLight',
  ])
    && Object.values(metrics).every((value) => value === true);
}

function validCleanupFailure(metrics, mode) {
  return exactKeys(metrics, [
    'actionAttempts', 'actionRejected', 'cookieInventoryUnchanged',
    'cookieOperations', 'flowAuthorityPreserved', 'mode',
    'pendingAuthorityProven', 'pendingControlsProven', 'privateMounted',
    'safeEntryVisible', 'unavailableVisible',
  ])
    && metrics.mode === mode
    && metrics.actionAttempts === 1
    && metrics.actionRejected === true
    && metrics.cookieInventoryUnchanged === true
    && metrics.cookieOperations === 0
    && metrics.flowAuthorityPreserved === true
    && metrics.pendingAuthorityProven === true
    && metrics.pendingControlsProven === true
    && metrics.privateMounted === false
    && metrics.safeEntryVisible === true
    && metrics.unavailableVisible === true;
}

function validUnsupportedLocks(metrics) {
  return exactKeys(metrics, [
    'actionAttempts', 'actionRejected', 'cookieOperations', 'locksUnavailable', 'privateMounted',
    'sessionRequests', 'unavailableVisible',
  ])
    && metrics.actionAttempts === 1
    && metrics.actionRejected === true
    && metrics.cookieOperations === 0
    && metrics.locksUnavailable === true
    && metrics.privateMounted === false
    && metrics.sessionRequests === 0
    && metrics.unavailableVisible === true;
}

function validLifecycle(metrics) {
  return exactKeys(metrics, [
    'actionEndpointsExact', 'actorIdentifiersPerScenario', 'actorKeyFamilies',
    'actorRotation', 'actorRotationRediscoveryResponses',
    'authoritativeRediscovery', 'canonical401Requests',
    'canonicalLoss', 'coldActorKeysExpected', 'coldActorKeysPurged', 'completed',
    'currentThemePreserved',
    'deletion', 'deletionEndpointRequests', 'expiry', 'logout',
    'logoutEndpointRequests', 'privateUnmountedLosses', 'productionActions',
    'retiredAbsent', 'revocation', 'scenarios', 'teardownActorKeysExpected',
    'teardownActorKeysPurged', 'transitionEnds', 'transitionStarts', 'unrelatedPreserved',
  ])
    && metrics.scenarios === 6
    && metrics.completed === metrics.scenarios
    && metrics.actorIdentifiersPerScenario === 2
    && metrics.actorKeyFamilies === 2
    && metrics.coldActorKeysExpected === 24
    && metrics.coldActorKeysPurged === metrics.coldActorKeysExpected
    && metrics.teardownActorKeysExpected === 24
    && metrics.teardownActorKeysPurged === metrics.teardownActorKeysExpected
    && metrics.currentThemePreserved === metrics.scenarios
    && metrics.unrelatedPreserved === metrics.scenarios
    && metrics.retiredAbsent === metrics.scenarios
    && metrics.privateUnmountedLosses === 5
    && metrics.authoritativeRediscovery === metrics.scenarios
    && metrics.actorRotationRediscoveryResponses === 1
    && metrics.productionActions === 2
    && metrics.logoutEndpointRequests === 1
    && metrics.deletionEndpointRequests === 1
    && metrics.canonical401Requests === 2
    && metrics.transitionStarts === 5
    && metrics.transitionEnds === 5
    && metrics.actionEndpointsExact === true
    && metrics.logout === true
    && metrics.expiry === true
    && metrics.revocation === true
    && metrics.actorRotation === true
    && metrics.canonicalLoss === true
    && metrics.deletion === true;
}

function validPrivateCache(metrics) {
  return exactKeys(metrics, [
    'apiEntries', 'apiProbeRequests', 'currentCacheEntries', 'inspectedEntries', 'privateEntries',
    'currentIndexRestored', 'currentScopedMissExercised',
    'hostileAssetCookieHeaders', 'hostileAssetEntries', 'hostileAssetExecuted',
    'hostileAssetServerRequests', 'hostileShellCookieHeaders', 'hostileShellEntries',
    'hostileShellServerRequests', 'installShellEntryPresent', 'installShellOfflineServed',
    'privateRouteProbeRequests',
    'publicEntriesExact', 'responseBodiesClean', 'retiredCurrentAbsent',
    'unrelatedAssetPoisonServed', 'unrelatedPoisonEntriesPreserved',
    'unrelatedShellPoisonServed',
  ])
    && metrics.apiEntries === 0
    && metrics.apiProbeRequests === 1
    && metrics.hostileAssetServerRequests === 1
    && metrics.hostileAssetCookieHeaders === 0
    && metrics.hostileAssetEntries === 0
    && metrics.hostileAssetExecuted === true
    && metrics.hostileShellServerRequests === 1
    && metrics.hostileShellCookieHeaders === 0
    && metrics.hostileShellEntries === 0
    && metrics.installShellEntryPresent === true
    && metrics.installShellOfflineServed === true
    && metrics.currentScopedMissExercised === true
    && metrics.currentIndexRestored === true
    && metrics.unrelatedAssetPoisonServed === false
    && metrics.unrelatedShellPoisonServed === false
    && metrics.unrelatedPoisonEntriesPreserved === true
    && metrics.privateEntries === 0
    && metrics.privateRouteProbeRequests === 1
    && Number.isSafeInteger(metrics.currentCacheEntries)
    && metrics.currentCacheEntries >= 1
    && metrics.inspectedEntries === metrics.currentCacheEntries
    && metrics.publicEntriesExact === true
    && metrics.responseBodiesClean === true
    && metrics.retiredCurrentAbsent === true;
}

function validPrivacySinks(metrics) {
  const zeroMetrics = [
    'cacheFindings', 'consoleFindings', 'cookieFindings', 'domFindings',
    'continuousCacheWrites', 'continuousCookieWrites', 'continuousDomWrites',
    'continuousHistoryWrites', 'continuousStorageWrites',
    'historyFindings', 'indexedDbCanaryWrites', 'indexedDbDeleteCalls',
    'indexedDbFindings', 'indexedDbOpenCalls', 'indexedDbWriteCalls',
    'networkFindings', 'newIndexedDbNames', 'storageFindings', 'urlFindings',
  ];
  const canaryMetrics = [
    'instrumentationCacheCanaryDetected', 'instrumentationCookieCanaryDetected',
    'instrumentationDomCanaryDetected', 'instrumentationHistoryCanaryDetected',
    'instrumentationStorageCanaryDetected',
  ];
  return exactKeys(metrics, [...zeroMetrics, ...canaryMetrics, 'instrumentationDocumentCount'])
    && zeroMetrics.every((key) => metrics[key] === 0)
    && canaryMetrics.every((key) => metrics[key] === true)
    && metrics.instrumentationDocumentCount === 2;
}

function validInheritedNyay5Contract(metrics) {
  return exactKeys(metrics, [
    'assertionInventoryExact', 'assertions', 'contractMutantsAllKilled', 'failed',
    'mutantInventoryExact', 'mutants', 'mutantsKilled',
  ])
    && metrics.assertions === 22
    && metrics.failed === 0
    && metrics.mutants === 46
    && metrics.mutantsKilled === metrics.mutants
    && metrics.assertionInventoryExact === true
    && metrics.mutantInventoryExact === true
    && metrics.contractMutantsAllKilled === true;
}

function validUnrelated(metrics) {
  return exactKeys(metrics, [
    'cachePreserved', 'localPreserved', 'sessionPreserved', 'surfaceCount', 'valuesExact',
  ])
    && metrics.surfaceCount === Object.keys(NYAY18_UNRELATED_CANARIES).length
    && metrics.localPreserved === true
    && metrics.sessionPreserved === true
    && metrics.cachePreserved === true
    && metrics.valuesExact === true;
}

function validActiveNamespaces(metrics) {
  return exactKeys(metrics, [
    'legacyCacheNames', 'legacyCookieNames', 'legacyGlobalNames', 'legacyLocalNames',
    'legacySessionNames', 'nyayOneOwnedNames', 'unexpectedOwnedNames',
  ])
    && metrics.legacyCacheNames === 0
    && metrics.legacyCookieNames === 0
    && metrics.legacyGlobalNames === 0
    && metrics.legacyLocalNames === 0
    && metrics.legacySessionNames === 0
    && metrics.unexpectedOwnedNames === 0
    && metrics.nyayOneOwnedNames >= 2;
}

function validServiceWorker(metrics) {
  return exactKeys(metrics, [
    'active', 'controller', 'initialRegistrations', 'registrations', 'reinstalled',
    'scriptPathExact', 'supported', 'unregistered',
  ])
    && metrics.supported === true
    && metrics.initialRegistrations >= 1
    && metrics.unregistered >= 1
    && metrics.registrations === 1
    && metrics.active === true
    && metrics.controller === true
    && metrics.scriptPathExact === true
    && metrics.reinstalled === true;
}

function validIdentity(metrics) {
  return exactKeys(metrics, [
    'bodyNyayOneVisible', 'brandSeparatorCanariesDetected',
    'legacyAriaMatches', 'legacyBodyMatches',
    'legacyCookieMatches', 'legacyDownloadMatches', 'legacyGlobalMatches',
    'legacyTitleMatches', 'titleExact',
  ])
    && metrics.titleExact === true
    && metrics.bodyNyayOneVisible === true
    && metrics.brandSeparatorCanariesDetected === 6
    && metrics.legacyTitleMatches === 0
    && metrics.legacyBodyMatches === 0
    && metrics.legacyAriaMatches === 0
    && metrics.legacyDownloadMatches === 0
    && metrics.legacyGlobalMatches === 0
    && metrics.legacyCookieMatches === 0;
}

function validViewport(metrics, expected) {
  return exactKeys(metrics, [
    'height', 'legacyVisibleMatches', 'noHorizontalOverflow', 'routeExact',
    'screenSelectorCount', 'screenshotCaptured', 'visible', 'width',
  ])
    && metrics.width === expected.width
    && metrics.height === expected.height
    && metrics.routeExact === true
    && metrics.screenSelectorCount === 1
    && metrics.visible === true
    && metrics.noHorizontalOverflow === true
    && metrics.legacyVisibleMatches === 0
    && metrics.screenshotCaptured === true;
}

function validScreenshots(metrics) {
  return exactKeys(metrics, ['checksumsExact', 'count', 'dimensionsExact', 'inventorySha256'])
    && metrics.count === NYAY18_SCREENSHOT_INVENTORY.length
    && metrics.dimensionsExact === true
    && metrics.checksumsExact === true
    && metrics.inventorySha256 === expectedInventory().screenshots.sha256;
}

function validSanitized(metrics) {
  return exactKeys(metrics, ['privacyFindings', 'rawPrivateValuesIncluded'])
    && metrics.privacyFindings === 0
    && metrics.rawPrivateValuesIncluded === false;
}

function validMutants(metrics) {
  return exactKeys(metrics, ['allKilled', 'killed', 'named'])
    && metrics.named === NYAY18_PLANTED_MUTANT_NAMES.length
    && metrics.killed === metrics.named
    && metrics.allKilled === true;
}

const ROW_VALIDATORS = Object.freeze({
  runtime_chromium: validRuntime,
  required_environment_exact: validEnvironment,
  fresh_profiles_reload_strictmode: validFreshProfiles,
  anonymous_session_canonical: validAnonymous,
  legacy_local_seed_complete: validLocalSeed,
  legacy_session_seed_complete: validSessionSeed,
  legacy_cache_seed_complete: validCacheSeed,
  leading_unrelated_keys_preserved: validLeadingUnrelated,
  storage_clear_never_called: validClear,
  legacy_value_reads_theme_only: validReads,
  legacy_local_purge_complete: (metrics) => validPurge(metrics, 'local'),
  legacy_session_purge_complete: (metrics) => validPurge(metrics, 'session'),
  legacy_cache_purge_complete: (metrics) => validPurge(metrics, 'cache'),
  theme_one_shot_migrated: validTheme,
  theme_current_precedence: validThemePrecedence,
  invalid_theme_retired: validInvalidTheme,
  inaccessible_storage_fail_closed: (metrics) => validCleanupFailure(metrics, 'inaccessible'),
  failed_removal_fail_closed: (metrics) => validCleanupFailure(metrics, 'throw'),
  no_progress_fail_closed: (metrics) => validCleanupFailure(metrics, 'no_progress'),
  unsupported_locks_fail_closed: validUnsupportedLocks,
  lifecycle_boundaries_complete: validLifecycle,
  private_api_cache_excluded: validPrivateCache,
  delete_only_privacy_sinks_clean: validPrivacySinks,
  unrelated_surfaces_preserved: validUnrelated,
  active_namespaces_nyayone_only: validActiveNamespaces,
  service_worker_reinstalled_active: validServiceWorker,
  runtime_identity_clean: validIdentity,
  s03_desktop_observed: (metrics) => validViewport(metrics, { width: 1440, height: 1024 }),
  s03_mobile_observed: (metrics) => validViewport(metrics, { width: 390, height: 844 }),
  screenshots_exact: validScreenshots,
  inherited_nyay5_contract_integrity: validInheritedNyay5Contract,
  evidence_sanitized: validSanitized,
  planted_mutants_killed: validMutants,
});

function privacyFindings(report) {
  const findings = [];
  const seen = new WeakSet();
  const visit = (value) => {
    if (typeof value === 'string') {
      // Cryptographic bindings are deliberately opaque and can coincidentally
      // contain phone-shaped digit runs; inspect every other string value.
      if (SHA256.test(value) || COMMIT.test(value)) return;
      for (const pattern of PRIVATE_EVIDENCE_PATTERNS) {
        if (pattern.test(value)) findings.push('private-evidence');
      }
      return;
    }
    if (value === null || typeof value !== 'object' || seen.has(value)) return;
    seen.add(value);
    for (const nested of Object.values(value)) visit(nested);
  };
  try {
    visit(report);
  } catch {
    findings.push('evidence-unserializable');
  }
  return [...new Set(findings)];
}

function screenshotArtifactsExact(screenshots) {
  if (!Array.isArray(screenshots)
    || screenshots.length !== NYAY18_SCREENSHOT_INVENTORY.length) return false;
  return screenshots.every((artifact, index) => {
    const expected = NYAY18_SCREENSHOT_INVENTORY[index];
    return exactKeys(artifact, ['bytes', 'height', 'name', 'sha256', 'width'])
      && artifact.name === expected.name
      && artifact.width === expected.width
      && artifact.height === expected.height
      && Number.isInteger(artifact.bytes)
      && artifact.bytes > 0
      && digest(artifact.sha256);
  });
}

export function inspectNyay18Evidence(report) {
  const findings = [];
  const topLevelKeys = [
    'exactCommit', 'exactParent', 'exactTree', 'executed', 'failed', 'failure', 'gate',
    'inventory', 'passed', 'previewServerSourceSha256', 'rows', 'schemaVersion',
    'screenshots', 'status', 'target', 'total',
  ];
  if (!exactKeys(report, topLevelKeys)) findings.push('schema');
  if (report?.schemaVersion !== 1
    || report?.gate !== 'nyay18_browser_namespace'
    || report?.target !== 'production-build-real-chromium') findings.push('identity');
  if (!COMMIT.test(report?.exactCommit ?? '')) findings.push('exact-commit');
  if (!COMMIT.test(report?.exactTree ?? '')) findings.push('exact-tree');
  if (report?.exactParent !== 'ROOT' && !COMMIT.test(report?.exactParent ?? '')) {
    findings.push('exact-parent');
  }
  if (!digest(report?.previewServerSourceSha256)) findings.push('preview-server-source');
  if (report?.executed !== true) findings.push('gate-unexecuted');
  if (!deepEqual(report?.inventory, expectedInventory())) findings.push('inventory');

  const rows = Array.isArray(report?.rows) ? report.rows : [];
  const ids = rows.map((entry) => entry?.id);
  const inventoryExact = deepEqual(ids, NYAY18_ASSERTION_INVENTORY);
  if (!inventoryExact) findings.push('row-inventory');
  let executed = 0;
  let failed = 0;
  for (const [index, id] of NYAY18_ASSERTION_INVENTORY.entries()) {
    const entry = rows[index];
    if (!exactKeys(entry, ['executed', 'id', 'metrics', 'pass']) || entry.id !== id) {
      failed += 1;
      continue;
    }
    if (entry.executed === true) executed += 1;
    if (entry.executed !== true || entry.pass !== true || !ROW_VALIDATORS[id](entry.metrics)) {
      failed += 1;
    }
  }
  if (rows.length !== NYAY18_ASSERTION_INVENTORY.length) {
    failed += Math.abs(rows.length - NYAY18_ASSERTION_INVENTORY.length) || 1;
  }
  if (executed !== NYAY18_ASSERTION_INVENTORY.length) findings.push('row-unexecuted');
  if (failed !== 0) findings.push('row-failed');

  if (!screenshotArtifactsExact(report?.screenshots)) findings.push('screenshots');
  findings.push(...privacyFindings(report));
  const expectedPassed = NYAY18_ASSERTION_INVENTORY.length;
  if (report?.total !== expectedPassed
    || report?.passed !== expectedPassed
    || report?.failed !== 0
    || report?.status !== 'PASS'
    || report?.failure !== null) findings.push('summary');
  const uniqueFindings = [...new Set(findings)];
  return {
    pass: uniqueFindings.length === 0,
    inventoryExact,
    executed,
    failed,
    findings: uniqueFindings,
  };
}

function validRows() {
  const localKeys = buildNyay18LegacyLocalSeedKeys();
  const cacheKeys = buildNyay18LegacyCacheSeedKeys();
  const sha = 'a'.repeat(64);
  const metrics = {
    runtime_chromium: { engine: 'chromium', headless: true, launches: 1, versionSha256: sha },
    required_environment_exact: {
      commitMatchesHead: true, commitRequired: true, outputAbsolute: true,
      outputOutsideRepository: true, parentMatchesHead: true, parentRequired: true,
      previewSourceMatches: true, treeMatchesHead: true, treeRequired: true, webOriginLoopback: true,
      webRequired: true, worktreeClean: true,
    },
    fresh_profiles_reload_strictmode: {
      contexts: 12, freshProfiles: 12, reloads: 2,
      strictModeRoot: true, strictModeSessionSettled: true,
    },
    anonymous_session_canonical: {
      canonicalBodies: 2, controls: 2, flowCookies: 2, flows: 2,
      denialCookieInventoryUnchanged: true, denialFlowAuthorityAbsent: true,
      denialFlowUnavailableProven: true, denialOtpControlsAbsent: true,
      denialRetiredInlineErrorAbsent: true, denialRoutesDenied: 2,
      getRequests: 2, otherRequests: 0, purposesExact: true, requestCount: 2,
      screens: 2, serverStateRequests: 2, sessionCookies: 0,
      sessionRequests: 2, startResponses: 2, stateResponses: 2, verifyControls: 2,
    },
    legacy_local_seed_complete: {
      exactFamilies: NYAY18_LEGACY_LOCAL_EXACT_KEYS.length,
      inventorySha256: digestLines(localKeys),
      prefixFamilies: NYAY18_LEGACY_LOCAL_PREFIXES.length,
      seededCount: localKeys.length,
      themeSeeded: true,
      unique: true,
    },
    legacy_session_seed_complete: {
      exactFamilies: NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
      inventorySha256: digestLines(NYAY18_LEGACY_SESSION_EXACT_KEYS),
      seededCount: NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
      unique: true,
    },
    legacy_cache_seed_complete: {
      inventorySha256: digestLines(cacheKeys),
      prefixFamilies: NYAY18_LEGACY_CACHE_PREFIXES.length,
      retiredCurrentSeeded: true,
      seededCount: cacheKeys.length,
      unique: true,
    },
    leading_unrelated_keys_preserved: {
      afterSha256: expectedInventory().leadingCandidates.sha256,
      beforeSha256: expectedInventory().leadingCandidates.sha256,
      candidateCount: NYAY18_LEADING_CANDIDATE_KEYS,
      candidateInventorySha256: expectedInventory().leadingCandidates.sha256,
      leadingBeforeOwned: true,
      preservedCount: NYAY18_LEADING_CANDIDATE_KEYS,
      selectionAttempts: 2,
      targetCandidates: NYAY18_LEADING_TARGET_KEYS,
      targetIndexBeforeBootstrap: 529,
      targetInventorySha256: expectedInventory().leadingTargets.sha256,
      targetRemoved: true,
      targetSurvivorsBeforeBootstrap: 1,
      unrelatedBeforeTarget: 529,
      valuesExact: true,
    },
    storage_clear_never_called: { localCalls: 0, sessionCalls: 0 },
    legacy_value_reads_theme_only: {
      localLegacyReads: 1, nonThemeLegacyReads: 0, sessionLegacyReads: 0, themeReads: 1,
    },
    legacy_local_purge_complete: {
      inventorySha256: digestLines(localKeys), remaining: 0, seededCount: localKeys.length,
    },
    legacy_session_purge_complete: {
      inventorySha256: digestLines(NYAY18_LEGACY_SESSION_EXACT_KEYS),
      remaining: 0,
      seededCount: NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
    },
    legacy_cache_purge_complete: {
      inventorySha256: digestLines(cacheKeys), remaining: 0, seededCount: cacheKeys.length,
    },
    theme_one_shot_migrated: {
      migratedDark: true, newThemePresent: true, oldThemeAbsent: true, oneShotRead: true,
    },
    theme_current_precedence: {
      currentLightPreserved: true, currentWon: true, legacyDarkSeeded: true,
      legacyThemeReads: 0, oldThemeAbsent: true,
    },
    invalid_theme_retired: {
      invalidLegacySeeded: true, invalidReadOnce: true,
      oldThemeAbsent: true, resolvedLight: true,
    },
    inaccessible_storage_fail_closed: {
      actionAttempts: 1, actionRejected: true, cookieInventoryUnchanged: true,
      cookieOperations: 0, flowAuthorityPreserved: true, mode: 'inaccessible',
      pendingAuthorityProven: true, pendingControlsProven: true,
      privateMounted: false, safeEntryVisible: true,
      unavailableVisible: true,
    },
    failed_removal_fail_closed: {
      actionAttempts: 1, actionRejected: true, cookieInventoryUnchanged: true,
      cookieOperations: 0, flowAuthorityPreserved: true, mode: 'throw',
      pendingAuthorityProven: true, pendingControlsProven: true,
      privateMounted: false, safeEntryVisible: true,
      unavailableVisible: true,
    },
    no_progress_fail_closed: {
      actionAttempts: 1, actionRejected: true, cookieInventoryUnchanged: true,
      cookieOperations: 0, flowAuthorityPreserved: true, mode: 'no_progress',
      pendingAuthorityProven: true, pendingControlsProven: true,
      privateMounted: false, safeEntryVisible: true,
      unavailableVisible: true,
    },
    unsupported_locks_fail_closed: {
      actionAttempts: 1, actionRejected: true, cookieOperations: 0,
      locksUnavailable: true, privateMounted: false,
      sessionRequests: 0, unavailableVisible: true,
    },
    lifecycle_boundaries_complete: {
      actionEndpointsExact: true, actorIdentifiersPerScenario: 2, actorKeyFamilies: 2,
      actorRotation: true, actorRotationRediscoveryResponses: 1,
      authoritativeRediscovery: 6,
      canonical401Requests: 2, canonicalLoss: true,
      coldActorKeysExpected: 24, coldActorKeysPurged: 24, completed: 6,
      currentThemePreserved: 6, deletion: true, deletionEndpointRequests: 1,
      expiry: true, logout: true, logoutEndpointRequests: 1,
      privateUnmountedLosses: 5, productionActions: 2, retiredAbsent: 6,
      revocation: true, scenarios: 6, transitionEnds: 5,
      teardownActorKeysExpected: 24, teardownActorKeysPurged: 24,
      transitionStarts: 5, unrelatedPreserved: 6,
    },
    private_api_cache_excluded: {
      apiEntries: 0, apiProbeRequests: 1, currentCacheEntries: 2, inspectedEntries: 2,
      currentIndexRestored: true, currentScopedMissExercised: true,
      hostileAssetCookieHeaders: 0, hostileAssetEntries: 0,
      hostileAssetExecuted: true, hostileAssetServerRequests: 1,
      hostileShellCookieHeaders: 0, hostileShellEntries: 0, hostileShellServerRequests: 1,
      installShellEntryPresent: true, installShellOfflineServed: true,
      privateEntries: 0, privateRouteProbeRequests: 1,
      publicEntriesExact: true, responseBodiesClean: true,
      retiredCurrentAbsent: true,
      unrelatedAssetPoisonServed: false, unrelatedPoisonEntriesPreserved: true,
      unrelatedShellPoisonServed: false,
    },
    delete_only_privacy_sinks_clean: {
      cacheFindings: 0, consoleFindings: 0, cookieFindings: 0,
      continuousCacheWrites: 0, continuousCookieWrites: 0, continuousDomWrites: 0,
      continuousHistoryWrites: 0, continuousStorageWrites: 0,
      domFindings: 0, historyFindings: 0, indexedDbCanaryWrites: 0,
      indexedDbDeleteCalls: 0, indexedDbFindings: 0, indexedDbOpenCalls: 0,
      indexedDbWriteCalls: 0, networkFindings: 0, newIndexedDbNames: 0,
      storageFindings: 0, urlFindings: 0,
      instrumentationCacheCanaryDetected: true,
      instrumentationCookieCanaryDetected: true,
      instrumentationDomCanaryDetected: true,
      instrumentationHistoryCanaryDetected: true,
      instrumentationStorageCanaryDetected: true,
      instrumentationDocumentCount: 2,
    },
    unrelated_surfaces_preserved: {
      cachePreserved: true, localPreserved: true, sessionPreserved: true,
      surfaceCount: 3, valuesExact: true,
    },
    active_namespaces_nyayone_only: {
      legacyCacheNames: 0, legacyCookieNames: 0, legacyGlobalNames: 0,
      legacyLocalNames: 0, legacySessionNames: 0, nyayOneOwnedNames: 2,
      unexpectedOwnedNames: 0,
    },
    service_worker_reinstalled_active: {
      active: true, controller: true, initialRegistrations: 1, registrations: 1,
      reinstalled: true, scriptPathExact: true, supported: true, unregistered: 1,
    },
    runtime_identity_clean: {
      bodyNyayOneVisible: true, brandSeparatorCanariesDetected: 6,
      legacyAriaMatches: 0, legacyBodyMatches: 0,
      legacyCookieMatches: 0, legacyDownloadMatches: 0, legacyGlobalMatches: 0,
      legacyTitleMatches: 0, titleExact: true,
    },
    s03_desktop_observed: {
      height: 1024, legacyVisibleMatches: 0, noHorizontalOverflow: true,
      routeExact: true, screenSelectorCount: 1, screenshotCaptured: true,
      visible: true, width: 1440,
    },
    s03_mobile_observed: {
      height: 844, legacyVisibleMatches: 0, noHorizontalOverflow: true,
      routeExact: true, screenSelectorCount: 1, screenshotCaptured: true,
      visible: true, width: 390,
    },
    screenshots_exact: {
      checksumsExact: true,
      count: NYAY18_SCREENSHOT_INVENTORY.length,
      dimensionsExact: true,
      inventorySha256: expectedInventory().screenshots.sha256,
    },
    inherited_nyay5_contract_integrity: {
      assertionInventoryExact: true, assertions: 22,
      contractMutantsAllKilled: true, failed: 0, mutantInventoryExact: true,
      mutants: 46, mutantsKilled: 46,
    },
    evidence_sanitized: { privacyFindings: 0, rawPrivateValuesIncluded: false },
    planted_mutants_killed: {
      allKilled: true,
      killed: NYAY18_PLANTED_MUTANT_NAMES.length,
      named: NYAY18_PLANTED_MUTANT_NAMES.length,
    },
  };
  return NYAY18_ASSERTION_INVENTORY.map((id) => ({
    id, executed: true, pass: true, metrics: metrics[id],
  }));
}

export function makeValidNyay18EvidenceFixture() {
  return {
    schemaVersion: 1,
    gate: 'nyay18_browser_namespace',
    target: 'production-build-real-chromium',
    exactCommit: '1'.repeat(40),
    exactTree: '2'.repeat(40),
    exactParent: '3'.repeat(40),
    previewServerSourceSha256: '4'.repeat(64),
    executed: true,
    status: 'PASS',
    total: NYAY18_ASSERTION_INVENTORY.length,
    passed: NYAY18_ASSERTION_INVENTORY.length,
    failed: 0,
    inventory: expectedInventory(),
    rows: validRows(),
    screenshots: NYAY18_SCREENSHOT_INVENTORY.map((entry, index) => ({
      ...entry,
      bytes: index + 1,
      sha256: String(index + 2).repeat(64),
    })),
    failure: null,
  };
}

function fixtureRow(report, id) {
  return report.rows.find((entry) => entry.id === id);
}

const MUTATORS = Object.freeze({
  'missing-required-row': (report) => { report.rows.pop(); },
  'reordered-required-rows': (report) => { [report.rows[0], report.rows[1]] = [report.rows[1], report.rows[0]]; },
  'duplicate-required-row': (report) => { report.rows.push(structuredClone(report.rows[0])); },
  'unexecuted-required-row': (report) => { fixtureRow(report, 'runtime_identity_clean').executed = false; },
  'failed-required-row': (report) => { fixtureRow(report, 'runtime_identity_clean').pass = false; },
  'bad-exact-commit': (report) => { report.exactCommit = 'deadbeef'; },
  'bad-exact-tree': (report) => { report.exactTree = 'deadbeef'; },
  'bad-exact-parent': (report) => { report.exactParent = 'not-a-parent'; },
  'bad-preview-server-source-sha': (report) => { report.previewServerSourceSha256 = 'bad'; },
  'dirty-worktree': (report) => { fixtureRow(report, 'required_environment_exact').metrics.worktreeClean = false; },
  'non-chromium-runtime': (report) => { fixtureRow(report, 'runtime_chromium').metrics.engine = 'webkit'; },
  'noncanonical-anonymous-session': (report) => { fixtureRow(report, 'anonymous_session_canonical').metrics.canonicalBodies = 0; },
  'pending-flow-authority-unproven': (report) => { fixtureRow(report, 'anonymous_session_canonical').metrics.startResponses = 1; },
  'pending-flow-controls-missing': (report) => { fixtureRow(report, 'anonymous_session_canonical').metrics.controls = 1; },
  'undersized-local-seed': (report) => { fixtureRow(report, 'legacy_local_seed_complete').metrics.seededCount = 256; },
  'missing-local-family': (report) => { fixtureRow(report, 'legacy_local_seed_complete').metrics.prefixFamilies -= 1; },
  'undersized-cache-seed': (report) => { fixtureRow(report, 'legacy_cache_seed_complete').metrics.seededCount = 256; },
  'undersized-leading-unrelated-seed': (report) => { fixtureRow(report, 'leading_unrelated_keys_preserved').metrics.targetIndexBeforeBootstrap = 256; },
  'leading-target-survived': (report) => { fixtureRow(report, 'leading_unrelated_keys_preserved').metrics.targetRemoved = false; },
  'storage-clear-called': (report) => { fixtureRow(report, 'storage_clear_never_called').metrics.localCalls = 1; },
  'non-theme-legacy-read': (report) => { fixtureRow(report, 'legacy_value_reads_theme_only').metrics.nonThemeLegacyReads = 1; },
  'retained-legacy-local': (report) => { fixtureRow(report, 'legacy_local_purge_complete').metrics.remaining = 1; },
  'retained-legacy-session': (report) => { fixtureRow(report, 'legacy_session_purge_complete').metrics.remaining = 1; },
  'retained-legacy-cache': (report) => { fixtureRow(report, 'legacy_cache_purge_complete').metrics.remaining = 1; },
  'failed-theme-migration': (report) => { fixtureRow(report, 'theme_one_shot_migrated').metrics.oldThemeAbsent = false; },
  'overwritten-current-theme': (report) => { fixtureRow(report, 'theme_current_precedence').metrics.currentWon = false; },
  'retained-invalid-theme': (report) => { fixtureRow(report, 'invalid_theme_retired').metrics.oldThemeAbsent = false; },
  'inaccessible-storage-mounted-private': (report) => { fixtureRow(report, 'inaccessible_storage_fail_closed').metrics.privateMounted = true; },
  'failed-removal-mounted-private': (report) => { fixtureRow(report, 'failed_removal_fail_closed').metrics.privateMounted = true; },
  'no-progress-mounted-private': (report) => { fixtureRow(report, 'no_progress_fail_closed').metrics.privateMounted = true; },
  'cleanup-failure-vacuous-action': (report) => { fixtureRow(report, 'inaccessible_storage_fail_closed').metrics.actionAttempts = 0; },
  'cleanup-failure-pending-control-unproven': (report) => { fixtureRow(report, 'inaccessible_storage_fail_closed').metrics.pendingControlsProven = false; },
  'cleanup-failure-mutated-cookie-authority': (report) => { fixtureRow(report, 'inaccessible_storage_fail_closed').metrics.cookieInventoryUnchanged = false; },
  'cleanup-failure-safe-entry-missing': (report) => { fixtureRow(report, 'inaccessible_storage_fail_closed').metrics.safeEntryVisible = false; },
  'cleanup-failure-pending-authority-unproven': (report) => { fixtureRow(report, 'inaccessible_storage_fail_closed').metrics.pendingAuthorityProven = false; },
  'unsupported-locks-cookie-work': (report) => { fixtureRow(report, 'unsupported_locks_fail_closed').metrics.cookieOperations = 1; },
  'unsupported-locks-vacuous-action': (report) => { fixtureRow(report, 'unsupported_locks_fail_closed').metrics.actionAttempts = 0; },
  'missing-lifecycle-scenario': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.completed = 5; },
  'lifecycle-bypassed-production-action': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.productionActions = 1; },
  'lifecycle-missing-canonical-401': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.canonical401Requests = 1; },
  'lifecycle-missing-transition': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.transitionStarts = 4; },
  'actor-rotation-unobserved': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.actorRotationRediscoveryResponses = 0; },
  'cold-actor-keys-survived-private-mount': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.coldActorKeysPurged = 5; },
  'profile-id-actor-key-survived-teardown': (report) => { fixtureRow(report, 'lifecycle_boundaries_complete').metrics.teardownActorKeysPurged = 23; },
  'cached-private-api-response': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.apiEntries = 1; },
  'unexercised-private-cache-probe': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.privateRouteProbeRequests = 0; },
  'unexercised-hostile-asset-probe': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.hostileAssetServerRequests = 0; },
  'cookie-bearing-hostile-asset-fetch': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.hostileAssetCookieHeaders = 1; },
  'cached-hostile-private-asset': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.hostileAssetEntries = 1; },
  'unexercised-hostile-shell-probe': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.hostileShellServerRequests = 0; },
  'cookie-bearing-hostile-shell-fetch': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.hostileShellCookieHeaders = 1; },
  'cached-hostile-private-shell': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.hostileShellEntries = 1; },
  'missing-install-created-shell': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.installShellEntryPresent = false; },
  'offline-install-shell-unserved': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.installShellOfflineServed = false; },
  'served-unrelated-asset-poison': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.unrelatedAssetPoisonServed = true; },
  'served-unrelated-shell-poison': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.unrelatedShellPoisonServed = true; },
  'deleted-unrelated-poison': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.unrelatedPoisonEntriesPreserved = false; },
  'delete-only-value-in-sink': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.consoleFindings = 1; },
  'transient-dom-private-write': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.continuousDomWrites = 1; },
  'transient-cache-private-write': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.continuousCacheWrites = 1; },
  'transient-cookie-private-write': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.continuousCookieWrites = 1; },
  'transient-history-private-write': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.continuousHistoryWrites = 1; },
  'transient-storage-private-write': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.continuousStorageWrites = 1; },
  'privacy-instrumentation-canary-missed': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.instrumentationHistoryCanaryDetected = false; },
  'single-privacy-probe-document': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.instrumentationDocumentCount = 1; },
  'indexeddb-private-write': (report) => { fixtureRow(report, 'delete_only_privacy_sinks_clean').metrics.indexedDbCanaryWrites = 1; },
  'missing-strictmode-reload': (report) => { fixtureRow(report, 'fresh_profiles_reload_strictmode').metrics.reloads = 0; },
  'inherited-nyay5-contract-failed': (report) => { fixtureRow(report, 'inherited_nyay5_contract_integrity').metrics.failed = 1; },
  'retained-current-brand-cache': (report) => { fixtureRow(report, 'private_api_cache_excluded').metrics.retiredCurrentAbsent = false; },
  'deleted-unrelated-canary': (report) => { fixtureRow(report, 'unrelated_surfaces_preserved').metrics.localPreserved = false; },
  'active-legacy-name': (report) => { fixtureRow(report, 'active_namespaces_nyayone_only').metrics.legacyLocalNames = 1; },
  'inactive-service-worker': (report) => { fixtureRow(report, 'service_worker_reinstalled_active').metrics.active = false; },
  'visible-legacy-brand': (report) => { fixtureRow(report, 'runtime_identity_clean').metrics.legacyTitleMatches = 1; },
  'brand-separator-canary-missed': (report) => { fixtureRow(report, 'runtime_identity_clean').metrics.brandSeparatorCanariesDetected = 5; },
  'wrong-desktop-geometry': (report) => { fixtureRow(report, 's03_desktop_observed').metrics.width = 1439; },
  'wrong-mobile-geometry': (report) => { fixtureRow(report, 's03_mobile_observed').metrics.height = 843; },
  'missing-screenshot': (report) => { report.screenshots.pop(); },
  'private-evidence': (report) => { report.rawPrivateValue = 'Bearer nyay18-private-local-value'; },
  'unchecked-planted-mutant': (report) => { fixtureRow(report, 'planted_mutants_killed').metrics.killed -= 1; },
});

export function runNyay18ContractSelfTest() {
  const results = NYAY18_PLANTED_MUTANT_NAMES.map((name) => {
    const fixture = makeValidNyay18EvidenceFixture();
    MUTATORS[name](fixture);
    return { name, killed: inspectNyay18Evidence(fixture).pass === false };
  });
  const killed = results.filter((entry) => entry.killed).length;
  return {
    names: [...NYAY18_PLANTED_MUTANT_NAMES],
    named: NYAY18_PLANTED_MUTANT_NAMES.length,
    killed,
    allKilled: killed === NYAY18_PLANTED_MUTANT_NAMES.length,
    results,
  };
}

export function nyay18Sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

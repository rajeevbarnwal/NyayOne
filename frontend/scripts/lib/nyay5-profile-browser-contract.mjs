const UUID_TEXT = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/iu;
const EMAIL_TEXT = /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/iu;
const MOBILE_TEXT = /(?<!\d)[6-9]\d{9}(?!\d)/u;
const DOB_TEXT = /\b(?:19|20)\d{2}-\d{2}-\d{2}\b/u;
const URL_CREDENTIAL = /https?:\/\/[^\s/@]+:[^\s/@]+@/iu;
const TOKEN_TEXT = /\b(?:bearer\s+|eyJ)[A-Za-z0-9._~+/-]{12,}/iu;

const FORBIDDEN_KEYS = new Set([
  'access_token',
  'actor',
  'actor_id',
  'authorization',
  'bearer',
  'cookie',
  'cookies',
  'date_of_birth',
  'dob',
  'email',
  'first_name',
  'guardian_name',
  'last_name',
  'middle_name',
  'mobile',
  'otp',
  'password',
  'profile_id',
  'refresh_token',
  'registration_id',
  'session_token',
  'student_profile_id',
  'token',
  'user_id',
]);

export const NYAY5_ASSERTION_INVENTORY = Object.freeze([
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
]);

// Exact IDs from the authoritative Option 3.2 acceptance matrix.  The values
// below are executable gate assertion IDs, never prose-only evidence.  A
// single assertion may satisfy more than one matrix row only when it performs
// all of those observations in the same runtime probe.
export const NYAY5_ACCEPTANCE_MATRIX_IDS = Object.freeze([
  'UX-01', 'UX-02', 'UX-03', 'UX-04', 'UX-05', 'UX-06',
  'AUTH-00', 'AUTH-01', 'AUTH-02', 'AUTH-03', 'AUTH-04', 'AUTH-05',
  'AUTH-06', 'AUTH-07', 'AUTH-08', 'AUTH-09',
  'REG-01', 'REG-02', 'REG-03', 'REG-04', 'REG-05',
  'OWN-01', 'OWN-02', 'OWN-03', 'OWN-04',
  'ROUTE-01', 'ROUTE-02', 'ROUTE-03', 'ROUTE-04', 'ROUTE-05', 'ROUTE-06',
  'PROFILE-01', 'PROFILE-02', 'PROFILE-03', 'PROFILE-04', 'PROFILE-05',
  'PROFILE-06', 'PROFILE-07', 'PROFILE-08', 'PROFILE-09', 'PROFILE-10',
  'PROFILE-11',
  'POPUP-01', 'POPUP-02', 'POPUP-03', 'POPUP-04',
  'GUARD-01', 'GUARD-02', 'GUARD-03', 'GUARD-04', 'GUARD-05',
  'A11Y-01', 'A11Y-02', 'A11Y-03', 'A11Y-04',
  'QA-01', 'QA-02', 'QA-03', 'QA-04', 'QA-05', 'QA-06',
]);

const BROWSER = (id) => `browser:${id}`;
const POSTGRES = (id) => `postgres:${id}`;
const OTP_POSTGRES = (id) => `nyay4-postgres:${id}`;

export const NYAY5_ACCEPTANCE_EXECUTION_MAP = Object.freeze({
  'UX-01': [BROWSER('s03_gateway_actions')],
  'UX-02': [BROWSER('redesigned_heading_stack')],
  'UX-03': [BROWSER('svg_icon_census')],
  'UX-04': [BROWSER('responsive_targets_and_no_overflow')],
  'UX-05': [BROWSER('responsive_targets_and_no_overflow')],
  'UX-06': [BROWSER('rebrand_visible_copy'), BROWSER('browser_persistence_inventory_clean')],
  'AUTH-00': [BROWSER('passwordless_surfaces')],
  'AUTH-01': [BROWSER('otp_exact_success_navigation')],
  'AUTH-02': [
    BROWSER('otp_input_accessibility'),
    OTP_POSTGRES('CONTRACT-LOCKOUT-SURVIVES-RESEND'),
    OTP_POSTGRES('CONCURRENCY-WRONG-VERIFY-CUMULATIVE'),
    OTP_POSTGRES('CONTRACT-RATE-BUDGETS-IDENTITY-IP-GLOBAL'),
    OTP_POSTGRES('CONTRACT-SERVER-METADATA-TYPED-OUTCOMES'),
  ],
  'AUTH-03': [
    OTP_POSTGRES('CONCURRENCY-RESEND-ONE-STAGED-ONE-ACTIVE'),
    OTP_POSTGRES('CONTRACT-FAILED-RESEND-PRESERVES-ACTIVE'),
    OTP_POSTGRES('CONTRACT-PROVIDER-IDEMPOTENCY-EXACTLY-ONCE'),
    OTP_POSTGRES('CONTRACT-RETRY-BACKOFF-EXHAUSTION-ERASURE'),
  ],
  'AUTH-04': [OTP_POSTGRES('CONTRACT-PREAUTH-ENUMERATION-NEUTRAL')],
  'AUTH-05': [
    BROWSER('s15_anonymous_disabled'),
    POSTGRES('CONTRACT-VERIFICATION-SELF-AUTHORITY-DENIED'),
  ],
  'AUTH-06': [
    BROWSER('browser_persistence_inventory_clean'),
    BROWSER('evidence_privacy_and_mutants'),
    BROWSER('cross_realm_auth_transition_barrier'),
  ],
  'AUTH-07': [
    BROWSER('signup_session_atomic_wire'),
    BROWSER('cross_realm_auth_transition_barrier'),
    OTP_POSTGRES('CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY'),
  ],
  'AUTH-08': [OTP_POSTGRES('CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY')],
  'AUTH-09': [OTP_POSTGRES('CONTRACT-SERVER-METADATA-TYPED-OUTCOMES')],
  'REG-01': [POSTGRES('CONTRACT-REGISTRATION-CONSENT-ZERO-MUTATION')],
  'REG-02': [BROWSER('s08_field_contract')],
  'REG-03': [POSTGRES('CONTRACT-REGISTRATION-ENUMERATION-NEUTRAL')],
  'REG-04': [
    BROWSER('s08_separate_consent_controls'),
    POSTGRES('CONTRACT-REGISTRATION-CONSENT-ZERO-MUTATION'),
  ],
  'REG-05': [BROWSER('unicode_legal_name_corpus')],
  'OWN-01': [POSTGRES('CONTRACT-ANONYMOUS-EXPIRED-REVOKED-DELETED-WRONG-ROLE')],
  'OWN-02': [
    BROWSER('cross_user_denied'),
    POSTGRES('CONTRACT-CROSS-USER-CLIENT-SELECTOR-DENIED'),
  ],
  'OWN-03': [POSTGRES('CONTRACT-VERIFICATION-SELF-AUTHORITY-DENIED')],
  'OWN-04': [
    BROWSER('production_actor_channel_exact'),
    POSTGRES('CONTRACT-NONTEST-ACTOR-HEADER-REJECTED'),
  ],
  'ROUTE-01': [BROWSER('s07_prompt_host')],
  'ROUTE-02': [BROWSER('prompt_session_scoped')],
  'ROUTE-03': [BROWSER('s15_back_to_dashboard_exact')],
  'ROUTE-04': [BROWSER('auth_route_mapping')],
  'ROUTE-05': [BROWSER('denial_matrix_fail_closed')],
  'ROUTE-06': [BROWSER('direct_step_skip_denied')],
  'PROFILE-01': [BROWSER('single_authoritative_projection')],
  'PROFILE-02': [POSTGRES('CONTRACT-COMPLETION-V1-DETERMINISTIC')],
  'PROFILE-03': [POSTGRES('CONTRACT-COMPLETION-V1-DETERMINISTIC')],
  'PROFILE-04': [BROWSER('confirmed_success_before_navigation')],
  'PROFILE-05': [
    BROWSER('typed_failures_retain_route_and_values'),
    BROWSER('canonical_401_draft_handoff'),
  ],
  'PROFILE-06': [BROWSER('uncertain_write_reconciles')],
  'PROFILE-07': [BROWSER('reload_new_tab_resume')],
  'PROFILE-08': [BROWSER('direct_step_skip_denied')],
  'PROFILE-09': [BROWSER('field_validation_no_bypass')],
  'PROFILE-10': [BROWSER('stale_multi_tab_conflict')],
  'PROFILE-11': [POSTGRES('CONTRACT-NORMALIZED-IDENTITY-NO-DUPLICATION')],
  'POPUP-01': [BROWSER('prompt_session_scoped')],
  'POPUP-02': [BROWSER('dialog_focus_and_inert_contract')],
  'POPUP-03': [BROWSER('prompt_lifecycle_teardown')],
  'POPUP-04': [BROWSER('completion_cards_until_100')],
  'GUARD-01': [POSTGRES('CONTRACT-DOB-GUARDIAN-ATOMIC')],
  'GUARD-02': [POSTGRES('CONTRACT-DOB-GUARDIAN-ATOMIC')],
  'GUARD-03': [POSTGRES('CONTRACT-VERIFICATION-SELF-AUTHORITY-DENIED')],
  'GUARD-04': [POSTGRES('CONTRACT-AUTHORIZED-TRANSITIONS-EXACT')],
  'GUARD-05': [BROWSER('limited_reload_login_direct')],
  'A11Y-01': [BROWSER('accessible_errors_and_controls')],
  'A11Y-02': [BROWSER('otp_input_accessibility')],
  'A11Y-03': [BROWSER('dialog_focus_and_inert_contract')],
  'A11Y-04': [BROWSER('responsive_targets_and_no_overflow')],
  'QA-01': [
    'native:frontend-typecheck', 'native:frontend-lint',
    'native:frontend-unit', 'native:frontend-production-build',
  ],
  'QA-02': [
    POSTGRES('RUNTIME-POSTGRES-16-PGVECTOR'),
    POSTGRES('MIGRATION-0020-0021-FORWARD-IMMUTABLE'),
    POSTGRES('MIGRATION-POPULATED-ROUNDTRIP-ATOMIC'),
    POSTGRES('SCHEMA-PROFILE-BOUNDARY-EXACT'),
    POSTGRES('CONTRACT-OPTIMISTIC-CONCURRENCY'),
  ],
  'QA-03': [
    BROWSER('runtime_chromium'),
    BROWSER('responsive_targets_and_no_overflow'),
    BROWSER('otp_input_accessibility'),
    BROWSER('verification_distinct_from_completion'),
  ],
  'QA-04': [
    'evidence:browser-report', 'evidence:screenshots', 'evidence:service-logs',
    'evidence:privacy-scan', 'evidence:sha256-manifest',
  ],
  'QA-05': [
    'ci:policy-verifier', 'ci:required-job-fail-closed', 'ci:prospective-merge',
  ],
  'QA-06': ['evidence:acceptance-execution-map'],
});

export const NYAY5_SELECTOR_EXECUTION_IDS = Object.freeze([
  BROWSER('s03_gateway_actions'),
  BROWSER('redesigned_heading_stack'),
  BROWSER('svg_icon_census'),
  BROWSER('responsive_targets_and_no_overflow'),
  BROWSER('rebrand_visible_copy'),
  BROWSER('passwordless_surfaces'),
  BROWSER('otp_exact_success_navigation'),
  BROWSER('otp_input_accessibility'),
  BROWSER('s15_anonymous_disabled'),
  BROWSER('s08_field_contract'),
  BROWSER('s08_separate_consent_controls'),
  BROWSER('s07_prompt_host'),
  BROWSER('s15_back_to_dashboard_exact'),
  BROWSER('auth_route_mapping'),
  BROWSER('denial_matrix_fail_closed'),
  BROWSER('direct_step_skip_denied'),
  BROWSER('single_authoritative_projection'),
  BROWSER('confirmed_success_before_navigation'),
  BROWSER('typed_failures_retain_route_and_values'),
  BROWSER('canonical_401_draft_handoff'),
  BROWSER('cross_realm_auth_transition_barrier'),
  BROWSER('uncertain_write_reconciles'),
  BROWSER('reload_new_tab_resume'),
  BROWSER('field_validation_no_bypass'),
  BROWSER('stale_multi_tab_conflict'),
  BROWSER('prompt_session_scoped'),
  BROWSER('dialog_focus_and_inert_contract'),
  BROWSER('prompt_lifecycle_teardown'),
  BROWSER('completion_cards_until_100'),
  BROWSER('limited_reload_login_direct'),
  BROWSER('accessible_errors_and_controls'),
  BROWSER('verification_distinct_from_completion'),
]);

const NYAY5_REQUIRED_BROWSER_EXECUTION_IDS = Object.freeze([
  ...new Set(
    Object.values(NYAY5_ACCEPTANCE_EXECUTION_MAP)
      .flat()
      .filter((id) => id.startsWith('browser:')),
  ),
]);

export function summarizeNyay5BrowserFailure(report) {
  const rows = Array.isArray(report?.rows) ? report.rows : [];
  const rowByName = new Map(rows.map((row) => [row?.name, row]));
  const failedAssertions = NYAY5_ASSERTION_INVENTORY.filter(
    (name) => rowByName.get(name)?.pass !== true,
  );
  const executions = Array.isArray(report?.executions) ? report.executions : [];
  const executionById = new Map(executions.map((row) => [row?.id, row]));
  const invalidExecutionIds = NYAY5_REQUIRED_BROWSER_EXECUTION_IDS.filter((id) => {
    const row = executionById.get(id);
    const selectorRequired = NYAY5_SELECTOR_EXECUTION_IDS.includes(id);
    return row?.executed !== true
      || row?.skipped !== false
      || row?.pass !== true
      || !Number.isSafeInteger(row?.evidenceCount)
      || row.evidenceCount <= 0
      || (selectorRequired && (
        !Number.isSafeInteger(row?.selectorCount) || row.selectorCount <= 0
      ));
  });
  const coverage = report?.acceptanceExecutionCoverage;
  const safeCount = (value) => (
    Number.isSafeInteger(value) && value >= 0 ? value : null
  );
  const safeFailureClass = typeof report?.failureClass === 'string'
    && /^(?:Error|[A-Z][A-Za-z0-9]{0,30}Error[0-9]?)$/u.test(report.failureClass)
    ? report.failureClass : null;
  const safeFailureStage = typeof report?.failureStage === 'string'
    && /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/u.test(report.failureStage)
    ? report.failureStage : null;
  const safeFailureCode = typeof report?.failureCode === 'string'
    && /^NYAY5_[A-Z0-9_]+$|^RUNTIME_ASSERTION_FAILED$/u.test(report.failureCode)
    ? report.failureCode : null;

  return {
    failedAssertions,
    invalidExecutionIds,
    failureClass: safeFailureClass,
    failureStage: safeFailureStage,
    failureCode: safeFailureCode,
    coverage: {
      mapped: safeCount(coverage?.mapped),
      missing: safeCount(coverage?.missing),
      skipped: safeCount(coverage?.skipped),
      unknown: safeCount(coverage?.unknown),
      unique: typeof coverage?.unique === 'boolean' ? coverage.unique : null,
    },
  };
}

function inspectExecutionCoverage(executions, prefix = null) {
  const mappedIds = Object.keys(NYAY5_ACCEPTANCE_EXECUTION_MAP);
  const rows = Array.isArray(executions) ? executions : [];
  const executionIds = rows.map((row) => row?.id);
  const allRequired = [...new Set(Object.values(NYAY5_ACCEPTANCE_EXECUTION_MAP).flat())];
  const requiredExecutionIds = new Set(prefix === null
    ? allRequired : allRequired.filter((id) => id.startsWith(prefix)));
  const uniqueEvidence = executionIds.length === new Set(executionIds).size;
  const exactMap = mappedIds.length === NYAY5_ACCEPTANCE_MATRIX_IDS.length
    && mappedIds.every((id, index) => id === NYAY5_ACCEPTANCE_MATRIX_IDS[index])
    && new Set(mappedIds).size === mappedIds.length
    && Object.values(NYAY5_ACCEPTANCE_EXECUTION_MAP).every((ids) => (
      Array.isArray(ids) && ids.length > 0 && new Set(ids).size === ids.length
    ));
  const evidence = new Map(rows.map((row) => [row?.id, row]));
  const mappedResults = NYAY5_ACCEPTANCE_MATRIX_IDS.map((matrixId) => {
    const ids = NYAY5_ACCEPTANCE_EXECUTION_MAP[matrixId] ?? [];
    const scopedIds = prefix === null ? ids : ids.filter((id) => id.startsWith(prefix));
    if (scopedIds.length === 0) return true;
    return scopedIds.every((id) => {
      const row = evidence.get(id);
      const selectorRequired = NYAY5_SELECTOR_EXECUTION_IDS.includes(id);
      return row?.executed === true
        && row?.skipped === false
        && row?.pass === true
        && Number.isSafeInteger(row?.evidenceCount)
        && row.evidenceCount > 0
        && (!selectorRequired || (
          Number.isSafeInteger(row?.selectorCount) && row.selectorCount > 0
        ));
    });
  });
  const unknownEvidence = executionIds.filter((id) => !requiredExecutionIds.has(id)).length;
  const skipped = rows.filter((row) => row?.skipped === true).length;
  const missing = mappedResults.filter((pass) => !pass).length;
  return {
    pass: exactMap && uniqueEvidence && unknownEvidence === 0 && skipped === 0 && missing === 0,
    mapped: exactMap ? mappedIds.length : 0,
    missing,
    skipped,
    unknown: unknownEvidence,
    unique: uniqueEvidence,
  };
}

export function inspectAcceptanceExecutionCoverage(executions) {
  return inspectExecutionCoverage(executions, null);
}

export function inspectBrowserExecutionCoverage(executions) {
  return inspectExecutionCoverage(executions, 'browser:');
}

export const NYAY5_REQUIRED_STORAGE_SURFACES = Object.freeze([
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

export const NYAY5_SEEDED_MUTANT_INVENTORY = Object.freeze([
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
]);

function canonicalKey(value) {
  return String(value)
    .replace(/([a-z0-9])([A-Z])/gu, '$1_$2')
    .replace(/[^a-z0-9]+/giu, '_')
    .replace(/^_+|_+$/gu, '')
    .toLowerCase();
}

function isRedacted(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return true;
  if (typeof value !== 'string') return false;
  return /^(?:\[?redacted\]?|masked|none|not[_ -]?stored|null|omitted|removed|synthetic)$/iu
    .test(value.trim());
}

export function scanNyay5Evidence(value) {
  const findings = new Set();
  const visit = (candidate, path = 'report') => {
    if (Array.isArray(candidate)) {
      candidate.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    if (candidate && typeof candidate === 'object') {
      Object.entries(candidate).forEach(([key, item]) => {
        const normalized = canonicalKey(key);
        if (FORBIDDEN_KEYS.has(normalized) && !isRedacted(item)) {
          findings.add(`${path}.${normalized}:forbidden_key`);
        }
        visit(item, `${path}.${normalized}`);
      });
      return;
    }
    if (typeof candidate !== 'string') return;
    for (const [label, pattern] of [
      ['uuid', UUID_TEXT],
      ['email', EMAIL_TEXT],
      ['mobile', MOBILE_TEXT],
      ['dob', DOB_TEXT],
      ['credential_url', URL_CREDENTIAL],
      ['token', TOKEN_TEXT],
    ]) {
      if (pattern.test(candidate)) findings.add(`${path}:${label}`);
    }
  };
  visit(value);
  return [...findings].sort();
}

export function summarizeNyay5Rows(rows) {
  const names = Array.isArray(rows) ? rows.map((row) => row?.name) : [];
  const exact = names.length === NYAY5_ASSERTION_INVENTORY.length
    && names.every((name, index) => name === NYAY5_ASSERTION_INVENTORY[index])
    && new Set(names).size === names.length
    && rows.every((row) => (
      row
      && Object.prototype.hasOwnProperty.call(row, 'pass')
      && typeof row.pass === 'boolean'
    ));
  const failedRows = Array.isArray(rows) ? rows.filter((row) => row?.pass !== true) : [];
  const failed = exact ? failedRows.length : Math.max(1, failedRows.length);
  return {
    total: Array.isArray(rows) ? rows.length : 0,
    passed: exact ? rows.length - failedRows.length : 0,
    failed,
    inventoryExact: exact,
    overallPass: exact && failedRows.length === 0,
  };
}

export function inspectPendingSessionObservation(value) {
  return {
    pass: Boolean(value?.sessionPending === true
      && value?.privateMounted === 0
      && value?.privateRequestCount === 0),
  };
}

export function inspectDenialObservation(value) {
  return {
    pass: Boolean(value?.anonymousDenied === true
      && value?.expiredDenied === true
      && value?.revokedDenied === true
      && value?.deletedDenied === true
      && value?.wrongRoleDenied === true
      && value?.privateRequestCount === 0),
  };
}

export function inspectConfirmedWriteObservation(value) {
  return {
    pass: Boolean(value?.serverSettled === true
      && value?.status === 200
      && value?.heldBeforeNavigation === true
      && value?.navigated === true),
  };
}

export function inspectTypedFailureObservation(value) {
  return {
    pass: Boolean(Number.isSafeInteger(value?.status)
      && value.status >= 400
      && value?.routeRetained === true
      && value?.valuesRetained === true
      && value?.errorRole === 'alert'),
  };
}

const TYPED_FAILURE_KINDS = Object.freeze([
  'missing_context', '401', '403', '409', '422', '429', '500',
  'abort', 'timeout', 'network',
]);

const TYPED_FAILURE_MESSAGES = Object.freeze({
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
});

export function inspectTypedFailureMatrix(rows) {
  const values = Array.isArray(rows) ? rows : [];
  const exact = values.length === TYPED_FAILURE_KINDS.length
    && values.every((row, index) => row?.kind === TYPED_FAILURE_KINDS[index])
    && new Set(values.map((row) => row?.kind)).size === values.length;
  const expectedStatus = (kind) => (
    ['abort', 'timeout', 'network'].includes(kind) ? null : Number(kind) || 422
  );
  const verdicts = values.map((row) => {
    const common = row?.status === expectedStatus(row?.kind)
      && row?.routeRetained === true
      && row?.valuesRetained === true
      && row?.errorVisible === true
      && row?.errorText === TYPED_FAILURE_MESSAGES[row?.kind];
    if (row?.kind !== '401') return Boolean(common && row?.errorRole === 'alert');
    return Boolean(common
      && row?.errorRole === 'status'
      && ['authentication_required', 'session_authority_required']
        .includes(row?.canonicalCode)
      && row?.pendingObserved === true
      && row?.privateUnmounted === true
      && row?.anonymousObserved === true
      && row?.sameActorResolved === true
      && row?.restoredSelectorCount === 1
      && row?.profilePatchCount === 1
      && row?.automaticRetryCount === 0
      && row?.browserPersistenceClean === true);
  });
  return {
    pass: exact && verdicts.every(Boolean),
    exact,
    total: values.length,
    passed: verdicts.filter(Boolean).length,
  };
}

export function inspectCrossRealmTransitionObservation(value) {
  return {
    pass: Boolean(
      value?.delayedPeerObserved === true
      && value?.verifyRequestsBeforeDelayedPeer === 0
      && value?.pendingSelectorCount === 1
      && value?.privateMountedBeforeVerify === 0
      && value?.verifyRequestsBeforeInflightRelease === 0
      && value?.verifyRequests === 1
      && value?.oldActorPatchCount === 1
      && value?.oldActorAutomaticRetryCount === 0
      && value?.postStartOldActorMutationRequests === 0
      && value?.profilePostStartAttemptObserved === true
      && value?.newPageSessionRequestsBeforeEnd === 0
      && value?.newActorProjectionUnchanged === true
      && value?.transitionMessagesExact === true
      && value?.transitionMessagePrivateFindings === 0
      && value?.missingPrimitivesUnavailable === true
      && value?.missingPrimitivesPrivateRequests === 0
      && value?.inaccessibleStorageUnavailable === true
      && value?.peerNackVerifyRequests === 0
      && value?.peerNackSessionCookieUnchanged === true
      && value?.m01HolderCompletionControls === 2
      && value?.m01AttackerCompletionControls === 2
      && value?.m01ServerSettledStatus === 200
      && value?.m01VerifyRequestsBeforeResponseRelease === 0
      && value?.m01VerifyRequests === 1
      && value?.m01CompletionRequests === 1
      && value?.m01CommitExactlyOnce === true
      && value?.m01FirstTargetCompleted === true
      && value?.m01FirstTargetAttendanceRecorded === true
      && value?.m01PostStartSecondTargetRequests === 0
      && value?.m01PostStartAttemptObserved === true
      && value?.m01PrivateControlsAfterTransitionStart === 0
      && value?.m01PrivateUiUnmounted === true
      && value?.m01SecondTargetUntouched === true
    ),
  };
}

function exactTransitionTrace(trace) {
  if (!Array.isArray(trace)) return false;
  return trace.every((row, index) => (
    exactKeys(row, ['direction', 'message', 'sequence'])
    && ['receive', 'send'].includes(row.direction)
    && row.sequence === index + 1
    && exactKeys(row.message, ['kind', 'sender', 'transition', 'version'])
    && row.message.version === 2
    && ['ack', 'end', 'nack', 'start'].includes(row.message.kind)
    && /^realm-[a-z0-9]+-[a-z0-9]+$/u.test(row.message.sender)
    && /^transition-[a-z0-9]+-[a-z0-9]+$/u.test(row.message.transition)
  ));
}

function traceMatches(row, { direction, kind, sender, transition }) {
  return (direction === undefined || row.direction === direction)
    && (kind === undefined || row.message.kind === kind)
    && (sender === undefined || row.message.sender === sender)
    && (transition === undefined || row.message.transition === transition);
}

function matchingTraceRows(trace, match) {
  return trace.filter((row) => traceMatches(row, match));
}

function inspectSingleTransitionCeremony(ceremony, expectLateRealm) {
  if (!exactKeys(ceremony, ['initiator', 'lateRealm', 'peers'])
    || !Array.isArray(ceremony.peers)
    || ceremony.peers.length !== 2) return { pass: false, transition: null };
  const traces = [ceremony.initiator, ...ceremony.peers, ceremony.lateRealm];
  if (!traces.every(exactTransitionTrace)) return { pass: false, transition: null };
  const allRows = traces.flat();
  if (allRows.some((row) => row.message.kind === 'nack')) {
    return { pass: false, transition: null };
  }

  const starts = matchingTraceRows(ceremony.initiator, { direction: 'send', kind: 'start' });
  const ends = matchingTraceRows(ceremony.initiator, { direction: 'send', kind: 'end' });
  if (ceremony.initiator.length !== 4 || starts.length !== 1 || ends.length !== 1) {
    return { pass: false, transition: null };
  }
  const transition = starts[0].message.transition;
  const initiatorSender = starts[0].message.sender;
  if (allRows.some((row) => row.message.transition !== transition)
    || ends[0].message.sender !== initiatorSender
    || starts[0].sequence >= ends[0].sequence
    || ceremony.initiator.some((row) => (
      row.direction === 'send'
        ? (!['start', 'end'].includes(row.message.kind)
          || row.message.sender !== initiatorSender)
        : row.message.kind !== 'ack'
    ))) return { pass: false, transition: null };

  const peerSenders = [];
  for (const peer of ceremony.peers) {
    const sent = peer.filter((row) => row.direction === 'send');
    const sender = sent[0]?.message.sender;
    const start = matchingTraceRows(peer, {
      direction: 'receive', kind: 'start', sender: initiatorSender, transition,
    });
    const ack = matchingTraceRows(peer, {
      direction: 'send', kind: 'ack', sender, transition,
    });
    const end = matchingTraceRows(peer, {
      direction: 'receive', kind: 'end', sender: initiatorSender, transition,
    });
    if (peer.length !== 4 || sent.length !== 1 || sender === initiatorSender
      || start.length !== 1 || ack.length !== 1 || end.length !== 1
      || !(start[0].sequence < ack[0].sequence && ack[0].sequence < end[0].sequence)) {
      return { pass: false, transition: null };
    }
    peerSenders.push(sender);
  }
  if (new Set(peerSenders).size !== peerSenders.length) {
    return { pass: false, transition: null };
  }
  for (const [peerIndex, peer] of ceremony.peers.entries()) {
    const otherPeerSender = peerSenders.find((_sender, index) => index !== peerIndex);
    if (matchingTraceRows(peer, {
      direction: 'receive', kind: 'ack', sender: otherPeerSender, transition,
    }).length !== 1) return { pass: false, transition: null };
  }
  const initiatorAcks = matchingTraceRows(ceremony.initiator, {
    direction: 'receive', kind: 'ack', transition,
  });
  if (initiatorAcks.length !== peerSenders.length
    || initiatorAcks.map((row) => row.message.sender).sort().join(',')
      !== [...peerSenders].sort().join(',')) return { pass: false, transition: null };

  const lateEnd = matchingTraceRows(ceremony.lateRealm, {
    direction: 'receive', kind: 'end', sender: initiatorSender, transition,
  });
  const lateExact = expectLateRealm
    ? ceremony.lateRealm.length === 1 && lateEnd.length === 1
    : ceremony.lateRealm.length === 0;
  return { pass: lateExact, transition };
}

/** Prove two exact successful ceremonies without persisting traces across navigation. */
export function inspectTransitionProtocolTrace(value) {
  if (!exactKeys(value, ['ceremonies'])
    || !Array.isArray(value.ceremonies)
    || value.ceremonies.length !== 2) return { pass: false };
  const first = inspectSingleTransitionCeremony(value.ceremonies[0], false);
  const second = inspectSingleTransitionCeremony(value.ceremonies[1], true);
  return {
    pass: first.pass && second.pass && first.transition !== second.transition,
  };
}

export function inspectVerificationObservation(value) {
  const pagePost = Array.isArray(value?.pagePosts) && value.pagePosts.length === 1
    ? value.pagePosts[0] : null;
  return {
    pass: Boolean(value?.completionPercent === 100
      && value?.institutionalStatus === 'pending'
      && pagePost?.pathname === '/api/v1/auth/student/verification/email/request'
      && pagePost?.query === ''
      && exactKeys(pagePost?.body, [])
      && value?.status === 202
      && value?.projectionExact === true
      && value?.responseInstitutionalStatus === 'pending'
      && value?.selectorCount === 0
      && value?.retryStatus === 202
      && value?.retryProjectionExact === true
      && value?.retryInstitutionalStatus === 'pending'
      && value?.retryProfileVersion === value?.responseProfileVersion
      && value?.refetched === true),
  };
}

export function inspectPromptRotationObservation(value) {
  return {
    pass: Boolean(value?.dismissStatus === 200
      && value?.sameSessionHidden === true
      && value?.rotatedSessionShown === true),
  };
}

export function inspectDialogObservation(value) {
  return {
    pass: Boolean(value?.initialFocus === true
      && value?.shiftWrapped === true
      && value?.tabWrapped === true
      && value?.focusRestored === true
      && value?.backgroundInert === true
      && value?.dismissErrorRetained === true),
  };
}

export function inspectGeometryObservation(value) {
  return {
    pass: Boolean(Number.isFinite(value?.minimumTarget)
      && value.minimumTarget >= 44
      && value?.overflow === false),
  };
}

export function inspectCrossUserObservation(value) {
  return {
    pass: Boolean(value?.selectorStatus === 422
      && value?.canonicalStatus === 200
      && value?.canonicalOwnerStayedSame === true
      && value?.otherOwnerReturned === false),
  };
}

export function inspectStaleConflictObservation(value) {
  return {
    pass: Boolean(value?.firstStatus === 409
      && value?.secondStatus === 409
      && value?.routeAndValuesRetained === true
      && value?.patchCountBeforeReview === 1
      && value?.conflictReviewVisible === true
      && value?.serverWinnerVisible === true
      && value?.retainedDraftVisible === true
      && value?.patchCountAfterAdopt === 1
      && value?.deliberateRetryStatus === 200
      && value?.wrongStaleStatus === 409
      && value?.deliberateDraftPersisted === true
      && value?.newerVersionPreserved === true),
  };
}

export function inspectCrossSectionConflictObservation(value) {
  const completeKeys = [
    'deliberateDraftPersisted',
    'deliberateRetryStatus',
    'firstStatus',
    'patchCountAfterAdopt',
    'patchCountBeforeAdopt',
    'reviewVisible',
    'routeAndDraftRetained',
    'section',
  ];
  const regressionKeys = [
    'adoptRoutedToPrerequisite',
    'browserPersistenceClean',
    'deliberateDraftPersisted',
    'draftRestoredAfterRepair',
    'finalRetryStatus',
    'firstStatus',
    'patchCountBeforeAdopt',
    'reviewVisible',
    'routeAndDraftRetained',
    'section',
  ];
  const sectionsExact = (rows) => Array.isArray(rows)
    && rows.length === 2
    && rows[0]?.section === 'academic'
    && rows[1]?.section === 'interests';
  const complete = value?.completePrerequisiteChanges;
  const regressions = value?.prerequisiteRegressions;
  const completeExact = sectionsExact(complete) && complete.every((row) => (
    exactKeys(row, completeKeys)
    && row.firstStatus === 409
    && row.reviewVisible === true
    && row.routeAndDraftRetained === true
    && row.patchCountBeforeAdopt === 1
    && row.patchCountAfterAdopt === 1
    && row.deliberateRetryStatus === 200
    && row.deliberateDraftPersisted === true
  ));
  const regressionsExact = sectionsExact(regressions) && regressions.every((row) => (
    exactKeys(row, regressionKeys)
    && row.firstStatus === 409
    && row.reviewVisible === true
    && row.routeAndDraftRetained === true
    && row.patchCountBeforeAdopt === 1
    && row.adoptRoutedToPrerequisite === true
    && row.browserPersistenceClean === true
    && row.draftRestoredAfterRepair === true
    && row.finalRetryStatus === 200
    && row.deliberateDraftPersisted === true
  ));
  return { pass: Boolean(completeExact && regressionsExact) };
}

export function inspectUncertainWriteObservation(value) {
  return {
    pass: Boolean(value?.writeStatus === 200
      && value?.writeCount === 1
      && value?.refetchedBeforeRetry === true
      && value?.retryCount === 0
      && value?.reconciled === true),
  };
}

export function inspectPromptHostObservation(value) {
  return {
    pass: Boolean(value?.pathname === '/s-07'
      && value?.dialogCount === 1
      && value?.dashboardHostCount === 0),
  };
}

export function inspectOtpSubmissionObservation(value) {
  return {
    pass: Boolean(typeof value?.input === 'string'
      && /^\d{6}$/u.test(value.input)
      && value?.requestCount === 1
      && value?.status === 200
      && value?.landing === '/s-07'),
  };
}

export function inspectUncheckedConsentObservation(value) {
  const unchecked = value?.termsAccepted === false
    || value?.privacyAcknowledged === false;
  return {
    pass: Boolean(unchecked
      && value?.requestCount === 0
      && value?.registrationRows === 0
      && value?.otpRows === 0
      && value?.outboxRows === 0),
  };
}

export function inspectRegistrationEnumerationObservation(value) {
  const known = value?.known;
  const unknown = value?.unknown;
  const exactWire = (wire) => Boolean(
    wire?.status === 202
    && inspectRegistrationStartWire(wire?.body).pass
    && wire?.headerClass === 'uniform'
    && wire?.cookieClass === 'uniform',
  );
  return {
    pass: Boolean(exactWire(known) && exactWire(unknown)
      && JSON.stringify(known) === JSON.stringify(unknown)),
  };
}

export function inspectValidationBypassObservation(value) {
  return {
    pass: Boolean(value?.invalidBefore === true
      && value?.reviewerOrDemoSelectorCount === 0
      && value?.profilePatchCount === 0
      && value?.invalidAfter === true),
  };
}

export function inspectFailedSaveObservation(value) {
  return {
    pass: Boolean(Number.isSafeInteger(value?.status) && value.status >= 400
      && value?.navigated === false
      && value?.routeRetained === true
      && value?.valuesRetained === true
      && value?.errorRole === 'alert'),
  };
}

export function inspectStudentAuthorityObservation(value) {
  return {
    pass: Boolean(value?.guardianStatus === 403
      && value?.verificationStatus === 403
      && value?.guardianPositiveRows === 0
      && value?.verificationPositiveRows === 0),
  };
}

export function inspectSelectorCensusObservation(value) {
  return {
    pass: Boolean(value?.claimedPass === true
      && Number.isSafeInteger(value?.selectorCount) && value.selectorCount > 0
      && Number.isSafeInteger(value?.iconCount) && value.iconCount > 0),
  };
}

export function inspectWorkflowAggregateObservation(value) {
  const jobs = Array.isArray(value?.requiredJobStatuses)
    ? value.requiredJobStatuses : [];
  return {
    pass: Boolean(jobs.length > 0
      && jobs.every((status) => status === 'success')
      && value?.aggregatorStatus === 'success'),
  };
}

export function inspectStorageSurfaceResults(rows) {
  const names = Array.isArray(rows) ? rows.map((row) => row?.surface) : [];
  const exact = names.length === NYAY5_REQUIRED_STORAGE_SURFACES.length
    && names.every((name, index) => name === NYAY5_REQUIRED_STORAGE_SURFACES[index])
    && new Set(names).size === names.length;
  return {
    pass: Boolean(exact && rows.every((row) => row?.pass === true)),
    exact,
  };
}

const PROJECTION_KEYS = Object.freeze([
  'profile_version',
  'completion_version',
  'completion_percent',
  'completed_sections',
  'missing_requirements',
  'next_incomplete_section',
  'is_complete',
  'institutional_email_status',
  'guardian',
  'access_mode',
  'disabled_capabilities',
  'profile_prompt',
  'profile',
]);

const PERSONAL_KEYS = Object.freeze([
  'first_name',
  'middle_name',
  'last_name',
  'date_of_birth',
  'preferred_language',
  'city',
  'pronouns',
]);
const ACADEMIC_KEYS = Object.freeze([
  'college',
  'year_of_study',
  'enrolment_number',
  'institutional_email',
  'bar_enrolment_number',
]);
const INTEREST_KEYS = Object.freeze(['interests', 'goals']);
const INSTITUTIONAL_STATUSES = new Set([
  'not_provided', 'pending', 'verified', 'rejected', 'expired', 'revoked',
]);
const GUARDIAN_STATUSES = new Set([
  'not_required', 'required_pending', 'verified', 'rejected', 'revoked',
]);
const OTP_FLOW_KEYS = Object.freeze([
  'attempts_left',
  'destination_masked',
  'expires_in_seconds',
  'locked_for_seconds',
  'purpose',
  'resend_allowed',
  'resend_in_seconds',
  'status',
]);
const OTP_VERIFICATION_KEYS = Object.freeze([...OTP_FLOW_KEYS, 'onboarding']);
const REGISTRATION_START_KEYS = Object.freeze([
  'expires_in_seconds', 'next', 'resend_after_seconds', 'status',
]);

function exactKeys(value, keys) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === [...keys].sort().join(','));
}

export function inspectOtpFlowWire(value) {
  const keysExact = exactKeys(value, OTP_FLOW_KEYS);
  const relative = [
    value?.attempts_left,
    value?.expires_in_seconds,
    value?.resend_in_seconds,
    value?.locked_for_seconds,
  ];
  const pending = value?.status === 'pending'
    && ['signup', 'login', 'recovery'].includes(value?.purpose)
    && typeof value?.destination_masked === 'string'
    && /^••••••\d{4}$/u.test(value.destination_masked)
    && relative.every((item) => Number.isSafeInteger(item) && item >= 0)
    && typeof value.resend_allowed === 'boolean'
    && (!value.resend_allowed || (
      value.resend_in_seconds === 0
      && value.locked_for_seconds === 0
      && value.attempts_left > 0
    ));
  const noCapabilities = value?.destination_masked === null
    && relative.every((item) => item === null)
    && value?.resend_allowed === false;
  const terminal = noCapabilities && (
    (value?.status === 'verified' && value?.purpose === 'recovery')
    || (value?.status === 'authenticated'
      && ['signup', 'login'].includes(value?.purpose))
    || (value?.status === 'unavailable' && value?.purpose === null)
  );
  return { pass: Boolean(keysExact && (pending || terminal)), keysExact };
}

export function inspectRegistrationStartWire(value) {
  const keysExact = exactKeys(value, REGISTRATION_START_KEYS);
  return {
    pass: Boolean(
      keysExact
      && value.status === 'accepted'
      && value.next === 'otp'
      && Number.isSafeInteger(value.expires_in_seconds)
      && value.expires_in_seconds > 0
      && Number.isSafeInteger(value.resend_after_seconds)
      && value.resend_after_seconds >= 0
    ),
    keysExact,
  };
}

export function inspectOtpVerificationWire(value) {
  const keysExact = exactKeys(value, OTP_VERIFICATION_KEYS);
  if (!keysExact) return { pass: false, keysExact, onboardingExact: false };
  const { onboarding, ...flow } = value;
  const flowExact = inspectOtpFlowWire(flow).pass
    && flow.status === 'authenticated'
    && ['signup', 'login'].includes(flow.purpose);
  const onboardingExact = inspectNyay5Projection(onboarding).pass;
  return {
    pass: Boolean(flowExact && onboardingExact),
    keysExact,
    onboardingExact,
  };
}

export function inspectAuthBoundaryObservation(value) {
  const passwordlessSurfaces = Array.isArray(value?.passwordlessSurfaces)
    ? value.passwordlessSurfaces : [];
  const otpFlowWires = Array.isArray(value?.otpFlowWires) ? value.otpFlowWires : [];
  const verificationWires = Array.isArray(value?.verificationWires)
    ? value.verificationWires : [];
  const authRequests = Array.isArray(value?.authRequests) ? value.authRequests : [];
  const passwordRequestsAbsent = authRequests.length > 0 && authRequests.every((request) => (
    typeof request?.path === 'string'
    && typeof request?.body === 'string'
    && !request.path.toLowerCase().includes('password')
    && !/password/iu.test(request.body)
  ));
  return {
    pass: Boolean(
      value?.registrationStartStatus === 202
      && value?.loginStartStatus === 202
      && inspectRegistrationStartWire(value?.registrationStartWire).pass
      && otpFlowWires.length === 3
      && otpFlowWires.every((wire) => inspectOtpFlowWire(wire).pass)
      && verificationWires.length === 2
      && verificationWires.every((wire) => inspectOtpVerificationWire(wire).pass)
      && verificationWires[0]?.purpose === 'signup'
      && verificationWires[1]?.purpose === 'login'
      && value?.signupScreenExact === true
      && value?.loginScreenExact === true
      && value?.signupLanding === '/s-07'
      && value?.loginLanding === '/s-07'
      && value?.signupCookieExact === true
      && value?.loginCookieExact === true
      && value?.logoutStatus === 200
      && passwordlessSurfaces.length === 4
      && passwordlessSurfaces.every((surface) => surface === true)
      && passwordRequestsAbsent
    ),
    passwordRequestsAbsent,
  };
}

function optionalString(value, maximum) {
  return value === null || (
    typeof value === 'string'
    && [...value].length >= 1
    && [...value].length <= maximum
    && value === value.normalize('NFC').trim().replace(/\s+/gu, ' ')
  );
}

function boundedUniqueStrings(value) {
  return Array.isArray(value)
    && value.length <= 20
    && new Set(value).size === value.length
    && value.every((item) => (
      typeof item === 'string'
      && [...item].length >= 1
      && [...item].length <= 80
      && item === item.normalize('NFC').trim().replace(/\s+/gu, ' ')
    ));
}

export function inspectNyay5Projection(value) {
  const keysExact = exactKeys(value, PROJECTION_KEYS);
  const sections = ['personal', 'academic', 'interests'];
  const completed = Array.isArray(value?.completed_sections) ? value.completed_sections : [];
  const completedExact = completed.length <= sections.length
    && completed.every((item, index) => item === sections[index])
    && new Set(completed).size === completed.length;
  const next = value?.next_incomplete_section;
  const expectedNext = sections[completed.length] ?? null;
  const percentByCount = [0, 34, 67, 100][completed.length];
  const profileKeysExact = exactKeys(value?.profile, ['academic', 'interests', 'personal']);
  const personal = value?.profile?.personal;
  const academic = value?.profile?.academic;
  const interests = value?.profile?.interests;
  const personalExact = exactKeys(personal, PERSONAL_KEYS)
    && validLegalName(personal.first_name)
    && personal.first_name === personal.first_name.normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '')
    && (personal.middle_name === null
      || (validLegalName(personal.middle_name)
        && personal.middle_name === personal.middle_name.normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '')))
    && validLegalName(personal.last_name)
    && personal.last_name === personal.last_name.normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '')
    && typeof personal.date_of_birth === 'string'
    && /^\d{4}-\d{2}-\d{2}$/u.test(personal.date_of_birth)
    && (personal.preferred_language === null
      || ['en', 'hi'].includes(personal.preferred_language))
    && optionalString(personal.city, 120)
    && optionalString(personal.pronouns, 60);
  const academicExact = exactKeys(academic, ACADEMIC_KEYS)
    && optionalString(academic.college, 160)
    && optionalString(academic.year_of_study, 40)
    && optionalString(academic.enrolment_number, 120)
    && optionalString(academic.institutional_email, 254)
    && optionalString(academic.bar_enrolment_number, 120);
  const interestsExact = exactKeys(interests, INTEREST_KEYS)
    && boundedUniqueStrings(interests.interests)
    && boundedUniqueStrings(interests.goals);
  const personalComplete = personalExact
    && ['en', 'hi'].includes(personal.preferred_language)
    && typeof personal.city === 'string';
  const academicComplete = academicExact
    && typeof academic.college === 'string'
    && typeof academic.year_of_study === 'string'
    && typeof academic.enrolment_number === 'string';
  const interestsComplete = interestsExact
    && interests.interests.length > 0
    && interests.goals.length > 0;
  const expectedMissing = [];
  if (personal?.preferred_language === null) {
    expectedMissing.push('personal.preferred_language');
  }
  if (!personal?.city) expectedMissing.push('personal.city');
  if (!academic?.college) expectedMissing.push('academic.college');
  if (!academic?.year_of_study) expectedMissing.push('academic.year_of_study');
  if (!academic?.enrolment_number) expectedMissing.push('academic.enrolment_number');
  if (!Array.isArray(interests?.interests) || interests.interests.length === 0) {
    expectedMissing.push('interests.interests');
  }
  if (!Array.isArray(interests?.goals) || interests.goals.length === 0) {
    expectedMissing.push('interests.goals');
  }
  const missingExact = Array.isArray(value?.missing_requirements)
    && value.missing_requirements.length === expectedMissing.length
    && value.missing_requirements.every(
      (requirement, index) => requirement === expectedMissing[index],
    );
  let completedByProfile = 0;
  if (personalComplete) {
    completedByProfile = 1;
    if (academicComplete) {
      completedByProfile = 2;
      if (interestsComplete) completedByProfile = 3;
    }
  }
  const guardianExact = exactKeys(value?.guardian, ['required', 'status']);
  const promptExact = exactKeys(
    value?.profile_prompt, ['dismissed_for_session', 'should_show'],
  );
  const guardianConsistent = guardianExact
    && typeof value.guardian.required === 'boolean'
    && GUARDIAN_STATUSES.has(value.guardian.status)
    && ((value.guardian.required === false
      && value.guardian.status === 'not_required'
      && value.access_mode === 'full'
      && Array.isArray(value.disabled_capabilities)
      && value.disabled_capabilities.length === 0)
      || (value.guardian.required === true
        && value.guardian.status !== 'not_required'
        && ((value.guardian.status === 'verified'
          && value.access_mode === 'full'
          && Array.isArray(value.disabled_capabilities)
          && value.disabled_capabilities.length === 0)
          || (value.guardian.status !== 'verified'
            && value.access_mode === 'limited'
            && Array.isArray(value.disabled_capabilities)
            && value.disabled_capabilities.join(',') === 'community,sharing'))));
  const institutionalConsistent = INSTITUTIONAL_STATUSES.has(
    value?.institutional_email_status,
  ) && ((academic?.institutional_email === null
    && value.institutional_email_status === 'not_provided')
    || (typeof academic?.institutional_email === 'string'
      && value.institutional_email_status !== 'not_provided'));
  const promptConsistent = promptExact
    && typeof value.profile_prompt.should_show === 'boolean'
    && typeof value.profile_prompt.dismissed_for_session === 'boolean'
    && value.profile_prompt.should_show
      === (!value.is_complete && !value.profile_prompt.dismissed_for_session);
  const pass = Boolean(
    keysExact
    && Number.isInteger(value.profile_version)
    && value.profile_version >= 1
    && value.completion_version === 'v1'
    && missingExact
    && completedExact
    && value.completion_percent === percentByCount
    && completed.length === completedByProfile
    && next === expectedNext
    && value.is_complete === (completed.length === 3)
    && institutionalConsistent
    && guardianConsistent
    && promptConsistent
    && profileKeysExact
    && personalExact
    && academicExact
    && interestsExact
  );
  return {
    pass,
    keysExact,
    completedExact,
    profileKeysExact,
    guardianExact,
    promptExact,
    personalExact,
    academicExact,
    interestsExact,
    missingExact,
    guardianConsistent,
    institutionalConsistent,
    promptConsistent,
  };
}

export function inspectBrowserPersistence(snapshot) {
  // NYAY-18 deliberately replaces the inherited NYAY-5 compatibility
  // allowlist. Only the current, non-sensitive theme preference may survive;
  // every LegalSaathi key is retired and therefore remains denied here.
  const allowedLocalValues = new Map([
    ['nyayone.theme.v1', new Set(['light', 'dark'])],
  ]);
  const allowedLocal = new Set(allowedLocalValues.keys());
  const localKeys = Array.isArray(snapshot?.localStorageKeys) ? snapshot.localStorageKeys : [];
  const localEntries = Array.isArray(snapshot?.localStorageEntries)
    ? snapshot.localStorageEntries : [];
  const sessionKeys = Array.isArray(snapshot?.sessionStorageKeys) ? snapshot.sessionStorageKeys : [];
  const cacheInventory = Array.isArray(snapshot?.cacheInventory) ? snapshot.cacheInventory : [];
  const indexedDatabases = Array.isArray(snapshot?.indexedDatabases)
    ? snapshot.indexedDatabases : [];
  const cookieNames = Array.isArray(snapshot?.javascriptCookieNames)
    ? snapshot.javascriptCookieNames : [];
  const globalKeys = Array.isArray(snapshot?.deterministicGlobalKeys)
    ? snapshot.deterministicGlobalKeys : [];
  const historyUrls = Array.isArray(snapshot?.historyUrls) ? snapshot.historyUrls : [];
  const unexpectedLocal = localKeys.filter((key) => !allowedLocal.has(key));
  const localEntryKeys = localEntries.map((entry) => entry?.[0]);
  const localEntryKeysExact = localEntries.length === localKeys.length
    && new Set(localEntryKeys).size === localEntryKeys.length
    && [...localEntryKeys].sort().every((key, index) => key === [...localKeys].sort()[index])
    && localEntries.every((entry) => Array.isArray(entry) && entry.length === 2);
  const localValuesExact = localEntries.every((entry) => (
    typeof entry?.[0] === 'string'
    && typeof entry?.[1] === 'string'
    && allowedLocalValues.get(entry[0])?.has(entry[1]) === true
  ));
  const localValuesCredentialFree = localEntries.every((entry) => {
    const value = typeof entry?.[1] === 'string' ? entry[1] : '';
    return !URL_CREDENTIAL.test(value)
      && !TOKEN_TEXT.test(value)
      && !UUID_TEXT.test(value)
      && !EMAIL_TEXT.test(value)
      && !MOBILE_TEXT.test(value)
      && !DOB_TEXT.test(value);
  });
  const cache = cacheInventory.length === 1 ? cacheInventory[0] : null;
  const cacheEntries = Array.isArray(cache?.entries) ? cache.entries : [];
  const indexEntries = cacheEntries.filter((entry) => entry?.pathname === '/index.html');
  const cacheInventoryExact = cache?.name === 'nyayone-shell-v1'
    && cacheEntries.length >= 1
    && indexEntries.length === 1
    && cacheEntries.every((entry) => {
      const publicShell = entry?.pathname === '/index.html';
      const publicAsset = typeof entry?.pathname === 'string'
        && /^\/assets\/[A-Za-z0-9._-]+$/u.test(entry.pathname);
      const credentialsExact = publicShell
        ? ['same-origin', 'omit'].includes(entry?.credentials)
        : entry?.credentials === 'omit';
      return (publicShell || publicAsset)
        && entry?.query === ''
        && entry?.method === 'GET'
        && credentialsExact
        && entry?.authorization === false
        && entry?.responseStatus === 200;
    });
  const serviceWorker = snapshot?.serviceWorker;
  const serviceWorkerExact = serviceWorker?.supported === true
    && serviceWorker?.controlled === true
    && serviceWorker?.registrations === 1
    && Array.isArray(serviceWorker?.scriptPathnames)
    && serviceWorker.scriptPathnames.length === 1
    && serviceWorker.scriptPathnames[0] === '/sw.js'
    && serviceWorker?.productionAssets === true
    && serviceWorker?.disableFlagAbsent === true;
  const privacyInstrumentation = snapshot?.privacyInstrumentation;
  const privacyInstrumentationExact = privacyInstrumentation?.installed === true
    && Number.isSafeInteger(privacyInstrumentation?.historyCallsObserved)
    && privacyInstrumentation.historyCallsObserved >= 0
    && privacyInstrumentation?.transientHistoryPrivateDetected === false
    && Number.isSafeInteger(privacyInstrumentation?.globalsScanned)
    && privacyInstrumentation.globalsScanned >= 0
    && privacyInstrumentation?.globalPrivateDetected === false
    && privacyInstrumentation?.windowNamePrivateDetected === false
    && privacyInstrumentation?.historyStatePrivateDetected === false;
  const serialized = JSON.stringify(snapshot ?? {});
  return {
    pass: unexpectedLocal.length === 0
      && localEntryKeysExact
      && localValuesExact
      && localValuesCredentialFree
      && sessionKeys.length === 0
      && cacheInventoryExact
      && serviceWorkerExact
      && privacyInstrumentationExact
      && indexedDatabases.length === 0
      && cookieNames.length === 0
      && globalKeys.length === 0
      && historyUrls.every((url) => !UUID_TEXT.test(url) && !EMAIL_TEXT.test(url))
      && !UUID_TEXT.test(serialized)
      && !EMAIL_TEXT.test(serialized)
      && !MOBILE_TEXT.test(serialized)
      && !DOB_TEXT.test(serialized)
      && !URL_CREDENTIAL.test(serialized)
      && !TOKEN_TEXT.test(serialized),
    unexpectedLocalCount: unexpectedLocal.length,
    localValueContractExact: localEntryKeysExact
      && localValuesExact && localValuesCredentialFree,
    sessionCount: sessionKeys.length,
    cacheCount: cacheEntries.length,
    cacheInventoryExact,
    serviceWorkerExact,
    privacyInstrumentationExact,
    indexedDatabaseCount: indexedDatabases.length,
    javascriptCookieCount: cookieNames.length,
    deterministicGlobalCount: globalKeys.length,
  };
}

export function inspectActorChannel(request) {
  const url = new URL(request.url());
  const headers = Object.fromEntries(
    (request.headersArray?.() ?? []).map(({ name, value }) => [name.toLowerCase(), value]),
  );
  const body = request.postDataJSON?.() ?? null;
  const serializedBody = JSON.stringify(body ?? {}).toLowerCase();
  const query = url.searchParams;
  const forbiddenHeader = Object.keys(headers).some((name) => (
    name === 'x-actor-claims' || name.includes('registration-id') || name.includes('profile-id')
  ));
  const forbiddenQuery = [...query.keys()].some((name) => (
    /(?:actor|owner|registration|profile|user).*id/iu.test(name)
  ));
  const forbiddenBody = /"(?:actor|owner|registration|profile|user)_?id"/iu
    .test(serializedBody);
  return {
    pass: !forbiddenHeader && !forbiddenQuery && !forbiddenBody,
    forbiddenHeader,
    forbiddenQuery,
    forbiddenBody,
  };
}

function validEmptyProjection() {
  return {
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
        first_name: 'Synthetic',
        middle_name: null,
        last_name: 'Student',
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
}

function validLegalName(value) {
  if (typeof value !== 'string') return false;
  if (/[^\S ]/u.test(value)) return false;
  const normalized = value.normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '');
  if ([...normalized].length < 1 || [...normalized].length > 60) return false;
  let hasLetter = false;
  let previousAllowsMark = false;
  for (const codePoint of normalized) {
    if (/^\p{L}$/u.test(codePoint)) {
      hasLetter = true;
      previousAllowsMark = true;
    } else if (/^\p{M}$/u.test(codePoint)) {
      if (!previousAllowsMark) return false;
      previousAllowsMark = true;
    } else if ([' ', '.', '-', "'", '‘', '’'].includes(codePoint)) {
      previousAllowsMark = false;
    } else {
      return false;
    }
  }
  return hasLetter;
}

/**
 * REG-05 is conjunctive: every shared-corpus case runs through the rendered
 * S-10 form and through the canonical backend endpoint.  Invalid UI cases must
 * be stopped before a PATCH, either by the form validator or by the browser's
 * single-line control boundary for line breaks; invalid backend cases must be
 * typed 422 with an unchanged profile. Valid cases normalize identically.
 */
export function inspectLegalNameCorpusObservation(rows, corpusCases) {
  const observations = Array.isArray(rows) ? rows : [];
  const cases = Array.isArray(corpusCases) ? corpusCases : [];
  const caseIds = cases.map((entry) => entry?.id);
  const rowIds = observations.map((entry) => entry?.id);
  const exact = cases.length > 0
    && observations.length === cases.length
    && new Set(caseIds).size === cases.length
    && new Set(rowIds).size === observations.length
    && rowIds.every((id, index) => id === caseIds[index]);
  let uiPassed = 0;
  let backendPassed = 0;
  let corpusDefinitionPassed = 0;
  const casePasses = [];
  for (let index = 0; index < cases.length; index += 1) {
    const testCase = cases[index] ?? {};
    const row = observations[index] ?? {};
    const repeat = Number(testCase.repeat ?? 1);
    const candidate = String(testCase.input ?? '').repeat(repeat);
    const expected = String(testCase.normalized ?? testCase.input ?? '')
      .repeat(repeat).normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '');
    const definitionExact = typeof testCase.valid === 'boolean'
      && validLegalName(candidate) === testCase.valid
      && (!testCase.valid || candidate.normalize('NFC').replace(/ +/gu, ' ')
        .replace(/^ | $/gu, '') === expected);
    corpusDefinitionPassed += Number(definitionExact);
    const valid = testCase.valid === true && row.valid === true;
    const invalid = testCase.valid === false && row.valid === false;
    const rejectedByForm = invalid
      && row.ui?.patchCount === 0
      && row.ui?.status === null
      && row.ui?.routeRetained === true
      && row.ui?.valueRetained === true
      && row.ui?.errorRole === 'alert'
      && row.ui?.errorVisible === true;
    const rejectedBySingleLineControl = invalid
      && /[\r\n]/u.test(candidate)
      && row.ui?.platformRejected === true
      && row.ui?.patchCount === 0
      && row.ui?.status === null
      && row.ui?.routeRetained === true
      && row.ui?.valueRetained === false
      && row.ui?.errorRole === null
      && row.ui?.errorVisible === false;
    const uiExact = valid
      ? row.ui?.patchCount === 1
        && row.ui?.status === 200
        && row.ui?.normalizedExact === true
        && row.ui?.projectionExact === true
        && row.ui?.routeAdvanced === true
      : rejectedByForm || rejectedBySingleLineControl;
    const backendExact = valid
      ? row.backend?.status === 200
        && row.backend?.normalizedExact === true
        && row.backend?.projectionExact === true
        && row.backend?.zeroMutation === false
      : invalid
        && row.backend?.status === 422
        && row.backend?.zeroMutation === true;
    uiPassed += Number(uiExact);
    backendPassed += Number(backendExact);
    casePasses.push(definitionExact && uiExact && backendExact);
  }
  const passed = casePasses.filter(Boolean).length;
  return {
    pass: exact
      && corpusDefinitionPassed === cases.length
      && uiPassed === cases.length
      && backendPassed === cases.length,
    exact,
    total: cases.length,
    passed,
    uiPassed,
    backendPassed,
    corpusDefinitionPassed,
  };
}

function fakeRequest({ url = 'https://app.invalid/api/v1/student/profile', headers = {}, body = null } = {}) {
  return {
    url: () => url,
    headersArray: () => Object.entries(headers).map(([name, value]) => ({ name, value })),
    postDataJSON: () => body,
  };
}

/** Execute one independent deterministic perturbation for every named mutant. */
export function seededNyay5MutantResults() {
  const passingRows = NYAY5_ASSERTION_INVENTORY.map((name) => ({ name, pass: true }));
  const projection = validEmptyProjection();
  const registrationStartWire = {
    status: 'accepted',
    next: 'otp',
    expires_in_seconds: 600,
    resend_after_seconds: 1,
  };
  const pendingWire = (purpose) => ({
    attempts_left: 5,
    destination_masked: '••••••0042',
    expires_in_seconds: 600,
    locked_for_seconds: 0,
    purpose,
    resend_allowed: false,
    resend_in_seconds: 1,
    status: 'pending',
  });
  const verificationWire = (purpose) => ({
    attempts_left: null,
    destination_masked: null,
    expires_in_seconds: null,
    locked_for_seconds: null,
    onboarding: projection,
    purpose,
    resend_allowed: false,
    resend_in_seconds: null,
    status: 'authenticated',
  });
  const authBoundary = {
    registrationStartStatus: 202,
    loginStartStatus: 202,
    registrationStartWire,
    otpFlowWires: [pendingWire('signup'), pendingWire('login'), pendingWire('login')],
    verificationWires: [verificationWire('signup'), verificationWire('login')],
    signupScreenExact: true,
    loginScreenExact: true,
    signupLanding: '/s-07',
    loginLanding: '/s-07',
    signupCookieExact: true,
    loginCookieExact: true,
    logoutStatus: 200,
    passwordlessSurfaces: [true, true, true, true],
    authRequests: [{ path: '/api/v1/auth/student/register', body: '{}' }],
  };
  const cleanStorage = {
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
    historyUrls: ['https://app.invalid/s-14'],
  };
  const verificationObservation = {
    completionPercent: 100,
    institutionalStatus: 'pending',
    pagePosts: [{
      pathname: '/api/v1/auth/student/verification/email/request',
      query: '',
      body: {},
    }],
    status: 202,
    projectionExact: true,
    responseInstitutionalStatus: 'pending',
    selectorCount: 0,
    retryStatus: 202,
    retryProjectionExact: true,
    retryInstitutionalStatus: 'pending',
    responseProfileVersion: 3,
    retryProfileVersion: 3,
    refetched: true,
  };
  const legalNameCases = [
    { id: 'decomposed_accent', input: 'A\u0301', valid: true, normalized: '\u00c1' },
    { id: 'punctuation_only', input: "-.'", valid: false },
    { id: 'tab', input: 'A\tB', valid: false },
    { id: 'supplementary_letter_61', input: '\ud801\udc00', repeat: 61, valid: false },
  ];
  const legalNameRows = legalNameCases.map((testCase) => ({
    id: testCase.id,
    valid: testCase.valid,
    ui: testCase.valid
      ? {
          patchCount: 1,
          status: 200,
          normalizedExact: true,
          projectionExact: true,
          routeAdvanced: true,
        }
      : {
          patchCount: 0,
          status: null,
          normalizedExact: false,
          projectionExact: false,
          routeRetained: true,
          valueRetained: true,
          errorRole: 'alert',
          errorVisible: true,
        },
    backend: testCase.valid
      ? {
          status: 200,
          normalizedExact: true,
          projectionExact: true,
          zeroMutation: false,
        }
      : {
          status: 422,
          normalizedExact: false,
          projectionExact: false,
          zeroMutation: true,
        },
  }));
  const mutateLegalNameRow = (id, mutation) => legalNameRows.map((row) => {
    const copy = structuredClone(row);
    if (copy.id === id) mutation(copy);
    return copy;
  });
  const neutralRegistrationWire = {
    status: 202,
    body: registrationStartWire,
    headerClass: 'uniform',
    cookieClass: 'uniform',
  };
  const kill = (name, baselinePassed, mutantPassed) => ({
    name,
    killed: baselinePassed === true && mutantPassed === false,
  });
  const rows = [
    kill(
      'mount-private-content-while-session-pending',
      inspectPendingSessionObservation({
        sessionPending: true, privateMounted: 0, privateRequestCount: 0,
      }).pass,
      inspectPendingSessionObservation({
        sessionPending: true, privateMounted: 1, privateRequestCount: 0,
      }).pass,
    ),
    kill(
      'accept-anonymous-profile-route',
      inspectDenialObservation({
        anonymousDenied: true, expiredDenied: true, revokedDenied: true,
        deletedDenied: true, wrongRoleDenied: true, privateRequestCount: 0,
      }).pass,
      inspectDenialObservation({
        anonymousDenied: false, expiredDenied: true, revokedDenied: true,
        deletedDenied: true, wrongRoleDenied: true, privateRequestCount: 0,
      }).pass,
    ),
    kill(
      'accept-wrong-role-profile-route',
      inspectDenialObservation({
        anonymousDenied: true, expiredDenied: true, revokedDenied: true,
        deletedDenied: true, wrongRoleDenied: true, privateRequestCount: 0,
      }).pass,
      inspectDenialObservation({
        anonymousDenied: true, expiredDenied: true, revokedDenied: true,
        deletedDenied: true, wrongRoleDenied: false, privateRequestCount: 0,
      }).pass,
    ),
    kill(
      'trust-client-owner-header',
      inspectActorChannel(fakeRequest()).pass,
      inspectActorChannel(fakeRequest({ headers: { 'x-actor-claims': 'forged' } })).pass,
    ),
    kill(
      'trust-client-owner-query',
      inspectActorChannel(fakeRequest()).pass,
      inspectActorChannel(fakeRequest({
        url: 'https://app.invalid/api/v1/student/profile?owner_id=forged',
      })).pass,
    ),
    kill(
      'trust-client-owner-body',
      inspectActorChannel(fakeRequest()).pass,
      inspectActorChannel(fakeRequest({ body: { registration_id: 'forged' } })).pass,
    ),
    kill(
      'navigate-before-server-success',
      inspectConfirmedWriteObservation({
        serverSettled: true, status: 200, heldBeforeNavigation: true, navigated: true,
      }).pass,
      inspectConfirmedWriteObservation({
        serverSettled: false, status: 0, heldBeforeNavigation: true, navigated: true,
      }).pass,
    ),
    kill(
      'discard-values-on-typed-error',
      inspectTypedFailureObservation({
        status: 409, routeRetained: true, valuesRetained: true, errorRole: 'alert',
      }).pass,
      inspectTypedFailureObservation({
        status: 409, routeRetained: true, valuesRetained: false, errorRole: 'alert',
      }).pass,
    ),
    kill(
      'complete-skipped-section',
      inspectNyay5Projection(projection).pass,
      inspectNyay5Projection({
        ...projection,
        completion_percent: 34,
        completed_sections: ['academic'],
        next_incomplete_section: 'academic',
      }).pass,
    ),
    kill(
      'derive-completion-in-browser',
      inspectNyay5Projection(projection).pass,
      inspectNyay5Projection({ ...projection, completion_percent: 67 }).pass,
    ),
    kill(
      'derive-verification-from-completion',
      inspectVerificationObservation(verificationObservation).pass,
      inspectVerificationObservation({
        ...verificationObservation, responseInstitutionalStatus: 'verified',
      }).pass,
    ),
    kill(
      'persist-prompt-dismissal-in-web-storage',
      inspectBrowserPersistence(cleanStorage).pass,
      inspectBrowserPersistence({ ...cleanStorage, sessionStorageKeys: ['profile-prompt-dismissed'] }).pass,
    ),
    kill(
      'retain-prompt-on-session-rotation',
      inspectPromptRotationObservation({
        dismissStatus: 200, sameSessionHidden: true, rotatedSessionShown: true,
      }).pass,
      inspectPromptRotationObservation({
        dismissStatus: 200, sameSessionHidden: true, rotatedSessionShown: false,
      }).pass,
    ),
    kill(
      'omit-dialog-focus-wrap',
      inspectDialogObservation({
        initialFocus: true, shiftWrapped: true, tabWrapped: true, focusRestored: true,
        backgroundInert: true, dismissErrorRetained: true,
      }).pass,
      inspectDialogObservation({
        initialFocus: true, shiftWrapped: false, tabWrapped: true, focusRestored: true,
        backgroundInert: true, dismissErrorRetained: true,
      }).pass,
    ),
    kill(
      'omit-dialog-background-inert',
      inspectDialogObservation({
        initialFocus: true, shiftWrapped: true, tabWrapped: true, focusRestored: true,
        backgroundInert: true, dismissErrorRetained: true,
      }).pass,
      inspectDialogObservation({
        initialFocus: true, shiftWrapped: true, tabWrapped: true, focusRestored: true,
        backgroundInert: false, dismissErrorRetained: true,
      }).pass,
    ),
    kill(
      'accept-sub-44px-target',
      inspectGeometryObservation({ minimumTarget: 44, overflow: false }).pass,
      inspectGeometryObservation({ minimumTarget: 43, overflow: false }).pass,
    ),
    kill(
      'allow-horizontal-overflow',
      inspectGeometryObservation({ minimumTarget: 44, overflow: false }).pass,
      inspectGeometryObservation({ minimumTarget: 44, overflow: true }).pass,
    ),
    kill(
      'accept-cross-user-projection',
      inspectCrossUserObservation({
        selectorStatus: 422, canonicalStatus: 200,
        canonicalOwnerStayedSame: true, otherOwnerReturned: false,
      }).pass,
      inspectCrossUserObservation({
        selectorStatus: 200, canonicalStatus: 200,
        canonicalOwnerStayedSame: false, otherOwnerReturned: true,
      }).pass,
    ),
    kill(
      'overwrite-newer-profile-version',
      inspectStaleConflictObservation({
        firstStatus: 409, secondStatus: 409,
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
      }).pass,
      inspectStaleConflictObservation({
        firstStatus: 200, secondStatus: 200,
        routeAndValuesRetained: false,
        patchCountBeforeReview: 2,
        conflictReviewVisible: false,
        serverWinnerVisible: false,
        retainedDraftVisible: false,
        patchCountAfterAdopt: 2,
        deliberateRetryStatus: 409,
        wrongStaleStatus: 200,
        deliberateDraftPersisted: false,
        newerVersionPreserved: false,
      }).pass,
    ),
    kill(
      'retry-uncertain-write-before-refetch',
      inspectUncertainWriteObservation({
        writeStatus: 200, writeCount: 1, refetchedBeforeRetry: true,
        retryCount: 0, reconciled: true,
      }).pass,
      inspectUncertainWriteObservation({
        writeStatus: 200, writeCount: 2, refetchedBeforeRetry: false,
        retryCount: 1, reconciled: false,
      }).pass,
    ),
    kill(
      'persist-profile-pii',
      inspectBrowserPersistence(cleanStorage).pass,
      inspectBrowserPersistence({ ...cleanStorage, persistedValue: 'student@example.test' }).pass,
    ),
    kill(
      'persist-uuid-capability',
      inspectBrowserPersistence(cleanStorage).pass,
      inspectBrowserPersistence({
        ...cleanStorage,
        historyUrls: ['https://app.invalid/s-14/123e4567-e89b-42d3-a456-426614174000'],
      }).pass,
    ),
    kill('accept-control-character-name', validLegalName('Aditi'), validLegalName('Adi\nTi')),
    kill('accept-61-code-point-name', validLegalName('Aditi'), validLegalName('A'.repeat(61))),
    kill(
      'render-password-auth-surface',
      inspectAuthBoundaryObservation(authBoundary).pass,
      inspectAuthBoundaryObservation({
        ...authBoundary,
        passwordlessSurfaces: [true, false, true, true],
      }).pass,
    ),
    kill(
      'omit-required-storage-surface',
      inspectStorageSurfaceResults(
        NYAY5_REQUIRED_STORAGE_SURFACES.map((surface) => ({ surface, pass: true })),
      ).pass,
      inspectStorageSurfaceResults(
        NYAY5_REQUIRED_STORAGE_SURFACES.slice(1).map((surface) => ({ surface, pass: true })),
      ).pass,
    ),
    kill(
      'omit-required-assertion',
      summarizeNyay5Rows(passingRows).overallPass,
      summarizeNyay5Rows(passingRows.slice(1)).overallPass,
    ),
    kill(
      'reorder-required-assertions',
      summarizeNyay5Rows(passingRows).overallPass,
      summarizeNyay5Rows([...passingRows].reverse()).overallPass,
    ),
    kill(
      'duplicate-required-assertion',
      summarizeNyay5Rows(passingRows).overallPass,
      summarizeNyay5Rows([...passingRows, passingRows[0]]).overallPass,
    ),
    kill(
      'emit-private-evidence',
      scanNyay5Evidence({ status: 'PASS', total: 22 }).length === 0,
      scanNyay5Evidence({ mobile: '9876543210' }).length === 0,
    ),
    kill(
      'substitute-s14-for-s07-popup-host',
      inspectPromptHostObservation({
        pathname: '/s-07', dialogCount: 1, dashboardHostCount: 0,
      }).pass,
      inspectPromptHostObservation({
        pathname: '/s-14', dialogCount: 1, dashboardHostCount: 1,
      }).pass,
    ),
    kill(
      'hard-code-progress-at-67',
      inspectNyay5Projection(projection).pass,
      inspectNyay5Projection({ ...projection, completion_percent: 67 }).pass,
    ),
    kill(
      'accept-empty-otp',
      inspectOtpSubmissionObservation({
        input: '123456', requestCount: 1, status: 200, landing: '/s-07',
      }).pass,
      inspectOtpSubmissionObservation({
        input: '', requestCount: 1, status: 200, landing: '/s-07',
      }).pass,
    ),
    kill(
      'accept-unchecked-consent',
      inspectUncheckedConsentObservation({
        termsAccepted: false,
        privacyAcknowledged: false,
        requestCount: 0,
        registrationRows: 0,
        otpRows: 0,
        outboxRows: 0,
      }).pass,
      inspectUncheckedConsentObservation({
        termsAccepted: false,
        privacyAcknowledged: false,
        requestCount: 1,
        registrationRows: 1,
        otpRows: 1,
        outboxRows: 1,
      }).pass,
    ),
    kill(
      'disagree-decomposed-valid-name',
      inspectLegalNameCorpusObservation(legalNameRows, legalNameCases).pass,
      inspectLegalNameCorpusObservation(
        mutateLegalNameRow('decomposed_accent', (row) => {
          row.ui.normalizedExact = false;
        }),
        legalNameCases,
      ).pass,
    ),
    kill(
      'disagree-punctuation-only-name',
      inspectLegalNameCorpusObservation(legalNameRows, legalNameCases).pass,
      inspectLegalNameCorpusObservation(
        mutateLegalNameRow('punctuation_only', (row) => {
          row.ui.patchCount = 1;
        }),
        legalNameCases,
      ).pass,
    ),
    kill(
      'disagree-tabbed-name',
      inspectLegalNameCorpusObservation(legalNameRows, legalNameCases).pass,
      inspectLegalNameCorpusObservation(
        mutateLegalNameRow('tab', (row) => {
          row.backend.status = 200;
          row.backend.zeroMutation = false;
        }),
        legalNameCases,
      ).pass,
    ),
    kill(
      'disagree-61-code-point-name',
      inspectLegalNameCorpusObservation(legalNameRows, legalNameCases).pass,
      inspectLegalNameCorpusObservation(
        mutateLegalNameRow('supplementary_letter_61', (row) => {
          row.ui.patchCount = 1;
        }),
        legalNameCases,
      ).pass,
    ),
    kill(
      'disclose-registration-existence',
      inspectRegistrationEnumerationObservation({
        known: neutralRegistrationWire, unknown: neutralRegistrationWire,
      }).pass,
      inspectRegistrationEnumerationObservation({
        known: {
          ...neutralRegistrationWire,
          body: { ...registrationStartWire, status: 'account_exists' },
        },
        unknown: neutralRegistrationWire,
      }).pass,
    ),
    kill(
      'navigate-after-failed-save',
      inspectFailedSaveObservation({
        status: 500,
        navigated: false,
        routeRetained: true,
        valuesRetained: true,
        errorRole: 'alert',
      }).pass,
      inspectFailedSaveObservation({
        status: 500,
        navigated: true,
        routeRetained: false,
        valuesRetained: true,
        errorRole: 'alert',
      }).pass,
    ),
    kill(
      'expose-reviewer-demo-validation-bypass',
      inspectValidationBypassObservation({
        invalidBefore: true,
        reviewerOrDemoSelectorCount: 0,
        profilePatchCount: 0,
        invalidAfter: true,
      }).pass,
      inspectValidationBypassObservation({
        invalidBefore: true,
        reviewerOrDemoSelectorCount: 1,
        profilePatchCount: 1,
        invalidAfter: false,
      }).pass,
    ),
    kill(
      'allow-student-guardian-verification-mutation',
      inspectStudentAuthorityObservation({
        guardianStatus: 403,
        verificationStatus: 403,
        guardianPositiveRows: 0,
        verificationPositiveRows: 0,
      }).pass,
      inspectStudentAuthorityObservation({
        guardianStatus: 200,
        verificationStatus: 200,
        guardianPositiveRows: 1,
        verificationPositiveRows: 1,
      }).pass,
    ),
    kill(
      'grant-authority-from-forged-registration-uuid',
      inspectActorChannel(fakeRequest()).pass,
      inspectActorChannel(fakeRequest({
        body: { registration_id: '123e4567-e89b-42d3-a456-426614174000' },
      })).pass,
    ),
    kill(
      'persist-raw-token-or-identity',
      inspectBrowserPersistence(cleanStorage).pass
        && scanNyay5Evidence({ status: 'PASS', total: 22 }).length === 0,
      inspectBrowserPersistence({
        ...cleanStorage,
        localStorageEntries: cleanStorage.localStorageEntries.map((entry) => (
          entry[0] === 'nyayone.theme.v1'
            ? ['nyayone.theme.v1', 'Bearer synthetic-private-credential']
            : entry
        )),
      }).pass
        && scanNyay5Evidence({
          user_id: '123e4567-e89b-42d3-a456-426614174000',
        }).length === 0,
    ),
    kill(
      'zero-selector-icon-success',
      inspectSelectorCensusObservation({
        claimedPass: true, selectorCount: 1, iconCount: 1,
      }).pass,
      inspectSelectorCensusObservation({
        claimedPass: true, selectorCount: 0, iconCount: 0,
      }).pass,
    ),
    kill(
      'green-aggregator-after-required-workflow-failure',
      inspectWorkflowAggregateObservation({
        requiredJobStatuses: ['success', 'success'], aggregatorStatus: 'success',
      }).pass,
      inspectWorkflowAggregateObservation({
        requiredJobStatuses: ['success', 'failure'], aggregatorStatus: 'success',
      }).pass,
    ),
  ];
  const exact = rows.length === NYAY5_SEEDED_MUTANT_INVENTORY.length
    && rows.every((row, index) => row.name === NYAY5_SEEDED_MUTANT_INVENTORY[index])
    && new Set(rows.map((row) => row.name)).size === rows.length;
  const killed = rows.filter((row) => row.killed === true).length;
  return {
    named: NYAY5_SEEDED_MUTANT_INVENTORY.length,
    killed,
    exact,
    allKilled: exact && killed === rows.length,
    rows,
  };
}

export function seededNyay5MutantsAreKilled() {
  return seededNyay5MutantResults().allKilled;
}

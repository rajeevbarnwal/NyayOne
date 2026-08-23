import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir } from 'node:fs/promises';
import {
  NYAY5_ACCEPTANCE_EXECUTION_MAP,
  NYAY5_ACCEPTANCE_MATRIX_IDS,
  NYAY5_ASSERTION_INVENTORY,
  NYAY5_SELECTOR_EXECUTION_IDS,
  inspectAcceptanceExecutionCoverage,
  scanNyay5Evidence,
} from './lib/nyay5-profile-browser-contract.mjs';

const SELF_EXECUTION_ID = 'evidence:acceptance-execution-map';

export const NYAY5_ACCEPTANCE_ATTESTATION_IDS = Object.freeze([
  'native:frontend-typecheck',
  'native:frontend-lint',
  'native:frontend-unit',
  'native:frontend-production-build',
  'evidence:browser-report',
  'evidence:screenshots',
  'evidence:service-logs',
  'evidence:privacy-scan',
  'evidence:sha256-manifest',
  'ci:policy-verifier',
  'ci:required-job-fail-closed',
  'ci:prospective-merge',
]);

// Exact ordered producer inventory from the NYAY-4 native gate.  The
// cross-gate aggregate independently validates it instead of trusting the
// producer's `exact_inventory` boolean.
export const NYAY4_POSTGRES_ASSERTION_IDS = Object.freeze([
  'RUNTIME-POSTGRES-16-PGVECTOR',
  'MIGRATION-0018-0019-LIFECYCLE-IMMUTABLE',
  'MIGRATION-POPULATED-UPGRADE-DOWNGRADE-REFUSAL',
  'SCHEMA-AUTHORITY-FLOW-RATE-OUTBOX-EXACT',
  'CONTRACT-LOCKOUT-SURVIVES-RESEND',
  'CONCURRENCY-WRONG-VERIFY-CUMULATIVE',
  'CONCURRENCY-RESEND-ONE-STAGED-ONE-ACTIVE',
  'CONTRACT-FAILED-RESEND-PRESERVES-ACTIVE',
  'CONTRACT-RATE-BUDGETS-IDENTITY-IP-GLOBAL',
  'CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY',
  'CONTRACT-PREAUTH-ENUMERATION-NEUTRAL',
  'CONTRACT-SERVER-METADATA-TYPED-OUTCOMES',
  'CONTRACT-OUTBOX-CLAIM-LEASE-FENCING',
  'CONTRACT-PROVIDER-IDEMPOTENCY-EXACTLY-ONCE',
  'CONTRACT-RETRY-BACKOFF-EXHAUSTION-ERASURE',
  'CONTRACT-PRODUCTION-CONFIG-FAIL-CLOSED',
  'HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP',
]);

const allMappedExecutionIds = Object.freeze([
  ...new Set(Object.values(NYAY5_ACCEPTANCE_EXECUTION_MAP).flat()),
]);
const requiredWithPrefix = (prefix) => allMappedExecutionIds
  .filter((id) => id.startsWith(prefix));

function validExecution(row, producerPass) {
  const selectorRequired = NYAY5_SELECTOR_EXECUTION_IDS.includes(row?.id);
  return Boolean(
    producerPass
    && row?.executed === true
    && row?.skipped === false
    && row?.pass === true
    && Number.isSafeInteger(row?.evidenceCount)
    && row.evidenceCount > 0
    && (!selectorRequired || (
      Number.isSafeInteger(row?.selectorCount) && row.selectorCount > 0
    ))
  );
}

function normalizeExecution(row, producerPass) {
  return {
    id: row?.id,
    executed: row?.executed === true,
    skipped: row?.skipped === true,
    pass: validExecution(row, producerPass),
    evidenceCount: Number.isSafeInteger(row?.evidenceCount) ? row.evidenceCount : 0,
    selectorCount: Number.isSafeInteger(row?.selectorCount) ? row.selectorCount : null,
  };
}

function browserExecutions(report) {
  const names = Array.isArray(report?.rows) ? report.rows.map((row) => row?.name) : [];
  const producerPass = Boolean(
    report?.gate === 'nyay5_profile_browser'
    && report?.status === 'PASS'
    && report?.executed === true
    && report?.total === NYAY5_ASSERTION_INVENTORY.length
    && report?.passed === NYAY5_ASSERTION_INVENTORY.length
    && report?.failed === 0
    && report?.inventoryExact === true
    && names.length === NYAY5_ASSERTION_INVENTORY.length
    && names.every((name, index) => name === NYAY5_ASSERTION_INVENTORY[index])
    && report.rows.every((row) => row?.pass === true)
    && report?.acceptanceExecutionCoverage?.pass === true
  );
  return {
    pass: producerPass,
    rows: Array.isArray(report?.executions)
      ? report.executions.map((row) => normalizeExecution(row, producerPass)) : [],
  };
}

function postgresExecutions(report) {
  const assertions = Array.isArray(report?.assertions) ? report.assertions : [];
  const failedAssertions = report?.assertion_summary?.failed;
  const producerPass = Boolean(
    report?.gate === 'nyay5_postgres'
    && report?.status === 'PASS'
    && report?.executed === true
    && report?.head === '0021_nyay5_profile_boundary'
    && report?.assertion_summary?.exact_inventory === true
    && report?.assertion_summary?.required === assertions.length
    && report?.assertion_summary?.passed === assertions.length
    && Array.isArray(failedAssertions)
    && failedAssertions.length === 0
    && report?.assertion_summary?.overall_pass === true
    && report?.privacy_scan?.passed === true
    && report?.privacy_scan?.findings === 0
  );
  const rows = requiredWithPrefix('postgres:').map((id) => {
    const assertionId = id.slice('postgres:'.length);
    const matches = assertions.filter((row) => row?.id === assertionId);
    const exact = matches.length === 1
      && matches[0]?.passed === true
      && matches[0]?.status === 'PASS';
    return {
      id,
      executed: report?.executed === true && matches.length === 1,
      skipped: false,
      pass: producerPass && exact,
      evidenceCount: matches.length,
      selectorCount: null,
    };
  });
  return { pass: producerPass, rows };
}

function otpPostgresExecutions(report) {
  const assertionIds = Array.isArray(report?.assertion_ids) ? report.assertion_ids : [];
  const exactAssertionInventory = assertionIds.length === NYAY4_POSTGRES_ASSERTION_IDS.length
    && assertionIds.every((id, index) => id === NYAY4_POSTGRES_ASSERTION_IDS[index])
    && new Set(assertionIds).size === assertionIds.length;
  const inventoryFailures = report?.assertions?.inventory_failures;
  const exactSummary = Boolean(
    report?.assertions?.required === NYAY4_POSTGRES_ASSERTION_IDS.length
    && report?.assertions?.passed === NYAY4_POSTGRES_ASSERTION_IDS.length
    && inventoryFailures?.missing === 0
    && inventoryFailures?.extra === 0
    && inventoryFailures?.duplicate === 0
    && inventoryFailures?.reordered === false
  );
  const producerPass = Boolean(
    report?.gate === 'nyay4_postgres_otp'
    && report?.status === 'PASS'
    && report?.executed === true
    && report?.assertions?.exact_inventory === true
    && report?.assertions?.overall_pass === true
    && Array.isArray(report?.assertions?.failed)
    && report.assertions.failed.length === 0
    && report?.privacy_findings === 0
    && exactAssertionInventory
    && exactSummary
  );
  const rows = requiredWithPrefix('nyay4-postgres:').map((id) => {
    const assertionId = id.slice('nyay4-postgres:'.length);
    const matches = assertionIds.filter((candidate) => candidate === assertionId);
    return {
      id,
      executed: report?.executed === true && matches.length === 1,
      skipped: false,
      pass: producerPass && matches.length === 1,
      evidenceCount: matches.length,
      selectorCount: null,
    };
  });
  return { pass: producerPass, rows };
}

function attestationExecutions(report) {
  const rows = Array.isArray(report?.executions) ? report.executions : [];
  const ids = rows.map((row) => row?.id);
  const exactInventory = ids.length === NYAY5_ACCEPTANCE_ATTESTATION_IDS.length
    && ids.every((id, index) => id === NYAY5_ACCEPTANCE_ATTESTATION_IDS[index])
    && new Set(ids).size === ids.length;
  const producerPass = Boolean(
    report?.gate === 'nyay5_acceptance_attestations_v1'
    && report?.status === 'PASS'
    && report?.executed === true
    && exactInventory
  );
  return {
    pass: producerPass,
    rows: rows.map((row) => normalizeExecution(row, producerPass)),
  };
}

function executionPass(row) {
  return validExecution(row, true);
}

export function aggregateNyay5Acceptance({ browser, postgres, otpPostgres, attestations }) {
  const producers = [
    browserExecutions(browser),
    postgresExecutions(postgres),
    otpPostgresExecutions(otpPostgres),
    attestationExecutions(attestations),
  ];
  const producerRows = producers.flatMap((producer) => producer.rows);
  const preflightSelf = {
    id: SELF_EXECUTION_ID,
    executed: true,
    skipped: false,
    pass: true,
    evidenceCount: NYAY5_ACCEPTANCE_MATRIX_IDS.length,
    selectorCount: null,
  };
  const preflightCoverage = inspectAcceptanceExecutionCoverage([
    ...producerRows,
    preflightSelf,
  ]);
  const selfExecution = {
    ...preflightSelf,
    pass: producers.every((producer) => producer.pass) && preflightCoverage.pass,
  };
  const executions = [...producerRows, selfExecution];
  const executionCoverage = inspectAcceptanceExecutionCoverage(executions);
  const evidence = new Map(executions.map((row) => [row.id, row]));
  const assertions = NYAY5_ACCEPTANCE_MATRIX_IDS.map((id) => {
    const required = NYAY5_ACCEPTANCE_EXECUTION_MAP[id];
    const matched = required.map((executionId) => evidence.get(executionId));
    return {
      id,
      passed: matched.length === required.length && matched.every(executionPass),
      evidenceCount: matched.reduce(
        (total, row) => total + Number(row?.evidenceCount ?? 0), 0,
      ),
    };
  });
  const privacyFindings = scanNyay5Evidence({
    browser,
    postgres,
    otpPostgres,
    attestations,
  });
  const passed = assertions.filter((row) => row.passed).length;
  const executionIds = executions.map((row) => row.id).sort();
  const producerPass = producers.every((producer) => producer.pass);
  const overallPass = producerPass
    && executionCoverage.pass
    && passed === NYAY5_ACCEPTANCE_MATRIX_IDS.length
    && privacyFindings.length === 0;
  return {
    gate: 'nyay5_acceptance_matrix',
    status: overallPass ? 'PASS' : 'FAIL',
    executed: producers.every((producer) => producer.rows.length > 0),
    total: NYAY5_ACCEPTANCE_MATRIX_IDS.length,
    passed,
    failed: NYAY5_ACCEPTANCE_MATRIX_IDS.length - passed,
    inventoryExact: executionCoverage.mapped === NYAY5_ACCEPTANCE_MATRIX_IDS.length,
    assertions,
    executionCoverage,
    executionInventory: {
      count: executionIds.length,
      sha256: createHash('sha256').update(`${executionIds.join('\n')}\n`).digest('hex'),
    },
    producerStatus: {
      browser: producers[0].pass,
      postgres: producers[1].pass,
      otpPostgres: producers[2].pass,
      attestations: producers[3].pass,
    },
    privacyScan: { passed: privacyFindings.length === 0, findings: privacyFindings.length },
  };
}

function parseArguments(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith('--') || !value || values.has(flag)) {
      throw new Error('NYAY5_ACCEPTANCE_ARGUMENTS_INVALID');
    }
    values.set(flag, value);
  }
  const expected = ['--browser', '--postgres', '--otp-postgres', '--attestations', '--output'];
  if (values.size !== expected.length || expected.some((flag) => !values.has(flag))) {
    throw new Error('NYAY5_ACCEPTANCE_ARGUMENTS_INVALID');
  }
  return Object.fromEntries(expected.map((flag) => [flag.slice(2), values.get(flag)]));
}

async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

async function main(argv) {
  const paths = parseArguments(argv);
  const report = aggregateNyay5Acceptance({
    browser: await readJson(paths.browser),
    postgres: await readJson(paths.postgres),
    otpPostgres: await readJson(paths['otp-postgres']),
    attestations: await readJson(paths.attestations),
  });
  const output = resolve(paths.output);
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, {
    encoding: 'utf8',
    mode: 0o600,
  });
  process.stdout.write(`${JSON.stringify({
    gate: report.gate,
    status: report.status,
    total: report.total,
    passed: report.passed,
    failed: report.failed,
  })}\n`);
  if (report.status !== 'PASS') process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main(process.argv.slice(2));
}

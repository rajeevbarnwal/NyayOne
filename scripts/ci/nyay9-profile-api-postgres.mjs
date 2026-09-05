#!/usr/bin/env node
/**
 * NYAY-9 native PostgreSQL evidence orchestrator.
 *
 * This process never implements an oracle itself and never treats producer
 * stdout as evidence. It validates the versioned contract, launches the
 * opt-in Python producer, reads the producer's aggregate JSON file, enforces
 * exact inventory and privacy shape, and only then publishes a PASS report.
 */

import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const CONTRACT_PATH = path.join(HERE, 'nyay9-profile-api-contract.json');
const PRODUCER_PATH = path.join(ROOT, 'backend', 'scripts', 'nyay9_postgres_profile_gate.py');
const BLOCKED_EXIT = 78;
const OPT_IN_ENV = 'NYAY9_POSTGRES_GATE';
const CONTRACT_SCHEMA = 'nyay9-profile-api-postgres/v1';
const PINNED_HEAD = '0022_nyay9_owner_profile_api';

// Keep this exact ordered inventory in executable source. Static contract
// tests and runtime report validation both consume it; zero/missing/duplicate
// rows can never be reported as PASS.
const ORACLE_INVENTORY = Object.freeze([
  'OWNER_ONLY_SESSION_AUTHORITY',
  'CROSS_OWNER_ISOLATION',
  'IDEMPOTENT_SAME_KEY_CONCURRENCY',
  'VERSION_CONFLICT_DIFFERENT_KEYS',
  'DOB_GUARDIAN_ATOMIC_TRANSITION',
  'PII_CLEAN_DIAGNOSTICS',
  'MIGRATION_UP_DOWN_UP',
]);

const AMBIENT_LIBPQ_KEYS = new Set([
  'PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD',
  'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS',
  'PGCONNECT_TIMEOUT', 'PGTARGETSESSIONATTRS',
]);

const FORBIDDEN_REPORT_KEYS = new Set([
  'actor_id', 'actor_user_id', 'canonical_payload', 'ciphertext', 'cookie',
  'database_name', 'database_url', 'date_of_birth', 'dob', 'email',
  'first_name', 'idempotency_key', 'idempotency_key_hash', 'last_name',
  'middle_name', 'mobile', 'outcome_ct', 'payload', 'profile_id',
  'registration_id', 'request_body', 'request_fingerprint',
  'scratch_database', 'session_token', 'token', 'user_id',
]);

const VALUE_PATTERNS = Object.freeze([
  ['uuid', /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i],
  ['email', /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/i],
  ['mobile', /(?<!\d)[6-9]\d{9}(?!\d)/],
  ['date', /\b(?:19|20)\d{2}-\d{2}-\d{2}\b/],
  ['url', /\b(?:postgres(?:ql)?|https?)\+?[^\s:]*:\/\//i],
  ['token', /\b(?:bearer\s+|eyJ)[A-Za-z0-9._~+/-]{12,}/i],
  ['digest', /(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])/i],
]);

function canonicalDigest(value) {
  const canonical = (candidate) => {
    if (Array.isArray(candidate)) return candidate.map(canonical);
    if (candidate && typeof candidate === 'object') {
      return Object.fromEntries(
        Object.keys(candidate).sort().map((key) => [key, canonical(candidate[key])]),
      );
    }
    return candidate;
  };
  return crypto.createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
}

function exactKeys(value, expected) {
  return Boolean(
    value && typeof value === 'object' && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort()),
  );
}

function sameArray(actual, expected) {
  return Array.isArray(actual)
    && actual.length === expected.length
    && actual.every((value, index) => value === expected[index]);
}

function loadContract() {
  let contract;
  try {
    contract = JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf8'));
  } catch {
    throw new Error('CONTRACT_UNREADABLE');
  }
  const runtime = contract?.runtime;
  const migration = contract?.migration;
  const evidence = contract?.evidence;
  if (
    contract?.schemaVersion !== CONTRACT_SCHEMA
    || contract?.ticket !== 'NYAY-9'
    || contract?.producer !== 'backend/scripts/nyay9_postgres_profile_gate.py'
    || contract?.orchestrator !== 'scripts/ci/nyay9-profile-api-postgres.mjs'
    || contract?.oracleCount !== ORACLE_INVENTORY.length
    || !sameArray(contract?.oracleInventory, ORACLE_INVENTORY)
    || !exactKeys(contract?.requiredOutcomes, ORACLE_INVENTORY)
    || runtime?.postgresMajor !== 16
    || runtime?.pgvectorRequired !== true
    || runtime?.scratchDatabasePrefix !== 'nyay9_profile_'
    || !sameArray(runtime?.scratchPurposeInventory, ['runtime', 'migration', 'behavior'])
    || runtime?.controlUrl?.literalLoopbackIpOnly !== true
    || runtime?.controlUrl?.queryFree !== true
    || runtime?.controlUrl?.ambientLibpqRejected !== true
    || migration?.revision !== PINNED_HEAD
    || migration?.downRevision !== '0021_nyay5_profile_boundary'
    || migration?.path !== 'backend/app/db/migrations/versions/0022_nyay9_owner_profile_api.py'
    || migration?.sha256Authority !== 'backend/app/db/migration_release_guard.py#NYAY9_SOURCE_SHA256'
    || evidence?.aggregateOnly !== true
    || evidence?.exactOracleInventoryRequired !== true
    || evidence?.zeroExecutedCannotPass !== true
    || evidence?.producerExitMustBeZero !== true
    || evidence?.scratchCleanupRequired !== true
  ) {
    throw new Error('CONTRACT_MISMATCH');
  }
  return contract;
}

function sourceContractCheck(contract) {
  let source;
  try {
    source = fs.readFileSync(PRODUCER_PATH, 'utf8');
  } catch {
    throw new Error('PRODUCER_UNREADABLE');
  }
  if (
    !ORACLE_INVENTORY.every((identifier) => source.includes(`"${identifier}"`))
    || !source.includes(`OPT_IN_ENV = "${OPT_IN_ENV}"`)
    || !source.includes('SCRATCH_PREFIX = "nyay9_profile_"')
    || !source.includes('ThreadPoolExecutor(max_workers=2)')
    || !source.includes('Idempotency-Replayed')
    || !source.includes('profile_version_conflict')
    || !source.includes('profile_idempotency_conflict')
    || !source.includes('upgrade", PINNED_HEAD')
    || !source.includes('downgrade", PREVIOUS_REVISION')
    || !source.includes('_privacy_findings(report)')
  ) {
    throw new Error('PRODUCER_SOURCE_CONTRACT_MISMATCH');
  }
  return {
    gate: 'nyay9_profile_api_postgres',
    status: 'PASS',
    classification: 'CONTRACT_CHECK_ONLY',
    executed: false,
    oracle_count: ORACLE_INVENTORY.length,
    oracle_inventory_exact: true,
    producer_source_bound: true,
    contract_digest: canonicalDigest(contract),
    exit_code: 0,
  };
}

function parseArgs(argv) {
  const result = {
    checkContract: false,
    execute: false,
    databaseUrl: process.env.DATABASE_URL || '',
    output: '',
    producerOutput: '',
    python: process.env.PYTHON || 'python3',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--check-contract') result.checkContract = true;
    else if (value === '--execute') result.execute = true;
    else if (['--database-url', '--output', '--producer-output', '--python'].includes(value)) {
      const next = argv[index + 1];
      if (!next) throw new Error('ARGUMENT_VALUE_REQUIRED');
      index += 1;
      if (value === '--database-url') result.databaseUrl = next;
      else if (value === '--output') result.output = next;
      else if (value === '--producer-output') result.producerOutput = next;
      else result.python = next;
    } else {
      throw new Error('UNKNOWN_ARGUMENT');
    }
  }
  return result;
}

function safeControlUrl(raw) {
  if (!raw || typeof raw !== 'string') throw new Error('CONTROL_URL_REQUIRED');
  if (
    Object.keys(process.env).some(
      (key) => AMBIENT_LIBPQ_KEYS.has(key) || key.startsWith('PGSSL'),
    )
  ) {
    throw new Error('AMBIENT_LIBPQ_REJECTED');
  }
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error('CONTROL_URL_INVALID');
  }
  if (
    !/^postgres(?:ql)?(?:\+psycopg)?:$/.test(parsed.protocol)
    || !['127.0.0.1', '[::1]'].includes(parsed.hostname)
    || parsed.search
    || parsed.hash
  ) {
    throw new Error('CONTROL_URL_POLICY_REJECTED');
  }
  return raw;
}

function normalizedKey(key) {
  return String(key).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function privacyFindings(value) {
  const findings = new Set();
  const visit = (candidate, at) => {
    if (Array.isArray(candidate)) {
      candidate.forEach((item, index) => visit(item, `${at}[${index}]`));
    } else if (candidate && typeof candidate === 'object') {
      Object.entries(candidate).forEach(([key, item]) => {
        const normalized = normalizedKey(key);
        if (FORBIDDEN_REPORT_KEYS.has(normalized)) {
          findings.add(`${at}.${normalized}:forbidden_key`);
        }
        visit(item, `${at}.${normalized}`);
      });
    } else if (typeof candidate === 'string') {
      VALUE_PATTERNS.forEach(([label, pattern]) => {
        if (pattern.test(candidate)) findings.add(`${at}:${label}`);
      });
    }
  };
  visit(value, 'report');
  return [...findings].sort();
}

function validMetrics(metrics) {
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) return false;
  const findings = privacyFindings(metrics);
  return findings.length === 0
    && Object.values(metrics).every(
      (value) => typeof value === 'boolean' || Number.isSafeInteger(value),
    );
}

function validateProducerReport(report, producerExit) {
  if (!exactKeys(report, [
    'gate', 'status', 'executed', 'head', 'assertions', 'assertion_summary',
    'scratch_cleanup', 'privacy_scan', 'exit_code',
  ])) return false;
  if (
    producerExit !== 0
    || report.gate !== 'nyay9_profile_api_postgres_producer'
    || report.status !== 'PASS'
    || report.executed !== true
    || report.head !== PINNED_HEAD
    || report.exit_code !== 0
    || !Array.isArray(report.assertions)
    || report.assertions.length !== ORACLE_INVENTORY.length
  ) return false;

  const ids = report.assertions.map((row) => row?.id);
  if (!sameArray(ids, ORACLE_INVENTORY)) return false;
  if (!report.assertions.every((row) => (
    exactKeys(row, ['id', 'status', 'passed', 'metrics'])
    && row.status === 'PASS'
    && row.passed === true
    && validMetrics(row.metrics)
  ))) return false;

  const summary = report.assertion_summary;
  const cleanup = report.scratch_cleanup;
  const privacy = report.privacy_scan;
  return Boolean(
    exactKeys(summary, [
      'required', 'executed', 'passed', 'failed', 'failed_ids',
      'exact_inventory', 'overall_pass',
    ])
    && summary.required === ORACLE_INVENTORY.length
    && summary.executed === ORACLE_INVENTORY.length
    && summary.passed === ORACLE_INVENTORY.length
    && summary.failed === 0
    && sameArray(summary.failed_ids, [])
    && summary.exact_inventory === true
    && summary.overall_pass === true
    && exactKeys(cleanup, [
      'created', 'removed', 'cleanup_failed', 'all_created_removed',
      'inventory_match', 'baseline_count', 'final_count', 'purposes',
    ])
    && cleanup.created === 3
    && cleanup.removed === 3
    && cleanup.cleanup_failed === 0
    && cleanup.all_created_removed === true
    && cleanup.inventory_match === true
    && cleanup.baseline_count === cleanup.final_count
    && sameArray(cleanup.purposes, ['runtime', 'migration', 'behavior'])
    && exactKeys(privacy, ['scanned', 'findings', 'passed'])
    && privacy.scanned === true
    && privacy.findings === 0
    && privacy.passed === true
    && privacyFindings(report).length === 0
  );
}

function blockedReport(reasonCode) {
  return {
    gate: 'nyay9_profile_api_postgres',
    status: 'BLOCKED',
    executed: false,
    reason_code: reasonCode,
    oracle_summary: {
      required: ORACLE_INVENTORY.length,
      executed: 0,
      passed: 0,
      failed: ORACLE_INVENTORY.length,
      exact_inventory: false,
    },
    exit_code: BLOCKED_EXIT,
  };
}

function failureReport(reasonCode, producerExit = null) {
  return {
    gate: 'nyay9_profile_api_postgres',
    status: 'FAIL',
    executed: producerExit !== null,
    reason_code: reasonCode,
    producer_exit_code: Number.isInteger(producerExit) ? producerExit : -1,
    oracle_summary: {
      required: ORACLE_INVENTORY.length,
      executed: 0,
      passed: 0,
      failed: ORACLE_INVENTORY.length,
      exact_inventory: false,
    },
    exit_code: 1,
  };
}

function writeReport(destination, report) {
  if (!destination) return;
  fs.mkdirSync(path.dirname(path.resolve(destination)), { recursive: true, mode: 0o700 });
  fs.writeFileSync(destination, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
}

function publishAndExit(report, output) {
  writeReport(output, report);
  process.stdout.write(`${JSON.stringify(report)}\n`);
  process.exitCode = report.exit_code;
}

function main() {
  let args;
  let contract;
  try {
    args = parseArgs(process.argv.slice(2));
    contract = loadContract();
    if (args.checkContract) {
      publishAndExit(sourceContractCheck(contract), args.output);
      return;
    }
  } catch (error) {
    publishAndExit(failureReport(error instanceof Error ? error.message : 'CONTRACT_INVALID'), args?.output || '');
    return;
  }

  if (!args.execute || process.env[OPT_IN_ENV] !== '1') {
    publishAndExit(blockedReport('EXPLICIT_EXECUTION_OPT_IN_REQUIRED'), args.output);
    return;
  }

  let databaseUrl;
  try {
    databaseUrl = safeControlUrl(args.databaseUrl);
  } catch (error) {
    publishAndExit(blockedReport(error instanceof Error ? error.message : 'CONTROL_URL_REJECTED'), args.output);
    return;
  }

  let temporaryRoot = '';
  let producerOutput = args.producerOutput;
  try {
    if (!producerOutput) {
      temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'nyay9-postgres-producer-'));
      fs.chmodSync(temporaryRoot, 0o700);
      producerOutput = path.join(temporaryRoot, 'producer-report.json');
    }
    if (args.output && path.resolve(args.output) === path.resolve(producerOutput)) {
      throw new Error('OUTPUT_PATHS_MUST_BE_DISTINCT');
    }
    const child = spawnSync(
      args.python,
      [
        PRODUCER_PATH,
        '--execute',
        '--database-url', databaseUrl,
        '--output', producerOutput,
      ],
      {
        cwd: path.join(ROOT, 'backend'),
        env: { ...process.env, [OPT_IN_ENV]: '1' },
        encoding: 'utf8',
        maxBuffer: 1024 * 1024,
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    const producerExit = Number.isInteger(child.status) ? child.status : 1;
    if (producerExit === BLOCKED_EXIT) {
      publishAndExit(blockedReport('PRODUCER_PREREQUISITE_BLOCKED'), args.output);
      return;
    }
    let producerReport;
    try {
      producerReport = JSON.parse(fs.readFileSync(producerOutput, 'utf8'));
    } catch {
      publishAndExit(failureReport('PRODUCER_REPORT_UNREADABLE', producerExit), args.output);
      return;
    }
    if (!validateProducerReport(producerReport, producerExit)) {
      publishAndExit(failureReport('PRODUCER_REPORT_REJECTED', producerExit), args.output);
      return;
    }
    const finalReport = {
      gate: 'nyay9_profile_api_postgres',
      status: 'PASS',
      executed: true,
      head: PINNED_HEAD,
      assertions: producerReport.assertions,
      oracle_summary: {
        required: ORACLE_INVENTORY.length,
        executed: ORACLE_INVENTORY.length,
        passed: ORACLE_INVENTORY.length,
        failed: 0,
        exact_inventory: true,
      },
      scratch_cleanup: producerReport.scratch_cleanup,
      privacy_scan: {
        scanned: true,
        findings: 0,
        passed: true,
      },
      producer_exit_code: 0,
      exit_code: 0,
    };
    if (privacyFindings(finalReport).length !== 0) {
      publishAndExit(failureReport('FINAL_REPORT_PRIVACY_REJECTED', 0), args.output);
      return;
    }
    publishAndExit(finalReport, args.output);
  } catch (error) {
    publishAndExit(failureReport(error instanceof Error ? error.message : 'ORCHESTRATOR_FAILURE'), args.output);
  } finally {
    if (temporaryRoot && temporaryRoot.startsWith(`${os.tmpdir()}${path.sep}nyay9-postgres-producer-`)) {
      fs.rmSync(temporaryRoot, { recursive: true, force: true });
    }
  }
}

main();

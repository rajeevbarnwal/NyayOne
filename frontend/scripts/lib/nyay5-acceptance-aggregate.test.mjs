import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  NYAY4_BLOCKING_POSTGRES_ASSERTION_IDS,
  NYAY4_POSTGRES_ASSERTION_IDS,
  NYAY4_QUARANTINED_ASSERTION_ID,
  NYAY4_QUARANTINE_REASON,
  NYAY5_ACCEPTANCE_ATTESTATION_IDS,
  aggregateNyay5Acceptance,
} from '../nyay5-acceptance-aggregate.mjs';
import {
  NYAY5_ACCEPTANCE_EXECUTION_MAP,
  NYAY5_ASSERTION_INVENTORY,
  NYAY5_SELECTOR_EXECUTION_IDS,
} from './nyay5-profile-browser-contract.mjs';

const mappedIds = [...new Set(Object.values(NYAY5_ACCEPTANCE_EXECUTION_MAP).flat())];
const idsWithPrefix = (prefix) => mappedIds.filter((id) => id.startsWith(prefix));

function execution(id) {
  return {
    id,
    executed: true,
    skipped: false,
    pass: true,
    evidenceCount: 1,
    selectorCount: NYAY5_SELECTOR_EXECUTION_IDS.includes(id) ? 1 : null,
  };
}

function fixtures() {
  const browserExecutions = idsWithPrefix('browser:').map(execution);
  const postgresIds = idsWithPrefix('postgres:').map((id) => id.slice('postgres:'.length));
  return {
    browser: {
      gate: 'nyay5_profile_browser',
      status: 'PASS',
      executed: true,
      total: NYAY5_ASSERTION_INVENTORY.length,
      passed: NYAY5_ASSERTION_INVENTORY.length,
      failed: 0,
      inventoryExact: true,
      artifacts: { screenshots: 2 },
      rows: NYAY5_ASSERTION_INVENTORY.map((name) => ({ name, pass: true })),
      executions: browserExecutions,
      acceptanceExecutionCoverage: {
        pass: true,
        mapped: 61,
        missing: 0,
        skipped: 0,
        unknown: 0,
        unique: true,
      },
    },
    postgres: {
      gate: 'nyay5_postgres',
      status: 'PASS',
      executed: true,
      head: '0021_nyay5_profile_boundary',
      assertions: postgresIds.map((id) => ({ id, status: 'PASS', passed: true })),
      assertion_summary: {
        exact_inventory: true,
        required: postgresIds.length,
        passed: postgresIds.length,
        failed: [],
        overall_pass: true,
      },
      privacy_scan: { findings: 0, passed: true },
    },
    otpPostgres: {
      gate: 'nyay4_postgres_otp',
      status: 'PASS',
      executed: true,
      assertion_ids: [...NYAY4_POSTGRES_ASSERTION_IDS],
      assertions: {
        exact_inventory: true,
        required: NYAY4_BLOCKING_POSTGRES_ASSERTION_IDS.length,
        passed: NYAY4_BLOCKING_POSTGRES_ASSERTION_IDS.length,
        overall_pass: true,
        failed: [],
        inventory_failures: {
          missing: 0,
          extra: 0,
          duplicate: 0,
          reordered: false,
        },
        quarantined: {
          executed: true,
          failed: [NYAY4_QUARANTINED_ASSERTION_ID],
          ids: [NYAY4_QUARANTINED_ASSERTION_ID],
          passed: 0,
          required: 1,
          skipped: false,
        },
      },
      mutants: { required: 27, killed: 27 },
      quarantine_diagnostic: {
        assertion_id: NYAY4_QUARANTINED_ASSERTION_ID,
        cookie_state: {
          httponly: true,
          raw_flow_token_rows: 0,
          reload_metadata_equal: true,
          reload_status: 200,
          samesite: 'strict',
          secure_nonlocal: true,
          start_signatures_equal: true,
          start_statuses: [202, 202],
          uuid_in_response: false,
        },
        executed: true,
        origin_values: {
          configured: { kind: 'configured_fixture', status: 200 },
          missing: { kind: 'absent', status: 403 },
          untrusted: { kind: 'untrusted_fixture', status: 403 },
        },
        passed: false,
        quarantine_eligible: true,
        quarantined_on: '2026-08-24',
        reason: NYAY4_QUARANTINE_REASON,
        skipped: false,
        stage: 'behavior-cookie-origin-reload-symmetry',
        timing: {
          bound_milli: 2000,
          p95_ratio_milli: 2001,
          samples_per_class: 40,
          within_bound: false,
        },
      },
      privacy_findings: 0,
    },
    attestations: {
      gate: 'nyay5_acceptance_attestations_v1',
      status: 'PASS',
      executed: true,
      executions: NYAY5_ACCEPTANCE_ATTESTATION_IDS.map(execution),
    },
  };
}

describe('NYAY-5 exact acceptance-matrix aggregate', () => {
  it('exposes one canonical package command for the cross-gate aggregate', () => {
    const packageJson = JSON.parse(readFileSync(
      new URL('../../package.json', import.meta.url), 'utf8',
    ));
    expect(packageJson.scripts['qa:nyay5:acceptance']).toBe(
      'node scripts/nyay5-acceptance-aggregate.mjs',
    );
  });

  it('maps all 61 IDs only from exact executed producer evidence', () => {
    const result = aggregateNyay5Acceptance(fixtures());
    expect(result).toMatchObject({
      gate: 'nyay5_acceptance_matrix',
      status: 'PASS',
      executed: true,
      total: 61,
      passed: 61,
      failed: 0,
      inventoryExact: true,
    });
    expect(result.assertions).toHaveLength(61);
    expect(result.executionCoverage).toMatchObject({
      pass: true,
      mapped: 61,
      missing: 0,
      skipped: 0,
      unknown: 0,
    });
    expect(result.executionInventory).toEqual({
      count: 77,
      sha256: '2f38f7d93992911c68f426aad28766d912235ac40bd6937c8ef3fee6105a9662',
    });
  });

  it('binds AUTH-04 to the exact four-class start-and-resend PostgreSQL assertion', () => {
    expect(NYAY5_ACCEPTANCE_EXECUTION_MAP['AUTH-04']).toEqual([
      'nyay4-postgres:CONTRACT-PREAUTH-ENUMERATION-NEUTRAL',
    ]);
    expect(NYAY4_POSTGRES_ASSERTION_IDS).toContain(
      'CONTRACT-PREAUTH-ENUMERATION-NEUTRAL',
    );
    const missing = fixtures();
    missing.otpPostgres.assertion_ids = missing.otpPostgres.assertion_ids.filter(
      (id) => id !== 'CONTRACT-PREAUTH-ENUMERATION-NEUTRAL',
    );
    expect(aggregateNyay5Acceptance(missing).status).toBe('FAIL');
    expect(aggregateNyay5Acceptance(missing).assertions.find(
      (row) => row.id === 'AUTH-04',
    )?.passed).toBe(false);
  });

  it('keeps the single quarantined assertion executed and visible without forging green', () => {
    const observedFlake = fixtures();
    expect(observedFlake.otpPostgres.quarantine_diagnostic.passed).toBe(false);
    expect(aggregateNyay5Acceptance(observedFlake).status).toBe('PASS');

    for (const mutate of [
      (value) => { delete value.quarantine_diagnostic; },
      (value) => { value.quarantine_diagnostic.assertion_id = 'REMOVED'; },
      (value) => { value.quarantine_diagnostic.executed = false; },
      (value) => { value.quarantine_diagnostic.skipped = true; },
      (value) => { delete value.quarantine_diagnostic.timing; },
      (value) => { value.quarantine_diagnostic.reason = 'weakened'; },
      (value) => { value.mutants.killed = 26; },
    ]) {
      const mutant = fixtures();
      mutate(mutant.otpPostgres);
      expect(aggregateNyay5Acceptance(mutant).status).toBe('FAIL');
    }
  });

  it('fails closed for missing, skipped, failed, duplicate, or zero-selector evidence', () => {
    const missing = fixtures();
    missing.postgres.assertions.shift();
    expect(aggregateNyay5Acceptance(missing).status).toBe('FAIL');

    const skipped = fixtures();
    skipped.attestations.executions[0].skipped = true;
    expect(aggregateNyay5Acceptance(skipped).status).toBe('FAIL');

    const failed = fixtures();
    failed.otpPostgres.status = 'FAIL';
    expect(aggregateNyay5Acceptance(failed).status).toBe('FAIL');

    const duplicate = fixtures();
    duplicate.browser.executions.push({ ...duplicate.browser.executions[0] });
    expect(aggregateNyay5Acceptance(duplicate).status).toBe('FAIL');

    const zeroSelector = fixtures();
    const selector = zeroSelector.browser.executions.find((row) => (
      NYAY5_SELECTOR_EXECUTION_IDS.includes(row.id)
    ));
    selector.selectorCount = 0;
    expect(aggregateNyay5Acceptance(zeroSelector).status).toBe('FAIL');
  });

  it('consumes the PostgreSQL producer exact schema and rejects the inverse spelling', () => {
    const inverseSpelling = fixtures();
    inverseSpelling.postgres.assertion_summary.inventory_exact = true;
    delete inverseSpelling.postgres.assertion_summary.exact_inventory;
    expect(aggregateNyay5Acceptance(inverseSpelling).status).toBe('FAIL');

    const hiddenFailure = fixtures();
    hiddenFailure.postgres.assertion_summary.failed = ['forged-hidden-failure'];
    expect(aggregateNyay5Acceptance(hiddenFailure).status).toBe('FAIL');
  });

  it('rejects fabricated or unknown supplemental attestations', () => {
    const unknown = fixtures();
    unknown.attestations.executions.push(execution('ci:not-a-required-check'));
    expect(aggregateNyay5Acceptance(unknown).status).toBe('FAIL');

    const missing = fixtures();
    missing.attestations.executions.pop();
    expect(aggregateNyay5Acceptance(missing).status).toBe('FAIL');
  });

  it('kills a failed-required-job with a forged green aggregator', () => {
    const failedRequiredJob = fixtures();
    const requiredJob = failedRequiredJob.attestations.executions.find(
      (row) => row.id === 'ci:required-job-fail-closed',
    );
    requiredJob.pass = false;
    failedRequiredJob.attestations.status = 'PASS';
    expect(aggregateNyay5Acceptance(failedRequiredJob)).toMatchObject({
      status: 'FAIL',
      producerStatus: { attestations: true },
    });
  });
});

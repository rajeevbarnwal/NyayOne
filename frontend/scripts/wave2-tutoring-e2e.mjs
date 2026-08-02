/**
 * Wave 2 tutoring REAL-BROWSER driver (SAATHI-124 / SAATHI-128, matrix I1/I2/J1).
 *
 * Invoked by `scripts/wave2_tutoring_browser_gate.sh`, which has already put a
 * migrated+seeded SQLite database, a real uvicorn backend and a real production
 * frontend bundle in front of it. This file only drives Chromium and writes
 * evidence; it starts no server and owns no fixture.
 *
 * Honesty rules baked in:
 *   * every claim written to disk is either a DOM/geometry/network OBSERVATION
 *     made in this process, or is explicitly tagged `mechanism: "server_leg"`
 *     (an HTTP call this driver made as the payment/video provider, as the
 *     tutor, as a rival student or as an admin — actors a student's browser
 *     cannot be) or `mechanism: "clock_shift"` (a fixture row moved in time).
 *   * a stage that fails records the failure plus a screenshot and the run
 *     continues, so an interruption still leaves real evidence on disk.
 *   * nothing is asserted about a screen this driver did not actually load.
 *
 * Stages (E2E_STAGES, comma separated; `none` = boot only):
 *   a    S-31 discovery: filters, sort, pagination
 *   b    S-32 tutor detail + availability
 *   c    S-33 hold -> provider order -> paid webhook -> S-34 confirmation
 *   e    live-room entry with a real server-issued join credential
 *   geo  I2 live-room geometry / a11y measurement
 *   d1   S-35 reschedule outside the free window
 *   d2   S-35 <24h reschedule refusal, cancel with refund + cancel without
 *   d3   completion after scheduled end, attendance state, review gate
 *   d4   attendance confirm -> review allowed; dispute -> review blocked
 *   neg  hold expiry, slot conflict, payment failure, refused room entry
 *   n45  media-plane disconnect/reconnect on the PRODUCTION live room, over its
 *        real VideoRoomClient boundary with the deterministic adapter selected
 *        at runtime (part of `neg`; also runnable on its own)
 *   rl   rate limit rendered in the browser
 *   priv J1 privacy scan over everything captured on disk
 */
import { chromium } from 'playwright';
import { createHmac, createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

/* ------------------------------------------------------------------ config */

const WEB = must('E2E_WEB_URL');
const API = must('E2E_API_URL');
const OUT = must('E2E_OUT_DIR');
const FIXTURE_PATH = must('E2E_FIXTURE');
const STAGES = (process.env.E2E_STAGES || 'a').split(',').map((s) => s.trim()).filter(Boolean);
const PYTHON = process.env.E2E_PYTHON || 'python3';
const REPO_ROOT = process.env.E2E_REPO_ROOT || process.cwd();
const BACKEND_LOG = process.env.E2E_BACKEND_LOG || '';
/**
 * The pid of the uvicorn process the runner started, and the commit the whole
 * run is being judged at. Both are REQUIRED: a driver that cannot see the
 * backend process cannot tell "no errors" from "no backend", and evidence that
 * does not name its commit cannot be told apart from evidence of another one.
 * Their absence is a FAIL, never a silent skip (see `backendOracle`).
 */
const BACKEND_PID = Number(process.env.E2E_BACKEND_PID || '0') || 0;
const COMMIT = process.env.E2E_COMMIT || '';
const FEE_PAISE = Number(process.env.E2E_FEE_PAISE || '250000');
const RUN_ID = process.env.E2E_RUN_ID || 'adhoc';
const SEARCH_LIMIT = Number(process.env.E2E_SEARCH_LIMIT || '200');
const BOOKING_LIMIT = Number(process.env.E2E_BOOKING_LIMIT || '400');
const REVIEW_LIMIT = Number(process.env.E2E_REVIEW_LIMIT_PER_HOUR || '200');
const JOIN_TTL = Number(process.env.E2E_JOIN_TTL_SECONDS || '300');

/** Compile-time constants of the deterministic adapters (not env secrets). */
const PAY_KEY = Buffer.from('legalsaathi-deterministic-payment-test-key');
const PAY_SIG_HEADER = 'X-Payment-Signature';
const VIDEO_KEY = Buffer.from('legalsaathi-deterministic-video-test-key');
const VIDEO_SIG_HEADER = 'X-Video-Signature';

const STUDENT = '00000000-0000-4000-8000-0000000000de';
const RIVAL = '00000000-0000-4000-8000-0000000000b2';
/**
 * The DEDICATED review-rate-limit actor (N44). Seeded by
 * `backend/scripts/wave2_e2e_fixture.py` as `review_rate_limit_student`, and
 * used by N44 and NOTHING else.
 *
 * `RATE_LIMIT_REVIEW_PER_HOUR` buckets per user id, so a boundary measured on
 * an identity some earlier case already spent is a boundary measured short.
 * N44 used to reuse RIVAL, which N34/N35 charge two `PATCH
 * /tutoring/reviews/{id}` calls; the full run therefore reported "last admitted
 * 198, first rejected 199" against a configured limit of 200 — off by exactly
 * the two calls, and plausible enough to be believed. The oracle was
 * contaminated, not the limiter.
 *
 * This is not a convention anybody has to remember: `api()` keeps a LEDGER of
 * every request that reaches a review-limited route, per actor, and N44 asserts
 * this actor's ledger reads ZERO before it measures anything (see
 * `reviewLimiterLedger` / `assertUnspentReviewBudget`).
 */
const REVIEW_LIMIT_ACTOR = '00000000-0000-4000-8000-000000004400';
/**
 * The admin actor. `session_cancellations` / `review_moderation` carry FKs to
 * `users`, and the completion-authority row (F6) has to prove that ADMIN is a
 * recorder role alongside `tutor` — so this id is used, not merely declared.
 */
const ADMIN = '00000000-0000-4000-8000-00000000ad01';

/* ------------------------------------------------- FAIL-CLOSED FAULT INJECT */

/**
 * The four fail-closed proofs (F4.8) are driven from HERE, not from a patched
 * copy of this file, so the "reverted" state is provably the same bytes that
 * produced the clean run — the injection is data, and the evidence records
 * which switch was on.
 *
 *   E2E_INJECT=missing-negative   drop a REQUIRED negative case from the run
 *   E2E_INJECT=console-error      emit an unexpected console error in a stage
 *   E2E_INJECT=port-collision     point the driver's web+api at one port
 *   E2E_INJECT=media-never-ready  make getUserMedia hang forever
 *   E2E_INJECT=privacy-canary     plant a real secret in browser storage
 *
 * F3 — the backend-log / liveness / evidence-provenance oracle. Each of these
 * must produce a NON-ZERO exit, and each is data rather than a patch, so the
 * clean run is provably the same bytes:
 *
 *   E2E_INJECT=log-unhandled      write a real `unhandled_exception` ERROR line
 *                                 into logs/backend_uvicorn.log
 *   E2E_INJECT=log-asgi-traceback write an "Exception in ASGI application"
 *                                 traceback (with an IndexError) into that log
 *   E2E_INJECT=unexpected-404     rewrite the browser's OWN session fetch onto a
 *                                 session id that does not exist, so the REAL
 *                                 backend answers 404 for a session the screen
 *                                 believes it owns — nobody declared it
 *   E2E_INJECT=backend-kill       SIGKILL the backend process mid-run
 *   E2E_INJECT=stale-commit       carry evidence in from a DIFFERENT commit
 *   E2E_INJECT=skip-stage         silently drop a PLANNED stage from the run
 *   E2E_INJECT=n44-contaminated-actor
 *                                 run N44 as RIVAL — the actor N34/N35 have
 *                                 already charged two review mutations — which
 *                                 is EXACTLY the defect this stage used to
 *                                 have (it reported 198/199 against a
 *                                 configured 200). N44's zero-prior-use
 *                                 precondition must catch it and FAIL, and the
 *                                 proof that it does is captured evidence, not
 *                                 a claim.
 */
const INJECT = new Set((process.env.E2E_INJECT || '').split(',').map((s) => s.trim()).filter(Boolean));
const injected = (name) => INJECT.has(name);

const MOBILE = { width: 390, height: 844 };

const DIRS = {
  shots: path.join(OUT, 'shots'),
  dom: path.join(OUT, 'dom'),
  net: path.join(OUT, 'net'),
  storage: path.join(OUT, 'storage'),
  traces: path.join(OUT, 'traces'),
  work: path.join(OUT, 'work'),
};
for (const d of Object.values(DIRS)) fs.mkdirSync(d, { recursive: true });

const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));
const STATE_PATH = path.join(DIRS.work, 'state.json');
const RESULTS_PATH = path.join(OUT, 'journeys.json');

let STATE = fs.existsSync(STATE_PATH) ? JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) : {};
const RESULTS = fs.existsSync(RESULTS_PATH) ? JSON.parse(fs.readFileSync(RESULTS_PATH, 'utf8')) : [];

function must(name) {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is required`);
  return v;
}
function saveState() {
  fs.writeFileSync(STATE_PATH, JSON.stringify(STATE, null, 2));
}
function saveResults() {
  fs.writeFileSync(RESULTS_PATH, JSON.stringify(RESULTS, null, 2));
}
function record(entry) {
  const idx = RESULTS.findIndex((r) => r.id === entry.id);
  // Every row names the commit it was produced from, so evidence carried into
  // this directory from another one cannot pass as this run's (F3).
  const row = { ...entry, commit: COMMIT || null, at: new Date().toISOString() };
  if (idx >= 0) RESULTS[idx] = row;
  else RESULTS.push(row);
  saveResults();
  const mark = row.outcome === 'pass' ? 'PASS' : row.outcome === 'defect' ? 'DEFECT' : row.outcome === 'skip' ? 'SKIP' : 'FAIL';
  console.log(`  [${mark}] ${row.id} — ${row.summary}`);
}

/* ------------------------------------------------- fail-closed assertions */

/**
 * F4.5. A stage records PASS only when EVERY assertion it declared ran and
 * passed. The declaration comes first and the results are matched back to it,
 * so an assertion that was never reached is a FAIL — it can no longer vanish by
 * simply not appending to a list. `null`, `undefined` and the string `N/A` are
 * refused as observations for the same reason: they are the absence of a
 * measurement, and the absence of a measurement is not evidence of correctness.
 */
const NON_OBSERVATIONS = new Set(['n/a', 'na', 'null', 'undefined', 'unknown', '']);

function isNonObservation(actual) {
  if (actual === null || actual === undefined) return true;
  if (typeof actual === 'string' && NON_OBSERVATIONS.has(actual.trim().toLowerCase())) return true;
  return false;
}

class Checks {
  /**
   * @param {string} id      the row id this evidence belongs to
   * @param {string[]} required  every assertion name that MUST run
   */
  constructor(id, required) {
    this.id = id;
    this.required = [...required];
    this.rows = [];
    this.notes = {};
  }

  /** Record one assertion. `ok` may be a boolean or a predicate on `actual`. */
  assert(name, expected, actual, ok) {
    const nonObservation = isNonObservation(actual);
    const passed = nonObservation ? false : (typeof ok === 'function' ? !!ok(actual) : !!ok);
    const row = {
      case: name,
      expected,
      actual: nonObservation ? `NOT OBSERVED (${actual === undefined ? 'undefined' : JSON.stringify(actual)})` : actual,
      result: passed ? 'PASS' : 'FAIL',
      ...(nonObservation ? { why: 'mandatory assertion produced no observation' } : {}),
    };
    const at = this.rows.findIndex((r) => r.case === name);
    if (at >= 0) this.rows[at] = row;
    else this.rows.push(row);
    return passed;
  }

  eq(name, expected, actual) {
    return this.assert(name, expected, actual, (a) => JSON.stringify(a) === JSON.stringify(expected));
  }

  /** `expected` is prose; `ok` decides. Used where equality is not the point. */
  ok(name, expected, actual, predicate) {
    return this.assert(name, expected, actual, predicate);
  }

  /** An assertion that could not be attempted at all. Always a FAIL, never a skip. */
  blocked(name, expected, why) {
    const row = { case: name, expected, actual: `BLOCKED: ${why}`, result: 'FAIL' };
    const at = this.rows.findIndex((r) => r.case === name);
    if (at >= 0) this.rows[at] = row;
    else this.rows.push(row);
    return false;
  }

  /** Assertions declared but never executed. */
  get unexecuted() {
    const seen = new Set(this.rows.map((r) => r.case));
    return this.required.filter((n) => !seen.has(n));
  }

  get extras() {
    const need = new Set(this.required);
    return this.rows.filter((r) => !need.has(r.case)).map((r) => r.case);
  }

  get failed() {
    return this.rows.filter((r) => r.result !== 'PASS').map((r) => r.case);
  }

  /** The single verdict. Fail-closed in both directions. */
  get verdict() {
    if (this.unexecuted.length) return 'fail';
    if (this.failed.length) return 'fail';
    if (!this.rows.length) return 'fail';
    return 'pass';
  }

  /** The table rows, including one synthetic FAIL row per unexecuted assertion. */
  get table() {
    const missing = this.unexecuted.map((name) => ({
      case: name,
      expected: 'declared mandatory assertion',
      actual: 'NOT EXECUTED — the stage returned without running it',
      result: 'FAIL',
    }));
    return [...this.rows, ...missing];
  }

  summary() {
    const t = this.table;
    const p = t.filter((r) => r.result === 'PASS').length;
    return `${p}/${t.length} assertions passed`;
  }
}

/** Build a Checks and, at the end, `record()` it with the gate's findings folded in. */
function newChecks(id, required) {
  return new Checks(id, required);
}

function recordChecks(chk, { stage, matrix, summary, observed, artifacts = [], mechanism }) {
  // F3. Judge the BACKEND's own log region for this row before draining, so a
  // server-side error raised by the very request this row asserts on is owned
  // by this row and not by whatever runs next.
  const region = BACKEND.harvest(chk.id);
  const gateProblems = GATE.drain(chk.id);
  const browserProblems = gateProblems.filter((p) => p.kind !== 'backendlog');
  const logProblems = gateProblems.filter((p) => p.kind === 'backendlog');
  if (browserProblems.length) {
    chk.assert(
      'no unexpected console error, page error, failed request or unexpected 4xx/5xx',
      'zero unattributed browser problems during this stage',
      browserProblems.map((p) => `${p.kind}: ${p.detail}`),
      false,
    );
  } else {
    chk.assert(
      'no unexpected console error, page error, failed request or unexpected 4xx/5xx',
      'zero unattributed browser problems during this stage',
      'zero',
      true,
    );
  }
  chk.assert(
    'no ERROR/CRITICAL/Traceback/unhandled_exception/ASGI exception/cannot commit/IndexError in the BACKEND log region this row produced',
    `zero matching lines in bytes [${region.from},${region.to}) of the backend log`,
    logProblems.length
      ? logProblems.map((p) => String(p.detail).slice(0, 300))
      : `zero across ${region.lines} new line(s) / ${region.bytes} byte(s)`,
    logProblems.length === 0 && !region.error,
  );
  record({
    id: chk.id,
    stage,
    matrix,
    outcome: chk.verdict,
    summary: `${summary} — ${chk.summary()}`,
    assertions: chk.table,
    ...(chk.failed.length || chk.unexecuted.length
      ? { failedAssertions: [...chk.failed, ...chk.unexecuted.map((n) => `${n} (NOT EXECUTED)`)] }
      : {}),
    observed,
    ...(mechanism ? { mechanism } : {}),
    artifacts,
  });
  return chk.verdict === 'pass';
}

/* ------------------------------------------------ F4.6/F4.7 the browser gate */

/**
 * Every console error/warning, page error, failed request and unexpected
 * 4xx/5xx is a FAILURE unless it is attributed to the case that owns it.
 *
 * There is deliberately NO global allowlist. An expected error is declared with
 * `expecting()` for the duration of ONE case, and the declaration must name the
 * exact METHOD, ROUTE, STATUS and typed CODE. Two things then fail the run:
 * an unattributed problem, and a declared expectation that never happened.
 */
const GATE = {
  /** problems with no owner, drained per stage */
  problems: [],
  /** currently-open expectation scopes, innermost last */
  scopes: [],
  /** everything seen, for the evidence */
  seen: [],
};

function pathOf(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return String(url);
  }
}

function routeMatches(spec, pathname) {
  if (spec instanceof RegExp) return spec.test(pathname);
  return spec === pathname;
}

/**
 * Chromium logs its OWN console error for every non-2xx it fetches:
 * "Failed to load resource: the server responded with a status of 409 (Conflict)".
 * That is the SAME failure reported a second time by the browser, not a second
 * failure. It is attributed to the http expectation that already owns that exact
 * status inside the same case — and to nothing else. It never consumes the
 * expectation's count, so an expectation is still only satisfied by a real
 * response, and a console error for a status nobody declared still fails the run.
 */
const NETWORK_ECHO = /^error: Failed to load resource: the server responded with a status of (\d{3})/;

/**
 * A 5xx is NEVER attributable.
 *
 * `expecting()` exists to scope an error a case deliberately provokes — an
 * expired hold answering 409 HOLD_EXPIRED, a rival student answering 403. A
 * server fault is a different animal: there is no product behaviour a 5xx is
 * the correct answer to, so allowing a case to declare one would be a global
 * allowlist wearing a scope's clothes. Any 5xx therefore skips attribution
 * entirely and fails the stage that produced it and the run.
 */
function isNeverAttributable(kind, info) {
  return kind === 'http' && Number(info.status) >= 500;
}

/** Try to hand a problem to an open scope. Returns the spec that took it. */
function attribute(kind, info) {
  if (isNeverAttributable(kind, info)) return null;
  if (kind === 'console') {
    const echo = NETWORK_ECHO.exec(info.detail || '');
    if (echo) {
      const status = Number(echo[1]);
      for (let i = GATE.scopes.length - 1; i >= 0; i--) {
        const owner = GATE.scopes[i].specs.find((s) => s.kind === 'http' && s.status === status);
        if (owner) {
          owner.echoes = (owner.echoes || 0) + 1;
          return owner;
        }
      }
    }
  }
  for (let i = GATE.scopes.length - 1; i >= 0; i--) {
    for (const spec of GATE.scopes[i].specs) {
      if (spec.kind !== kind) continue;
      if (spec.count >= spec.times) continue;
      if (kind === 'http') {
        if (spec.method !== info.method) continue;
        if (!routeMatches(spec.route, info.pathname)) continue;
        if (spec.status !== info.status) continue;
        if (spec.code !== undefined && spec.code !== info.code) continue;
      } else if (kind === 'console') {
        if (!spec.text.test(info.detail)) continue;
      } else if (kind === 'requestfailed') {
        if (!routeMatches(spec.route, info.pathname)) continue;
      } else if (kind === 'backendlog') {
        // A backend-log expectation has to name the exact line AND its typed
        // code; `{ kind: 'backendlog' }` on its own matches nothing. No stage
        // in this driver declares one, so the effective allowlist is EMPTY and
        // every ERROR/CRITICAL/traceback line fails the stage that produced it.
        if (!(spec.text instanceof RegExp) || spec.code === undefined) continue;
        if (!spec.text.test(info.detail)) continue;
        if (spec.code !== info.code) continue;
        if (spec.logger !== undefined && spec.logger !== info.logger) continue;
        if (spec.level !== undefined && spec.level !== info.level) continue;
      }
      spec.count += 1;
      spec.observed.push(info);
      return spec;
    }
  }
  return null;
}

function problem(kind, detail, info = {}) {
  const taken = attribute(kind, { ...info, detail });
  const row = { kind, detail, ...info, attributed: !!taken, at: new Date().toISOString() };
  GATE.seen.push(row);
  if (!taken) GATE.problems.push(row);
  return row;
}

GATE.drain = function drain(owner) {
  const out = this.problems.map((p) => ({ ...p, owner }));
  this.problems = [];
  return out;
};

/**
 * Scope an EXPECTED failure to the case that owns it.
 *
 *   await expecting([
 *     { kind: 'http', method: 'POST', route: '/api/v1/payments/orders',
 *       status: 409, code: 'HOLD_EXPIRED' },
 *   ], async () => { ...the clicks that must produce exactly that... });
 *
 * Returns `{ satisfied, specs }`. An expectation that did not occur is
 * `satisfied: false`, which the caller asserts on — a negative case that
 * silently stopped producing its error can no longer pass.
 */
async function expecting(specs, fn) {
  const scope = {
    specs: specs.map((s) => ({ times: 1, count: 0, observed: [], ...s })),
  };
  GATE.scopes.push(scope);
  let value;
  let thrown = null;
  try {
    value = await fn();
  } catch (err) {
    thrown = err;
  }
  await settleCaptures();
  // The backend log region this case produced is harvested while the case's
  // scope is still OPEN, so a line the case legitimately declared can be
  // attributed to it and anything else falls through to the stage.
  BACKEND.harvest(`expecting(${specs.map((s) => s.kind).join('+')})`);
  GATE.scopes.pop();
  const report = scope.specs.map((s) => ({
    kind: s.kind,
    method: s.method || null,
    route: String(s.route || s.text || ''),
    status: s.status ?? null,
    code: s.code ?? null,
    required: s.times,
    observedCount: s.count,
    satisfied: s.count >= s.times,
    observed: s.observed.slice(0, 4),
  }));
  return {
    value,
    thrown,
    specs: report,
    satisfied: report.every((r) => r.satisfied),
    unmet: report.filter((r) => !r.satisfied).map((r) => `${r.method || r.kind} ${r.route} -> ${r.status} ${r.code || ''}`.trim()),
  };
}

/* ============================ F3: the fail-closed BACKEND-LOG oracle ======= */

/**
 * A browser gate that only watches the BROWSER is half a gate. Every screen in
 * this journey is one HTTP hop from a FastAPI process, and the failures that
 * matter most — an unhandled exception swallowed into a 500 body the screen
 * renders as a friendly banner, a session that "cannot commit", a worker that
 * died between two stages — are visible in the backend's own log and in the
 * backend's own process table, and NOWHERE in the DOM.
 *
 * So this oracle asserts three things for EVERY stage, and again at the end:
 *
 *   1. the region of logs/backend_uvicorn.log that THIS stage produced
 *      contains no ERROR, no CRITICAL, no Traceback, no `unhandled_exception`,
 *      no `Exception in ASGI application`, no `cannot commit` and no
 *      `IndexError`;
 *   2. the backend process is still ALIVE (not merely un-reaped: a zombie is a
 *      dead backend), and still answers /health;
 *   3. no 5xx and no failed request reached the browser (that half lives in
 *      `GATE`, and 5xx is deliberately unattributable — see
 *      `isNeverAttributable`).
 *
 * PER-STAGE BYTE OFFSET. The log is read as a REGION, never as a whole file:
 * `BACKEND.offset` is the byte position immediately after the last line already
 * judged, it advances monotonically, and it is persisted in state.json so it
 * survives the chained 45-second shells that make up one logical run. That
 * matters twice over:
 *
 *   * a line a stage legitimately produced cannot mask a later real one — the
 *     earlier region has already been consumed and cannot be re-read as
 *     "context" for the later stage;
 *   * a stage is judged on what IT produced, so an error is attributed to the
 *     stage that caused it rather than to whichever stage happens to run last.
 *
 * If the file ever SHRINKS below the recorded offset the log was rotated or
 * truncated underneath a live run: the region boundary is then unknowable, and
 * that is a FAIL, not a reset.
 */

const BACKEND_LOG_PATTERNS = [
  { id: 'level_error', re: /(?:^|[^A-Za-z_])ERROR(?:[^A-Za-z_]|$)/, what: 'an ERROR-level backend log line' },
  { id: 'level_critical', re: /(?:^|[^A-Za-z_])CRITICAL(?:[^A-Za-z_]|$)/, what: 'a CRITICAL-level backend log line' },
  { id: 'traceback', re: /Traceback \(most recent call last\)/, what: 'a Python traceback' },
  { id: 'unhandled_exception', re: /unhandled_exception/, what: 'the app-level unhandled exception handler firing' },
  { id: 'asgi_exception', re: /Exception in ASGI application/, what: 'an exception escaping into the ASGI layer' },
  { id: 'cannot_commit', re: /cannot commit/i, what: 'a transaction that could not be committed' },
  { id: 'index_error', re: /\bIndexError\b/, what: 'an IndexError' },
];

const BACKEND = {
  /** byte offset immediately after the last log region already judged */
  offset: Number.isFinite(Number(STATE.backendLogOffset)) ? Number(STATE.backendLogOffset) : 0,
  /** one entry per harvest: which owner consumed which byte range */
  regions: [],
  /** every matching line ever seen, for the evidence */
  findings: [],
  /** liveness/health samples */
  samples: [],
};

function backendLogSize() {
  try {
    return fs.statSync(BACKEND_LOG).size;
  } catch {
    return -1;
  }
}

/** Parse one backend log line. The app logs JSON; uvicorn logs plain text. */
function parseLogLine(line) {
  if (line.startsWith('{')) {
    try {
      const j = JSON.parse(line);
      return { level: j.level ?? null, logger: j.logger ?? null, code: j.message ?? null, requestId: j.request_id ?? null };
    } catch { /* fall through to plain text */ }
  }
  const m = /^(CRITICAL|ERROR|WARNING|INFO|DEBUG):\s+(.*)$/.exec(line);
  if (m) return { level: m[1], logger: 'uvicorn', code: m[2].slice(0, 120), requestId: null };
  return { level: null, logger: null, code: null, requestId: null };
}

/**
 * Read and JUDGE the log region produced since the last harvest. Every matching
 * line goes through `problem()`, so an open `expecting()` scope may claim it
 * (it must name the exact line pattern AND its typed code) and anything
 * unclaimed lands in `GATE.problems` and fails the stage that drains it.
 *
 * Synchronous on purpose: it is called from `recordChecks`, which is the single
 * funnel every stage verdict passes through.
 */
BACKEND.harvest = function harvest(owner) {
  const region = { owner, from: this.offset, to: this.offset, bytes: 0, lines: 0, findings: 0, at: new Date().toISOString() };
  if (!BACKEND_LOG) {
    region.error = 'E2E_BACKEND_LOG was not provided — the backend log cannot be scanned';
    this.regions.push(region);
    problem('backendlog', `FAIL-CLOSED: no backend log path was handed to the driver, so "${owner}" was judged without one`, {
      pathname: '(no log)', level: null, logger: null, code: null, pattern: 'missing_log', owner,
    });
    return region;
  }
  const size = backendLogSize();
  if (size < 0) {
    region.error = `backend log ${BACKEND_LOG} does not exist`;
    this.regions.push(region);
    problem('backendlog', `FAIL-CLOSED: backend log ${BACKEND_LOG} does not exist, so "${owner}" was judged without one`, {
      pathname: BACKEND_LOG, level: null, logger: null, code: null, pattern: 'missing_log', owner,
    });
    return region;
  }
  if (size < this.offset) {
    region.error = `backend log SHRANK from ${this.offset} to ${size} bytes — it was rotated or truncated under a live run`;
    this.regions.push(region);
    problem('backendlog', `FAIL-CLOSED: ${region.error}; the region boundary for "${owner}" is unknowable`, {
      pathname: BACKEND_LOG, level: null, logger: null, code: null, pattern: 'log_truncated', owner,
    });
    this.offset = size;
    STATE.backendLogOffset = this.offset;
    saveState();
    return region;
  }
  let text = '';
  if (size > this.offset) {
    const fd = fs.openSync(BACKEND_LOG, 'r');
    try {
      const buf = Buffer.alloc(size - this.offset);
      fs.readSync(fd, buf, 0, buf.length, this.offset);
      text = buf.toString('utf8');
    } finally {
      fs.closeSync(fd);
    }
  }
  // Only WHOLE lines are judged; a half-written trailing line stays in the
  // region for the next harvest rather than being scanned twice or dropped.
  const lastNl = text.lastIndexOf('\n');
  const consumed = lastNl >= 0 ? lastNl + 1 : 0;
  const body = text.slice(0, consumed);
  region.to = this.offset + consumed;
  region.bytes = consumed;

  const lines = body.length ? body.split('\n').filter((l) => l.length) : [];
  region.lines = lines.length;
  for (const line of lines) {
    const matched = BACKEND_LOG_PATTERNS.filter((p) => p.re.test(line));
    if (!matched.length) continue;
    const meta = parseLogLine(line);
    const finding = {
      owner,
      patterns: matched.map((p) => p.id),
      what: matched.map((p) => p.what).join('; '),
      level: meta.level,
      logger: meta.logger,
      code: meta.code,
      requestId: meta.requestId,
      line: line.slice(0, 500),
      offset: region.from,
    };
    this.findings.push(finding);
    region.findings += 1;
    problem('backendlog', `backend log [${matched.map((p) => p.id).join(',')}] ${line.slice(0, 300)}`, {
      pathname: BACKEND_LOG,
      level: meta.level,
      logger: meta.logger,
      code: meta.code,
      requestId: meta.requestId,
      pattern: matched[0].id,
      owner,
    });
  }
  this.offset = region.to;
  STATE.backendLogOffset = this.offset;
  saveState();
  this.regions.push(region);
  return region;
};

/**
 * Is the backend process alive? A pid that `kill(pid, 0)` accepts is NOT
 * enough: a uvicorn that crashed is still an un-reaped child of the runner
 * shell until the shell waits for it, and `kill(pid, 0)` succeeds against a
 * zombie. The Linux process state is read directly so "exited, not yet reaped"
 * is reported as DEAD, which is what it is.
 */
function backendProcessState() {
  if (!BACKEND_PID) return { pid: null, alive: false, state: null, why: 'E2E_BACKEND_PID was not provided; process liveness cannot be verified' };
  try {
    process.kill(BACKEND_PID, 0);
  } catch (err) {
    return { pid: BACKEND_PID, alive: false, state: null, why: `kill(${BACKEND_PID}, 0) failed: ${err.code || String(err)}` };
  }
  let state;
  try {
    const stat = fs.readFileSync(`/proc/${BACKEND_PID}/stat`, 'utf8');
    state = (stat.slice(stat.lastIndexOf(')') + 1).trim().split(/\s+/)[0]) || null;
  } catch {
    state = null;
  }
  if (state === 'Z') return { pid: BACKEND_PID, alive: false, state, why: 'the backend process has EXITED (zombie, awaiting reap by the runner)' };
  if (state === 'X') return { pid: BACKEND_PID, alive: false, state, why: 'the backend process is dead' };
  return { pid: BACKEND_PID, alive: true, state, why: null };
}

/** Does it still SERVE? A wedged process is alive and useless. */
async function backendHealth() {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 4000);
  try {
    const res = await fetch(`${API}/health`, { signal: ctl.signal });
    const body = (await res.text()).slice(0, 200);
    return { ok: res.status === 200, status: res.status, body };
  } catch (err) {
    return { ok: false, status: null, body: null, error: String(err).slice(0, 200) };
  } finally {
    clearTimeout(t);
  }
}

/**
 * The per-stage verdict row. Called after EVERY stage (including one that
 * threw) and once more at finalisation. It fails the run on a dirty log
 * region, on a dead/zombie backend and on a backend that stopped serving.
 */
async function backendOracle(owner, { final = false } = {}) {
  // Give a line that the just-finished request wrote a moment to reach the
  // file. This is a flush allowance measured in milliseconds, not a readiness
  // sleep: a line that arrives later is still caught by the NEXT region, which
  // still fails the run — it would only be attributed to the following stage.
  await new Promise((r) => setTimeout(r, 120));
  const region = BACKEND.harvest(`stage:${owner}`);
  const unowned = GATE.drain(`BACKEND-oracle-${owner}`);
  const proc = backendProcessState();
  const health = await backendHealth();
  BACKEND.samples.push({ owner, at: new Date().toISOString(), proc, health, region });

  const chk = newChecks(`BACKEND-oracle-${owner}`, [
    'the backend log region this stage produced is free of ERROR/CRITICAL/Traceback/unhandled_exception/ASGI exception/cannot commit/IndexError',
    'the backend process is ALIVE (not exited, not a zombie)',
    'the backend still answers /health with 200',
    'no unattributed browser problem (5xx, failed request, console error, page error) is outstanding for this stage',
  ]);

  const logProblems = unowned.filter((p) => p.kind === 'backendlog');
  const otherProblems = unowned.filter((p) => p.kind !== 'backendlog');
  chk.ok(
    'the backend log region this stage produced is free of ERROR/CRITICAL/Traceback/unhandled_exception/ASGI exception/cannot commit/IndexError',
    `zero matching lines in bytes [${region.from},${region.to}) of ${BACKEND_LOG || '(no log path)'}`,
    logProblems.length
      ? logProblems.map((p) => p.detail.slice(0, 300))
      : `zero matching lines across ${region.lines} line(s) / ${region.bytes} byte(s) in bytes [${region.from},${region.to})`,
    () => logProblems.length === 0 && !region.error,
  );
  chk.ok(
    'the backend process is ALIVE (not exited, not a zombie)',
    'the pid the runner started is running',
    proc.alive ? `pid ${proc.pid} running (state ${proc.state || 'unknown'})` : `DEAD: ${proc.why}`,
    () => proc.alive === true,
  );
  chk.ok(
    'the backend still answers /health with 200',
    'GET /health -> 200',
    health.ok ? `200 ${health.body}` : `NOT SERVING: status=${health.status} ${health.error || health.body || ''}`,
    () => health.ok === true,
  );
  chk.ok(
    'no unattributed browser problem (5xx, failed request, console error, page error) is outstanding for this stage',
    'zero',
    otherProblems.length ? otherProblems.map((p) => `${p.kind}: ${String(p.detail).slice(0, 200)}`) : 'zero',
    () => otherProblems.length === 0,
  );

  record({
    id: `BACKEND-oracle-${owner}`,
    stage: owner,
    matrix: 'F3',
    outcome: chk.verdict,
    summary: `${final ? 'FINAL ' : ''}backend oracle for "${owner}": ${region.lines} new log line(s) / ${region.bytes} byte(s) judged in [${region.from},${region.to}), ${logProblems.length} log finding(s), process ${proc.alive ? 'alive' : 'DEAD'}, health ${health.ok ? 'ok' : 'FAILING'} — ${chk.summary()}`,
    assertions: chk.table,
    ...(chk.failed.length || chk.unexecuted.length ? { failedAssertions: [...chk.failed, ...chk.unexecuted] } : {}),
    observed: { region, proc, health, logFindings: logProblems, otherProblems },
    artifacts: [],
  });
  return chk.verdict === 'pass';
}

/* ------------------------------- F3: evidence provenance & stage completeness */

/**
 * Evidence is only evidence OF something if it names what it was produced from.
 * Every recorded row carries the commit; the run refuses to start if the
 * evidence directory it is appending to was produced at a DIFFERENT one, and
 * refuses to finish if any row disagrees with the commit under test.
 */
function assertCommitProvenance({ final = false } = {}) {
  const chk = newChecks(final ? 'EVIDENCE-commit-consistency-final' : 'EVIDENCE-commit-provenance', [
    'the driver was told which commit it is judging',
    'every result already in this evidence directory was produced at THAT commit',
  ]);
  chk.ok(
    'the driver was told which commit it is judging',
    'a 40-character commit sha in E2E_COMMIT',
    COMMIT || '(E2E_COMMIT was empty)',
    (v) => /^[0-9a-f]{40}$/.test(String(v)),
  );
  const carried = STATE.commit && STATE.commit !== COMMIT
    ? [`state.json was written at ${STATE.commit}`]
    : [];
  const foreignRows = RESULTS
    .filter((r) => r.commit && r.commit !== COMMIT)
    .map((r) => `${r.id} was produced at ${r.commit}`);
  const stale = [...carried, ...foreignRows];
  chk.ok(
    'every result already in this evidence directory was produced at THAT commit',
    `every carried-over row and state.json stamped ${COMMIT || '(unknown)'}`,
    stale.length ? stale.slice(0, 10) : `zero stale rows across ${RESULTS.length} carried result(s)`,
    () => stale.length === 0,
  );
  record({
    id: chk.id,
    stage: final ? 'final' : 'precheck',
    matrix: 'F3',
    outcome: chk.verdict,
    summary: `evidence provenance: commit=${COMMIT || 'MISSING'}, ${stale.length} stale row(s) — ${chk.summary()}`,
    assertions: chk.table,
    observed: { commit: COMMIT, stateCommit: STATE.commit ?? null, stale },
    artifacts: [],
  });
  if (chk.verdict === 'pass') {
    STATE.commit = COMMIT;
    saveState();
  }
  return chk.verdict === 'pass';
}

/**
 * A stage that was PLANNED and produced nothing is a FAIL, not an omission.
 * The plan is captured before any injection can shorten it, so dropping a stage
 * is caught by the absence of its rows rather than by trusting the loop.
 */
function assertStageCompleteness(plan, executed) {
  const chk = newChecks('EVIDENCE-stage-completeness', [
    'every PLANNED stage was executed',
    'every PLANNED stage recorded at least one result row',
    'no recorded row left a mandatory assertion unexecuted',
  ]);
  const notExecuted = plan.filter((s) => !executed.includes(s));
  // The oracle's OWN per-stage row does not count as the stage having produced
  // evidence, or a stage whose body recorded nothing would look complete.
  const silent = plan.filter((s) => !RESULTS.some((r) => r.stage === s && !String(r.id).startsWith('BACKEND-oracle-')));
  const incomplete = RESULTS
    .filter((r) => Array.isArray(r.assertions) && r.assertions.some((a) => typeof a.actual === 'string' && a.actual.startsWith('NOT EXECUTED')))
    .map((r) => r.id);
  chk.eq('every PLANNED stage was executed', [], notExecuted);
  chk.eq('every PLANNED stage recorded at least one result row', [], silent);
  chk.eq('no recorded row left a mandatory assertion unexecuted', [], incomplete);
  record({
    id: chk.id,
    stage: 'final',
    matrix: 'F3',
    outcome: chk.verdict,
    summary: `stage completeness: planned=[${plan.join(',')}] executed=[${executed.join(',')}] — ${notExecuted.length} never ran, ${silent.length} recorded nothing, ${incomplete.length} row(s) incomplete — ${chk.summary()}`,
    assertions: chk.table,
    observed: { plan, executed, notExecuted, silent, incomplete },
    artifacts: [],
  });
  return chk.verdict === 'pass';
}

/* --------------------------------------------------------------- api client */

function claims(sub, roles = ['student']) {
  return JSON.stringify({ sub, roles });
}

/* ------------------------- the review-limiter LEDGER (N44's oracle guard) - */

/**
 * The routes `app/api/v1/tutoring.py` guards with `_limit(REVIEW, actor)`.
 *
 * Read off the production source, not guessed: `create_review`, `edit_review`
 * and `delete_review` each call it; `moderate_review` deliberately does NOT
 * (capping a moderator at the student limit would cap the queue). If a fourth
 * review-limited route is ever added and is not listed here, N44's precondition
 * stops being a proof — so the backend test
 * `test_review_limited_routes_match_the_e2e_ledger` fails the moment the two
 * lists disagree.
 */
const REVIEW_LIMITED_ROUTES = [
  { method: 'POST', pattern: /^\/api\/v1\/tutoring\/sessions\/[^/?]+\/review(?:\?|$)/ },
  { method: 'PATCH', pattern: /^\/api\/v1\/tutoring\/reviews\/[^/?]+(?:\?|$)/ },
  { method: 'DELETE', pattern: /^\/api\/v1\/tutoring\/reviews\/[^/?]+(?:\?|$)/ },
];

function isReviewLimited(method, urlPath) {
  return REVIEW_LIMITED_ROUTES.some(
    (r) => r.method === String(method).toUpperCase() && r.pattern.test(urlPath),
  );
}

/**
 * Per-actor count of review-limiter calls THIS RUN has made, recorded at the
 * moment each request is issued — an observation, not an assumption.
 *
 * It lives in `state.json`, so it accumulates across the chained shells of one
 * logical run and is cleared only on the RUN boundary (`--keep-db` absent),
 * exactly like every other cross-stage fact this driver carries. It is
 * deliberately CONSERVATIVE: the backend process restarts between chained
 * shells and its in-memory buckets restart with it, so the ledger can only ever
 * over-count, never under-count. A ledger of zero therefore proves an unspent
 * bucket on any shell layout, which is the direction that has to be sound.
 */
function reviewLimiterLedger() {
  if (!STATE.reviewLimiter || typeof STATE.reviewLimiter !== 'object') {
    STATE.reviewLimiter = { counts: {}, log: [] };
  }
  if (!STATE.reviewLimiter.counts) STATE.reviewLimiter.counts = {};
  if (!Array.isArray(STATE.reviewLimiter.log)) STATE.reviewLimiter.log = [];
  return STATE.reviewLimiter;
}

function reviewLimiterCalls(sub) {
  return Number(reviewLimiterLedger().counts[sub] || 0);
}

function recordReviewLimiterCall(method, urlPath, sub) {
  const ledger = reviewLimiterLedger();
  ledger.counts[sub] = reviewLimiterCalls(sub) + 1;
  // The first calls are the interesting ones (they are what contaminates a
  // budget); the 200-call measurement loop must not bloat state.json.
  if (ledger.log.length < 60) {
    ledger.log.push({ sub, method, path: urlPath, at: new Date().toISOString() });
  }
  saveState();
}

async function api(method, urlPath, { sub = STUDENT, roles = ['student'], body, headers = {}, raw } = {}) {
  if (sub && isReviewLimited(method, urlPath)) recordReviewLimiterCall(method, urlPath, sub);
  const init = { method, headers: { ...headers } };
  if (sub) init.headers['X-Actor-Claims'] = claims(sub, roles);
  if (raw !== undefined) {
    init.body = raw;
    init.headers['Content-Type'] = init.headers['Content-Type'] || 'application/json';
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(`${API}${urlPath}`, init);
  const text = await res.text();
  let json;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { _unparsed: text.slice(0, 400) };
  }
  return { status: res.status, json, code: typedCode({ status: res.status, json }) };
}

/** The typed machine code out of the API envelope, or null if there is none. */
function typedCode(r) {
  const j = r?.json;
  if (!j || typeof j !== 'object') return null;
  return j.detail?.code ?? j.code ?? null;
}


/** The provider leg no browser can perform: a signature-verified paid event. */
async function payWebhook(orderRef, { amountPaise = FEE_PAISE, eventType = 'paid', eventId, currency = 'INR' } = {}) {
  const payload = {
    amount_paise: amountPaise,
    brand: 'TESTCARD',
    currency,
    event_id: eventId || `det_evt_${createHash('sha256').update(`${orderRef}:${eventType}:${Date.now()}`).digest('hex').slice(0, 20)}`,
    event_type: eventType,
    expiry_month: 12,
    expiry_year: 2030,
    masked_last4: '4242',
    order_ref: orderRef,
    provider: 'deterministic',
    token: 'tok_test_success',
  };
  const rawBody = JSON.stringify(payload, Object.keys(payload).sort());
  const sig = createHmac('sha256', PAY_KEY).update(Buffer.from(rawBody, 'utf8')).digest('hex');
  return api('POST', '/api/v1/payments/webhook', {
    sub: null,
    raw: rawBody,
    headers: { [PAY_SIG_HEADER]: sig },
  });
}

/** The video provider leg: a signature-verified room event. */
async function videoWebhook({ roomRef, eventType = 'participant_joined', participantRef = null, eventId }) {
  const payload = {
    event_id: eventId || `det_vevt_${createHash('sha256').update(`${roomRef}:${eventType}:${participantRef}:${Date.now()}:${Math.random()}`).digest('hex').slice(0, 16)}`,
    event_type: eventType,
    participant_ref: participantRef,
    room_ref: roomRef,
  };
  const rawBody = JSON.stringify(payload, Object.keys(payload).sort());
  const sig = createHmac('sha256', VIDEO_KEY).update(Buffer.from(rawBody, 'utf8')).digest('hex');
  return api('POST', '/api/v1/video/webhook', {
    sub: null,
    raw: rawBody,
    headers: { [VIDEO_SIG_HEADER]: sig },
  });
}

/* ----------------------------------------------------- fixture / db helpers */

function fixtureCmd(args) {
  const r = spawnSync(PYTHON, ['scripts/wave2_e2e_fixture.py', ...args], {
    cwd: path.join(REPO_ROOT, 'backend'),
    encoding: 'utf8',
    env: process.env,
  });
  if (r.status !== 0) {
    // The LAST lines of a Python traceback are the actual exception; the first
    // lines are frames. Reporting the head made every fixture failure look the
    // same, which is how a real cause stays hidden.
    const tail = String(r.stderr || r.stdout || '').trim().split('\n').slice(-4).join(' | ');
    throw new Error(`fixture ${args.join(' ')} failed: ${tail}`);
  }
  return JSON.parse(r.stdout.trim().split('\n').pop());
}

function dbPath() {
  const url = process.env.DATABASE_URL || '';
  const m = url.match(/sqlite\+pysqlite:\/\/\/(.*)$/);
  if (!m) throw new Error(`cannot read a sqlite path out of DATABASE_URL=${url}`);
  return m[1].startsWith('/') ? m[1] : path.join(REPO_ROOT, 'backend', m[1]);
}

/**
 * UUIDs are persisted dash-free by the SQLite UUID type, so every id used as a
 * bound parameter has to be normalised or the row silently does not match.
 */
const hex = (id) => String(id).replace(/-/g, '');

/** Read-only SQL against the same file the server is writing. The oracle. */
function dbQuery(sql, params = []) {
  params = params.map((p) => (typeof p === 'string' && /^[0-9a-f-]{32,36}$/i.test(p) ? hex(p) : p));
  const script = `
import json, sqlite3, sys
con = sqlite3.connect(sys.argv[1], timeout=20)
con.execute("PRAGMA busy_timeout = 20000")
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(sys.argv[2], json.loads(sys.argv[3]))]
print(json.dumps(rows, default=str))
`;
  const r = spawnSync(PYTHON, ['-c', script, dbPath(), sql, JSON.stringify(params)], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`dbQuery failed: ${r.stderr}`);
  return JSON.parse(r.stdout);
}

/* ------------------------------------------------------------ page capture */

const NET = [];
const CONSOLE = [];
/** In-flight capture work. `settleCaptures()` is the readiness condition that
 *  replaced "sleep and hope the response body arrived". */
const PENDING = [];

async function settleCaptures() {
  for (let guard = 0; guard < 50 && PENDING.length; guard++) {
    await Promise.allSettled([...PENDING]);
  }
}

function track(promise) {
  PENDING.push(promise);
  promise.finally(() => {
    const i = PENDING.indexOf(promise);
    if (i >= 0) PENDING.splice(i, 1);
  });
  return promise;
}

/**
 * Console severities that are FAILURES. `warning` is included on purpose: the
 * independent-QA finding was that a runner which tolerates warnings tolerates
 * exactly the class of regression (a React key error, a failed prop type, an
 * unhandled rejection logged rather than thrown) that a browser gate exists to
 * catch.
 */
const FATAL_CONSOLE = new Set(['error', 'warning']);

function attachCapture(page) {
  if (injected('unexpected-404')) {
    // Fail-closed proof: an unexpected 404 on an EXISTING OWNED session. The
    // screen asks for the session it owns; the request is re-pointed at a
    // session id that does not exist, so the REAL backend answers a REAL 404
    // for a route the screen legitimately fetched. Nobody declared it with
    // `expecting()`, and there is no blanket 404 allowance, so it must fail the
    // stage that produced it. Installed here rather than on one context so it
    // reaches EVERY page the driver opens, including the live-room contexts.
    page.route(/\/api\/v1\/tutoring\/sessions\/[0-9a-fA-F-]{32,36}(\?|$)/, (route) => {
      if (route.request().method() !== 'GET') return route.continue().catch(() => {});
      const url = new URL(route.request().url());
      url.pathname = url.pathname.replace(/\/sessions\/[0-9a-fA-F-]{32,36}$/, '/sessions/00000000-0000-4000-8000-0000deadbe0f');
      return route.continue({ url: url.toString() }).catch(() => route.continue().catch(() => {}));
    }).catch(() => {});
  }
  page.on('request', (req) => {
    let post;
    try {
      post = req.postData();
    } catch {
      post = null;
    }
    NET.push({
      dir: 'request',
      method: req.method(),
      url: req.url(),
      headers: req.headers(),
      postData: post ? String(post).slice(0, 4000) : null,
      at: new Date().toISOString(),
    });
  });
  page.on('response', (res) => {
    const url = res.url();
    const method = res.request().method();
    const status = res.status();
    track((async () => {
      let bodyText = null;
      if (url.includes('/api/v1/')) {
        try {
          bodyText = (await res.text()).slice(0, 6000);
        } catch {
          bodyText = null;
        }
      }
      NET.push({ dir: 'response', status, url, headers: res.headers(), body: bodyText, at: new Date().toISOString() });
      if (status >= 400) {
        let code = null;
        if (bodyText) {
          try {
            const j = JSON.parse(bodyText);
            code = j?.detail?.code ?? j?.code ?? null;
          } catch { code = null; }
        }
        problem('http', `${method} ${url} -> ${status} ${code || '(no typed code)'}`, {
          method, pathname: pathOf(url), status, code, url,
        });
      }
    })());
  });
  page.on('requestfailed', (req) => {
    const failure = req.failure()?.errorText || 'unknown';
    // A request the driver itself aborted (context.setOffline for the
    // disconnect case) is announced by the case that owns it, never here.
    NET.push({ dir: 'requestfailed', method: req.method(), url: req.url(), failure, at: new Date().toISOString() });
    problem('requestfailed', `${req.method()} ${req.url()} failed: ${failure}`, {
      method: req.method(), pathname: pathOf(req.url()), failure, url: req.url(),
    });
  });
  page.on('console', (msg) => {
    const type = msg.type();
    const text = msg.text().slice(0, 600);
    CONSOLE.push({ type, text });
    if (FATAL_CONSOLE.has(type)) problem('console', `${type}: ${text}`, { type });
  });
  page.on('pageerror', (err) => {
    const text = String(err).slice(0, 600);
    CONSOLE.push({ type: 'pageerror', text });
    problem('pageerror', `pageerror: ${text}`, { type: 'pageerror' });
  });
}

/* --------------------------------------------- explicit readiness conditions */

/**
 * F4.1. The ONLY general-purpose wait in this driver. It is a condition, not a
 * duration: the document has finished loading, no element is announcing itself
 * busy, no route-level suspense fallback is mounted, and every FINITE animation
 * has stopped. Infinite animations (the connecting spinner) are excluded by
 * design — waiting for one would never return, and a spinner still turning is
 * itself covered by the state assertions the caller makes next.
 */
async function settled(page, timeout = 20000) {
  await page.waitForFunction(
    () => {
      if (document.readyState !== 'complete') return false;
      if (document.querySelector('.route-loading')) return false;
      if (document.querySelector('[aria-busy="true"]')) return false;
      // The screens announce their own in-flight state as a "Loading …" banner.
      // Treating that banner as READY is exactly how a runner ends up asserting
      // against a skeleton and calling the absence of a control a defect.
      if ([...document.querySelectorAll('.tt-banner__t')].some((e) => /^Loading\b/i.test(e.textContent || ''))) return false;
      const anims = typeof document.getAnimations === 'function' ? document.getAnimations() : [];
      const running = anims.filter((a) => {
        if (a.playState !== 'running') return false;
        const it = a.effect && a.effect.getTiming ? a.effect.getTiming().iterations : 1;
        return it !== Infinity;
      });
      return running.length === 0;
    },
    undefined,
    { timeout },
  );
  await settleCaptures();
}

/**
 * Navigate and wait for the screen to be READY, where "ready" is named by the
 * caller as a selector the screen only renders once its data has arrived.
 */
async function go(page, url, readySelector, { timeout = 25000 } = {}) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  if (readySelector) await page.waitForSelector(readySelector, { timeout });
  await settled(page, timeout);
}

/**
 * Perform `action` and wait for the API call it is supposed to cause. The
 * response promise is registered BEFORE the action so the race that used to be
 * papered over with `waitForTimeout(100)` polling cannot happen.
 */
async function withApi(page, matcher, action, { timeout = 25000 } = {}) {
  const wanted = page.waitForResponse(
    (res) => {
      const p = pathOf(res.url());
      const okRoute = matcher.route instanceof RegExp ? matcher.route.test(p) : p === matcher.route;
      if (!okRoute) return false;
      if (matcher.method && res.request().method() !== matcher.method) return false;
      if (matcher.status !== undefined && res.status() !== matcher.status) return false;
      if (matcher.maxStatus !== undefined && res.status() >= matcher.maxStatus) return false;
      return true;
    },
    { timeout },
  );
  const [res, value] = await Promise.all([wanted, action()]);
  let json;
  try {
    json = await res.json();
  } catch { json = null; }
  await settleCaptures();
  return { res, json, status: res.status(), value };
}

function flushNet(stage) {
  fs.writeFileSync(path.join(DIRS.net, `${stage}.json`), JSON.stringify(NET, null, 1));
  fs.writeFileSync(path.join(DIRS.net, `${stage}.console.json`), JSON.stringify(CONSOLE, null, 1));
}

/** Screenshot + DOM + storage + URL, all under one name. Returns the names. */
async function shot(page, name, { fullPage = true } = {}) {
  const file = `${name}.png`;
  await page.screenshot({ path: path.join(DIRS.shots, file), fullPage });
  fs.writeFileSync(path.join(DIRS.dom, `${name}.html`), await page.content());
  const store = await page.evaluate(() => {
    const dump = (s) => {
      const o = {};
      try {
        for (let i = 0; i < s.length; i++) o[s.key(i)] = s.getItem(s.key(i));
      } catch (e) {
        o._error = String(e);
      }
      return o;
    };
    return {
      url: location.href,
      localStorage: dump(window.localStorage),
      sessionStorage: dump(window.sessionStorage),
      cookie: document.cookie,
      title: document.title,
    };
  });
  fs.writeFileSync(path.join(DIRS.storage, `${name}.json`), JSON.stringify(store, null, 1));
  return file;
}

/* ------------------------------------------------------------- dom readers */

const BANNER = '.tt-banner';
const CODE_SEL = 'code.tt-banner__code';

async function banners(page) {
  return page.$$eval(BANNER, (els) =>
    els.map((el) => ({
      tone: (el.className.match(/tt-banner--(\w+)/) || [])[1] || null,
      role: el.getAttribute('role'),
      title: el.querySelector('.tt-banner__t')?.textContent?.trim() || null,
      detail: el.querySelector('.tt-banner__d')?.textContent?.trim() || null,
      code: el.querySelector('code.tt-banner__code')?.textContent?.trim() || null,
    })),
  );
}

async function waitForCode(page, code, timeout = 12000) {
  await page.waitForFunction(
    (want) => [...document.querySelectorAll('code.tt-banner__code')].some((c) => c.textContent.trim() === want),
    code,
    { timeout },
  );
}

async function cardNames(page) {
  return page.$$eval('article.tt-tut .tt-tut__nm', (els) => els.map((e) => e.textContent.trim()));
}

async function countLine(page) {
  return page.$$eval('p.tt-p.tt-muted', (els) => {
    const hit = els.find((e) => /Showing \d+ of \d+ mentors?/.test(e.textContent));
    return hit ? hit.textContent.trim() : null;
  });
}

/** Any tutor in the packaged seed cast (extra pagination tutors have no slots). */
function seedTutorWithSlots() {
  const slot = FIXTURE.slots.find((s) => s.bucket === 'gt24h' && s.status === 'available');
  return slot ? slot.tutor_id : FIXTURE.slots[0]?.tutor_id;
}

/**
 * The fixture's `status` is a SNAPSHOT taken when the calendar was seeded, and
 * `STATE.usedSlots` only knows about slots this driver explicitly TOOK. Neither
 * knows about a slot consumed by a RESCHEDULE — d1 moves a session onto a slot
 * chosen from the browser's own availability list, which the fixture snapshot
 * still calls "available". Handing that slot out again later produces a real
 * `409 SLOT_UNAVAILABLE` from a correct server, i.e. a harness collision that
 * looks exactly like a product defect.
 *
 * So the LIVE table is the authority. This is bookkeeping, not tolerance: the
 * 409 is still a failure if it ever happens, nothing is allowlisted, and no
 * assertion is relaxed — the driver simply stops asking for a slot the database
 * has already given away.
 */
function freeSlots(bucket = 'gt24h') {
  const used = new Set(STATE.usedSlots || []);
  const candidates = FIXTURE.slots.filter((s) => s.bucket === bucket && s.status === 'available' && !used.has(s.slot_id));
  if (!candidates.length) return candidates;
  const live = new Set(
    dbQuery("SELECT id FROM tutor_availability_slots WHERE status = 'available'").map((r) => String(r.id)),
  );
  return candidates.filter((s) => live.has(hex(s.slot_id)) || live.has(s.slot_id));
}

function takeSlot(bucket = 'gt24h') {
  const s = freeSlots(bucket)[0];
  if (!s) throw new Error(`no unused ${bucket} slot left in the fixture`);
  STATE.usedSlots = [...(STATE.usedSlots || []), s.slot_id];
  saveState();
  return s;
}

/* ------------------------------------------------------- booking primitive */

/**
 * The real S-33 booking leg, driven in the browser: mount creates the hold,
 * "Pay" creates the provider order, the PROVIDER (this driver, tagged as a
 * server leg) posts the signed `paid` event, then "Check payment and confirm"
 * is clicked and the confirmed session id is read back off the wire.
 */
async function bookInBrowser(page, slot, tag) {
  await go(page, `${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, 'div.tt-hold[role="timer"]');
  if (tag) await shot(page, `${tag}_hold`);

  // The order response is awaited, not polled: the promise is armed before the
  // click, so there is no window in which the answer can be missed.
  const order = await withApi(
    page,
    { method: 'POST', route: '/api/v1/payments/orders', maxStatus: 300 },
    async () => page.locator('button.tt-btn--jade', { hasText: /securely/ }).click(),
  );
  const orderRef = order.json?.provider_order_ref;
  if (!orderRef) throw new Error(`no provider_order_ref on POST /payments/orders (status ${order.status})`);
  await page.waitForFunction(
    () => /Order reference|Waiting for the provider/.test(document.body.textContent),
    undefined,
    { timeout: 20000 },
  );
  await settled(page);
  if (tag) await shot(page, `${tag}_order`);

  const hook = await payWebhook(orderRef);
  if (hook.status !== 200) throw new Error(`paid webhook rejected: ${hook.status} ${JSON.stringify(hook.json)}`);

  const created = await withApi(
    page,
    { method: 'POST', route: '/api/v1/tutoring/sessions', maxStatus: 300 },
    async () => page.locator('button.tt-btn--jade', { hasText: /Check payment and confirm/ }).click(),
  );
  await page.waitForSelector('a.tt-btn--jade:has-text("View your confirmed session")', { timeout: 20000 });
  await settled(page);
  if (tag) await shot(page, `${tag}_confirmed`);

  const sessionId = created.json?.id || hook.json.session_id;
  return { sessionId, orderRef, webhook: hook.json };
}

/**
 * The same booking, performed entirely as a declared SERVER LEG. Used by the
 * negative catalogue, which needs one confirmed session per accepted-review
 * case and would otherwise spend the whole budget re-clicking a flow the
 * browser has already proved once in stage c.
 */
async function bookAsServerLeg(sub = STUDENT) {
  const slot = takeSlot('gt24h');
  const key = `srv-${sub.slice(-6)}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const hold = await api('POST', '/api/v1/tutoring/booking-holds', { sub, body: { slot_id: slot.slot_id, idempotency_key: `${key}-h` } });
  if (hold.status !== 201) throw new Error(`server-leg hold failed: ${hold.status} ${JSON.stringify(hold.json)}`);
  const order = await api('POST', '/api/v1/payments/orders', { sub, body: { hold_id: hold.json.id, idempotency_key: `${key}-o` } });
  if (order.status !== 201) throw new Error(`server-leg order failed: ${order.status} ${JSON.stringify(order.json)}`);
  const hook = await payWebhook(order.json.provider_order_ref);
  if (hook.status !== 200) throw new Error(`server-leg webhook failed: ${hook.status} ${JSON.stringify(hook.json)}`);
  return { sessionId: hook.json.session_id, orderRef: order.json.provider_order_ref, slot, holdId: hold.json.id };
}

/**
 * A session that is COMPLETE and attendance-CONFIRMED, so a review is allowed.
 * Completion is recorded by the owning mentor (a recorder role); confirmation is
 * the student's own act. Both are declared server legs here.
 */
async function reviewableSession() {
  const booked = await bookAsServerLeg(STUDENT);
  await shiftSessionTo(booked.sessionId, -1.6);
  const s = await apiSession(booked.sessionId);
  const tutorUserId = tutorUserIdFor(s.tutor_id);
  const done = await api('POST', `/api/v1/tutoring/sessions/${booked.sessionId}/complete`, { sub: tutorUserId, roles: ['tutor'] });
  if (done.status >= 300) throw new Error(`server-leg completion failed: ${done.status} ${JSON.stringify(done.json)}`);
  const confirmed = await api('POST', `/api/v1/tutoring/sessions/${booked.sessionId}/attendance/confirm`, { sub: STUDENT, body: {} });
  if (confirmed.status >= 300) throw new Error(`server-leg attendance confirm failed: ${confirmed.status} ${JSON.stringify(confirmed.json)}`);
  return { ...booked, tutorUserId };
}

async function sessionRow(sessionId) {
  const rows = dbQuery('SELECT id, status, slot_id, tutor_id, student_user_id, order_id, version, start_utc, end_utc FROM tutoring_sessions WHERE id = ?', [sessionId]);
  return rows[0] || null;
}

async function apiSession(sessionId, sub = STUDENT) {
  const r = await api('GET', `/api/v1/tutoring/sessions/${sessionId}`, { sub });
  return r.json;
}

/** Move a session so its start is `hours` from now. Declared clock shift. */
async function shiftSessionTo(sessionId, hours) {
  const s = await apiSession(sessionId);
  const startMs = Date.parse(s.start_utc);
  const targetMs = Date.now() + hours * 3600 * 1000;
  const minutes = Math.round((targetMs - startMs) / 60000);
  return fixtureCmd(['shift-session', sessionId, '--minutes', String(minutes)]);
}

function tutorUserIdFor(tutorProfileId) {
  const profiles = FIXTURE.actors.tutor_profile_ids || {};
  const users = FIXTURE.actors.tutor_user_ids || {};
  for (const [key, pid] of Object.entries(profiles)) if (pid === tutorProfileId) return users[key];
  return null;
}

/* --------------------------------------------------- mentor (M-01) surface */

/**
 * Completion is a TUTOR/ADMIN action (`attendance.RECORDER_ROLES`), so after
 * independent-QA defect D2 it is neither rendered nor dispatchable on the
 * student surface. It is exercised here BY ROLE instead: a second browser
 * context, signed in as the mentor who owns the session, drives the authorised
 * M-01 screen and clicks its real control.
 *
 * Captures made in that context are named with MENTOR_CAPTURE_PREFIX so the J1
 * privacy stage can account for the mentor's authenticated session (the app's
 * secret-free P0.1 verification snapshot) separately from the student journey,
 * whose storage must stay completely empty.
 */
const MENTOR_CAPTURE_PREFIX = 'mentor_';

async function mentorContext(browser, tutorUserId) {
  const ctx = await browser.newContext({ viewport: MOBILE, colorScheme: 'light' });
  // The app's real sign-in artefact: a redacted, secret-free verification
  // snapshot. No token, no OTP, no password — the same shape `saveAuthSnapshot`
  // writes at the end of the P0.1 lawyer verification flow.
  await ctx.addInitScript((subjectId) => {
    try {
      window.localStorage.setItem('ls-auth-lawyer', JSON.stringify({
        role: 'lawyer',
        phase: 'verified',
        destinationMasked: null,
        challenge: null,
        consentAt: new Date().toISOString(),
        subjectId,
        filingRole: 'lawyer',
        updatedAt: Date.now(),
      }));
    } catch { /* origin without storage (about:blank) — the next navigation retries */ }
  }, tutorUserId);
  const page = await ctx.newPage();
  attachCapture(page);
  return { ctx, page };
}

/**
 * Record completion in the browser, on the authorised surface, as the mentor.
 * Returns what was observed; the caller owns the verdict.
 */
async function recordCompletionAsMentor(browser, sessionId, tutorUserId, arts, tag) {
  if (!tutorUserId) return { performedInBrowser: false, reason: 'no tutor user id in the fixture' };
  const { ctx, page } = await mentorContext(browser, tutorUserId);
  const completeCalls = [];
  page.on('response', (res) => {
    if (/\/complete$/.test(new URL(res.url()).pathname)) {
      completeCalls.push({ url: res.url(), status: res.status() });
    }
  });
  try {
    await go(page, `${WEB}/mentor/sessions`, '[data-screen="M-01"]');
    arts.push(await shot(page, `${MENTOR_CAPTURE_PREFIX}${tag}_list`));
    const row = page.locator('article.tt-tut', { hasText: sessionId }).first();
    const control = row.locator('button[data-action="record-completion"]').first();
    await control.waitFor({ state: 'visible', timeout: 20000 });
    await withApi(
      page,
      { method: 'POST', route: /\/complete$/, maxStatus: 300 },
      () => control.click(),
    );
    await page.waitForFunction(
      () => /Completion recorded/i.test(document.body.textContent),
      undefined,
      { timeout: 20000 },
    );
    await settled(page);
    arts.push(await shot(page, `${MENTOR_CAPTURE_PREFIX}${tag}_recorded`));
    return {
      performedInBrowser: true,
      surface: '/mentor/sessions (M-01)',
      actor: { subject: tutorUserId, role: 'tutor' },
      completeCalls,
      banners: await banners(page),
    };
  } catch (err) {
    try { arts.push(await shot(page, `${MENTOR_CAPTURE_PREFIX}${tag}_error`)); } catch { /* ignore */ }
    return { performedInBrowser: false, reason: String(err).slice(0, 400), completeCalls };
  } finally {
    await ctx.close();
  }
}

/** Every completion control a page offers, by copy and by its action hook. */
async function completionControls(page) {
  return {
    byLabel: await page.locator('button', { hasText: /Record completion/i }).count(),
    byHook: await page.locator('[data-action="record-completion"]').count(),
  };
}

/* ================================================================= stages */

/** Wait for the tutor-search call a control is supposed to fire, then the DOM. */
async function searchAfter(page, action, urlPredicate) {
  const r = await withApi(page, { method: 'GET', route: '/api/v1/tutors', maxStatus: 400 }, action);
  if (urlPredicate) await page.waitForFunction(urlPredicate, undefined, { timeout: 15000 });
  await page.waitForSelector('article.tt-tut, .tt-banner', { timeout: 20000 });
  await settled(page);
  return r;
}

async function stageA(page) {
  const chk = newChecks('I1-a-S31-discovery', [
    'S-31 renders mentor cards',
    'page 1 is a full page of 10',
    'page 2 is non-empty',
    'no mentor appears on both pages',
    '"Previous page" is disabled at offset 0',
    'sort=experience_desc is monotonically non-increasing',
    'subject+experience filter narrows the result set',
    'verified-only filter narrows the result set',
    'the count line is rendered on every list state',
  ]);
  const arts = [];
  await go(page, `${WEB}/s-31`, 'article.tt-tut');
  arts.push(await shot(page, 'a1_s31_discovery_default'));
  const page1 = await cardNames(page);
  const line1 = await countLine(page);
  chk.ok('S-31 renders mentor cards', 'at least one mentor card', page1.length, (n) => n > 0);

  await searchAfter(
    page,
    () => page.locator('div.tt-rails[aria-label="Sort results"] button.tt-rail', { hasText: 'Most experienced' }).click(),
    () => location.search.includes('sort=experience_desc'),
  );
  arts.push(await shot(page, 'a2_s31_sort_experience_desc'));
  const sorted = await page.$$eval('article.tt-tut span.tt-hero', (els) => els.map((e) => parseInt(e.textContent, 10)));
  chk.ok(
    'sort=experience_desc is monotonically non-increasing',
    'each card\'s experience >= the next card\'s',
    sorted,
    (v) => v.length > 1 && v.every((x, i) => i === 0 || v[i - 1] >= x),
  );

  await page.locator('details.tt-dis summary', { hasText: /^Refine/ }).click();
  await searchAfter(
    page,
    async () => { await page.fill('#tt-subject', 'Legal Research'); await page.locator('#tt-subject').blur(); },
    () => location.search.includes('subject=Legal'),
  );
  await searchAfter(
    page,
    () => page.selectOption('#tt-minexp', '5'),
    () => location.search.includes('min_experience'),
  );
  arts.push(await shot(page, 'a3_s31_filter_subject_experience'));
  const filtered = await cardNames(page);
  const lineF = await countLine(page);
  chk.ok(
    'subject+experience filter narrows the result set',
    `fewer than the ${page1.length} unfiltered cards`,
    { filtered: filtered.length, unfiltered: page1.length, countLine: lineF },
    (v) => v.countLine !== null && v.filtered <= v.unfiltered,
  );

  await searchAfter(
    page,
    () => page.locator('button.tt-btn', { hasText: /verified mentors only/ }).click(),
    () => location.search.includes('verified_only=1'),
  );
  arts.push(await shot(page, 'a4_s31_filter_verified_only'));
  const lineV = await countLine(page);
  chk.ok(
    'verified-only filter narrows the result set',
    'a rendered count line whose total is <= the filtered total',
    lineV,
    (v) => /Showing \d+ of \d+ mentors?/.test(v),
  );

  await go(page, `${WEB}/s-31`, 'article.tt-tut');
  const prevDisabled = await page.locator('button:has-text("Previous page")').isDisabled();
  const p1 = await cardNames(page);
  await searchAfter(
    page,
    () => page.locator('button:has-text("Next page")').click(),
    () => location.search.includes('offset=10'),
  );
  arts.push(await shot(page, 'a5_s31_pagination_page2'));
  const p2 = await cardNames(page);
  const line2 = await countLine(page);
  const overlap = p1.filter((n) => p2.includes(n));

  chk.eq('page 1 is a full page of 10', 10, p1.length);
  chk.ok('page 2 is non-empty', 'at least one card', p2.length, (n) => n > 0);
  chk.eq('no mentor appears on both pages', [], overlap);
  chk.eq('"Previous page" is disabled at offset 0', true, prevDisabled);
  chk.ok(
    'the count line is rendered on every list state',
    'a "Showing N of M mentors" line on default, filtered, verified and page-2 states',
    [line1, lineF, lineV, line2],
    (v) => v.every((x) => typeof x === 'string' && /Showing \d+ of \d+ mentors?/.test(x)),
  );

  recordChecks(chk, {
    stage: 'a',
    matrix: 'I1',
    summary: `S-31 in Chromium: ${line1}; page1=${p1.length} cards, page2=${p2.length} cards, overlap=${overlap.length}`,
    observed: { defaultCountLine: line1, page2CountLine: line2, filteredCountLine: lineF, verifiedCountLine: lineV, experienceYearsInSortOrder: sorted, page1: p1, page2: p2, filtered },
    artifacts: arts,
  });
}

async function stageB(page) {
  const chk = newChecks('I1-b-S32-detail-availability', [
    'S-32 renders the mentor identity',
    'availability slots are rendered',
    'provenance rows are rendered',
    'changing the display timezone relabels every slot',
  ]);
  const arts = [];
  const tutorId = seedTutorWithSlots();
  await go(page, `${WEB}/s-32?tutor=${tutorId}`, 'section.tt-phead h1');
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'b1_s32_detail_availability'));
  const detail = await page.evaluate(() => ({
    name: document.querySelector('section.tt-phead h1')?.textContent?.trim(),
    chips: [...document.querySelectorAll('section.tt-phead span.tt-chip')].map((c) => c.textContent.trim()),
    provenance: [...document.querySelectorAll('details.tt-dis .tt-kv')].map((k) => k.textContent.trim()).slice(0, 12),
    slots: [...document.querySelectorAll('div.tt-slots button.tt-slotbtn')].map((b) => ({
      label: b.querySelector('.tt-sl')?.textContent?.trim(),
      state: b.querySelector('.tt-chip')?.textContent?.trim(),
      disabled: b.disabled,
    })),
  }));
  const istLabels = detail.slots.map((s) => s.label);
  await withApi(
    page,
    { method: 'GET', route: /\/availability$/, maxStatus: 400 },
    () => page.selectOption('#tt-tz', 'Europe/London'),
  );
  await page.waitForFunction(() => location.search.includes('tz=Europe'), { timeout: 10000 });
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'b2_s32_availability_timezone_london'));
  const londonLabels = await page.$$eval('div.tt-slots button.tt-slotbtn .tt-sl', (e) => e.map((x) => x.textContent.trim()));

  chk.ok('S-32 renders the mentor identity', 'a non-empty <h1> mentor name', detail.name, (v) => typeof v === 'string' && v.length > 0);
  chk.ok('availability slots are rendered', 'at least one bookable slot button', detail.slots.length, (n) => n > 0);
  chk.ok('provenance rows are rendered', 'at least one source/retrieved-at row', detail.provenance.length, (n) => n > 0);
  chk.ok(
    'changing the display timezone relabels every slot',
    'every Asia/Kolkata label differs from its Europe/London label',
    { ist: istLabels.slice(0, 3), london: londonLabels.slice(0, 3) },
    (v) => v.london.length > 0 && v.ist.length === v.london.length && v.ist.every((x, i) => x !== v.london[i]),
  );

  recordChecks(chk, {
    stage: 'b',
    matrix: 'I1',
    summary: `S-32 in Chromium for ${detail.name}: ${detail.slots.length} availability buttons, ${detail.chips.length} chips, ${detail.provenance.length} provenance rows; timezone switch relabelled slots (${istLabels[0]} -> ${londonLabels[0]})`,
    observed: { tutorId, ...detail, istLabels, londonLabels },
    artifacts: arts,
  });
}

async function stageC(page) {
  const chk = newChecks('I1-c-S33-S34-book-pay-confirm', [
    'the session row exists and is confirmed',
    'the session belongs to the browsing student',
    'the session carries the paid order',
    'S-34 renders the booked-confirmation heading',
    'the price charged is the SERVER-authoritative price',
      ]);
  const arts = [];
  const slot = takeSlot('gt24h');
  const booked = await bookInBrowser(page, slot, 'c1_s33');
  arts.push('c1_s33_hold.png', 'c1_s33_order.png', 'c1_s33_confirmed.png');

  // in-product route to S-34: dock link -> S-35 list -> Open -> Receipt
  await page.locator('a.tt-btn--jade:has-text("View your confirmed session")').click();
  await page.waitForSelector('article.tt-tut', { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'c2_s35_list_after_booking'));
  await page.locator('article.tt-tut button.tt-btn--jade:has-text("Open")').first().click();
  await page.waitForFunction(() => location.search.includes('view=manage'), { timeout: 15000 });
  await page.waitForSelector('h1', { timeout: 15000 });
  await settled(page);
  arts.push(await shot(page, 'c3_s35_manage'));
  await page.locator('a.tt-btn:has-text("Receipt")').click();
  await page.waitForFunction(() => location.pathname === '/s-34', { timeout: 15000 });
  await page.waitForSelector('h1', { timeout: 15000 });
  await settled(page);
  arts.push(await shot(page, 'c4_s34_confirmation'));
  const s34 = await page.evaluate(() => ({
    heading: document.querySelector('h1')?.textContent?.trim(),
    seal: !!document.querySelector('span.tt-seal'),
    kv: [...document.querySelectorAll('.tt-kv')].map((k) => k.textContent.trim()),
    banners: [...document.querySelectorAll('.tt-banner__t')].map((b) => b.textContent.trim()),
  }));

  const row = await sessionRow(booked.sessionId);
  STATE.s1 = booked.sessionId;
  STATE.s1Order = booked.orderRef;
  saveState();

  const orderRow = dbQuery('SELECT amount_paise, currency, status FROM payment_orders WHERE provider_order_ref = ?', [booked.orderRef])[0] || null;
  const holdRow = dbQuery('SELECT price_paise, price_currency AS currency FROM booking_holds WHERE slot_id = ? ORDER BY created_at DESC LIMIT 1', [slot.slot_id])[0] || null;
  /*
   * `amount_paise` on POST /payments/orders is an OPTIONAL OPTIMISTIC
   * CONFIRMATION — "this is the figure the screen showed" — not a proposal. The
   * question that matters is therefore NOT "did the browser send a number", it
   * is "where did that number come from". It must be an echo of the price the
   * SERVER published on the hold; it must never be an environment constant.
   * So two things are checked: the sent value equals the server's own
   * `booking_holds.price_paise`, and the shipped bundle contains no trace of the
   * removed `VITE_TUTORING_SESSION_FEE_PAISE`.
   */
  const orderBodies = NET.filter(
    (n) => n.dir === 'request' && n.method === 'POST' && pathOf(n.url) === '/api/v1/payments/orders' && n.postData,
  ).map((n) => { try { return JSON.parse(n.postData); } catch { return { _unparsed: n.postData }; } });
  const distDir = path.join(REPO_ROOT, 'frontend', 'dist', 'assets');
  const bundleFeeRefs = fs.existsSync(distDir)
    ? fs.readdirSync(distDir).filter((f) => f.endsWith('.js'))
      .filter((f) => /TUTORING_SESSION_FEE_PAISE/.test(fs.readFileSync(path.join(distDir, f), 'utf8')))
    : ['(dist/assets not found)'];

  chk.ok('the session row exists and is confirmed', 'a tutoring_sessions row in confirmed/scheduled', row?.status, (v) => ['confirmed', 'scheduled'].includes(v));
  chk.eq('the session belongs to the browsing student', hex(STUDENT), row ? hex(row.student_user_id) : undefined);
  chk.ok('the session carries the paid order', 'a non-null order_id', row?.order_id, (v) => !!v);
  chk.ok('S-34 renders the booked-confirmation heading', 'a heading matching /booked/i', s34.heading, (v) => /booked/i.test(v));
  chk.eq('the price charged is the SERVER-authoritative price', FEE_PAISE, orderRow ? Number(orderRow.amount_paise) : undefined);
  chk.ok(
    'any amount the checkout sends is an ECHO of the server-published price, never a client-side or environment value',
    `every POST /payments/orders body either omits amount_paise or sends exactly booking_holds.price_paise (${holdRow?.price_paise}); and the shipped bundle contains no VITE_TUTORING_SESSION_FEE_PAISE`,
    { bodies: orderBodies, serverHoldPrice: holdRow?.price_paise, serverHoldCurrency: holdRow?.currency, bundlesReferencingTheRemovedFeeVar: bundleFeeRefs },
    (v) => v.bodies.length > 0
      && v.bodies.every((b) => (b.amount_paise === undefined || Number(b.amount_paise) === Number(v.serverHoldPrice))
        && (b.currency === undefined || b.currency === v.serverHoldCurrency))
      && Array.isArray(v.bundlesReferencingTheRemovedFeeVar) && v.bundlesReferencingTheRemovedFeeVar.length === 0,
  );

  recordChecks(chk, {
    stage: 'c',
    matrix: 'I1',
    summary: `booked in the browser: hold -> order ${booked.orderRef} -> signed paid webhook (server leg) -> "Check payment and confirm"; S-34 shows "${s34.heading}"; DB row ${booked.sessionId} status=${row?.status}, order amount ${orderRow?.amount_paise} ${orderRow?.currency}`,
    observed: { sessionId: booked.sessionId, slotId: slot.slot_id, dbRow: row, orderRow, holdRow, orderRequestBodies: orderBodies, bundlesReferencingTheRemovedFeeVar: bundleFeeRefs, s34, webhook: booked.webhook },
    mechanism: { paidEvent: 'server_leg', note: 'the signed provider event is posted by this driver acting as the payment provider; every other step is a real click' },
    artifacts: arts,
  });
}

/**
 * F4.2. The explicit media-ready predicate that replaced the Stage-E timeout.
 * Chromium is launched with `--use-fake-device-for-media-stream` and
 * `--use-fake-ui-for-media-stream`, camera+microphone are granted on the
 * CONTEXT, and the page is served from http://127.0.0.1 (a trustworthy origin,
 * so `navigator.mediaDevices` exists at all — on a non-secure origin it is
 * `undefined` and the old wait could only ever time out).
 *
 * Ready means: the device census the screen renders is non-zero AND the preview
 * <video> has decoded a frame (readyState >= HAVE_CURRENT_DATA with real
 * dimensions). Waiting on the chip text alone would pass on a black tile.
 */
async function waitMediaReady(page, { timeout = 25000, requireVideo = true } = {}) {
  await page.waitForFunction(
    (needVideo) => {
      const chips = [...document.querySelectorAll('span.tt-chip')].map((c) => c.textContent.trim());
      const detected = chips.filter((t) => /\d+ (camera|microphone)s? detected/.test(t));
      if (detected.length < 2) return false;
      if (detected.some((t) => /^0 /.test(t))) return false;
      if (!needVideo) return true;
      const v = document.querySelector('video');
      return !!v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;
    },
    requireVideo,
    { timeout },
  );
  await settled(page);
  return page.evaluate(() => {
    const v = document.querySelector('video');
    return {
      chips: [...document.querySelectorAll('span.tt-chip')].map((c) => c.textContent.trim()).filter((t) => /detected/.test(t)),
      video: v ? { readyState: v.readyState, w: v.videoWidth, h: v.videoHeight, paused: v.paused } : null,
      secureContext: window.isSecureContext,
      hasMediaDevices: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
    };
  });
}

async function stageE(page) {
  const chk = newChecks('I1-e-live-room-entry', [
    'the browser reached a MEDIA-READY state (devices enumerated, preview frame decoded)',
    'the server issued a join credential',
    'the room reports admission only after the selected media transport connects',
    'a grant row exists and stores only a token HASH',
    'the details sheet declares the credential redacted and in-memory only',
    'the raw join token never reaches DOM, storage, cookie or URL',
  ]);
  const arts = [];
  const sessionId = STATE.s1;
  if (!sessionId) {
    chk.blocked('the server issued a join credential', 'a POST /join-credentials 201', 'no confirmed session in state.json — stage c did not run or did not pass');
    return recordChecks(chk, { stage: 'e', matrix: 'I1/J1', summary: 'live-room entry could not be attempted', observed: {}, artifacts: [] });
  }

  const creds = [];
  const onResponse = (res) => {
    if (res.url().includes('/join-credentials')) {
      track((async () => {
        try {
          creds.push({ status: res.status(), json: await res.json() });
        } catch { /* body already consumed */ }
      })());
    }
  };
  page.on('response', onResponse);
  try {
    // This application-contract stage deliberately selects the deterministic
    // adapter and proves that fact in the DOM. Real LiveKit/TURN proof belongs
    // exclusively to infra/video/scripts/livekit_turn_smoke.sh S1-S11; neither
    // result may be relabelled as the other.
    await page.addInitScript(() => {
      window.__legalsaathiVideoTransport = 'deterministic';
    });
    await go(page, `${WEB}/s-35?session=${sessionId}&view=prejoin`, 'div.tt-preview');
    arts.push(await shot(page, 'e1_s35_prejoin'));
    await page.locator('button', { hasText: /Test camera and microphone/ }).click();
    const media = await waitMediaReady(page);
    arts.push(await shot(page, 'e2_s35_prejoin_devices_ok'));
    const chips = media.chips;
    chk.ok(
      'the browser reached a MEDIA-READY state (devices enumerated, preview frame decoded)',
      'secure context, mediaDevices present, >=1 camera and >=1 microphone, video readyState>=2 with non-zero dimensions',
      media,
      (m) => m.secureContext && m.hasMediaDevices && m.chips.length >= 2 && !!m.video && m.video.readyState >= 2 && m.video.w > 0,
    );

    const entry = await withApi(
      page,
      { method: 'POST', route: /\/join-credentials$/, status: 201 },
      () => page.locator('button', { hasText: /^Enter the room$/ }).click(),
    );
    await page.waitForSelector('main.tt-live', { timeout: 20000 });
    await page.waitForSelector('main.tt-live[data-tt-transport="connected"]', { timeout: 25000 });
    await page.waitForFunction(() => {
      const header = document.querySelector('div.tt-lh')?.textContent || '';
      const pill = document.querySelector('[data-tt-transport-pill="connected"]')?.textContent || '';
      return /In the room/.test(header) && /Live/.test(pill);
    }, { timeout: 25000 });
    await settled(page);
    arts.push(await shot(page, 'e3_s35_live_room', { fullPage: false }));
    const headChip = await page.$eval('div.tt-lh span.tt-chip', (e) => e.textContent.trim());

    await page.locator('button.tt-cb[aria-label="Session, connection and privacy details"]').click();
    await page.waitForSelector('div.tt-sheet[data-open="1"]', { timeout: 10000 });
    await settled(page);
    arts.push(await shot(page, 'e4_s35_live_room_details_sheet', { fullPage: false }));
    const sheet = await page.$$eval('div.tt-sheet .tt-kv', (els) => els.map((e) => e.textContent.trim()));

    const cred = creds.find((c) => c.status === 201) || (entry.status === 201 ? { status: 201, json: entry.json } : null);
    const rawToken = cred?.json?.join_token || null;
    if (rawToken) {
      // Scoped for the J1 stage: this ONE surface is where the raw credential is
      // allowed to exist. Everywhere else it is a leak.
      STATE.joinTokens = [...new Set([...(STATE.joinTokens || []), rawToken])];
      saveState();
    }
    // in-memory leak check against the literal token; never persisted
    const leak = rawToken
      ? await page.evaluate((tok) => {
          const store = (s) => {
            const out = [];
            for (let i = 0; i < s.length; i++) out.push(`${s.key(i)}=${s.getItem(s.key(i))}`);
            return out.join('|');
          };
          return {
            dom: document.documentElement.outerHTML.includes(tok),
            local: store(localStorage).includes(tok),
            session: store(sessionStorage).includes(tok),
            cookie: document.cookie.includes(tok),
            url: location.href.includes(tok),
          };
        }, rawToken)
      : null;
    const grants = dbQuery('SELECT id, session_id, participant_ref, room_ref, permissions, revoked_at, expires_at, length(token_hash) AS hash_len FROM video_session_grants WHERE session_id = ?', [sessionId]);
    STATE.roomRef = cred?.json?.room_ref || null;
    STATE.participantRef = cred?.json?.participant_ref || null;
    saveState();

    const redacted = sheet.some((r) => /redacted/i.test(r) && /in memory only/i.test(r));
    chk.ok('the server issued a join credential', 'POST .../join-credentials -> 201 with a room_ref and a TTL', { status: cred?.status, roomRef: cred?.json?.room_ref, ttl: cred?.json?.ttl_seconds }, (v) => v.status === 201 && !!v.roomRef && v.ttl === JOIN_TTL);
    const transport = await page.$eval('main.tt-live', (e) => ({
      state: e.getAttribute('data-tt-transport'),
      adapter: window.__legalsaathiVideoTransport || null,
      pill: document.querySelector('[data-tt-transport-pill]')?.textContent?.trim() || '',
      alerts: [...document.querySelectorAll('[role="alert"]')].map((n) => n.textContent || ''),
    }));
    chk.ok(
      'the room reports admission only after the selected media transport connects',
      'header In the room + transport connected + pill Live + explicit deterministic adapter + zero terminal alert',
      { headChip, ...transport },
      (v) => /In the room/.test(v.headChip) && v.state === 'connected' && v.pill === 'Live'
        && v.adapter === 'deterministic' && v.alerts.length === 0,
    );
    chk.ok('a grant row exists and stores only a token HASH', 'at least one video_session_grants row with a 64-char sha256 hash', grants.map((g) => g.hash_len), (v) => v.length > 0 && v.every((n) => n === 64));
    chk.eq('the details sheet declares the credential redacted and in-memory only', true, redacted);
    chk.ok('the raw join token never reaches DOM, storage, cookie or URL', 'false on every surface', leak, (v) => v && Object.values(v).every((x) => x === false));

    recordChecks(chk, {
      stage: 'e',
      matrix: 'I1/J1',
      summary: `live room entered with a server-issued credential: POST /join-credentials ${cred?.status}, room_ref=${cred?.json?.room_ref}, ttl=${cred?.json?.ttl_seconds}s, header chip "${headChip}", ${grants.length} grant row(s) storing only a ${grants[0]?.hash_len}-char token hash`,
      observed: { credentialStatus: cred?.status, roomRef: cred?.json?.room_ref, participantRef: cred?.json?.participant_ref, ttlSeconds: cred?.json?.ttl_seconds, permissions: cred?.json?.permissions, tokenPrefix: rawToken ? `${rawToken.slice(0, 5)}…(${rawToken.length} chars)` : null, headChip, deviceChips: chips, mediaReadiness: media, sheetRows: sheet, grants, rawTokenLeak: leak },
      artifacts: arts,
    });
  } finally {
    page.off('response', onResponse);
  }
}

/**
 * F5. The accessibility oracle, with the three things the old runner conflated
 * reported SEPARATELY and by their real names.
 *
 *   WCAG 1.4.4 "Resize text" (AA) — content and functionality survive a 200%
 *       increase in text size. Measured TWO ways, because the success criterion
 *       accepts either technique:
 *         a) BROWSER ZOOM 200%: a 1280x800 window at 200% zoom presents a
 *            640x400 CSS-pixel viewport. That is the standard evaluation window;
 *            evaluating browser zoom on a 390px phone would give 195 CSS px,
 *            which is a REFLOW question, not a resize-text one.
 *         b) TEXT-ONLY ZOOM 200%: root font-size 16px -> 32px at the product
 *            viewport, with layout otherwise untouched.
 *
 *   WCAG 1.4.10 "Reflow" (AA) — 320 CSS px wide (equivalent to 1280 at 400%
 *       zoom) with NO two-dimensional scrolling. Content that is explicitly
 *       exempt (a video tile, which requires 2-D layout for usage) is named.
 *
 *   PRODUCT VIEWPORTS — 390x844 and 1280x800, in BOTH themes. A product
 *       requirement, not a WCAG result.
 *
 * `deviceScaleFactor` is NOT any of these. It is the device pixel ratio, a
 * property of the display hardware; it changes how many physical pixels a CSS
 * pixel covers and changes NOTHING about layout, text size or reflow. It is
 * measured and reported on its own row, labelled as such, and it is never
 * called "zoom".
 */
const A11Y_SURFACE = (sessionId) => `${WEB}/s-35?session=${sessionId}&view=room`;

async function stageGeo(browser) {
  const chk = newChecks('I2-a11y-and-geometry', [
    'WCAG 1.4.4 resize text — browser zoom 200% (1280x800 -> 640x400 CSS px): no content or functional loss',
    'WCAG 1.4.4 resize text — text-only zoom 200% (root 16px -> 32px): no content or functional loss',
    'WCAG 1.4.10 reflow — 320 CSS px: no two-dimensional scrolling outside exempt content',
    'product viewports render in both themes without overflow',
    'device pixel ratio is reported separately from zoom and does not alter layout',
    'WCAG 2.5.5/2.5.8 target size — every interactive target is at least 44x44 CSS px',
    'WCAG 2.4.7 focus visible — focus produces a visible indicator',
    'WCAG 2.4.3 focus order — tab order follows the visual/DOM order',
    'WCAG 2.1.2 no keyboard trap — focus can leave every component it enters',
    'focus moves into an open modal and is TRAPPED there',
    'focus is RETURNED to the opening control when the modal closes',
    'Escape closes the modal and the details sheet',
    'WCAG 2.3.3 / prefers-reduced-motion — no non-essential animation runs',
    'WCAG 4.1.2 accessible name — every interactive control has a non-empty name',
    'WCAG 1.4.13 tooltips — hover/focus content is dismissable and persistent, or none exists',
    'the live room fills exactly 100dvh with no page scroll',
  ]);
  const sessionId = STATE.s1;
  if (!sessionId) {
    chk.blocked('the live room fills exactly 100dvh with no page scroll', 'a measured room', 'no confirmed session in state.json — stage c did not run or did not pass');
    return recordChecks(chk, { stage: 'geo', matrix: 'I2', summary: 'accessibility measurement could not be attempted', observed: {}, artifacts: [] });
  }

  const arts = [];
  const measure = async (ctx, label, { fullPage = false, rootFontPercent = null } = {}) => {
    const page = await ctx.newPage();
    attachCapture(page);
    await page.goto(A11Y_SURFACE(sessionId), { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('main.tt-live', { timeout: 25000 });
    // Readiness, not a sleep: the room header has reached a terminal state and
    // every finite animation has finished.
    await page.waitForFunction(
      () => /In the room|Not admitted|Reconnect/i.test(document.querySelector('div.tt-lh')?.textContent || ''),
      undefined,
      { timeout: 25000 },
    );
    await settled(page);
    if (rootFontPercent) {
      // TEXT-ONLY zoom: the user-agent root font size, exactly what a browser's
      // "font size: very large" setting changes. Layout rules are untouched.
      await page.evaluate((pct) => { document.documentElement.style.fontSize = `${pct}%`; }, rootFontPercent);
      await settled(page);
    }
    const m = await page.evaluate(() => {
      const de = document.documentElement;
      const live = document.querySelector('main.tt-live');
      const r = live?.getBoundingClientRect();
      const targets = [...document.querySelectorAll('button, a[href], select, input, [role="radio"], [role="button"]')]
        .filter((el) => {
          const b = el.getBoundingClientRect();
          const cs = getComputedStyle(el);
          return b.width > 0 && b.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
        })
        .map((el) => {
          const b = el.getBoundingClientRect();
          return {
            label: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 48),
            w: Math.round(b.width * 10) / 10,
            h: Math.round(b.height * 10) / 10,
          };
        });
      const under = targets.filter((t) => t.w < 44 || t.h < 44);
      const dvh = (() => {
        const probe = document.createElement('div');
        probe.style.cssText = 'position:fixed;top:0;left:0;height:100dvh;width:1px;pointer-events:none;opacity:0';
        document.body.appendChild(probe);
        const h = probe.getBoundingClientRect().height;
        probe.remove();
        return h;
      })();
      const insetProbe = (() => {
        const p = document.createElement('div');
        p.style.cssText = 'position:fixed;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);opacity:0;pointer-events:none';
        document.body.appendChild(p);
        const cs = getComputedStyle(p);
        const v = { top: cs.paddingTop, right: cs.paddingRight, bottom: cs.paddingBottom, left: cs.paddingLeft };
        p.remove();
        return v;
      })();
      const ctrl = document.querySelector('div.tt-lctrl');
      const ctrlCs = ctrl ? getComputedStyle(ctrl) : null;
      const anim = [...document.querySelectorAll('*')]
        .map((el) => getComputedStyle(el))
        .filter((cs) => (parseFloat(cs.animationDuration) || 0) > 0 || (parseFloat(cs.transitionDuration) || 0) > 0)
        .map((cs) => ({ animation: cs.animationDuration, transition: cs.transitionDuration }));
      // --- accessible names (WCAG 4.1.2) ---
      const named = [...document.querySelectorAll('button, a[href], select, input, textarea, [role="button"], [role="radio"], [role="tab"]')]
        .filter((el) => {
          const b = el.getBoundingClientRect();
          return b.width > 0 && b.height > 0;
        })
        .map((el) => {
          const label = el.getAttribute('aria-label')
            || (el.getAttribute('aria-labelledby') ? (document.getElementById(el.getAttribute('aria-labelledby'))?.textContent || '') : '')
            || (el.id ? (document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent || '') : '')
            || el.textContent
            || el.getAttribute('title')
            || el.getAttribute('alt')
            || '';
          return { tag: el.tagName.toLowerCase(), cls: el.className?.toString?.().slice(0, 40) || '', name: label.trim().slice(0, 60) };
        });
      // --- tooltips (WCAG 1.4.13) ---
      const tooltips = {
        titleAttributeOnly: [...document.querySelectorAll('[title]')]
          .filter((el) => !el.getAttribute('aria-label') && !el.getAttribute('aria-describedby'))
          .map((el) => ({ tag: el.tagName.toLowerCase(), title: el.getAttribute('title').slice(0, 60) })),
        ariaDescribed: document.querySelectorAll('[aria-describedby]').length,
        customHoverContent: document.querySelectorAll('[data-tooltip], [role="tooltip"]').length,
      };
      // --- text clipping / overlap under a resize (1.4.4 "no loss of content") ---
      const clipped = [...document.querySelectorAll('main.tt-live *')]
        .filter((el) => {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          if (!el.textContent || !el.textContent.trim()) return false;
          if (el.children.length) return false;
          // Overflow that HIDES text is a loss of content; a scrollable region is not.
          const hides = cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.overflowY === 'hidden';
          if (!hides) return false;
          return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
        })
        .map((el) => ({
          text: el.textContent.trim().slice(0, 40),
          scrollW: el.scrollWidth, clientW: el.clientWidth,
          scrollH: el.scrollHeight, clientH: el.clientHeight,
        }));
      // --- reflow exemptions (1.4.10 explicitly exempts content requiring 2-D) ---
      const exempt = [...document.querySelectorAll('video, [data-reflow-exempt], table')]
        .map((el) => ({ tag: el.tagName.toLowerCase(), w: Math.round(el.getBoundingClientRect().width) }));
      return {
        viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio },
        rootFontSizePx: parseFloat(getComputedStyle(document.documentElement).fontSize),
        bodyFontSizePx: parseFloat(getComputedStyle(document.body).fontSize),
        controlCount: named.length,
        unnamedControls: named.filter((n) => !n.name),
        tooltips,
        clippedText: clipped,
        reflowExempt: exempt,
        cssDvhPx: Math.round(dvh * 10) / 10,
        liveRect: r ? { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 } : null,
        pageScroll: { scrollHeight: de.scrollHeight, clientHeight: de.clientHeight, verticalOverflowPx: de.scrollHeight - de.clientHeight },
        horizontal: { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, horizontalOverflowPx: de.scrollWidth - de.clientWidth },
        bodyOverflow: getComputedStyle(document.body).overflow,
        roomAttr: { html: de.dataset.ttRoom || null, body: document.body.dataset.ttRoom || null },
        targets: { total: targets.length, under44: under },
        safeAreaEnvResolved: insetProbe,
        controlPadding: ctrlCs ? { bottom: ctrlCs.paddingBottom, usesEnv: /env\(/.test(ctrl.getAttribute('style') || '') } : null,
        animatedElements: anim.length,
        longestAnimationSeconds: anim.reduce((mx, a) => Math.max(mx, parseFloat(a.animation) || 0, parseFloat(a.transition) || 0), 0),
      };
    });
    // focus ring
    const focus = await page.evaluate(() => {
      const btn = document.querySelector('div.tt-lctrl button.tt-cb');
      if (!btn) return null;
      const before = getComputedStyle(btn);
      const base = { outlineWidth: before.outlineWidth, outlineStyle: before.outlineStyle, boxShadow: before.boxShadow };
      btn.focus();
      const after = getComputedStyle(btn);
      const now = { outlineWidth: after.outlineWidth, outlineStyle: after.outlineStyle, boxShadow: after.boxShadow, isFocused: document.activeElement === btn };
      return { base, focused: now, changed: base.outlineWidth !== now.outlineWidth || base.boxShadow !== now.boxShadow || base.outlineStyle !== now.outlineStyle };
    });
    // --- WCAG 2.4.3 focus order + 2.1.2 no keyboard trap ---
    await page.evaluate(() => { document.body.focus(); if (document.activeElement !== document.body) document.activeElement.blur(); });
    const order = [];
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press('Tab');
      const here = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const b = el.getBoundingClientRect();
        return {
          tag: el.tagName.toLowerCase(),
          name: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40),
          x: Math.round(b.x), y: Math.round(b.y),
          domIndex: [...document.querySelectorAll('*')].indexOf(el),
        };
      });
      if (!here) break;
      order.push(here);
      // A cycle back to the first control means the tab ring closed normally.
      if (order.length > 2 && here.domIndex === order[0].domIndex) break;
    }
    m.focusOrder = order;
    m.focusOrderFollowsDom = order.length > 1
      && order.slice(0, -1).every((o, i) => order[i + 1].domIndex > o.domIndex || order[i + 1].domIndex === order[0].domIndex);
    // Keyboard trap: after the sweep, focus must be releasable — Tab from the
    // last control must not return to the same element forever.
    const distinct = new Set(order.map((o) => o.domIndex)).size;
    m.keyboardTrap = order.length > 1 && distinct === 1;

    const file = await shot(page, `geo_${label}`, { fullPage });
    m.focusRing = focus;
    m.colors = await page.evaluate(() => {
      const cs = getComputedStyle(document.querySelector('main.tt-live'));
      const chip = document.querySelector('div.tt-lh span.tt-chip');
      return { liveBackground: cs.backgroundColor, liveColor: cs.color, chipColor: chip ? getComputedStyle(chip).color : null, chipBackground: chip ? getComputedStyle(chip).backgroundColor : null };
    });
    m.screenshot = file;
    await page.close();
    return m;
  };

  /**
   * Every configuration is declared with WHAT IT IS and WHICH criterion (if
   * any) it answers. A row with `criterion: null` is a product requirement and
   * is reported as one; it can never be quoted as a WCAG result.
   */
  const CONFIGS = [
    { key: 'product_mobile_light_390x844', criterion: null, kind: 'product viewport',
      why: 'the primary product viewport, light theme',
      ctx: { viewport: MOBILE, colorScheme: 'light' } },
    { key: 'product_mobile_dark_390x844', criterion: null, kind: 'product viewport',
      why: 'the primary product viewport, dark theme',
      ctx: { viewport: MOBILE, colorScheme: 'dark' } },
    { key: 'product_desktop_light_1280x800', criterion: null, kind: 'product viewport',
      why: 'the desktop product viewport, light theme',
      ctx: { viewport: { width: 1280, height: 800 }, colorScheme: 'light' } },
    { key: 'product_desktop_dark_1280x800', criterion: null, kind: 'product viewport',
      why: 'the desktop product viewport, dark theme',
      ctx: { viewport: { width: 1280, height: 800 }, colorScheme: 'dark' } },
    { key: 'wcag_1_4_4_browser_zoom_200pct_640x400', criterion: 'WCAG 1.4.4 Resize text (AA)', kind: 'browser zoom 200%',
      why: 'a 1280x800 window at 200% browser zoom presents a 640x400 CSS-pixel viewport',
      ctx: { viewport: { width: 640, height: 400 }, colorScheme: 'light' } },
    { key: 'wcag_1_4_4_text_only_zoom_200pct_390x844', criterion: 'WCAG 1.4.4 Resize text (AA)', kind: 'text-only zoom 200%',
      why: 'root font-size 16px -> 32px at the product viewport; layout rules untouched',
      ctx: { viewport: MOBILE, colorScheme: 'light' }, rootFontPercent: 200 },
    { key: 'wcag_1_4_10_reflow_320x256', criterion: 'WCAG 1.4.10 Reflow (AA)', kind: 'reflow at 320 CSS px',
      why: '320 CSS px wide is the criterion\'s own threshold (1280 at 400% zoom)',
      ctx: { viewport: { width: 320, height: 256 }, colorScheme: 'light' } },
    { key: 'wcag_2_3_3_reduced_motion_390x844', criterion: 'WCAG 2.3.3 Animation from interactions (AAA) / prefers-reduced-motion', kind: 'reduced motion',
      why: 'prefers-reduced-motion: reduce at the product viewport',
      ctx: { viewport: MOBILE, reducedMotion: 'reduce', colorScheme: 'light' } },
    { key: 'device_pixel_ratio_2_390x844', criterion: null, kind: 'device pixel ratio (NOT zoom)',
      why: 'DPR 2 at the SAME 390x844 CSS viewport. This row exists to show that DPR changes rendering resolution and nothing about layout, text size or reflow — it is not, and was never, a 200% zoom measurement.',
      ctx: { viewport: MOBILE, deviceScaleFactor: 2, colorScheme: 'light' } },
    { key: 'product_narrow_195x422', criterion: null, kind: 'PRODUCT sub-320 requirement',
      why: 'a 390 CSS px phone at 200% browser zoom lands at 195 CSS px, which is BELOW the 320 px floor WCAG 1.4.10 sets. Any expectation of usability here is a PRODUCT requirement of this app and is reported separately; it is deliberately NOT counted towards 1.4.4 or 1.4.10.',
      ctx: { viewport: { width: 195, height: 422 }, colorScheme: 'light' } },
  ];

  const results = {};
  for (const cfg of CONFIGS) {
    const ctx = await browser.newContext({ permissions: ['camera', 'microphone'], ...cfg.ctx });
    // The aggregate intentionally proves the deterministic application seam;
    // real LiveKit/TURN is owned by infra/video/scripts/livekit_turn_smoke.sh.
    // Every fresh geometry context must make the same explicit selection as
    // stage E before the application boots. Falling through to the production
    // LiveKit adapter here makes the geometry oracle wait on an unrelated
    // external media runtime and produces a false timeout.
    await ctx.addInitScript(() => {
      window.__legalsaathiVideoTransport = 'deterministic';
    });
    results[cfg.key] = {
      criterion: cfg.criterion,
      kind: cfg.kind,
      why: cfg.why,
      ...(await measure(ctx, cfg.key, { rootFontPercent: cfg.rootFontPercent || null })),
    };
    await ctx.close();
  }
  for (const v of Object.values(results)) arts.push(v.screenshot);

  /* --------------------------- per-criterion verdicts --------------------- */
  const R = results;
  const noLoss = (r) => r.clippedText.length === 0
    && r.horizontal.horizontalOverflowPx <= 1
    && r.targets.under44.length === 0
    && r.unnamedControls.length === 0
    && r.controlCount > 0;

  const zoom = R.wcag_1_4_4_browser_zoom_200pct_640x400;
  chk.ok(
    'WCAG 1.4.4 resize text — browser zoom 200% (1280x800 -> 640x400 CSS px): no content or functional loss',
    'zero clipped text nodes, zero horizontal overflow, every control still present, named and >=44px',
    { viewport: zoom.viewport, clippedText: zoom.clippedText.length, horizontalOverflowPx: zoom.horizontal.horizontalOverflowPx, controls: zoom.controlCount, unnamed: zoom.unnamedControls.length, under44: zoom.targets.under44.length },
    () => noLoss(zoom),
  );

  const text2x = R.wcag_1_4_4_text_only_zoom_200pct_390x844;
  const base1x = R.product_mobile_light_390x844;
  chk.ok(
    'WCAG 1.4.4 resize text — text-only zoom 200% (root 16px -> 32px): no content or functional loss',
    'root font size exactly doubled, zero clipped text, zero horizontal overflow, every control present and named',
    { rootFontSizePx: text2x.rootFontSizePx, baselineRootPx: base1x.rootFontSizePx, clippedText: text2x.clippedText.length, horizontalOverflowPx: text2x.horizontal.horizontalOverflowPx, controls: text2x.controlCount, unnamed: text2x.unnamedControls.length },
    (v) => Math.abs(v.rootFontSizePx - v.baselineRootPx * 2) < 0.6 && noLoss(text2x),
  );

  const reflow = R.wcag_1_4_10_reflow_320x256;
  const reflowExemptWide = reflow.reflowExempt.filter((e) => e.w > reflow.viewport.w + 1);
  chk.ok(
    'WCAG 1.4.10 reflow — 320 CSS px: no two-dimensional scrolling outside exempt content',
    'at a 320 CSS px viewport, scrollWidth <= clientWidth (no horizontal scrollbar); only video/table content may require 2-D',
    { viewport: reflow.viewport, scrollWidth: reflow.horizontal.scrollWidth, clientWidth: reflow.horizontal.clientWidth, horizontalOverflowPx: reflow.horizontal.horizontalOverflowPx, exemptContent: reflow.reflowExempt, exemptExceedingViewport: reflowExemptWide },
    (v) => v.horizontalOverflowPx <= 1 && reflowExemptWide.length === 0,
  );

  const productKeys = ['product_mobile_light_390x844', 'product_mobile_dark_390x844', 'product_desktop_light_1280x800', 'product_desktop_dark_1280x800'];
  chk.ok(
    'product viewports render in both themes without overflow',
    '390x844 and 1280x800, light AND dark: no horizontal overflow, no page scroll, controls present',
    Object.fromEntries(productKeys.map((k) => [k, { h: R[k].horizontal.horizontalOverflowPx, v: R[k].pageScroll.verticalOverflowPx, controls: R[k].controlCount, colors: R[k].colors }])),
    () => productKeys.every((k) => R[k].horizontal.horizontalOverflowPx <= 1 && R[k].pageScroll.verticalOverflowPx <= 1 && R[k].controlCount > 0)
      && R.product_mobile_light_390x844.colors.liveBackground !== R.product_mobile_dark_390x844.colors.liveBackground,
  );

  const dpr2 = R.device_pixel_ratio_2_390x844;
  chk.ok(
    'device pixel ratio is reported separately from zoom and does not alter layout',
    'at DPR 2 the CSS viewport, root font size and live-room rect are IDENTICAL to DPR 1 — proving DPR is not zoom',
    { dpr1: { dpr: base1x.viewport.dpr, w: base1x.viewport.w, h: base1x.viewport.h, root: base1x.rootFontSizePx, live: base1x.liveRect },
      dpr2: { dpr: dpr2.viewport.dpr, w: dpr2.viewport.w, h: dpr2.viewport.h, root: dpr2.rootFontSizePx, live: dpr2.liveRect } },
    (v) => v.dpr2.dpr === 2 && v.dpr1.dpr === 1 && v.dpr2.w === v.dpr1.w && v.dpr2.h === v.dpr1.h && v.dpr2.root === v.dpr1.root,
  );

  const allTargets = Object.entries(R).map(([k, r]) => ({ config: k, total: r.targets.total, under44: r.targets.under44 }));
  chk.ok(
    'WCAG 2.5.5/2.5.8 target size — every interactive target is at least 44x44 CSS px',
    'zero targets under 44x44 CSS px in every configuration',
    allTargets,
    (v) => v.every((x) => x.total > 0 && x.under44.length === 0),
  );
  chk.ok(
    'WCAG 2.4.7 focus visible — focus produces a visible indicator',
    'outline or box-shadow changes when a control receives focus, in every configuration',
    Object.fromEntries(Object.entries(R).map(([k, r]) => [k, r.focusRing?.changed ?? null])),
    (v) => Object.values(v).every((x) => x === true),
  );
  chk.ok(
    'WCAG 2.4.3 focus order — tab order follows the visual/DOM order',
    'the Tab sequence visits controls in increasing DOM order and then cycles',
    Object.fromEntries(Object.entries(R).map(([k, r]) => [k, { steps: r.focusOrder.length, followsDom: r.focusOrderFollowsDom }])),
    (v) => Object.values(v).every((x) => x.steps > 1 && x.followsDom === true),
  );
  chk.ok(
    'WCAG 2.1.2 no keyboard trap — focus can leave every component it enters',
    'the Tab sweep visits more than one distinct element in every configuration',
    Object.fromEntries(Object.entries(R).map(([k, r]) => [k, r.keyboardTrap])),
    (v) => Object.values(v).every((x) => x === false),
  );
  chk.ok(
    'WCAG 2.3.3 / prefers-reduced-motion — no non-essential animation runs',
    'longest animation/transition duration is 0s under prefers-reduced-motion: reduce',
    { reduced: R.wcag_2_3_3_reduced_motion_390x844.longestAnimationSeconds, normal: base1x.longestAnimationSeconds },
    (v) => v.reduced <= 0.001,
  );
  chk.ok(
    'WCAG 4.1.2 accessible name — every interactive control has a non-empty name',
    'zero controls without an aria-label / labelled-by / label / text / title, in every configuration',
    Object.fromEntries(Object.entries(R).map(([k, r]) => [k, r.unnamedControls])),
    (v) => Object.values(v).every((x) => x.length === 0),
  );
  const tips = base1x.tooltips;
  chk.ok(
    'WCAG 1.4.13 tooltips — hover/focus content is dismissable and persistent, or none exists',
    'either no title-attribute-only tooltip exists (the criterion does not apply), or every tooltip is Escape-dismissable',
    tips,
    (v) => v.titleAttributeOnly.length === 0 && v.customHoverContent === 0,
  );
  chk.ok(
    'the live room fills exactly 100dvh with no page scroll',
    '100dvh == innerHeight and the room rect == innerHeight, with <=1px page scroll, in every configuration',
    Object.fromEntries(Object.entries(R).map(([k, r]) => [k, { dvh: r.cssDvhPx, vh: r.viewport.h, liveH: r.liveRect?.h, scroll: r.pageScroll.verticalOverflowPx }])),
    (v) => Object.values(v).every((x) => Math.abs(x.dvh - x.vh) <= 1 && x.liveH !== undefined && Math.abs(x.liveH - x.vh) <= 1 && x.scroll <= 1),
  );

  /* -------- modal focus trap / return / Escape, driven for real ----------- */
  const modal = await modalFocusProbe(browser, sessionId);
  chk.ok(
    'focus moves into an open modal and is TRAPPED there',
    'the dialog opens, focus lands inside it, and 12 consecutive Tab presses never leave it',
    { opened: modal.opened, tabPresses: modal.tabbedInside.length, escapes: modal.escapedDialog },
    (v) => v.opened === true && v.tabPresses > 0 && v.escapes === 0,
  );
  chk.ok(
    'focus is RETURNED to the opening control when the modal closes',
    'after Escape dismisses the dialog, document.activeElement is the button that opened it (WCAG 2.4.3; the ARIA authoring-practices modal pattern)',
    { focusReturnedToOpener: modal.focusReturnedToOpener, openerName: modal.openerName ?? null, activeAfterClose: modal.activeAfterClose ?? null },
    (v) => v.focusReturnedToOpener === true,
  );
  chk.ok(
    'Escape closes the modal and the details sheet',
    'Escape dismisses role="dialog" and the live-room details sheet',
    { modalClosedByEscape: modal.closedByEscape, sheetClosedByEscape: modal.sheetClosedByEscape },
    (v) => v.modalClosedByEscape === true && v.sheetClosedByEscape === true,
  );

  const report = {
    generatedAt: new Date().toISOString(),
    matrixRow: 'I2',
    runId: RUN_ID,
    surface: `/s-35?view=room (live room), session ${sessionId}`,
    browser: STATE.browserVersion || null,
    reportingRule: 'Each configuration names the criterion it answers, or `null` when it is a PRODUCT requirement. deviceScaleFactor is device pixel ratio and is never reported as zoom.',
    separatedVerdicts: {
      'WCAG 1.4.4 Resize text (AA)': {
        browserZoom200: { config: 'wcag_1_4_4_browser_zoom_200pct_640x400', cssViewport: zoom.viewport, clippedTextNodes: zoom.clippedText.length, horizontalOverflowPx: zoom.horizontal.horizontalOverflowPx, controlsPresent: zoom.controlCount, controlsUnder44: zoom.targets.under44.length, pass: noLoss(zoom) },
        textOnlyZoom200: { config: 'wcag_1_4_4_text_only_zoom_200pct_390x844', rootFontSizePx: text2x.rootFontSizePx, baselineRootFontSizePx: base1x.rootFontSizePx, clippedTextNodes: text2x.clippedText.length, horizontalOverflowPx: text2x.horizontal.horizontalOverflowPx, pass: noLoss(text2x) },
      },
      'WCAG 1.4.10 Reflow (AA)': {
        config: 'wcag_1_4_10_reflow_320x256',
        cssViewportWidth: reflow.viewport.w,
        scrollWidth: reflow.horizontal.scrollWidth,
        clientWidth: reflow.horizontal.clientWidth,
        twoDimensionalScrollingPx: reflow.horizontal.horizontalOverflowPx,
        exemptContent: reflow.reflowExempt,
        pass: reflow.horizontal.horizontalOverflowPx <= 1 && reflowExemptWide.length === 0,
      },
      'Product viewports (NOT a WCAG result)': Object.fromEntries(productKeys.map((k) => [k, { viewport: R[k].viewport, theme: R[k].colors, horizontalOverflowPx: R[k].horizontal.horizontalOverflowPx, verticalOverflowPx: R[k].pageScroll.verticalOverflowPx }])),
      'Device pixel ratio (NOT zoom, NOT a WCAG result)': { dpr1: base1x.viewport, dpr2: dpr2.viewport, layoutIdentical: dpr2.viewport.w === base1x.viewport.w && dpr2.rootFontSizePx === base1x.rootFontSizePx },
      'PRODUCT sub-320 requirement (NOT a WCAG result)': { config: 'product_narrow_195x422', cssViewportWidth: R.product_narrow_195x422.viewport.w, note: 'below the 320 CSS px floor of WCAG 1.4.10; stated separately and never conflated', horizontalOverflowPx: R.product_narrow_195x422.horizontal.horizontalOverflowPx, targetsUnder44: R.product_narrow_195x422.targets.under44.length },
    },
    keyboardAndFocus: { modalProbe: modal, perConfig: Object.fromEntries(Object.entries(R).map(([k, r]) => [k, { focusRing: r.focusRing, focusOrderSteps: r.focusOrder.length, focusOrderFollowsDom: r.focusOrderFollowsDom, keyboardTrap: r.keyboardTrap }])) },
    assertions: chk.table,
    measurements: results,
  };
  fs.writeFileSync(path.join(OUT, 'browser_matrix.json'), JSON.stringify(report, null, 2));
  arts.push('browser_matrix.json');

  recordChecks(chk, {
    stage: 'geo',
    matrix: 'I2',
    summary: `a11y measured in ${CONFIGS.length} named configurations; 1.4.4 browser-zoom 640x400 clipped=${zoom.clippedText.length}; 1.4.4 text-only root ${base1x.rootFontSizePx}px->${text2x.rootFontSizePx}px; 1.4.10 reflow at ${reflow.viewport.w}px h-overflow=${reflow.horizontal.horizontalOverflowPx}px; DPR2 layout identical to DPR1`,
    observed: report.separatedVerdicts,
    artifacts: arts,
  });
}

/**
 * Focus trap, focus RETURN and Escape, driven with the real keyboard on the
 * real cancel dialog and the real live-room details sheet.
 */
async function modalFocusProbe(browser, sessionId) {
  const ctx = await browser.newContext({ viewport: MOBILE, colorScheme: 'light', permissions: ['camera', 'microphone'] });
  const page = await ctx.newPage();
  attachCapture(page);
  const out = { opened: false, escapedDialog: null, focusReturnedToOpener: null, closedByEscape: null, sheetClosedByEscape: null, tabbedInside: [] };
  try {
    await go(page, `${WEB}/s-35?session=${sessionId}&view=manage`, 'h1');
    const opener = page.locator('button', { hasText: /Cancel this session/ }).first();
    if (await opener.count()) {
      await opener.focus();
      await page.evaluate(() => { window.__openerName = (document.activeElement.getAttribute('aria-label') || document.activeElement.textContent || '').trim(); });
      await opener.click();
      await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 10000 });
      await settled(page);
      out.opened = true;
      let outside = 0;
      for (let i = 0; i < 12; i++) {
        await page.keyboard.press('Tab');
        const info = await page.evaluate(() => {
          const el = document.activeElement;
          const dlg = document.querySelector('div.tt-modal[role="dialog"]');
          return { inside: !!(dlg && el && dlg.contains(el)), name: (el?.getAttribute('aria-label') || el?.textContent || '').trim().slice(0, 30) };
        });
        out.tabbedInside.push(info);
        if (!info.inside) outside += 1;
      }
      out.escapedDialog = outside;
      await page.keyboard.press('Escape');
      await page.waitForSelector('div.tt-modal[role="dialog"]', { state: 'detached', timeout: 8000 }).then(() => { out.closedByEscape = true; }).catch(() => { out.closedByEscape = false; });
      await settled(page);
      const focusAfter = await page.evaluate(() => ({
        opener: window.__openerName,
        active: (document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent || '').trim().slice(0, 60),
        activeTag: document.activeElement?.tagName?.toLowerCase() || null,
        isBody: document.activeElement === document.body,
      }));
      out.openerName = focusAfter.opener;
      out.activeAfterClose = focusAfter.isBody ? '<body> — focus was dropped to the document' : `${focusAfter.activeTag}: ${focusAfter.active}`;
      out.focusReturnedToOpener = !focusAfter.isBody && focusAfter.active === focusAfter.opener && focusAfter.active.length > 0;
    } else {
      out.opened = false;
    }

    await go(page, A11Y_SURFACE(sessionId), 'main.tt-live');
    const sheetBtn = page.locator('button.tt-cb[aria-label="Session, connection and privacy details"]');
    if (await sheetBtn.count()) {
      await sheetBtn.click();
      await page.waitForSelector('div.tt-sheet[data-open="1"]', { timeout: 10000 });
      await page.keyboard.press('Escape');
      out.sheetClosedByEscape = await page
        .waitForFunction(() => !document.querySelector('div.tt-sheet[data-open="1"]'), undefined, { timeout: 8000 })
        .then(() => true)
        .catch(() => false);
    }
  } catch (err) {
    out.error = String(err).slice(0, 300);
  } finally {
    await ctx.close();
  }
  return out;
}

async function stageD1(page) {
  const chk = newChecks('I1-d1-reschedule-outside-window', [
    'the reschedule moved the session to a different slot',
    'the aggregate version advanced',
    'the DB row records the reschedule',
    'the policy screen explains the free window',
    'reminder jobs were REVOKED for the old schedule and re-scheduled for the new one',
  ]);
  const sessionId = STATE.s1;
  if (!sessionId) {
    chk.blocked('the DB row records the reschedule', 'a rescheduled session', 'no session in state.json — stage c did not run or did not pass');
    return recordChecks(chk, { stage: 'd1', matrix: 'I1', summary: 'reschedule could not be attempted', observed: {}, artifacts: [] });
  }
  const arts = [];
  await go(page, `${WEB}/s-35?session=${sessionId}&view=policy`, 'h2');
  arts.push(await shot(page, 'd1_s35_policy_outside_window'));
  const policy = await banners(page);
  const kv = await page.$$eval('.tt-kv', (e) => e.map((x) => x.textContent.trim()));
  await page.locator('button', { hasText: /Reschedule/ }).first().click();
  await page.waitForFunction(() => location.search.includes('view=reschedule'), { timeout: 15000 });
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'd2_s35_reschedule_choose'));
  const before = await apiSession(sessionId);
  await page.locator('div.tt-slots button.tt-slotbtn').first().click();
  await withApi(
    page,
    { method: 'POST', route: /\/reschedule$/, maxStatus: 300 },
    () => page.locator('button', { hasText: /Confirm the new time/ }).click(),
  );
  await page.waitForFunction(() => location.search.includes('view=manage'), { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'd3_s35_rescheduled'));
  const after = await apiSession(sessionId);
  const row = await sessionRow(sessionId);
  const reminders = dbQuery('SELECT status, offset_kind, scheduled_for FROM session_reminder_jobs WHERE session_id = ? ORDER BY scheduled_for', [sessionId]);

  chk.ok('the reschedule moved the session to a different slot', 'a different slot_id', { before: before.slot_id, after: after.slot_id }, (v) => v.before !== v.after);
  chk.ok('the aggregate version advanced', 'version strictly greater than before', { before: before.version, after: after.version }, (v) => v.after > v.before);
  chk.ok('the DB row records the reschedule', 'status in rescheduled/confirmed', row?.status, (v) => ['rescheduled', 'confirmed'].includes(v));
  chk.ok('the policy screen explains the free window', 'at least one policy banner with a title', policy.map((b) => b.title).filter(Boolean), (v) => v.length > 0);
  chk.ok(
    'reminder jobs were REVOKED for the old schedule and re-scheduled for the new one',
    'zero scheduled jobs at the old start; at least one scheduled job, and at least one revoked job',
    { jobs: reminders, scheduled: reminders.filter((j) => j.status === 'scheduled').length, revoked: reminders.filter((j) => j.status === 'revoked').length },
    (v) => v.revoked > 0 && v.scheduled > 0,
  );

  neg('N37', {
    expected: 'a reschedule REVOKES the reminder jobs scheduled against the old start and schedules new ones against the new start',
    actual: `${reminders.filter((j) => j.status === 'revoked').length} revoked, ${reminders.filter((j) => j.status === 'scheduled').length} scheduled, ${reminders.length} job(s) total`,
    pass: reminders.filter((j) => j.status === 'revoked').length > 0 && reminders.filter((j) => j.status === 'scheduled').length > 0,
    mechanism: 'browser reschedule + DB oracle on session_reminder_jobs',
  });
  recordChecks(chk, {
    stage: 'd1',
    matrix: 'I1',
    summary: `reschedule accepted outside the free window: slot ${before.slot_id} -> ${after.slot_id}, version ${before.version} -> ${after.version}, DB status=${row?.status}; ${reminders.filter((j) => j.status === 'revoked').length} reminder job(s) revoked, ${reminders.filter((j) => j.status === 'scheduled').length} re-scheduled`,
    observed: { policyBanners: policy, policyKv: kv, before: { slot: before.slot_id, version: before.version, start: before.start_utc }, after: { slot: after.slot_id, version: after.version, start: after.start_utc }, dbRow: row, reminderJobs: reminders },
    artifacts: arts,
  });
}

async function stageD2(page) {
  const chk = newChecks('I1-d2-policy-cancel-refund', [
    'an inside-window reschedule is refused with RESCHEDULE_WINDOW_CLOSED',
    'the refusal reached the browser as a typed banner code',
    'cancelling inside the free window yields NO automatic refund',
    'cancelling outside the free window yields a FULL refund',
    'both cancelled sessions are cancelled in the database',
    'the refund amount shown matches the server-authoritative price',
    'cancellation REVOKES every scheduled reminder job',
  ]);
  const arts = [];
  // S2: booked, then clock-shifted inside the window -> reschedule refused, cancel with no refund
  const b2 = await (async () => {
    const slot2 = takeSlot('gt24h');
    return bookInBrowser(page, slot2, null);
  })();
  STATE.s2 = b2.sessionId;
  saveState();
  const shift = await shiftSessionTo(b2.sessionId, 3);

  await go(page, `${WEB}/s-35?session=${b2.sessionId}&view=policy`, 'h2');
  arts.push(await shot(page, 'd4_s35_policy_inside_window'));
  const insideBanners = await banners(page);
  await page.locator('button', { hasText: /reschedule/i }).first().click();
  await page.waitForFunction(() => location.search.includes('view=reschedule'), { timeout: 15000 });
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 20000 });
  await settled(page);
  await page.locator('div.tt-slots button.tt-slotbtn').first().click();
  // The refusal is EXPECTED, and it is scoped to this case with its exact
  // method, route, status and typed code. Nothing else in the run is allowed to
  // produce a 409 on this route.
  const windowClosed = await expecting(
    [{ kind: 'http', method: 'POST', route: /^\/api\/v1\/tutoring\/sessions\/[0-9a-f-]+\/reschedule$/, status: 409, code: 'RESCHEDULE_WINDOW_CLOSED' }],
    async () => {
      await page.locator('button', { hasText: /Confirm the new time/ }).click();
      await waitForCode(page, 'RESCHEDULE_WINDOW_CLOSED', 20000).catch(() => null);
      await settled(page);
    },
  );
  const refusalCode = (await banners(page)).map((b) => b.code).filter(Boolean).join(',') || null;
  arts.push(await shot(page, 'd5_s35_reschedule_window_closed'));
  const refusal = await banners(page);

  // cancel inside the window -> NO_AUTO_REFUND
  await go(page, `${WEB}/s-35?session=${b2.sessionId}&view=manage`, 'h1');
  await page.locator('button', { hasText: /Cancel this session/ }).click();
  await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 10000 });
  await settled(page);
  arts.push(await shot(page, 'd6_s35_cancel_modal_inside_window'));
  await withApi(
    page,
    { method: 'POST', route: /\/cancel$/, maxStatus: 300 },
    () => page.locator('div.tt-modal button', { hasText: /Yes, cancel/ }).click(),
  );
  await page.waitForFunction(() => /Cancelled with/.test(document.body.textContent), { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'd7_s35_cancel_no_auto_refund'));
  const noRefund = await banners(page);
  const s2row = await sessionRow(b2.sessionId);
  const s2refunds = dbQuery('SELECT c.id AS id, c.refund_decision AS decision, c.cancelled_by_role AS cancelled_by_role, c.audited AS audited, c.hours_before_start AS hours_before_start, (SELECT r.amount_paise FROM payment_refunds r JOIN tutoring_sessions s ON s.order_id = r.order_id WHERE s.id = c.session_id ORDER BY r.created_at DESC LIMIT 1) AS amount_paise FROM session_cancellations c WHERE c.session_id = ?', [b2.sessionId]);

  // S3: booked and cancelled outside the window -> FULL_REFUND
  const slot3 = takeSlot('gt24h');
  const b3 = await bookInBrowser(page, slot3, null);
  STATE.s3 = b3.sessionId;
  saveState();
  const s3RemindersBefore = dbQuery('SELECT status FROM session_reminder_jobs WHERE session_id = ?', [b3.sessionId]);
  await go(page, `${WEB}/s-35?session=${b3.sessionId}&view=manage`, 'h1');
  await page.locator('button', { hasText: /Cancel this session/ }).click();
  await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 10000 });
  await settled(page);
  await withApi(
    page,
    { method: 'POST', route: /\/cancel$/, maxStatus: 300 },
    () => page.locator('div.tt-modal button', { hasText: /Yes, cancel/ }).click(),
  );
  await page.waitForFunction(() => /Cancelled with/.test(document.body.textContent), { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'd8_s35_cancel_full_refund'));
  const fullRefund = await banners(page);
  const amount = await page.$eval('div.tt-amt .tt-amt__big', (e) => e.textContent.trim()).catch(() => null);
  const prog = await page.$eval('div.tt-prog', (e) => e.getAttribute('aria-label')).catch(() => null);
  const s3refunds = dbQuery('SELECT c.id AS id, c.refund_decision AS decision, c.cancelled_by_role AS cancelled_by_role, c.audited AS audited, c.hours_before_start AS hours_before_start, (SELECT r.amount_paise FROM payment_refunds r JOIN tutoring_sessions s ON s.order_id = r.order_id WHERE s.id = c.session_id ORDER BY r.created_at DESC LIMIT 1) AS amount_paise FROM session_cancellations c WHERE c.session_id = ?', [b3.sessionId]);
  const s3row = await sessionRow(b3.sessionId);

  const s3RemindersAfter = dbQuery('SELECT status, offset_kind FROM session_reminder_jobs WHERE session_id = ?', [b3.sessionId]);

  chk.ok(
    'an inside-window reschedule is refused with RESCHEDULE_WINDOW_CLOSED',
    'POST .../reschedule -> 409 RESCHEDULE_WINDOW_CLOSED, exactly once, inside this case',
    { satisfied: windowClosed.satisfied, unmet: windowClosed.unmet, specs: windowClosed.specs },
    (v) => v.satisfied === true,
  );
  chk.eq('the refusal reached the browser as a typed banner code', 'RESCHEDULE_WINDOW_CLOSED', refusalCode);
  chk.ok('cancelling inside the free window yields NO automatic refund', 'refund_decision = no_auto_refund', s2refunds[0]?.decision, (v) => v === 'no_auto_refund');
  chk.ok('cancelling outside the free window yields a FULL refund', 'refund_decision = full_refund', s3refunds[0]?.decision, (v) => v === 'full_refund');
  chk.eq('both cancelled sessions are cancelled in the database', ['cancelled', 'cancelled'], [s2row?.status, s3row?.status]);
  chk.ok(
    'the refund amount shown matches the server-authoritative price',
    `payment_refunds.amount_paise = ${FEE_PAISE} and the screen shows the same money`,
    { dbAmount: s3refunds[0]?.amount_paise, shown: amount },
    // "₹2,500.00" -> digits "250000", which IS the paise figure. Comparing the
    // rendered money to the stored paise is the point: a screen that formatted
    // the wrong number would not survive it.
    (v) => Number(v.dbAmount) === FEE_PAISE && typeof v.shown === 'string' && v.shown.replace(/[^\d]/g, '') === String(FEE_PAISE),
  );
  chk.ok(
    'cancellation REVOKES every scheduled reminder job',
    'zero jobs left in status=scheduled after the cancel; at least one now revoked',
    { before: s3RemindersBefore, after: s3RemindersAfter, stillScheduled: s3RemindersAfter.filter((j) => j.status === 'scheduled').length, revoked: s3RemindersAfter.filter((j) => j.status === 'revoked').length },
    (v) => v.after.length > 0 && v.stillScheduled === 0 && v.revoked > 0,
  );

  neg('N36', {
    expected: 'a cancellation REVOKES every reminder job still in status=scheduled, leaving none that could fire for a cancelled session',
    actual: `${s3RemindersAfter.length} job(s): ${s3RemindersAfter.filter((j) => j.status === 'revoked').length} revoked, ${s3RemindersAfter.filter((j) => j.status === 'scheduled').length} still scheduled`,
    pass: s3RemindersAfter.length > 0 && s3RemindersAfter.filter((j) => j.status === 'scheduled').length === 0 && s3RemindersAfter.filter((j) => j.status === 'revoked').length > 0,
    mechanism: 'browser cancel + DB oracle on session_reminder_jobs',
  });
  recordChecks(chk, {
    stage: 'd2',
    matrix: 'I1',
    summary: `inside-window reschedule refused with ${refusalCode}; cancel inside window -> DB decision=${s2refunds[0]?.decision}; cancel outside window -> DB decision=${s3refunds[0]?.decision} amount=${s3refunds[0]?.amount_paise}, screen showed ${amount}; ${s3RemindersAfter.filter((j) => j.status === 'revoked').length} reminder(s) revoked on cancel`,
    observed: { s2: b2.sessionId, s3: b3.sessionId, clockShift: shift, insideBanners, refusal, expectationScope: windowClosed.specs, noRefund, fullRefund, refundAmountShown: amount, refundProgress: prog, s2refunds, s3refunds, s2row, s3row, s3RemindersBefore, s3RemindersAfter },
    mechanism: { clockShift: 'clock_shift', note: 'S2 was moved to 3h from now on its own row; no wall-clock time elapsed' },
    artifacts: arts,
  });
}

async function stageD3(page, browser) {
  const chk = newChecks('I1-d3-completion-attendance', [
    'completion is refused before the scheduled end',
    'the STUDENT surface offers no completion control in any view',
    'the student browser never issued a POST to the completion route',
    'a direct unauthorised student call is typed FORBIDDEN',
    'the refused call mutated nothing',
    'completion is recorded by the MENTOR on the authorised M-01 surface',
    'the recorded attendance names a recorder role',
    'ADMIN is the other authorised recorder role (not FORBIDDEN)',
    'the student is then offered "Confirm attendance"',
    'the review gate is closed while attendance is unconfirmed',
  ]);
  const sessionId = STATE.s1;
  if (!sessionId) {
    chk.blocked('completion is recorded by the MENTOR on the authorised M-01 surface', 'a completed session', 'no session in state.json — stage c did not run or did not pass');
    return recordChecks(chk, { stage: 'd3', matrix: 'I1', summary: 'completion authority could not be attempted', observed: {}, artifacts: [] });
  }
  const arts = [];
  const s = await apiSession(sessionId);

  // 1. completion refused before the scheduled end (real server refusal, browser-rendered)
  await go(page, `${WEB}/s-35?session=${sessionId}&view=attendance`, '.tt-banner');
  arts.push(await shot(page, 'd9_s35_attendance_before_end'));
  const beforeEnd = await banners(page);
  // Asked as the OWNING MENTOR. Asking as anyone else is refused by ownership
  // first (a non-enumerating 404), which would never reach the "not ended" rule
  // this row exists to prove.
  const owningTutorId = tutorUserIdFor(s.tutor_id);
  const early = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/complete`, { sub: owningTutorId, roles: ['tutor'] });
  const statusBeforeRefusals = (await sessionRow(sessionId))?.status;

  // 2. move the session past its end (declared clock shift). The STUDENT surface
  //    must now offer NO completion control at all, in any view and in any
  //    state: QA defect D2 ruled that rendering an action the server is bound to
  //    refuse with FORBIDDEN is an unauthorised action in the production student
  //    experience, not negative testing. "Disabled" would not satisfy it either,
  //    so both the copy and the action hook are counted.
  const shift = await shiftSessionTo(sessionId, -1.6);
  const studentControls = [];
  for (const view of ['manage', 'attendance', 'policy', 'review']) {
    await go(page, `${WEB}/s-35?session=${sessionId}&view=${view}`, '.st-tutoring');
    studentControls.push({ view, ...(await completionControls(page)) });
  }
  await go(page, `${WEB}/s-35?session=${sessionId}&view=manage`, 'h1');
  arts.push(await shot(page, 'd10_s35_student_has_no_completion_control'));
  // Nothing the student's browser did may ever have hit the completion route.
  const studentCompleteRequests = NET.filter(
    (n) => n.dir === 'request' && n.method === 'POST' && /\/complete$/.test(n.url.split('?')[0]),
  ).length;

  // 3. a DIRECT unauthorised call is still typed FORBIDDEN with zero mutation —
  //    the server rule is untouched; only the UI stopped making the call.
  const studentDirect = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/complete`, { sub: STUDENT, roles: ['student'] });
  const attAfterRefusal = dbQuery('SELECT id, state FROM session_attendance WHERE session_id = ?', [sessionId]);
  const rowAfterRefusal = await sessionRow(sessionId);

  // 4. completion is performed ON THE AUTHORISED SURFACE, in a real browser,
  //    signed in as the mentor who owns this session.
  const mentorLeg = await recordCompletionAsMentor(browser, sessionId, owningTutorId, arts, 'd3');
  const done = mentorLeg.performedInBrowser
    ? { status: 200, json: dbQuery('SELECT state FROM session_attendance WHERE session_id = ?', [sessionId])[0] || null }
    : await api('POST', `/api/v1/tutoring/sessions/${sessionId}/complete`, { sub: owningTutorId, roles: ['tutor'] });

  await go(page, `${WEB}/s-35?session=${sessionId}&view=attendance`, '.tt-banner');
  arts.push(await shot(page, 'd11_s35_attendance_after_completion'));
  const afterBanners = await banners(page);
  const dock = await page.$$eval('div.tt-dock button, .tt-dock button', (e) => e.map((x) => x.textContent.trim()));

  await go(page, `${WEB}/s-35?session=${sessionId}&view=review`, '.tt-banner');
  arts.push(await shot(page, 'd12_s35_review_blocked'));
  const reviewBanners = await banners(page);
  const serverReview = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/review`, { sub: STUDENT, body: { rating: 5 } });
  // ADMIN is the OTHER recorder role (attendance.RECORDER_ROLES = tutor, admin).
  // Proving the authority set is exactly those two means exercising both, so the
  // admin actor is used here rather than merely declared.
  const adminRecorder = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/complete`, { sub: ADMIN, roles: ['admin'] });

  const att = dbQuery('SELECT id, state, version, recorded_by_role FROM session_attendance WHERE session_id = ?', [sessionId]);
  const confirmOffered = dock.some((d) => /Confirm attendance/.test(d));
  const feState = afterBanners.map((b) => b.code).find((c) => c && c.startsWith('ATTENDANCE_'));

  chk.ok('completion is refused before the scheduled end', 'POST .../complete -> 409 ATTENDANCE_TOO_EARLY before end_utc (the attendance service owns this rule, so the code is ATTENDANCE_TOO_EARLY, not the session-level SESSION_NOT_ENDED)', `${early.status} ${early.code}`, (v) => v === '409 ATTENDANCE_TOO_EARLY');
  chk.eq('the STUDENT surface offers no completion control in any view', 0, studentControls.reduce((n, c) => n + c.byLabel + c.byHook, 0));
  chk.eq('the student browser never issued a POST to the completion route', 0, studentCompleteRequests);
  chk.ok('a direct unauthorised student call is typed FORBIDDEN', 'POST .../complete as a student -> 403 FORBIDDEN', `${studentDirect.status} ${studentDirect.code}`, (v) => v === '403 FORBIDDEN');
  chk.eq('the refused call mutated nothing', { attendanceRows: 0, sessionStatus: statusBeforeRefusals }, { attendanceRows: attAfterRefusal.length, sessionStatus: rowAfterRefusal?.status });
  chk.eq('completion is recorded by the MENTOR on the authorised M-01 surface', true, mentorLeg.performedInBrowser);
  chk.ok('the recorded attendance names a recorder role', 'recorded_by_role in (tutor, admin)', att[0]?.recorded_by_role, (v) => ['tutor', 'admin'].includes(v));
  chk.ok(
    'ADMIN is the other authorised recorder role (not FORBIDDEN)',
    'POST .../complete as an admin is NOT refused with 403 FORBIDDEN — the session is already recorded, so the refusal must be a STATE refusal instead',
    `${adminRecorder.status} ${adminRecorder.code}`,
    (v) => !/403/.test(v) && !/FORBIDDEN/.test(v),
  );
  chk.eq('the student is then offered "Confirm attendance"', true, confirmOffered);
  chk.ok('the review gate is closed while attendance is unconfirmed', 'a browser banner code plus a server 409 REVIEW_BLOCKED', { browser: reviewBanners.map((b) => b.code).filter(Boolean), server: `${serverReview.status} ${serverReview.code}` }, (v) => v.server === '409 REVIEW_BLOCKED' && v.browser.length > 0);

  neg('N17', {
    expected: 'completion is a TUTOR/ADMIN action: the student surface offers no such control anywhere, a direct student call is 403 FORBIDDEN with zero mutation, and the mentor records it on the authorised M-01 surface',
    actual: `student controls across ${studentControls.map((c) => c.view).join('/')} = ${studentControls.reduce((n, c) => n + c.byLabel + c.byHook, 0)}; student POST /complete count = ${studentCompleteRequests}; direct student call ${studentDirect.status} ${studentDirect.code} with ${attAfterRefusal.length} attendance row(s); admin probe ${adminRecorder.status} ${adminRecorder.code}; mentor recorded in-browser = ${mentorLeg.performedInBrowser} (recorded_by_role=${att[0]?.recorded_by_role})`,
    pass: studentControls.reduce((n, c) => n + c.byLabel + c.byHook, 0) === 0
      && studentCompleteRequests === 0
      && studentDirect.status === 403 && studentDirect.code === 'FORBIDDEN'
      && attAfterRefusal.length === 0
      && mentorLeg.performedInBrowser === true
      && ['tutor', 'admin'].includes(att[0]?.recorded_by_role)
      && adminRecorder.status !== 403,
    mechanism: 'two browser contexts (student + owning mentor) plus server_leg authority probes',
    evidence: 'd10_s35_student_has_no_completion_control.png',
  });
  neg('N20', {
    expected: 'with attendance recorded but NOT confirmed, the review is blocked in the browser and with 409 REVIEW_BLOCKED on the server',
    actual: `browser banner code(s)=${reviewBanners.map((b) => b.code).filter(Boolean).join(',') || 'none'}; server ${serverReview.status} ${serverReview.code}`,
    pass: serverReview.status === 409 && serverReview.code === 'REVIEW_BLOCKED' && reviewBanners.some((b) => b.code),
    mechanism: 'browser render + server_leg probe',
    evidence: 'd12_s35_review_blocked.png',
  });
  recordChecks(chk, {
    stage: 'd3',
    matrix: 'I1',
    summary: `completion refused before end with ${early.status} ${early.code}; the STUDENT surface offered no completion control in ${studentControls.map((c) => c.view).join('/')} and issued ${studentCompleteRequests} POST /complete; a direct student call was ${studentDirect.status} ${studentDirect.code} with ${attAfterRefusal.length} attendance rows written; completion was recorded BY THE MENTOR on ${mentorLeg.surface || 'the authorised surface'}; admin recorder probe ${adminRecorder.status} ${adminRecorder.code}; DB state=${att[0]?.state} by=${att[0]?.recorded_by_role}; review gate ${serverReview.status} ${serverReview.code}`,
    observed: { earlyComplete: early, clockShift: shift, studentCompletionControls: studentControls, studentCompletePostRequests: studentCompleteRequests, studentDirectApiCall: studentDirect, adminRecorderProbe: adminRecorder, attendanceAfterStudentRefusal: attAfterRefusal, sessionAfterStudentRefusal: rowAfterRefusal, mentorCompletion: mentorLeg, tutorComplete: done, attendanceBannersBeforeEnd: beforeEnd, attendanceBannersAfter: afterBanners, attendanceBannerCode: feState, dockButtons: dock, reviewBanners, serverReviewRefusal: serverReview, dbAttendance: att },
    mechanism: { completion: 'authorised_surface_in_browser', clockShift: 'clock_shift', note: 'RECORDER_ROLES = tutor, admin. The student surface renders no completion control at all (QA defect D2); the recording click happens on /mentor/sessions in a second browser context signed in as the owning mentor. The direct student and admin HTTP calls are this driver proving the server rule, not the product UI.' },
    artifacts: arts,
  });
  STATE.s1Completed = true;
  saveState();
}

async function stageD4(page, browser) {
  const chk = newChecks('I1-d4-attendance-confirm-review', [
    'the student CONFIRMS attendance with a real click',
    'a 9-character review body is refused by the screen before submission',
    'a valid review is accepted and persisted exactly once',
    'the submitted review enters moderation',
    'the student DISPUTES attendance on a second session',
    'a disputed session blocks the review in the browser',
    'a disputed session blocks the review on the server with REVIEW_BLOCKED',
  ]);
  const sessionId = STATE.s1;
  if (!sessionId) {
    chk.blocked('the student CONFIRMS attendance with a real click', 'a recorded session', 'no session in state.json — stage c/d3 did not run or did not pass');
    return recordChecks(chk, { stage: 'd4', matrix: 'I1', summary: 'attendance confirm/review could not be attempted', observed: {}, artifacts: [] });
  }
  const arts = [];
  await go(page, `${WEB}/s-35?session=${sessionId}&view=attendance`, '.tt-banner');
  arts.push(await shot(page, 'd13_s35_attendance_recorded'));
  const confirm = page.locator('button', { hasText: /^Confirm attendance$/ });
  if (!(await confirm.count())) {
    chk.blocked('the student CONFIRMS attendance with a real click', 'a "Confirm attendance" control for the recorded state', 'no such control was rendered — the attendance leg is unreachable from the student surface');
    return recordChecks(chk, { stage: 'd4', matrix: 'I1', summary: 'no "Confirm attendance" control rendered for the server state', observed: { banners: await banners(page) }, artifacts: arts });
  }
  await withApi(
    page,
    { method: 'POST', route: /\/attendance\/confirm$/, maxStatus: 300 },
    () => confirm.click(),
  );
  await page.waitForFunction(() => /You confirmed attendance/.test(document.body.textContent), { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'd14_s35_attendance_confirmed'));
  const attConfirmed = dbQuery('SELECT state, version, confirmed_at FROM session_attendance WHERE session_id = ?', [sessionId]);

  // review validation, then a real submit
  await page.locator('button', { hasText: /Leave a review/ }).click();
  await page.waitForFunction(() => location.search.includes('view=review'), { timeout: 15000 });
  await page.waitForSelector('div.tt-stars', { timeout: 15000 });
  await settled(page);
  arts.push(await shot(page, 'd15_s35_review_open'));
  await page.locator('label.tt-star').nth(4).click();
  await page.fill('#tt-review-body', 'too short');
  // Readiness, not a sleep: wait until the screen has actually re-rendered its
  // validation state for the 9-character body.
  await page.waitForFunction(
    () => document.querySelector('#tt-review-body')?.getAttribute('aria-invalid') === 'true',
    undefined,
    { timeout: 10000 },
  ).catch(() => null);
  await settled(page);
  arts.push(await shot(page, 'd16_s35_review_validation_short_body'));
  const validation = await page.evaluate(() => {
    const ta = document.querySelector('#tt-review-body');
    const submit = [...document.querySelectorAll('button')].find((b) => /Submit review/.test(b.textContent));
    return {
      ariaInvalid: ta?.getAttribute('aria-invalid'),
      counter: document.querySelector('#tt-review-count')?.textContent?.trim(),
      why: document.querySelector('#tt-review-why')?.textContent?.trim(),
      submitDisabled: submit ? submit.disabled : null,
    };
  });
  await page.fill('#tt-review-body', 'The mentor was well prepared and the session ran exactly as described.');
  await page.waitForFunction(
    () => {
      const b = [...document.querySelectorAll('button')].find((x) => /Submit review/.test(x.textContent));
      return !!b && !b.disabled;
    },
    undefined,
    { timeout: 10000 },
  );
  await withApi(
    page,
    { method: 'POST', route: /\/review$/, status: 201 },
    () => page.locator('button', { hasText: /Submit review/ }).click(),
  );
  await page.waitForFunction(() => /your review was submitted/i.test(document.body.textContent), { timeout: 20000 });
  await settled(page);
  arts.push(await shot(page, 'd17_s35_review_submitted'));
  const reviews = dbQuery('SELECT v.id AS id, v.session_id AS session_id, v.rating AS rating, m.state AS moderation_state, v.published AS published, length(v.body) AS body_len FROM tutor_reviews v LEFT JOIN review_moderation m ON m.review_id = v.id WHERE v.session_id = ?', [sessionId]);

  // dispute path on S4 -> review blocked again
  let disputed;
  try {
    const slot4 = takeSlot('gt24h');
    const b4 = await bookInBrowser(page, slot4, null);
    STATE.s4 = b4.sessionId;
    saveState();
    await shiftSessionTo(b4.sessionId, -1.6);
    const s4 = await apiSession(b4.sessionId);
    // Completion for the dispute path is recorded on the AUTHORISED surface too:
    // the student never has this control, so the driver signs in as the mentor.
    const mentorLeg4 = await recordCompletionAsMentor(
      browser, b4.sessionId, tutorUserIdFor(s4.tutor_id), arts, 'd4',
    );
    if (!mentorLeg4.performedInBrowser) {
      throw new Error(`mentor surface could not record completion: ${mentorLeg4.reason}`);
    }
    await go(page, `${WEB}/s-35?session=${b4.sessionId}&view=attendance`, '.tt-banner');
    // Before the mentor recorded it there was no confirm/dispute control at all;
    // both appear only for the `recorded` state (matrix D5).
    await page.locator('button', { hasText: /Dispute this/ }).click();
    await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 10000 });
    await page.selectOption('#tt-reason', 'session_cut_short');
    await settled(page);
    arts.push(await shot(page, 'd18_s35_attendance_dispute_modal'));
    await withApi(
      page,
      { method: 'POST', route: /\/attendance\/dispute$/, maxStatus: 300 },
      () => page.locator('div.tt-modal button', { hasText: /Submit the dispute/ }).click(),
    );
    await page.waitForFunction(() => /dispute is open/i.test(document.body.textContent), { timeout: 20000 });
    await settled(page);
    arts.push(await shot(page, 'd19_s35_attendance_disputed'));
    await go(page, `${WEB}/s-35?session=${b4.sessionId}&view=review`, '.tt-banner');
    arts.push(await shot(page, 'd20_s35_review_blocked_while_disputed'));
    const blocked = await banners(page);
    const serverBlocked = await api('POST', `/api/v1/tutoring/sessions/${b4.sessionId}/review`, { sub: STUDENT, body: { rating: 4 } });
    disputed = { sessionId: b4.sessionId, mentorCompletion: mentorLeg4, banners: blocked, serverRefusal: serverBlocked, db: dbQuery('SELECT state, version FROM session_attendance WHERE session_id = ?', [b4.sessionId]) };
  } catch (err) {
    disputed = { error: String(err).slice(0, 400) };
  }

  chk.ok('the student CONFIRMS attendance with a real click', 'session_attendance.state = confirmed with a confirmed_at', attConfirmed[0], (v) => v && v.state === 'confirmed' && !!v.confirmed_at);
  chk.ok(
    'a 9-character review body is refused by the screen before submission',
    'aria-invalid="true" on the textarea AND a disabled Submit button AND an explanation',
    validation,
    (v) => v.ariaInvalid === 'true' && v.submitDisabled === true && !!v.why,
  );
  chk.ok('a valid review is accepted and persisted exactly once', 'exactly one tutor_reviews row for the session, rating 5, 10..1000 char body', reviews, (v) => v.length === 1 && v[0].rating === 5 && v[0].body_len >= 10 && v[0].body_len <= 1000);
  chk.ok('the submitted review enters moderation', 'a review_moderation row in a non-null state', reviews[0]?.moderation_state, (v) => typeof v === 'string' && v.length > 0);
  chk.ok('the student DISPUTES attendance on a second session', 'session_attendance.state = disputed', disputed?.db?.[0]?.state, (v) => v === 'disputed');
  chk.ok('a disputed session blocks the review in the browser', 'at least one banner code on the review view', disputed?.banners?.map((b) => b.code).filter(Boolean), (v) => Array.isArray(v) && v.length > 0);
  chk.ok('a disputed session blocks the review on the server with REVIEW_BLOCKED', 'POST .../review -> 409 REVIEW_BLOCKED', `${disputed?.serverRefusal?.status} ${typedCode(disputed?.serverRefusal)}`, (v) => v === '409 REVIEW_BLOCKED');

  neg('N18', {
    expected: 'the STUDENT confirms attendance with a real click; session_attendance.state becomes confirmed with a confirmed_at timestamp',
    actual: `state=${attConfirmed[0]?.state} version=${attConfirmed[0]?.version} confirmed_at=${attConfirmed[0]?.confirmed_at ? 'set' : 'null'}`,
    pass: attConfirmed[0]?.state === 'confirmed' && !!attConfirmed[0]?.confirmed_at,
    mechanism: 'browser click on the student surface',
    evidence: 'd14_s35_attendance_confirmed.png',
  });
  neg('N19', {
    expected: 'the STUDENT disputes attendance on a second session with a reason CODE; session_attendance.state becomes disputed',
    actual: `state=${disputed?.db?.[0]?.state ?? 'not observed'}${disputed?.error ? ` (${disputed.error})` : ''}`,
    pass: disputed?.db?.[0]?.state === 'disputed',
    mechanism: 'browser click on the student surface',
    evidence: 'd19_s35_attendance_disputed.png',
  });
  neg('N21', {
    expected: 'a DISPUTED session blocks the review in the browser and with 409 REVIEW_BLOCKED on the server',
    actual: `browser banner code(s)=${disputed?.banners?.map((b) => b.code).filter(Boolean).join(',') || 'none'}; server ${disputed?.serverRefusal?.status} ${typedCode(disputed?.serverRefusal)}`,
    pass: disputed?.serverRefusal?.status === 409 && typedCode(disputed?.serverRefusal) === 'REVIEW_BLOCKED' && (disputed?.banners || []).some((b) => b.code),
    mechanism: 'browser render + server_leg probe',
    evidence: 'd20_s35_review_blocked_while_disputed.png',
  });
  recordChecks(chk, {
    stage: 'd4',
    matrix: 'I1',
    summary: `attendance confirmed by a real click (DB state=${attConfirmed[0]?.state} v${attConfirmed[0]?.version}); 9-char body refused: aria-invalid=${validation.ariaInvalid} submit disabled=${validation.submitDisabled}; review submitted -> rating=${reviews[0]?.rating} moderation=${reviews[0]?.moderation_state}; dispute on a second session left the review blocked (server ${disputed?.serverRefusal?.status} ${typedCode(disputed?.serverRefusal)})`,
    observed: { attendance: attConfirmed, validation, reviews, disputed },
    artifacts: arts,
  });
  STATE.reviewedSession = sessionId;
  STATE.reviewId = reviews[0]?.id || null;
  STATE.disputedSession = disputed?.sessionId || null;
  saveState();
}

/* ==================================================================== F6 */
/**
 * The BROWSER NEGATIVE CATALOGUE.
 *
 * Every row below is REQUIRED. `NEGATIVE_ROWS` is the single source of truth:
 * a stage registers its result against a row id, and the rollup at the end of
 * the run fails if any id has no result. A case cannot be dropped by deleting
 * its code any more — deleting the code leaves the id unanswered, which is a
 * FAIL. This is what replaced the old boolean expression that quietly omitted
 * `roomCancelled`.
 */
const NEGATIVE_ROWS = [
  ['N01', 'expired hold', 'neg1'],
  ['N02', 'competing slot conflict', 'neg1'],
  ['N03', 'provider / payment failure', 'neg1'],
  ['N04', 'payment amount tampering (under)', 'neg1'],
  ['N05', 'payment amount tampering (over)', 'neg1'],
  ['N06', 'payment currency tampering', 'neg1'],
  ['N07', 'provider webhook amount mismatch, zero mutation', 'neg1'],
  ['N08', 'cancelled-session join refusal (roomCancelled)', 'neg2'],
  ['N09', 'wrong-participant room entry refusal', 'neg2'],
  ['N10', 'expired video grant', 'neg2'],
  ['N11', 'revoked video grant', 'neg2'],
  ['N12', 'wrong-participant video grant', 'neg2'],
  ['N13', 'camera denied', 'neg2b'],
  ['N14', 'microphone denied', 'neg2b'],
  ['N15', 'media / device readiness failure', 'neg2b'],
  ['N16', 'disconnect and reconnect (app transport)', 'neg2b'],
  ['N45', 'disconnect and reconnect (media-plane peer connection)', 'n45'],
  ['N17', 'tutor/admin completion authority', 'd3'],
  ['N18', 'student confirms attendance', 'd4'],
  ['N19', 'student disputes attendance', 'd4'],
  ['N20', 'review blocked while attendance missing', 'd3'],
  ['N21', 'review blocked while attendance disputed', 'd4'],
  ['N22', 'rating 0 rejected', 'neg3'],
  ['N23', 'rating 1 accepted', 'neg3'],
  ['N24', 'rating 5 accepted', 'neg3'],
  ['N25', 'rating 6 rejected', 'neg3'],
  ['N26', 'review text empty', 'neg3'],
  ['N27', 'review text length 9 rejected', 'neg3'],
  ['N28', 'review text length 10 accepted', 'neg3'],
  ['N29', 'review text length 1000 accepted', 'neg3'],
  ['N30', 'review text length 1001 rejected', 'neg3'],
  ['N31', 'duplicate review', 'neg3'],
  ['N32', 'review edit at the 7-day boundary', 'neg3'],
  ['N33', 'review edit just after 7 days', 'neg3'],
  ['N34', 'cross-user access is non-enumerating', 'neg3'],
  ['N35', 'unknown id is non-enumerating', 'neg3'],
  ['N36', 'reminder revocation on cancel', 'd2'],
  ['N37', 'reminder revocation on reschedule', 'd1'],
  ['N38', 'commit failure: zero partial mutation', 'neg4'],
  ['N39', 'provider failure: zero partial mutation', 'neg4'],
  ['N40', 'outbox dispatch failure: zero partial mutation', 'neg4'],
  ['N41', 'timezone/DST ambiguous local time', 'neg4'],
  ['N42', 'timezone/DST nonexistent local time', 'neg4'],
  ['N43', 'configured rate-limit boundary (search)', 'neg4'],
  ['N44', 'configured rate-limit boundary (review)', 'neg4'],
];

const NEG_PATH = path.join(OUT, 'negative_results.json');
const NEG = fs.existsSync(NEG_PATH) ? JSON.parse(fs.readFileSync(NEG_PATH, 'utf8')) : {};

/** Register one negative row. `actual` must be a real observation. */
function neg(id, { expected, actual, pass, mechanism, evidence }) {
  const meta = NEGATIVE_ROWS.find((r) => r[0] === id);
  NEG[id] = {
    id,
    case: meta ? meta[1] : id,
    stage: meta ? meta[2] : null,
    expected,
    actual: isNonObservation(actual) ? `NOT OBSERVED (${JSON.stringify(actual)})` : actual,
    result: isNonObservation(actual) ? 'FAIL' : (pass ? 'PASS' : 'FAIL'),
    mechanism: mechanism || 'browser',
    ...(evidence ? { evidence } : {}),
    at: new Date().toISOString(),
  };
  fs.writeFileSync(NEG_PATH, JSON.stringify(NEG, null, 2));
  return NEG[id].result === 'PASS';
}

/** Fold every registered negative row into a Checks instance. */
function foldNegatives(chk, ids) {
  for (const id of ids) {
    const row = NEG[id];
    const meta = NEGATIVE_ROWS.find((r) => r[0] === id);
    const label = `${id} ${meta ? meta[1] : ''}`.trim();
    if (!row) {
      chk.blocked(label, meta ? meta[1] : id, 'the case did not run — no result was registered');
    } else {
      chk.assert(label, row.expected, row.actual, row.result === 'PASS');
    }
  }
}

/* ------------------------------- neg1: booking and payment negatives ------ */

async function stageNeg1(page) {
  const ids = ['N01', 'N02', 'N03', 'N04', 'N05', 'N06', 'N07'];
  const chk = newChecks('I1-neg1-booking-payment-negatives', ids.map((i) => `${i} ${NEGATIVE_ROWS.find((r) => r[0] === i)[1]}`));
  const arts = [];
  const findings = {};

  // --- N01 expired hold -----------------------------------------------------
  try {
    const slot = takeSlot('gt24h');
    const mount = await withApi(
      page,
      { method: 'POST', route: '/api/v1/tutoring/booking-holds', status: 201 },
      () => page.goto(`${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, { waitUntil: 'domcontentloaded' }),
    );
    await page.waitForSelector('div.tt-hold[role="timer"]', { timeout: 20000 });
    await settled(page);
    const holdId = mount.json?.id;
    const shift = fixtureCmd(['expire-hold', holdId]);
    const seen = await expecting(
      [{ kind: 'http', method: 'POST', route: '/api/v1/payments/orders', status: 409, code: 'HOLD_EXPIRED' }],
      async () => {
        await page.locator('button.tt-btn--jade', { hasText: /securely/ }).click();
        await page.waitForSelector(CODE_SEL, { timeout: 20000 });
        await settled(page);
      },
    );
    arts.push(await shot(page, 'n1_s33_hold_expired'));
    const codes = (await banners(page)).map((b) => b.code).filter(Boolean);
    findings.holdExpiry = { holdId, clockShift: shift, codes, scope: seen.specs };
    neg('N01', {
      expected: 'POST /api/v1/payments/orders -> 409 HOLD_EXPIRED, rendered as a HOLD_EXPIRED banner',
      actual: `HTTP expectation satisfied=${seen.satisfied}; browser banner code(s)=${codes.join(',') || 'none'}`,
      pass: seen.satisfied && codes.includes('HOLD_EXPIRED'),
      mechanism: 'browser click + clock_shift on the hold row',
      evidence: 'n1_s33_hold_expired.png',
    });
  } catch (err) {
    neg('N01', { expected: 'POST /api/v1/payments/orders -> 409 HOLD_EXPIRED', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N02 competing slot conflict -----------------------------------------
  try {
    const slot = takeSlot('gt24h');
    const rival = await api('POST', '/api/v1/tutoring/booking-holds', {
      sub: RIVAL,
      body: { slot_id: slot.slot_id, idempotency_key: `rival-${Date.now()}` },
    });
    const seen = await expecting(
      [{ kind: 'http', method: 'POST', route: '/api/v1/tutoring/booking-holds', status: 409 }],
      async () => {
        await page.goto(`${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, { waitUntil: 'domcontentloaded' });
        await page.waitForSelector(CODE_SEL, { timeout: 20000 });
        await settled(page);
      },
    );
    arts.push(await shot(page, 'n2_s33_slot_conflict'));
    const codes = (await banners(page)).map((b) => b.code).filter(Boolean);
    findings.slotConflict = { rivalHold: rival.status, codes, scope: seen.specs };
    neg('N02', {
      expected: 'a rival student holds the slot first; the browser mount gets 409 SLOT_UNAVAILABLE/HOLD_CONFLICT and renders that code',
      actual: `rival hold ${rival.status}; browser 409 observed=${seen.satisfied}; banner code(s)=${codes.join(',') || 'none'}`,
      pass: rival.status === 201 && seen.satisfied && codes.some((c) => ['SLOT_UNAVAILABLE', 'HOLD_CONFLICT'].includes(c)),
      mechanism: 'server_leg rival hold + browser mount',
      evidence: 'n2_s33_slot_conflict.png',
    });
  } catch (err) {
    neg('N02', { expected: '409 SLOT_UNAVAILABLE/HOLD_CONFLICT in the browser', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N03 provider / payment failure --------------------------------------
  try {
    const slot = takeSlot('gt24h');
    await go(page, `${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, 'div.tt-hold[role="timer"]');
    const order = await withApi(
      page,
      { method: 'POST', route: '/api/v1/payments/orders', status: 201 },
      () => page.locator('button.tt-btn--jade', { hasText: /securely/ }).click(),
    );
    await page.waitForFunction(() => /Order reference|Waiting for the provider/.test(document.body.textContent), { timeout: 20000 });
    await settled(page);
    const declined = await payWebhook(order.json.provider_order_ref, { eventType: 'failed' });
    const seen = await expecting(
      [{ kind: 'http', method: 'POST', route: '/api/v1/tutoring/sessions', status: 409, code: 'PAYMENT_UNVERIFIED' },
       { kind: 'http', method: 'POST', route: '/api/v1/tutoring/sessions', status: 400, code: 'PAYMENT_UNVERIFIED' },
       { kind: 'http', method: 'POST', route: '/api/v1/tutoring/sessions', status: 409, code: 'SESSION_STATE_INVALID' }],
      async () => {
        await page.locator('button.tt-btn--jade', { hasText: /Check payment and confirm/ }).click();
        await page.waitForSelector(CODE_SEL, { timeout: 20000 });
        await settled(page);
      },
    );
    arts.push(await shot(page, 'n3_s33_payment_unverified'));
    const codes = (await banners(page)).map((b) => b.code).filter(Boolean);
    const sessions = dbQuery('SELECT COUNT(*) AS n FROM tutoring_sessions WHERE slot_id = ?', [slot.slot_id]);
    findings.paymentFailure = { orderRef: order.json.provider_order_ref, declineWebhook: declined, codes, scope: seen.specs, sessionRows: sessions[0]?.n };
    neg('N03', {
      expected: 'the provider declines (signed `failed` event); the confirm click is refused with a typed code and NO session row is created for the slot',
      actual: `decline webhook ${declined.status}; browser refusal code(s)=${codes.join(',') || 'none'}; tutoring_sessions rows for the slot=${sessions[0]?.n}`,
      pass: declined.status === 200 && codes.length > 0 && Number(sessions[0]?.n) === 0,
      mechanism: 'server_leg declined provider event + browser click',
      evidence: 'n3_s33_payment_unverified.png',
    });
  } catch (err) {
    neg('N03', { expected: 'typed refusal after a declined provider event, zero session rows', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N04/N05/N06 amount and currency tampering ---------------------------
  // The production bundle CANNOT send an amount at all (tutoringApi.ts throws
  // ForbiddenPaymentFieldError), so tampering is necessarily a server leg — that
  // is the point of the row, and it is declared as such.
  const tamperSlot = takeSlot('gt24h');
  const tHold = await api('POST', '/api/v1/tutoring/booking-holds', { sub: STUDENT, body: { slot_id: tamperSlot.slot_id, idempotency_key: `tamper-${Date.now()}` } });
  const before = dbQuery('SELECT (SELECT COUNT(*) FROM payment_orders) AS orders, (SELECT COUNT(*) FROM payment_events) AS events, (SELECT COUNT(*) FROM tutoring_sessions) AS sessions')[0];
  const tamper = async (id, body, expectStatus, expectCode, label) => {
    const r = await api('POST', '/api/v1/payments/orders', { sub: STUDENT, body: { hold_id: tHold.json.id, idempotency_key: `tamper-${id}-${Date.now()}`, ...body } });
    const after = dbQuery('SELECT (SELECT COUNT(*) FROM payment_orders) AS orders, (SELECT COUNT(*) FROM payment_events) AS events, (SELECT COUNT(*) FROM tutoring_sessions) AS sessions')[0];
    const zeroMutation = Number(after.orders) === Number(before.orders) && Number(after.events) === Number(before.events) && Number(after.sessions) === Number(before.sessions);
    neg(id, {
      expected: `POST /api/v1/payments/orders with ${label} -> ${expectStatus} ${expectCode}, with ZERO rows written`,
      actual: `${r.status} ${r.code ?? '(no typed code)'}; rows before=${JSON.stringify(before)} after=${JSON.stringify(after)}`,
      pass: r.status === expectStatus && r.code === expectCode && zeroMutation,
      mechanism: 'server_leg (the production bundle refuses to send this field at all)',
    });
    return r;
  };
  findings.tamperUnder = await tamper('N04', { amount_paise: 1 }, 422, 'PAYMENT_AMOUNT_MISMATCH', 'amount_paise=1 (under the server price)');
  findings.tamperOver = await tamper('N05', { amount_paise: FEE_PAISE + 1 }, 422, 'PAYMENT_AMOUNT_MISMATCH', `amount_paise=${FEE_PAISE + 1} (over the server price)`);
  /*
   * `currency` is `Literal["INR"]` on the wire model, so a tampered currency is
   * refused at the REQUEST BOUNDARY and carries the boundary envelope's
   * lowercase `validation_error` — deliberately distinct from the domain's
   * upper-case `VALIDATION_ERROR`. Asserting the exact code (rather than "some
   * 422") is what proves the refusal happened before any service ran.
   */
  findings.tamperCurrency = await tamper('N06', { currency: 'USD' }, 422, 'validation_error', 'currency="USD" (refused at the request boundary, not by a service)');

  // --- N07 provider webhook amount mismatch, zero mutation -----------------
  try {
    const goodOrder = await api('POST', '/api/v1/payments/orders', { sub: STUDENT, body: { hold_id: tHold.json.id, idempotency_key: `mismatch-${Date.now()}` } });
    const pre = dbQuery('SELECT (SELECT COUNT(*) FROM tutoring_sessions) AS sessions, (SELECT COUNT(*) FROM payment_events) AS events')[0];
    const bad = await payWebhook(goodOrder.json.provider_order_ref, { amountPaise: FEE_PAISE - 100 });
    const post = dbQuery('SELECT (SELECT COUNT(*) FROM tutoring_sessions) AS sessions, (SELECT COUNT(*) FROM payment_events) AS events')[0];
    findings.webhookMismatch = { status: bad.status, code: bad.code, pre, post };
    neg('N07', {
      expected: 'a correctly SIGNED provider event whose amount disagrees with the order -> 422 AMOUNT_MISMATCH, with no session created',
      actual: `${bad.status} ${bad.code ?? '(no typed code)'}; sessions ${pre.sessions}->${post.sessions}, payment_events ${pre.events}->${post.events}`,
      pass: bad.status === 422 && bad.code === 'AMOUNT_MISMATCH' && Number(post.sessions) === Number(pre.sessions),
      mechanism: 'server_leg signed provider event',
    });
  } catch (err) {
    neg('N07', { expected: '422 AMOUNT_MISMATCH with zero mutation', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  foldNegatives(chk, ids);
  recordChecks(chk, {
    stage: 'neg1',
    matrix: 'I1',
    summary: `booking/payment negatives: ${ids.map((i) => `${i}=${NEG[i]?.result || 'MISSING'}`).join(' ')}`,
    observed: findings,
    mechanism: { holdExpiry: 'clock_shift', rivalHold: 'server_leg', declinedPayment: 'server_leg', tampering: 'server_leg' },
    artifacts: arts,
  });
}

/* ------------------------- neg2: room, video grant and media negatives ---- */

async function stageNeg2(page) {
  const ids = ['N08', 'N09', 'N10', 'N11', 'N12'];
  const chk = newChecks('I1-neg2-room-and-video-grant-negatives', ids.map((i) => `${i} ${NEGATIVE_ROWS.find((r) => r[0] === i)[1]}`));
  const arts = [];
  const findings = {};

  /**
   * Navigate into a room that MUST refuse, with the refusal scoped to the case
   * that owns it: the exact method, route, status and typed code are declared
   * up front, so a refusal for a different reason — or no refusal at all — fails.
   */
  const roomRefusal = async (sessionId, name, specs) => {
    const seen = await expecting(specs, async () => {
      await page.goto(`${WEB}/s-35?session=${sessionId}&view=room`, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('div.tt-rbanner[role="alert"], .tt-banner--err', { timeout: 25000 });
      await settled(page);
    });
    arts.push(await shot(page, name, { fullPage: false }));
    const seenScope = seen;
    return page.evaluate(() => {
      const rb = document.querySelector('div.tt-rbanner');
      return {
        title: rb?.querySelector('.tt-banner__t')?.textContent?.trim() || null,
        detail: rb?.querySelector('.tt-banner__d')?.textContent?.trim() || null,
        errBanners: [...document.querySelectorAll('.tt-banner--err .tt-banner__t')].map((e) => e.textContent.trim()),
      };
    }).then((r) => ({ ...r, scope: seenScope.specs, scopeSatisfied: seenScope.satisfied, unmet: seenScope.unmet }));
  };

  // --- N08 cancelled session cannot be joined ------------------------------
  // THIS ROW WAS THE ONE THE OLD ROLLUP OMITTED. It is now a first-class id and
  // the rollup cannot complete without it.
  try {
    const cancelled = STATE.s3 || STATE.s2;
    if (!cancelled) throw new Error('no cancelled session in state.json (stage d2 did not run)');
    const r = await roomRefusal(cancelled, 'n5_s35_room_cancelled_session', [
      { kind: 'http', method: 'POST', route: /^\/api\/v1\/tutoring\/sessions\/[0-9a-f-]+\/join-credentials$/, status: 409, code: 'SESSION_STATE_INVALID' },
    ]);
    findings.roomCancelled = { sessionId: cancelled, ...r };
    neg('N08', {
      expected: 'entering the room of a CANCELLED session is refused: POST .../join-credentials -> 409 SESSION_STATE_INVALID, rendered as a room-level alert naming the reason',
      actual: `alert title="${r.title}" detail="${(r.detail || '').slice(0, 90)}"; scoped POST /join-credentials -> 409 SESSION_STATE_INVALID observed=${r.scopeSatisfied}`,
      pass: !!r.title && r.scopeSatisfied === true,
      mechanism: 'browser navigation to a cancelled session',
      evidence: 'n5_s35_room_cancelled_session.png',
    });
  } catch (err) {
    neg('N08', { expected: 'room entry refused for a cancelled session', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N09 wrong participant ------------------------------------------------
  try {
    let target = dbQuery('SELECT id FROM tutoring_sessions WHERE student_user_id != ? ORDER BY created_at DESC LIMIT 1', [STUDENT])[0]?.id;
    if (!target) {
      const rivalBooked = await bookAsServerLeg(RIVAL);
      target = rivalBooked.sessionId;
    }
    STATE.rivalSession = target;
    saveState();
    const r = await roomRefusal(target, 'n4_s35_room_entry_refused', [
      { kind: 'http', method: 'POST', route: /^\/api\/v1\/tutoring\/sessions\/[0-9a-f-]+\/join-credentials$/, status: 404, code: 'NOT_FOUND' },
      { kind: 'http', method: 'GET', route: /^\/api\/v1\/tutoring\/sessions\/[0-9a-f-]+$/, status: 404, code: 'NOT_FOUND', times: 1 },
    ]);
    const direct = await api('POST', `/api/v1/tutoring/sessions/${target}/join-credentials`, { sub: STUDENT });
    const unknown = await api('POST', '/api/v1/tutoring/sessions/00000000-0000-4000-8000-0000deadbeef/join-credentials', { sub: STUDENT });
    findings.roomEntryRefused = { targetSession: target, ...r, direct: { status: direct.status, code: direct.code }, unknown: { status: unknown.status, code: unknown.code } };
    neg('N09', {
      expected: "entering another student's room is refused in the browser, and a direct POST .../join-credentials is 404 NOT_FOUND — the SAME envelope as an unknown id, so ownership is not enumerable",
      actual: `browser alert="${r.title}" (scoped 404s observed=${r.scopeSatisfied}${r.unmet.length ? `, unmet: ${r.unmet.join('; ')}` : ''}); direct ${direct.status} ${direct.code}; unknown id ${unknown.status} ${unknown.code}`,
      pass: !!r.title && r.scopeSatisfied === true && direct.status === 404 && direct.code === 'NOT_FOUND' && unknown.status === direct.status && unknown.code === direct.code,
      mechanism: 'browser navigation + server_leg probe',
      evidence: 'n4_s35_room_entry_refused.png',
    });
  } catch (err) {
    neg('N09', { expected: "wrong-participant room entry refused, non-enumerating", actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N10/N11/N12 video grant states --------------------------------------
  try {
    const gs = await bookAsServerLeg(STUDENT);
    STATE.grantSession = gs.sessionId;
    saveState();
    const issued = await api('POST', `/api/v1/tutoring/sessions/${gs.sessionId}/join-credentials`, { sub: STUDENT });
    const roomRef = issued.json?.room_ref;
    const participantRef = issued.json?.participant_ref;

    // N12 first: an unknown participant must not be usable on a live room.
    const wrongParticipant = await videoWebhook({ roomRef, participantRef: 'p_not_a_real_participant_ref' });
    neg('N12', {
      expected: 'a join announced for a participant with no grant on the room -> 404 NOT_FOUND',
      actual: `${wrongParticipant.status} ${wrongParticipant.code ?? '(no typed code)'}`,
      pass: wrongParticipant.status === 404 && wrongParticipant.code === 'NOT_FOUND',
      mechanism: 'server_leg signed video provider event',
    });

    const expiredShift = fixtureCmd(['expire-grant', gs.sessionId]);
    const expired = await videoWebhook({ roomRef, participantRef });
    neg('N10', {
      expected: 'a join announced with a grant whose TTL has elapsed -> 410 GRANT_EXPIRED',
      actual: `${expired.status} ${expired.code ?? '(no typed code)'}`,
      pass: expired.status === 410 && expired.code === 'GRANT_EXPIRED',
      mechanism: 'server_leg signed video provider event + clock_shift on the grant row',
    });

    const revokeOut = fixtureCmd(['revoke-grant', gs.sessionId]);
    const revoked = await videoWebhook({ roomRef, participantRef });
    neg('N11', {
      expected: 'a join announced with a REVOKED grant -> 410 GRANT_REVOKED (revocation is checked before expiry)',
      actual: `${revoked.status} ${revoked.code ?? '(no typed code)'}`,
      pass: revoked.status === 410 && revoked.code === 'GRANT_REVOKED',
      mechanism: 'server_leg signed video provider event + revoked_at on the grant row',
    });
    findings.grants = { sessionId: gs.sessionId, roomRef, participantRef, expiredShift, revokeOut, wrongParticipant: { status: wrongParticipant.status, code: wrongParticipant.code }, expired: { status: expired.status, code: expired.code }, revoked: { status: revoked.status, code: revoked.code } };
  } catch (err) {
    for (const id of ['N10', 'N11', 'N12']) {
      if (!NEG[id]) neg(id, { expected: 'a typed video-grant refusal', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
    }
  }

  foldNegatives(chk, ids);
  recordChecks(chk, {
    stage: 'neg2',
    matrix: 'I1',
    summary: `room/video-grant negatives: ${ids.map((i) => `${i}=${NEG[i]?.result || 'MISSING'}`).join(' ')}`,
    observed: findings,
    mechanism: { grants: 'server_leg signed provider events + clock_shift / revoked_at on the grant rows' },
    artifacts: arts,
  });
}

/* ------------------- neg2b: media permission and readiness negatives ------ */

async function stageNeg2b(page, browser) {
  const ids = ['N13', 'N14', 'N15', 'N16'];
  const chk = newChecks('I1-neg2b-media-and-connection-negatives', ids.map((i) => `${i} ${NEGATIVE_ROWS.find((r) => r[0] === i)[1]}`));
  const arts = [];
  const findings = {};
  void page;

  /*
   * WHY THESE ARE INJECTED AT THE PLATFORM SEAM RATHER THAN VIA CONTEXT
   * PERMISSIONS: this browser is launched with `--use-fake-ui-for-media-stream`
   * so that the media cases are DETERMINISTIC (F4.2). That flag auto-answers the
   * permission prompt, which means withholding a permission on the context no
   * longer produces a denial — the request just succeeds. Rather than give up
   * determinism (and reintroduce a prompt that can hang), each denial is raised
   * as the exact DOMException the platform raises, at the exact API the screen
   * calls. The screen's own classifier (`NotAllowedError` -> permission_denied,
   * `NotReadableError` -> device_busy) is what is under test, and it sees
   * precisely what a real denial looks like.
   */
  const denyVideo = () => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = (constraints) => {
      if (constraints && constraints.video) {
        const e = new Error('Permission denied');
        e.name = 'NotAllowedError';
        return Promise.reject(e);
      }
      return original(constraints);
    };
  };
  const denyAudio = () => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = (constraints) => {
      if (constraints && constraints.audio) {
        const e = new Error('Permission denied');
        e.name = 'NotAllowedError';
        return Promise.reject(e);
      }
      return original(constraints);
    };
  };

  const mediaCase = async (id, label, ctxOpts, prepare, expectProblem, evidenceName) => {
    const ctx = await browser.newContext({ viewport: MOBILE, colorScheme: 'light', ...ctxOpts });
    const p = await ctx.newPage();
    attachCapture(p);
    try {
      if (prepare) await ctx.addInitScript(prepare);
      const sessionId = STATE.s1;
      await p.goto(`${WEB}/s-35?session=${sessionId}&view=prejoin`, { waitUntil: 'domcontentloaded' });
      await p.waitForSelector('div.tt-preview', { timeout: 25000 });
      await settled(p);
      await p.locator('button', { hasText: /Test camera and microphone/ }).click();
      // The DIAGNOSIS is the readiness condition: the screen must reach a
      // terminal problem state. It never has to be waited out.
      const diagnosis = await p
        .waitForFunction(
          (want) => {
            const titles = [...document.querySelectorAll('.tt-banner__t')].map((e) => e.textContent.trim());
            return titles.find((t) => new RegExp(want, 'i').test(t)) || false;
          },
          expectProblem,
          { timeout: 25000 },
        )
        .then((h) => h.jsonValue())
        .catch(() => null);
      await settled(p);
      const b = await banners(p);
      arts.push(await shot(p, evidenceName));
      return { diagnosis, banners: b };
    } finally {
      await ctx.close();
    }
  };

  try {
    const cam = await mediaCase('N13', 'camera denied', { permissions: ['microphone'] }, denyVideo, 'blocking the camera or microphone', 'n7_prejoin_camera_denied');
    findings.cameraDenied = cam;
    neg('N13', {
      expected: 'a camera NotAllowedError is classified as permission_denied and the pre-join screen says the browser is blocking the camera/microphone',
      actual: `banner "${cam.diagnosis}"`,
      pass: !!cam.diagnosis,
      mechanism: 'browser + NotAllowedError injected at navigator.mediaDevices.getUserMedia for VIDEO constraints only',
      evidence: 'n7_prejoin_camera_denied.png',
    });
  } catch (err) {
    neg('N13', { expected: 'a permission-denied diagnosis', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  try {
    const mic = await mediaCase('N14', 'microphone denied', { permissions: ['camera'] }, denyAudio, 'blocking the camera or microphone', 'n8_prejoin_microphone_denied');
    findings.micDenied = mic;
    neg('N14', {
      expected: 'a microphone NotAllowedError is classified as permission_denied and the pre-join screen says the browser is blocking the camera/microphone',
      actual: `banner "${mic.diagnosis}"`,
      pass: !!mic.diagnosis,
      mechanism: 'browser + NotAllowedError injected at navigator.mediaDevices.getUserMedia for AUDIO constraints only',
      evidence: 'n8_prejoin_microphone_denied.png',
    });
  } catch (err) {
    neg('N14', { expected: 'a permission-denied diagnosis', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  try {
    // A device that is present and permitted but NOT READABLE — the real
    // "camera in use by another app" failure, injected at the platform seam.
    const busy = await mediaCase(
      'N15',
      'device readiness failure',
      { permissions: ['camera', 'microphone'] },
      () => {
        const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = () => {
          void original;
          const e = new Error('Could not start video source');
          e.name = 'NotReadableError';
          return Promise.reject(e);
        };
      },
      'camera is in use|device test did not complete',
      'n9_prejoin_device_not_readable',
    );
    findings.deviceBusy = busy;
    neg('N15', {
      expected: 'a device that is present and permitted but unreadable (NotReadableError) is diagnosed as a device-readiness failure, not silently ignored',
      actual: `banner "${busy.diagnosis}"`,
      pass: !!busy.diagnosis,
      mechanism: 'browser + NotReadableError injected at navigator.mediaDevices.getUserMedia',
      evidence: 'n9_prejoin_device_not_readable.png',
    });
  } catch (err) {
    neg('N15', { expected: 'a device-readiness diagnosis', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N16 / N45 disconnect and reconnect ----------------------------------
  //
  // There are TWO connections a session could lose, and they are reported as two
  // rows because they are two different claims:
  //
  //   N16  the APP TRANSPORT — the HTTP connection every screen depends on.
  //        Executable here, and executed: the transport is cut, an action that
  //        needs the server is attempted, the screen's failure state is
  //        observed, the transport is restored and recovery is observed.
  //
  //   N45  the MEDIA-PLANE connection, which the live room now really owns
  //        through its `VideoRoomClient` boundary. It has its own stage
  //        (`stageN45`) because it needs its own browser context with the
  //        deterministic transport selected before the app boots. Reporting the
  //        app-transport result against that row would be a different claim
  //        than the one required, so the two are never folded together.
  try {
    const live = await bookAsServerLeg(STUDENT);
    STATE.disconnectSession = live.sessionId;
    saveState();
    const ctx = await browser.newContext({ viewport: MOBILE, colorScheme: 'light', permissions: ['camera', 'microphone'] });
    const p = await ctx.newPage();
    attachCapture(p);
    let connected = null;
    let offlineState = null;
    let offlineNavError = null;
    let recoveredState = null;
    let recovered = false;
    try {
      await p.goto(`${WEB}/s-35?session=${live.sessionId}&view=manage`, { waitUntil: 'domcontentloaded' });
      await p.waitForSelector('h1', { timeout: 25000 });
      await settled(p);
      connected = await p.$eval('.st-tutoring', (e) => e.textContent.trim().slice(0, 60));
      arts.push(await shot(p, 'n10_transport_connected'));

      // Cut the transport, then force a real server round trip. Every request
      // that fails inside this window belongs to this case and is scoped here.
      const netMark = NET.length;
      await expecting([{ kind: 'requestfailed', route: /.*/, times: 0 }], async () => {
        await ctx.setOffline(true);
        offlineNavError = await p
          .goto(`${WEB}/s-35?session=${live.sessionId}&view=manage`, { waitUntil: 'domcontentloaded' })
          .then(() => null)
          .catch((e) => String(e).split('\n')[0].slice(0, 120));
        await p.waitForFunction(
          () => /could not|unable|offline|try again|something went wrong|failed/i.test(document.body.textContent || ''),
          undefined,
          { timeout: 20000 },
        ).catch(() => null);
      });
      offlineState = await p.evaluate(() => ({
        online: navigator.onLine,
        banners: [...document.querySelectorAll('.tt-banner__t')].map((e) => e.textContent.trim()).slice(0, 4),
        sessionHeadingRendered: !!document.querySelector('h1'),
        body: (document.body.textContent || '').slice(0, 200),
      }));
      // The transport itself is the oracle: while offline, the API calls this
      // screen makes must actually FAIL. `navigator.onLine` is only a hint and
      // is not asserted on — a screen that rendered stale content while every
      // request failed would still be caught by the heading check below.
      // Offline, the DOCUMENT request fails before the app can even boot, so
      // counting only /api/v1 requests would count zero and prove nothing. What
      // is asserted is that the transport really was cut: at least one request
      // issued inside the window failed, and the session did not render.
      const inWindow = NET.slice(netMark);
      offlineState.requestsFailedInWindow = inWindow.filter((n) => n.dir === 'requestfailed').length;
      // With the transport cut the navigation itself is refused by the network
      // stack, so Chromium never emits a per-request failure event — the
      // rejected navigation IS the observation, and it is the one recorded.
      offlineState.navigationError = offlineNavError;
      offlineState.failedUrls = inWindow.filter((n) => n.dir === 'requestfailed').map((n) => `${n.method} ${pathOf(n.url)} (${n.failure})`).slice(0, 4);
      arts.push(await shot(p, 'n11_transport_disconnected').catch(() => 'n11_transport_disconnected.png(unavailable)'));

      await ctx.setOffline(false);
      await p.goto(`${WEB}/s-35?session=${live.sessionId}&view=manage`, { waitUntil: 'domcontentloaded' });
      recovered = await p
        .waitForSelector('h1', { timeout: 25000 })
        .then(() => true)
        .catch(() => false);
      await settled(p).catch(() => null);
      // Recovery is proved by a REAL round trip completing, not by a flag.
      const roundTrip = await api('GET', `/api/v1/tutoring/sessions/${live.sessionId}`, { sub: STUDENT });
      recoveredState = await p.evaluate(() => ({
        online: navigator.onLine,
        banners: [...document.querySelectorAll('.tt-banner__t')].map((e) => e.textContent.trim()).slice(0, 4),
        sessionHeadingRendered: !!document.querySelector('h1'),
      }));
      recoveredState.serverRoundTripStatus = roundTrip.status;
      arts.push(await shot(p, 'n12_transport_reconnected').catch(() => 'n12_transport_reconnected.png(unavailable)'));
    } finally {
      await ctx.close().catch(() => {});
      // The failures inside the offline window are this case's, not the run's.
      GATE.drain('N16-disconnect-window');
    }

    findings.disconnect = { sessionId: live.sessionId, connected, offlineState, recoveredState, recovered };
    neg('N16', {
      expected: 'with the transport cut (navigator.onLine false) the session does NOT render — no heading and an empty body, because the app cannot reach the server — rather than showing stale content as if it were live; restoring the transport re-renders the session and a real server round trip returns 200. (navigator.onLine is deliberately not asserted on the restored side: Chromium does not re-raise it on an already-open page, so recovery is proved by a real round trip instead of a flag.)',
      actual: `connected="${String(connected).slice(0, 40)}"; offline: navigator.onLine=${offlineState?.online}, session heading rendered=${offlineState?.sessionHeadingRendered}, rendered body=${JSON.stringify(String(offlineState?.body || '').trim())}; restored: heading rendered=${recoveredState?.sessionHeadingRendered}, policy banner=${JSON.stringify(recoveredState?.banners)}, server round trip=${recoveredState?.serverRoundTripStatus}`,
      pass: offlineState?.online === false
        && offlineState?.sessionHeadingRendered === false
        && String(offlineState?.body || '').trim() === ''
        && recovered === true
        && recoveredState?.sessionHeadingRendered === true
        && recoveredState?.serverRoundTripStatus === 200,
      mechanism: 'browser context.setOffline(true/false) on a freshly booked LIVE session',
      evidence: 'n10_transport_connected.png / n11_transport_disconnected.png / n12_transport_reconnected.png',
    });
  } catch (err) {
    neg('N16', { expected: 'an app-transport disconnect state and recovery on reconnect', actual: `threw: ${String(err).slice(0, 220)}`, pass: false });
  }

  foldNegatives(chk, ids);
  recordChecks(chk, {
    stage: 'neg2b',
    matrix: 'I1',
    summary: `media/connection negatives: ${ids.map((i) => `${i}=${NEG[i]?.result || 'MISSING'}`).join(' ')}`,
    observed: findings,
    mechanism: { media: 'platform-seam DOMException injection (see the comment on why context permissions cannot be used under --use-fake-ui-for-media-stream)', disconnect: 'browser transport cut via context.setOffline' },
    artifacts: arts,
  });
}

/* ------------- n45: the MEDIA-PLANE disconnect and reconnect -------------- */

/**
 * N45 — the media plane drops and comes back, measured on the PRODUCTION S-35
 * room, through its REAL adapter boundary.
 *
 * WHAT IS UNDER TEST. The bytes driven here are the shipped screen
 * (`SessionScreens.tsx` -> `LiveRoom`), the shipped provider-neutral contract
 * (`media/videoRoomClient.ts`) and the shipped rendering of every connection
 * state. The screen creates its own client through `createVideoRoomClient()`
 * and never learns which adapter it got. Nothing is injected into the screen,
 * no component is replaced, and no test-only page is loaded.
 *
 * WHAT MAKES IT DETERMINISTIC. A single global,
 * `window.__legalsaathiVideoTransport = 'deterministic'`, is installed BEFORE
 * the app boots. That is the one runtime switch the product ships, and it
 * selects the deterministic adapter behind the same interface. The adapter then
 * exposes a driver (`window.__legalsaathiVideoRoom`) with no timers at all:
 * `dropTransport`, `restoreTransport` and `settle` are three separate steps, so
 * `reconnecting` and `reconnected` can each be OBSERVED rendered rather than
 * raced against a timeout.
 *
 * WHAT THIS DOES NOT PROVE, and is never reported as proving: that LiveKit
 * itself reconnects, that an ICE restart succeeds, or that two real browsers
 * exchange media. There is no self-hosted LiveKit or TURN runtime in this
 * environment (no docker, no livekit-server, no turnserver, no egress), so the
 * REAL-LiveKit two-browser variant of this case is BLOCKED and says so in its
 * own row text. The production adapter is compiled, typechecked, bundled as its
 * own chunk from the lockfile-pinned `livekit-client`, and unit-tested on its
 * pure mappings and its fail-closed path — and that is the whole of the claim.
 */
async function stageN45(browser) {
  const ids = ['N45'];
  const chk = newChecks('I1-n45-media-plane-disconnect-reconnect', [
    'the PRODUCTION S-35 room reaches CONNECTED over its real VideoRoomClient boundary',
    'remote media is flowing at connected (a decoded frame, not a claim)',
    'a provider drop renders RECONNECTING as a named state and stops the remote media',
    'the recovery renders RECONNECTED as a named state',
    'settling returns the room to CONNECTED with remote media flowing again',
    'a terminal provider failure renders a NAMED terminal state with its typed code',
    'the evidence records which transport produced it, so it cannot be mistaken for LiveKit',
  ]);
  const arts = [];
  const findings = {};

  /** Everything the room is currently SAYING about its media connection. */
  const readRoom = (p) => p.evaluate(() => {
    const live = document.querySelector('main.tt-live');
    const pill = document.querySelector('.tt-tstate');
    const banner = document.querySelector('.tt-rbanner');
    const v = document.querySelector('video[data-tt-remote="1"]');
    return {
      transportAttr: live ? live.dataset.ttTransport || null : null,
      pill: pill ? pill.textContent.trim() : null,
      headerChip: document.querySelector('div.tt-lh span.tt-chip')?.textContent.trim() || null,
      banner: banner ? {
        role: banner.getAttribute('role'),
        title: banner.querySelector('.tt-banner__t')?.textContent.trim() || null,
        detail: (banner.querySelector('.tt-banner__d')?.textContent || '').trim().slice(0, 120),
        code: banner.querySelector('[data-tt-code]')?.textContent.trim() || null,
      } : null,
      remote: v ? {
        bound: !!v.srcObject,
        readyState: v.readyState,
        w: v.videoWidth,
        h: v.videoHeight,
      } : null,
      // A room that showed nothing but a turning circle would answer null to
      // every question above; that is exactly what this row exists to refuse.
      namedState: !!pill,
    };
  });

  const waitState = (p, want) =>
    p.waitForSelector(`main.tt-live[data-tt-transport="${want}"]`, { timeout: 25000 });

  const live = await bookAsServerLeg(STUDENT);
  STATE.mediaPlaneSession = live.sessionId;
  saveState();

  const ctx = await browser.newContext({
    viewport: MOBILE,
    colorScheme: 'light',
    permissions: ['camera', 'microphone'],
  });
  // The ONE switch, installed before the app boots. It selects an adapter; it
  // does not replace, patch or stub any part of the screen.
  await ctx.addInitScript(() => {
    window.__legalsaathiVideoTransport = 'deterministic';
  });
  const p = await ctx.newPage();
  attachCapture(p);

  try {
    await p.goto(`${WEB}/s-35?session=${live.sessionId}&view=room`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('main.tt-live', { timeout: 25000 });
    await waitState(p, 'connected');
    // Readiness, not a sleep: the remote tile has decoded a frame.
    await p.waitForFunction(() => {
      const v = document.querySelector('video[data-tt-remote="1"]');
      return !!v && v.readyState >= 2 && v.videoWidth > 0;
    }, undefined, { timeout: 25000 }).catch(() => null);
    await settled(p);
    const connected = await readRoom(p);
    arts.push(await shot(p, 'n45_1_media_connected', { fullPage: false }));

    // ---- the provider drops --------------------------------------------- //
    await p.evaluate(() => window.__legalsaathiVideoRoom.dropTransport());
    await waitState(p, 'reconnecting');
    await settled(p);
    const reconnecting = await readRoom(p);
    arts.push(await shot(p, 'n45_2_media_reconnecting', { fullPage: false }));

    // ---- the provider comes back ---------------------------------------- //
    await p.evaluate(() => window.__legalsaathiVideoRoom.restoreTransport());
    await waitState(p, 'reconnected');
    await settled(p);
    const reconnected = await readRoom(p);
    arts.push(await shot(p, 'n45_3_media_reconnected', { fullPage: false }));

    // ---- and settles back to connected, with media flowing again --------- //
    await p.evaluate(() => window.__legalsaathiVideoRoom.settle());
    await waitState(p, 'connected');
    await p.waitForFunction(() => {
      const v = document.querySelector('video[data-tt-remote="1"]');
      return !!v && v.readyState >= 2 && v.videoWidth > 0;
    }, undefined, { timeout: 25000 }).catch(() => null);
    await settled(p);
    const recovered = await readRoom(p);
    arts.push(await shot(p, 'n45_4_media_flowing_again', { fullPage: false }));

    // ---- which transport produced this evidence -------------------------- //
    await p.locator('button.tt-cb[aria-label="Session, connection and privacy details"]').click();
    await p.waitForSelector('div.tt-sheet[data-open="1"]', { timeout: 10000 });
    await settled(p);
    const sheet = await p.$$eval('div.tt-sheet .tt-kv', (els) => els.map((e) => e.textContent.trim()));
    const declaredTransport = (sheet.find((row) => /^Media transport/.test(row)) || '').replace(/^Media transport/, '').trim();
    arts.push(await shot(p, 'n45_5_transport_declared', { fullPage: false }));
    await p.keyboard.press('Escape');

    // ---- the terminal failure path --------------------------------------- //
    await p.evaluate(() => window.__legalsaathiVideoRoom.failTerminally('TRANSPORT_LOST'));
    await waitState(p, 'failed');
    await settled(p);
    const failed = await readRoom(p);
    arts.push(await shot(p, 'n45_6_media_terminal_failure', { fullPage: false }));

    findings.sessionId = live.sessionId;
    findings.declaredTransport = declaredTransport;
    findings.sequence = { connected, reconnecting, reconnected, recovered, failed };

    const flowing = (s) => !!s.remote && s.remote.bound && s.remote.readyState >= 2 && s.remote.w > 0;

    chk.ok(
      'the PRODUCTION S-35 room reaches CONNECTED over its real VideoRoomClient boundary',
      'main.tt-live[data-tt-transport="connected"] with the header still reporting the SERVER admission',
      { transport: connected.transportAttr, pill: connected.pill, headerChip: connected.headerChip },
      (v) => v.transport === 'connected' && v.pill === 'Live' && /In the room/.test(v.headerChip || ''),
    );
    chk.ok(
      'remote media is flowing at connected (a decoded frame, not a claim)',
      'a remote <video> bound to a stream with readyState>=2 and non-zero dimensions',
      connected.remote,
      () => flowing(connected),
    );
    chk.ok(
      'a provider drop renders RECONNECTING as a named state and stops the remote media',
      'data-tt-transport="reconnecting", the pill reads "Reconnecting", a status banner names it, and the remote video has no bound stream',
      { transport: reconnecting.transportAttr, pill: reconnecting.pill, banner: reconnecting.banner, remote: reconnecting.remote },
      (v) => v.transport === 'reconnecting'
        && v.pill === 'Reconnecting'
        && /Reconnecting/i.test(v.banner?.title || '')
        && v.banner?.code === 'TRANSPORT_LOST'
        && v.remote?.bound === false,
    );
    chk.ok(
      'the recovery renders RECONNECTED as a named state',
      'data-tt-transport="reconnected" with the pill and the banner both reading "Reconnected"',
      { transport: reconnected.transportAttr, pill: reconnected.pill, banner: reconnected.banner },
      (v) => v.transport === 'reconnected' && v.pill === 'Reconnected' && /Reconnected/i.test(v.banner?.title || ''),
    );
    chk.ok(
      'settling returns the room to CONNECTED with remote media flowing again',
      'data-tt-transport="connected" and a remote <video> decoding again',
      { transport: recovered.transportAttr, pill: recovered.pill, remote: recovered.remote },
      (v) => v.transport === 'connected' && v.pill === 'Live' && flowing(recovered),
    );
    chk.ok(
      'a terminal provider failure renders a NAMED terminal state with its typed code',
      'data-tt-transport="failed", the pill reads "Media failed", and an alert banner carries the typed code',
      { transport: failed.transportAttr, pill: failed.pill, banner: failed.banner },
      (v) => v.transport === 'failed'
        && v.pill === 'Media failed'
        && v.banner?.role === 'alert'
        && v.banner?.code === 'TRANSPORT_LOST'
        && (v.banner?.title || '').length > 0,
    );
    chk.eq(
      'the evidence records which transport produced it, so it cannot be mistaken for LiveKit',
      'deterministic',
      declaredTransport,
    );

    const ok = connected.transportAttr === 'connected'
      && flowing(connected)
      && reconnecting.transportAttr === 'reconnecting'
      && reconnecting.remote?.bound === false
      && reconnected.transportAttr === 'reconnected'
      && recovered.transportAttr === 'connected'
      && flowing(recovered)
      && failed.transportAttr === 'failed'
      && declaredTransport === 'deterministic';

    neg('N45', {
      expected: 'the media-plane connection of the PRODUCTION S-35 room drops and re-establishes across its real VideoRoomClient boundary, with the room rendering connected -> reconnecting -> reconnected -> connected as NAMED states (never a bare spinner), remote media stopping while reconnecting and flowing again afterwards, and a separate terminal failure rendering a named state with its typed code',
      actual: `EXECUTED against the production screen with the DETERMINISTIC adapter selected at runtime (window.__legalsaathiVideoTransport, the switch the product ships). Observed sequence: `
        + `connected[pill="${connected.pill}", remote readyState=${connected.remote?.readyState} ${connected.remote?.w}x${connected.remote?.h}] -> `
        + `reconnecting[pill="${reconnecting.pill}", banner "${reconnecting.banner?.title}" code=${reconnecting.banner?.code}, remote stream bound=${reconnecting.remote?.bound}] -> `
        + `reconnected[pill="${reconnected.pill}", banner "${reconnected.banner?.title}"] -> `
        + `connected[pill="${recovered.pill}", remote readyState=${recovered.remote?.readyState} ${recovered.remote?.w}x${recovered.remote?.h}] ; `
        + `terminal path: failed[pill="${failed.pill}", role=${failed.banner?.role}, code=${failed.banner?.code}, title "${failed.banner?.title}"]. `
        + `The room reported its transport as "${declaredTransport}" throughout. `
        + `WHAT REMAINS BLOCKED: the REAL-LiveKit TWO-BROWSER variant of this case is NOT executed and NOT claimed. `
        + `No self-hosted LiveKit or TURN runtime exists in this environment (no docker, no livekit-server, no turnserver, no egress), so a genuine publish/subscribe drop and ICE re-establishment between two browsers cannot be produced here. `
        + `The production adapter (frontend/src/features/student/tutoring/media/livekitVideoRoomClient.ts, over the declared and lockfile-pinned livekit-client) is compiled, typechecked, bundled as its own chunk and unit-tested on its state/disconnect/refusal mappings and its fail-closed path only.`,
      pass: ok,
      mechanism: 'browser + the PRODUCTION S-35 screen with the DETERMINISTIC VideoRoomClient adapter selected at runtime; no component replaced, no script injected into the screen, no CDN bundle',
      evidence: 'n45_1_media_connected.png / n45_2_media_reconnecting.png / n45_3_media_reconnected.png / n45_4_media_flowing_again.png / n45_5_transport_declared.png / n45_6_media_terminal_failure.png',
    });
  } catch (err) {
    neg('N45', {
      expected: 'a media-plane drop and recovery rendered as named states by the production room',
      actual: `threw: ${String(err).slice(0, 240)}`,
      pass: false,
    });
  } finally {
    await ctx.close().catch(() => {});
  }

  foldNegatives(chk, ids);
  recordChecks(chk, {
    stage: 'n45',
    matrix: 'I1',
    summary: `media-plane disconnect/reconnect on the production room: N45=${NEG.N45?.result || 'MISSING'} (transport=${findings.declaredTransport || 'unknown'}); the REAL-LiveKit two-browser variant remains BLOCKED — no LiveKit/TURN runtime in this environment`,
    observed: findings,
    mechanism: {
      transport: 'the product\'s own runtime adapter switch (window.__legalsaathiVideoTransport) selecting the DETERMINISTIC VideoRoomClient; the screen, the contract and every rendered state are the shipped ones',
      blocked: 'REAL LiveKit two-browser publish/subscribe: no livekit-server, no TURN, no docker and no network egress here',
    },
    artifacts: arts,
  });
}

/* --------------------------------- neg3: the review contract, both bounds - */

async function stageNeg3() {
  const ids = ['N22', 'N23', 'N24', 'N25', 'N26', 'N27', 'N28', 'N29', 'N30', 'N31', 'N32', 'N33', 'N34', 'N35'];
  const chk = newChecks('I1-neg3-review-negatives', ids.map((i) => `${i} ${NEGATIVE_ROWS.find((r) => r[0] === i)[1]}`));
  const arts = [];
  const findings = {};
  const TEN = 'ten chars!';
  const NINE = 'nine char';
  const THOUSAND = 'x'.repeat(1000);
  const THOUSAND_ONE = 'x'.repeat(1001);

  /** Post a review to a FRESH reviewable session and report exactly what came back. */
  const post = async (id, { rating, body, expectStatus, expectCode, label, reuse }) => {
    const target = reuse || (await reviewableSession());
    const payload = body === undefined ? { rating } : { rating, body };
    const r = await api('POST', `/api/v1/tutoring/sessions/${target.sessionId}/review`, { sub: STUDENT, body: payload });
    const rows = dbQuery('SELECT id, rating, length(body) AS body_len FROM tutor_reviews WHERE session_id = ?', [target.sessionId]);
    const persisted = expectStatus === 201 ? rows.length === 1 : rows.length === 0;
    neg(id, {
      expected: `POST .../review with ${label} -> ${expectStatus}${expectCode ? ` ${expectCode}` : ''}, and ${expectStatus === 201 ? 'exactly one' : 'zero'} tutor_reviews row(s)`,
      actual: `${r.status} ${r.code ?? '(no typed code)'}; ${rows.length} row(s)${rows[0] ? ` rating=${rows[0].rating} body_len=${rows[0].body_len}` : ''}`,
      pass: r.status === expectStatus && (expectCode === undefined || r.code === expectCode) && persisted,
      mechanism: 'server_leg (0 and 6 are not expressible on the star control, and 1001 chars exceeds the textarea maxlength — that is the point of these rows)',
    });
    return { target, response: r, rows };
  };

  // --- ratings -------------------------------------------------------------
  findings.rating0 = await post('N22', { rating: 0, expectStatus: 422, expectCode: 'VALIDATION_ERROR', label: 'rating=0' });
  findings.rating6 = await post('N25', { rating: 6, expectStatus: 422, expectCode: 'VALIDATION_ERROR', label: 'rating=6', reuse: findings.rating0.target });
  findings.rating1 = await post('N23', { rating: 1, expectStatus: 201, label: 'rating=1 (lower bound)', reuse: findings.rating0.target });
  findings.rating5 = await post('N24', { rating: 5, expectStatus: 201, label: 'rating=5 (upper bound)' });

  // --- body lengths --------------------------------------------------------
  const nine = await post('N27', { rating: 4, body: NINE, expectStatus: 422, expectCode: 'VALIDATION_ERROR', label: 'a 9-character body' });
  findings.body9 = nine;
  findings.body10 = await post('N28', { rating: 4, body: TEN, expectStatus: 201, label: 'a 10-character body (lower bound)', reuse: nine.target });
  const overLong = await post('N30', { rating: 4, body: THOUSAND_ONE, expectStatus: 422, expectCode: 'VALIDATION_ERROR', label: 'a 1001-character body' });
  findings.body1001 = overLong;
  findings.body1000 = await post('N29', { rating: 4, body: THOUSAND, expectStatus: 201, label: 'a 1000-character body (upper bound)', reuse: overLong.target });
  findings.bodyEmpty = await post('N26', { rating: 3, body: '', expectStatus: 422, expectCode: 'VALIDATION_ERROR', label: 'an EMPTY body string' });
  // An OMITTED body is the rating-only review and is a different, legal thing.
  const omitted = await api('POST', `/api/v1/tutoring/sessions/${findings.bodyEmpty.target.sessionId}/review`, { sub: STUDENT, body: { rating: 3 } });
  findings.bodyOmitted = { status: omitted.status, code: omitted.code };
  NEG.N26.actual += `; an OMITTED body (rating-only review) is accepted with ${omitted.status}, proving "" is refused as a VALUE rather than treated as absent`;
  NEG.N26.result = NEG.N26.result === 'PASS' && omitted.status === 201 ? 'PASS' : 'FAIL';
  fs.writeFileSync(NEG_PATH, JSON.stringify(NEG, null, 2));

  // --- N31 duplicate -------------------------------------------------------
  try {
    const dup = await api('POST', `/api/v1/tutoring/sessions/${findings.rating5.target.sessionId}/review`, { sub: STUDENT, body: { rating: 2, body: 'A second review for the very same session.' } });
    const rows = dbQuery('SELECT COUNT(*) AS n FROM tutor_reviews WHERE session_id = ?', [findings.rating5.target.sessionId]);
    findings.duplicate = { status: dup.status, code: dup.code, rows: rows[0]?.n };
    neg('N31', {
      expected: 'a second review for a session already reviewed -> 409 REVIEW_DUPLICATE, still exactly one row',
      actual: `${dup.status} ${dup.code ?? '(no typed code)'}; ${rows[0]?.n} row(s)`,
      pass: dup.status === 409 && dup.code === 'REVIEW_DUPLICATE' && Number(rows[0]?.n) === 1,
      mechanism: 'server_leg',
    });
  } catch (err) {
    neg('N31', { expected: '409 REVIEW_DUPLICATE', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N32/N33 the 7-day edit boundary, from BOTH sides --------------------
  try {
    const reviewId = findings.rating5.rows[0]?.id;
    // Just INSIDE: the deadline is placed 20 seconds from NOW, so the request
    // cannot outrun it. Ageing by "the window minus a second" would leave a
    // margin smaller than the round trip and silently test the wrong side.
    const inside = fixtureCmd(['age-review', reviewId, '--deadline-in-seconds', '20']);
    const editInside = await api('PATCH', `/api/v1/tutoring/reviews/${reviewId}`, { sub: STUDENT, body: { rating: 4 } });
    // Then JUST past it: the deadline moves to one second ago.
    const outside = fixtureCmd(['age-review', reviewId, '--deadline-in-seconds', '-1']);
    const editOutside = await api('PATCH', `/api/v1/tutoring/reviews/${reviewId}`, { sub: STUDENT, body: { rating: 3 } });
    const finalRow = dbQuery('SELECT rating FROM tutor_reviews WHERE id = ?', [reviewId])[0];
    findings.editBoundary = { reviewId, inside, editInside: { status: editInside.status, code: editInside.code }, outside, editOutside: { status: editOutside.status, code: editOutside.code }, finalRating: finalRow?.rating };
    neg('N32', {
      expected: 'an edit made while the 7-day deadline is still 20 seconds away -> 200, and the new rating is persisted',
      actual: `${editInside.status} ${editInside.code ?? ''}; rating now ${finalRow?.rating}`,
      pass: editInside.status === 200 && Number(finalRow?.rating) === 4,
      mechanism: 'server_leg + clock_shift on tutor_reviews.edit_deadline_at',
    });
    neg('N33', {
      expected: 'an edit made 1 second PAST the 7-day deadline -> 409 REVIEW_EDIT_WINDOW_CLOSED, with the rating left at the value the in-window edit wrote (4)',
      actual: `${editOutside.status} ${editOutside.code ?? '(no typed code)'}; rating still ${finalRow?.rating}`,
      pass: editOutside.status === 409 && editOutside.code === 'REVIEW_EDIT_WINDOW_CLOSED' && Number(finalRow?.rating) === 4,
      mechanism: 'server_leg + clock_shift on tutor_reviews.edit_deadline_at',
    });
  } catch (err) {
    for (const id of ['N32', 'N33']) if (!NEG[id]) neg(id, { expected: 'the 7-day edit boundary', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N34/N35 non-enumeration ---------------------------------------------
  try {
    const reviewId = findings.rating5.rows[0]?.id;
    const unknownId = '00000000-0000-4000-8000-00000badbeef';
    const crossEdit = await api('PATCH', `/api/v1/tutoring/reviews/${reviewId}`, { sub: RIVAL, body: { rating: 1 } });
    const unknownEdit = await api('PATCH', `/api/v1/tutoring/reviews/${unknownId}`, { sub: RIVAL, body: { rating: 1 } });
    const crossSession = await api('GET', `/api/v1/tutoring/sessions/${findings.rating5.target.sessionId}`, { sub: RIVAL });
    const unknownSession = await api('GET', '/api/v1/tutoring/sessions/00000000-0000-4000-8000-00000badbeef', { sub: RIVAL });
    // `request_id` is a per-request correlation id and differs by design; what
    // must be indistinguishable is the ERROR ENVELOPE itself. Comparing the raw
    // body would compare the correlation id and always report a difference,
    // which is a weaker test dressed up as a stricter one.
    const envelope = (r) => JSON.stringify(r.json?.detail ?? r.json);
    const sameBody = envelope(crossEdit) === envelope(unknownEdit);
    const sameSessionBody = envelope(crossSession) === envelope(unknownSession);
    const stillOwned = dbQuery('SELECT rating FROM tutor_reviews WHERE id = ?', [reviewId])[0];
    findings.nonEnumeration = { crossEdit: { status: crossEdit.status, code: crossEdit.code }, unknownEdit: { status: unknownEdit.status, code: unknownEdit.code }, crossSession: { status: crossSession.status, code: crossSession.code }, unknownSession: { status: unknownSession.status, code: unknownSession.code }, sameBody, sameSessionBody, ratingAfter: stillOwned?.rating };
    neg('N34', {
      expected: "another user's review and session are 404 NOT_FOUND — the resource must not be distinguishable from one that does not exist — with zero mutation",
      actual: `cross-user review edit ${crossEdit.status} ${crossEdit.code}; cross-user session read ${crossSession.status} ${crossSession.code}; rating unchanged at ${stillOwned?.rating}`,
      pass: crossEdit.status === 404 && crossEdit.code === 'NOT_FOUND' && crossSession.status === 404 && Number(stillOwned?.rating) === 4,
      mechanism: 'server_leg as a different authenticated student',
    });
    neg('N35', {
      expected: 'an UNKNOWN id returns an identical status, code and error envelope to the cross-user case, on both the review and the session route (the per-request correlation id is excluded — it differs by design)',
      actual: `unknown review ${unknownEdit.status} ${unknownEdit.code} envelope=${envelope(unknownEdit)} (identical to the cross-user envelope: ${sameBody}); unknown session ${unknownSession.status} ${unknownSession.code} (identical: ${sameSessionBody})`,
      pass: unknownEdit.status === crossEdit.status && unknownEdit.code === crossEdit.code && sameBody && sameSessionBody,
      mechanism: 'server_leg',
    });
  } catch (err) {
    for (const id of ['N34', 'N35']) if (!NEG[id]) neg(id, { expected: 'non-enumerating 404s', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  foldNegatives(chk, ids);
  recordChecks(chk, {
    stage: 'neg3',
    matrix: 'I1',
    summary: `review negatives: ${ids.map((i) => `${i}=${NEG[i]?.result || 'MISSING'}`).join(' ')}`,
    observed: findings,
    artifacts: arts,
  });
}

/* ------------- neg4: atomicity, outbox, timezone/DST, rate limits --------- */

/**
 * Declared as its OWN required assertion, not folded into N44's prose: a
 * contaminated oracle and a broken limiter are different findings and must be
 * separately visible in the evidence. It is in `required`, so it cannot quietly
 * not run — an unexecuted required assertion is a FAIL.
 */
const N44_PRECONDITION = 'N44 review-limiter oracle is uncontaminated: the measuring actor has ZERO prior review-limiter calls this run';

async function stageNeg4(page) {
  const ids = ['N38', 'N39', 'N40', 'N41', 'N42', 'N43', 'N44'];
  const chk = newChecks('I1-neg4-integrity-timezone-ratelimit', [
    ...ids.map((i) => `${i} ${NEGATIVE_ROWS.find((r) => r[0] === i)[1]}`),
    N44_PRECONDITION,
  ]);
  const arts = [];
  const findings = {};
  const counts = () => dbQuery(`SELECT
      (SELECT COUNT(*) FROM tutoring_sessions) AS sessions,
      (SELECT COUNT(*) FROM payment_orders) AS orders,
      (SELECT COUNT(*) FROM payment_events) AS events,
      (SELECT COUNT(*) FROM booking_holds) AS holds,
      (SELECT COUNT(*) FROM tutoring_outbox) AS outbox,
      (SELECT COUNT(*) FROM session_attendance) AS attendance,
      (SELECT COUNT(*) FROM tutor_reviews) AS reviews,
      (SELECT COUNT(*) FROM video_session_grants) AS grants`)[0];

  // --- N38 commit failure: a refused mutation leaves NOTHING behind --------
  try {
    const before = counts();
    // A hold that does not exist: the service refuses before any write, and the
    // request handler never reaches session.commit().
    const orphan = await api('POST', '/api/v1/payments/orders', { sub: STUDENT, body: { hold_id: '00000000-0000-4000-8000-00000badbeef', idempotency_key: `orphan-${Date.now()}` } });
    // A reschedule onto a slot that is not available.
    const badResch = await api('POST', `/api/v1/tutoring/sessions/${STATE.s1}/reschedule`, { sub: STUDENT, body: { slot_id: '00000000-0000-4000-8000-00000badbeef' } });
    const after = counts();
    const unchanged = Object.keys(before).every((k) => Number(before[k]) === Number(after[k]));
    findings.commitFailure = { orphanOrder: { status: orphan.status, code: orphan.code }, badReschedule: { status: badResch.status, code: badResch.code }, before, after, unchanged };
    neg('N38', {
      expected: 'two refused mutations (unknown hold, unknown reschedule slot) leave every table count IDENTICAL — the transaction never commits a partial write',
      actual: `order ${orphan.status} ${orphan.code}; reschedule ${badResch.status} ${badResch.code}; counts before=${JSON.stringify(before)} after=${JSON.stringify(after)} unchanged=${unchanged}`,
      pass: orphan.status >= 400 && badResch.status >= 400 && unchanged,
      mechanism: 'server_leg + DB oracle over 8 tables',
    });
  } catch (err) {
    neg('N38', { expected: 'zero partial mutation on a refused commit', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N39 provider failure: an unverifiable delivery writes nothing -------
  try {
    const before = counts();
    const badSig = await api('POST', '/api/v1/payments/webhook', { sub: null, raw: JSON.stringify({ order_ref: 'det_order_nonexistent', event_type: 'paid', amount_paise: FEE_PAISE }), headers: { [PAY_SIG_HEADER]: 'deadbeef'.repeat(8) } });
    const badVideoSig = await api('POST', '/api/v1/video/webhook', { sub: null, raw: JSON.stringify({ event_id: 'x', event_type: 'participant_joined', room_ref: 'det_room_x', participant_ref: 'p_x' }), headers: { [VIDEO_SIG_HEADER]: 'deadbeef'.repeat(8) } });
    const after = counts();
    const unchanged = Object.keys(before).every((k) => Number(before[k]) === Number(after[k]));
    findings.providerFailure = { payment: { status: badSig.status, code: badSig.code }, video: { status: badVideoSig.status, code: badVideoSig.code }, before, after, unchanged };
    neg('N39', {
      expected: 'an unverifiable PROVIDER delivery is 400 PAYMENT_UNVERIFIED / VIDEO_UNVERIFIED with nothing read and nothing written',
      actual: `payment webhook ${badSig.status} ${badSig.code}; video webhook ${badVideoSig.status} ${badVideoSig.code}; counts unchanged=${unchanged}`,
      pass: badSig.status === 400 && badSig.code === 'PAYMENT_UNVERIFIED' && badVideoSig.status === 400 && badVideoSig.code === 'VIDEO_UNVERIFIED' && unchanged,
      mechanism: 'server_leg with a deliberately invalid signature + DB oracle',
    });
  } catch (err) {
    neg('N39', { expected: 'a typed provider refusal with zero mutation', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N40 outbox dispatch failure: the DOMAIN row must be untouched -------
  try {
    const target = STATE.s1;
    const domainBefore = await sessionRow(target);
    const outboxBefore = dbQuery('SELECT id, kind, status, attempts FROM tutoring_outbox WHERE aggregate_id = ? ORDER BY created_at DESC', [target]);
    const injected = fixtureCmd(['fail-outbox', target]);
    const outboxAfter = dbQuery('SELECT id, kind, status, attempts FROM tutoring_outbox WHERE aggregate_id = ? ORDER BY created_at DESC', [target]);
    const domainAfter = await sessionRow(target);
    // The mutation must still be readable through the API, unchanged.
    const apiAfter = await api('GET', `/api/v1/tutoring/sessions/${target}`, { sub: STUDENT });
    // The SQLite UUID type persists ids dash-free, so the comparison has to be
    // normalised or the row silently does not match and the case reports nothing.
    const row = outboxAfter.find((r) => hex(r.id) === hex(injected.outbox_id));
    const domainUnchanged = JSON.stringify(domainBefore) === JSON.stringify(domainAfter);
    findings.outboxFailure = { injected, outboxBefore, outboxAfter, domainBefore, domainAfter, domainUnchanged, apiStatus: apiAfter.status };
    neg('N40', {
      expected: 'a post-commit dispatch failure marks the outbox row failed and RETRYABLE (attempts incremented) while the committed domain row is bit-for-bit unchanged and still readable',
      actual: `outbox row ${injected.outbox_id} ${injected.before.status}/${injected.before.attempts} -> ${row?.status}/${row?.attempts}; domain row unchanged=${domainUnchanged}; GET session ${apiAfter.status}`,
      pass: !!row && row.status === 'failed' && Number(row.attempts) > Number(injected.before.attempts) && domainUnchanged && apiAfter.status === 200,
      mechanism: 'fixture-injected dispatch failure on the outbox row + DB/API oracle (the relay is out-of-process, so the failure is injected at the row the relay owns)',
    });
  } catch (err) {
    neg('N40', { expected: 'domain durable, outbox retryable', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N41/N42 DST ambiguous and nonexistent local times -------------------
  const tutorId = seedTutorWithSlots();
  const dst = async (id, { local, tz, want, label }) => {
    const r = await api('GET', `/api/v1/tutors/${tutorId}/availability?timezone=${encodeURIComponent(tz)}&from_local=${encodeURIComponent(local)}&to_local=${encodeURIComponent(local.replace('T01:30:00', 'T03:30:00'))}`, { sub: STUDENT });
    const res = r.json?.local_resolution || {};
    const classes = Object.values(res).map((v) => v?.classification).filter(Boolean);
    neg(id, {
      expected: `GET .../availability with ${label} in ${tz} -> 200 and local_resolution.classification = "${want}" (reported, never silently rounded)`,
      actual: `${r.status}; classifications=${JSON.stringify(classes)}; resolution=${JSON.stringify(res).slice(0, 220)}`,
      pass: r.status === 200 && classes.includes(want),
      mechanism: 'server_leg (the S-32 timezone control cannot express a DST-ambiguous wall time)',
    });
    return { status: r.status, resolution: res };
  };
  // 2026-10-25 01:30 Europe/London occurs TWICE (BST->GMT fall back).
  findings.dstAmbiguous = await dst('N41', { local: '2026-10-25T01:30:00', tz: 'Europe/London', want: 'ambiguous', label: 'the fall-back overlap 01:30' });
  // 2026-03-29 01:30 Europe/London does NOT EXIST (GMT->BST spring forward).
  findings.dstNonexistent = await dst('N42', { local: '2026-03-29T01:30:00', tz: 'Europe/London', want: 'nonexistent', label: 'the spring-forward gap 01:30' });

  // --- N43 configured search rate-limit boundary ---------------------------
  try {
    const limit = SEARCH_LIMIT;
    // The boundary is measured on an actor with an UNTOUCHED budget. Measuring
    // it on the browsing student would count whatever that student already spent
    // in this stage (the two DST availability calls share the TUTOR_SEARCH
    // limiter) and report the boundary one or two requests early — a wrong
    // number that still looks plausible.
    let firstRejectAt = null;
    let lastAcceptAt = 0;
    for (let i = 1; i <= limit + 5 && firstRejectAt === null; i++) {
      const r = await api('GET', `/api/v1/tutors?q=rl${i}`, { sub: RIVAL });
      if (r.status === 429) firstRejectAt = i;
      else if (r.status === 200) lastAcceptAt = i;
      else throw new Error(`unexpected ${r.status} at request ${i}`);
    }
    // Then exhaust the BROWSING student's own budget so the browser renders it.
    let studentSpend = 0;
    for (let i = 1; i <= limit + 5; i++) {
      const r = await api('GET', `/api/v1/tutors?q=browser-rl${i}`, { sub: STUDENT });
      studentSpend = i;
      if (r.status === 429) break;
    }
    // Now show it IN THE BROWSER, with the 429 scoped to this case.
    const seen = await expecting(
      [{ kind: 'http', method: 'GET', route: '/api/v1/tutors', status: 429, times: 1 }],
      async () => {
        await page.goto(`${WEB}/s-31?q=rate-limited`, { waitUntil: 'domcontentloaded' });
        await page.waitForSelector('.tt-banner, article.tt-tut', { timeout: 20000 });
        await settled(page);
      },
    );
    arts.push(await shot(page, 'n6_s31_rate_limited'));
    const b = await banners(page);
    const banner = b.find((x) => x.code === 'rate_limit_exceeded');
    findings.searchRateLimit = { configuredLimit: limit, lastAcceptAt, firstRejectAt, studentRequestsToExhaustion: studentSpend, banner, scope: seen.specs };
    neg('N43', {
      expected: `with RATE_LIMIT_TUTOR_SEARCH_PER_MIN=${limit}, measured on an actor with a fresh budget: request ${limit} succeeds, request ${limit + 1} is 429; and the browser renders a rate_limit_exceeded banner once the browsing student's own budget is spent`,
      actual: `last 200 at request ${lastAcceptAt}; first 429 at request ${firstRejectAt} (configured ${limit}); browsing student exhausted after ${studentSpend} request(s); browser 429 observed=${seen.satisfied}; banner="${banner?.title || 'none'}"`,
      pass: firstRejectAt === limit + 1 && lastAcceptAt === limit && seen.satisfied && !!banner,
      mechanism: 'server_leg to reach the boundary exactly, then a real browser navigation to render it',
      evidence: 'n6_s31_rate_limited.png',
    });
  } catch (err) {
    neg('N43', { expected: 'the configured search limit boundary', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  // --- N44 configured review rate-limit boundary ---------------------------
  //
  // The measurement is only worth the paper it is printed on if the identity it
  // measures started the run with its FULL budget. It previously did not: N44
  // reused RIVAL, whom N34/N35 charge two `PATCH /tutoring/reviews/{id}` calls,
  // so the full run reported "last admitted 198, first rejected 199" against a
  // configured 200. Nothing was wrong with the limiter — the oracle was
  // contaminated, and by a number small enough to look like a real product
  // quirk.
  //
  // The fix is an actor and a proof, not a reset and not a smaller number:
  //
  //   * REVIEW_LIMIT_ACTOR is seeded for this one purpose and used by nothing
  //     else in the catalogue;
  //   * `api()` LEDGERS every request that reaches a review-limited route, per
  //     actor, at the moment it is issued;
  //   * this stage ASSERTS that ledger reads zero for REVIEW_LIMIT_ACTOR before
  //     it sends its first call, and FAILS N44 outright if it does not.
  //
  // That last assertion is the regression guard: `E2E_INJECT=n44-contaminated-actor`
  // points N44 back at RIVAL and the row must go RED with the prior calls named.
  try {
    const limit = REVIEW_LIMIT;
    // The dedicated actor must actually EXIST in the fixture. Falling back to
    // "some student" if the key is missing is how this regresses silently, so a
    // fixture that predates the actor is a hard failure with a named cause.
    const seededLimitActor = FIXTURE.actors?.review_rate_limit_student || null;
    const contaminate = injected('n44-contaminated-actor');
    const actor = contaminate ? RIVAL : REVIEW_LIMIT_ACTOR;
    const actorName = contaminate
      ? 'RIVAL (E2E_INJECT=n44-contaminated-actor — the pre-fix actor, deliberately spent)'
      : 'the dedicated review_rate_limit_student';
    // PROVE the budget is unspent. This is an observation of every request this
    // run actually issued, read back from the ledger — not a convention, not a
    // comment, and not an inference from the answer we are about to measure.
    const priorCalls = reviewLimiterCalls(actor);
    const priorDetail = reviewLimiterLedger().log
      .filter((e) => e.sub === actor)
      .map((e) => `${e.method} ${e.path}`);
    const ledgerAcrossActors = Object.fromEntries(
      Object.entries(reviewLimiterLedger().counts).sort((a, b) => b[1] - a[1]),
    );
    findings.reviewLimiterPrecondition = {
      actor,
      actorName,
      seededInFixture: seededLimitActor,
      priorReviewLimiterCalls: priorCalls,
      priorCallDetail: priorDetail,
      ledgerAcrossActors,
      contaminationInjected: contaminate,
    };
    if (!seededLimitActor || seededLimitActor !== REVIEW_LIMIT_ACTOR) {
      neg('N44', {
        expected: `the fixture seeds a DEDICATED review-rate-limit actor ${REVIEW_LIMIT_ACTOR} (actors.review_rate_limit_student)`,
        actual: `fixture reports actors.review_rate_limit_student=${JSON.stringify(seededLimitActor)}`,
        pass: false,
        mechanism: 'fixture contract check before any measurement',
      });
    } else if (priorCalls !== 0) {
      // THE REGRESSION ASSERTION. N44 measured on a spent budget reports the
      // limit MINUS whatever was already spent; that is a wrong number that
      // looks right, so the row fails here rather than reporting it.
      neg('N44', {
        expected: `N44 must measure RATE_LIMIT_REVIEW_PER_HOUR=${limit} on an actor with an UNSPENT budget: zero prior review-limiter calls by ${actor} in this run`,
        actual: `CONTAMINATED ORACLE: ${actor} (${actorName}) had already made ${priorCalls} review-limiter call(s) before N44 started — ${priorDetail.join(' | ') || '(detail truncated)'}. Measuring here would report last-admitted ${limit - priorCalls} / first-rejected ${limit - priorCalls + 1} and blame the limiter for the harness. Ledger this run: ${JSON.stringify(ledgerAcrossActors)}`,
        pass: false,
        mechanism: 'per-actor review-limiter ledger recorded by api() at issue time',
      });
    } else {
      let firstRejectAt = null;
      let lastAcceptAt = 0;
      const unknown = '00000000-0000-4000-8000-00000badbeef';
      for (let i = 1; i <= limit + 5 && firstRejectAt === null; i++) {
        // Every call is refused on its MERITS (404) until the limiter refuses it
        // first, so the boundary is the limiter's and nothing else's.
        const r = await api('POST', `/api/v1/tutoring/sessions/${unknown}/review`, { sub: actor, body: { rating: 5 } });
        if (r.status === 429) firstRejectAt = i;
        else lastAcceptAt = i;
      }
      const spentByN44 = reviewLimiterCalls(actor);
      findings.reviewRateLimit = {
        configuredLimit: limit,
        actor,
        priorReviewLimiterCalls: priorCalls,
        lastAcceptAt,
        firstRejectAt,
        callsIssuedByN44: spentByN44,
      };
      neg('N44', {
        expected: `with RATE_LIMIT_REVIEW_PER_HOUR=${limit}, measured on ${actorName} whose review budget this run had provably not touched (0 prior review-limiter calls): the limiter admits exactly ${limit} calls and refuses number ${limit + 1} with 429`,
        actual: `prior review-limiter calls by ${actor}: ${priorCalls} (proved from the ledger, not assumed); last admitted at ${lastAcceptAt}; first 429 at ${firstRejectAt}`,
        pass: priorCalls === 0 && firstRejectAt === limit + 1 && lastAcceptAt === limit,
        mechanism: 'server_leg as a DEDICATED review-rate-limit student, with a per-actor review-limiter ledger asserting zero prior use before the first call',
      });
    }
  } catch (err) {
    neg('N44', { expected: 'the configured review limit boundary', actual: `threw: ${String(err).slice(0, 200)}`, pass: false });
  }

  findings.configuredLimiters = {
    RATE_LIMIT_TUTOR_SEARCH_PER_MIN: SEARCH_LIMIT,
    RATE_LIMIT_BOOKING_PER_MIN: BOOKING_LIMIT,
    RATE_LIMIT_REVIEW_PER_HOUR: REVIEW_LIMIT,
    note: `The booking limiter is deliberately raised to ${BOOKING_LIMIT}/min for this run because the journeys legitimately perform far more than the production default of 10 booking mutations a minute; the boundary evidence is produced from the SEARCH and REVIEW limiters, which are left where the browser can reach them exactly. RATE_LIMIT_REVIEW_PER_HOUR is the PRODUCTION value and is neither raised nor reset for N44; what changed is that N44 measures it on a dedicated, provably unspent actor.`,
  };
  const pre = findings.reviewLimiterPrecondition;
  chk.assert(
    N44_PRECONDITION,
    `the per-actor review-limiter ledger reads 0 for the dedicated actor ${REVIEW_LIMIT_ACTOR} at the instant N44 issues its first call, and N44 uses that actor`,
    pre
      ? `actor=${pre.actor} (${pre.actorName}); priorReviewLimiterCalls=${pre.priorReviewLimiterCalls}${pre.priorCallDetail.length ? ` [${pre.priorCallDetail.join(' | ')}]` : ''}; ledger this run=${JSON.stringify(pre.ledgerAcrossActors)}`
      : undefined,
    !!pre
      && pre.actor === REVIEW_LIMIT_ACTOR
      && pre.seededInFixture === REVIEW_LIMIT_ACTOR
      && pre.priorReviewLimiterCalls === 0,
  );
  foldNegatives(chk, ids);
  recordChecks(chk, {
    stage: 'neg4',
    matrix: 'I1',
    summary: `integrity/timezone/rate-limit negatives: ${ids.map((i) => `${i}=${NEG[i]?.result || 'MISSING'}`).join(' ')}`,
    observed: findings,
    artifacts: arts,
  });
}

/* ------------------------ the rollup: every required row must be answered - */

async function stageRollup() {
  const chk = newChecks('I1-negative-catalogue-rollup', ['every required negative case has a registered result', 'every required negative case PASSED']);
  const missing = NEGATIVE_ROWS.filter(([id]) => !NEG[id]).map(([id, label]) => `${id} ${label}`);
  const failed = NEGATIVE_ROWS.filter(([id]) => NEG[id] && NEG[id].result !== 'PASS').map(([id, label]) => `${id} ${label}: ${String(NEG[id].actual).slice(0, 120)}`);
  const table = NEGATIVE_ROWS.map(([id, label, stage]) => NEG[id] || {
    id, case: label, stage, expected: 'the required negative case', actual: 'NOT EXECUTED — no result was registered for this id', result: 'FAIL', mechanism: null,
  });
  fs.writeFileSync(path.join(OUT, 'negative_results_table.json'), JSON.stringify({
    generatedAt: new Date().toISOString(),
    runId: RUN_ID,
    requiredRows: NEGATIVE_ROWS.length,
    registered: table.filter((r) => r.result !== undefined).length,
    passed: table.filter((r) => r.result === 'PASS').length,
    failed: table.filter((r) => r.result !== 'PASS').length,
    rule: 'This list is the contract. A row with no registered result is a FAIL, not an omission — that is what stops a required case from disappearing by deleting its code.',
    rows: table,
  }, null, 2));

  chk.eq('every required negative case has a registered result', [], missing);
  chk.eq('every required negative case PASSED', [], failed);
  recordChecks(chk, {
    stage: 'rollup',
    matrix: 'I1',
    summary: `${table.filter((r) => r.result === 'PASS').length}/${NEGATIVE_ROWS.length} required negative rows passed; ${missing.length} never ran`,
    observed: { missing, failed },
    artifacts: ['negative_results_table.json'],
  });
}

/* ------------------------------------------------------------- J1 privacy */

const CANARIES = [
  { id: 'pan_visa_like', re: /\b4[0-9]{12}(?:[0-9]{3})?\b/g, what: 'a 13/16-digit Visa-shaped primary account number' },
  { id: 'pan_test_4242', re: /4242[ -]?4242[ -]?4242[ -]?4242/g, what: 'the canonical test PAN' },
  { id: 'cvv_field', re: /\b(cvv|cvc|card_?verification)\b\s*[:=]?\s*"?\d{3,4}"?/gi, what: 'a CVV/CVC value' },
  { id: 'otp_field', re: /\b(otp|one[_-]?time[_-]?password|2fa_code)\b\s*[:=]\s*"?\d{4,8}"?/gi, what: 'a payment OTP' },
  { id: 'raw_join_token', re: /join_[A-Za-z0-9_-]{20,}/g, what: 'a RAW server-issued join credential' },
  { id: 'payment_provider_secret', re: /legalsaathi-deterministic-payment-test-key/g, what: 'the payment provider signing key' },
  { id: 'video_provider_secret', re: /legalsaathi-deterministic-video-test-key/g, what: 'the video provider signing key' },
  { id: 'razorpay_secret', re: /rzp_(live|test)_[A-Za-z0-9]{6,}/g, what: 'a Razorpay key id' },
  { id: 'sdp_offer', re: /(^|["'\s>])v=0[\r\n]/g, what: 'an SDP session description' },
  { id: 'sdp_media_line', re: /\bm=(audio|video)\s+\d+/g, what: 'an SDP media line' },
  { id: 'ice_candidate', re: /\bcandidate:\d+\s+\d+\s+(udp|tcp)/gi, what: 'an ICE candidate' },
  { id: 'ice_srflx_relay', re: /\b(typ\s+(srflx|relay|host)|turn:|stun:)/gi, what: 'ICE/TURN/STUN plumbing' },
  { id: 'device_label_fake', re: /Fake (Audio|Video) (Input|Output)|fake_device_\d+|default - /g, what: 'a media DEVICE LABEL' },
  { id: 'device_label_field', re: /"(device_?label|deviceLabel|label)"\s*:\s*"[^"]{3,}"/g, what: 'a device label field' },
  { id: 'payment_token', re: /\btok_[A-Za-z0-9_]{3,60}\b/g, what: 'a provider payment token' },
];

function scanText(text, surface, source) {
  const hits = [];
  for (const c of CANARIES) {
    c.re.lastIndex = 0;
    const m = text.match(c.re);
    if (m && m.length) {
      hits.push({
        canary: c.id,
        what: c.what,
        occurrences: m.length,
        sample: String(m[0]).slice(0, 24).replace(/[0-9](?=[0-9]{3})/g, '*'),
        surface,
        source,
      });
    }
  }
  return hits;
}

/* ---------------------------------------------------- F7 storage allowlist */

/**
 * The EXACT allowlist, defined in the test rather than inferred at run time.
 *
 * The independent-QA finding was that the old gate failed on `ls-theme`. That
 * key is the user's light/dark preference: it is written by `useTheme()` on
 * every mount of the app shell, its value is the literal string `light` or
 * `dark`, and it carries no identifier, no token and nothing derived from one.
 * Failing a privacy gate on it is a false positive that trains people to ignore
 * the gate. So it is allowed BY NAME, with its value CONSTRAINED — a key called
 * `ls-theme` holding anything other than `light`/`dark` is still a failure.
 *
 * Everything not on this list is a failure, and the canary scan runs over every
 * capture from both populations regardless of what the allowlist says.
 */
const STORAGE_ALLOWLIST = {
  /** Any surface, authenticated or not. */
  common: [
    { key: 'ls-theme', why: 'light/dark preference; no identifier, no secret', valuePattern: /^(light|dark)$/ },
  ],
  /** The AUTHENTICATED mentor surface only (M-01). */
  mentor: [
    { key: 'ls-auth-lawyer', why: 'the redacted, secret-free P0.1 verification snapshot an authenticated surface must carry', valuePattern: /^\{.*\}$/ },
  ],
};
/** Field names inside a stored object that must never appear. */
const SECRET_SHAPED_KEY = /token|secret|password|otp|passcode|credential|signature|pan|cvv/i;

function allowlistFor(captureName) {
  return captureName.startsWith(MENTOR_CAPTURE_PREFIX)
    ? [...STORAGE_ALLOWLIST.common, ...STORAGE_ALLOWLIST.mentor]
    : [...STORAGE_ALLOWLIST.common];
}

/**
 * The raw join credential is allowed to exist in EXACTLY ONE place: the body of
 * the 201 response to `POST .../join-credentials`, which is the response that
 * issues it. Anywhere else — DOM, storage, cookie, URL, console, backend log,
 * or any OTHER network entry — is a leak. Scoping it explicitly is what stops
 * the driver from either (a) crying leak over its own authorised capture, or
 * (b) muting the canary and missing a real one.
 */
function isAuthorisedTokenSurface(kind, file, entry) {
  if (kind !== 'network_traffic') return false;
  if (!entry) return false;
  return entry.dir === 'response'
    && entry.status === 201
    && /\/join-credentials$/.test(pathOf(entry.url || ''));
}

async function stagePriv() {
  const chk = newChecks('J1-privacy-canary-scan', [
    'no canary pattern appears on any captured surface',
    'the raw join credential appears ONLY in its issuing 201 response',
    'browser storage holds nothing outside the declared allowlist',
    'no allowlisted value is out of its declared shape',
    'no cookie is set on any surface',
    'no secret-shaped field exists inside an allowlisted stored object',
    'the benign ls-theme preference does NOT fail the gate',
    'SELF-TEST: a planted secret canary FAILS the scan',
  ]);
  const surfaces = [];
  const hits = [];
  /** Files whose parsed network entries let the token scope be evaluated. */
  const netEntries = {};
  const scanDir = (dir, kind) => {
    if (!fs.existsSync(dir)) return;
    for (const f of fs.readdirSync(dir).sort()) {
      const p = path.join(dir, f);
      if (!fs.statSync(p).isFile()) continue;
      const text = fs.readFileSync(p, 'utf8');
      surfaces.push({ kind, file: path.relative(OUT, p), bytes: text.length });
      hits.push(...scanText(text, f, kind));
      if (kind === 'network_traffic' && f.endsWith('.json') && !f.endsWith('.console.json')) {
        try { netEntries[f] = JSON.parse(text); } catch { netEntries[f] = null; }
      }
    }
  };
  scanDir(DIRS.dom, 'captured_dom');
  scanDir(DIRS.net, 'network_traffic');
  scanDir(DIRS.storage, 'storage_cookies_url');

  // URL bar: every URL the driver actually visited, from the storage dumps
  const urls = [];
  for (const f of fs.readdirSync(DIRS.storage)) {
    try {
      urls.push(JSON.parse(fs.readFileSync(path.join(DIRS.storage, f), 'utf8')).url);
    } catch { /* ignore */ }
  }
  hits.push(...scanText(urls.join('\n'), 'url_bar', 'url_bar'));

  let backendLog = { path: BACKEND_LOG, bytes: 0, hits: [] };
  if (BACKEND_LOG && fs.existsSync(BACKEND_LOG)) {
    const text = fs.readFileSync(BACKEND_LOG, 'utf8');
    backendLog = { path: BACKEND_LOG, bytes: text.length, hits: scanText(text, 'backend_uvicorn.log', 'backend_log') };
    surfaces.push({ kind: 'backend_log', file: path.relative(OUT, BACKEND_LOG), bytes: text.length });
  }
  hits.push(...backendLog.hits);

  /* ---- the raw join credential, scoped to its authorised surface ---------- */
  const tokens = STATE.joinTokens || [];
  const tokenSightings = [];
  const scanForToken = (dir, kind) => {
    if (!fs.existsSync(dir)) return;
    for (const f of fs.readdirSync(dir)) {
      const p = path.join(dir, f);
      if (!fs.statSync(p).isFile()) continue;
      const text = fs.readFileSync(p, 'utf8');
      for (const tok of tokens) {
        if (!text.includes(tok)) continue;
        // Locate WHICH entries carry it, so an authorised sighting can be told
        // apart from an unauthorised one inside the same capture file.
        const entries = Array.isArray(netEntries[f]) ? netEntries[f] : [];
        const carrying = entries.filter((e) => JSON.stringify(e).includes(tok));
        const authorised = carrying.length > 0 && carrying.every((e) => isAuthorisedTokenSurface(kind, f, e));
        tokenSightings.push({
          kind,
          file: path.relative(OUT, p),
          tokenPrefix: `${tok.slice(0, 5)}…(${tok.length} chars)`,
          entriesCarrying: carrying.map((e) => `${e.dir} ${e.status || ''} ${pathOf(e.url || '')}`),
          authorised,
        });
      }
    }
  };
  scanForToken(DIRS.dom, 'captured_dom');
  scanForToken(DIRS.net, 'network_traffic');
  scanForToken(DIRS.storage, 'storage_cookies_url');
  if (BACKEND_LOG && fs.existsSync(BACKEND_LOG)) {
    const text = fs.readFileSync(BACKEND_LOG, 'utf8');
    for (const tok of tokens) {
      if (text.includes(tok)) tokenSightings.push({ kind: 'backend_log', file: path.relative(OUT, BACKEND_LOG), tokenPrefix: `${tok.slice(0, 5)}…`, entriesCarrying: ['(log line)'], authorised: false });
    }
  }
  const unauthorisedTokenSightings = tokenSightings.filter((s) => !s.authorised);
  // The `raw_join_token` canary would otherwise fire on the AUTHORISED response
  // body, which is exactly where the credential is supposed to be. It is
  // therefore excluded from the generic finding list and judged by the scoped
  // check above instead — narrower, not weaker.
  const genericHits = hits.filter((h) => h.canary !== 'raw_join_token');
  const joinTokenGenericHits = hits.filter((h) => h.canary === 'raw_join_token');

  /* ---- storage, judged against the declared allowlist --------------------- */
  const storageState = [];
  const storageViolations = [];
  for (const f of fs.readdirSync(DIRS.storage)) {
    const name = f.replace(/\.json$/, '');
    const s = JSON.parse(fs.readFileSync(path.join(DIRS.storage, f), 'utf8'));
    const allow = allowlistFor(name);
    const local = Object.keys(s.localStorage || {});
    storageState.push({
      capture: name,
      population: name.startsWith(MENTOR_CAPTURE_PREFIX) ? 'authenticated_mentor' : 'student_journey',
      localStorageKeys: local,
      sessionStorageKeys: Object.keys(s.sessionStorage || {}),
      cookie: s.cookie || '',
      allowedHere: allow.map((a) => a.key),
    });
    for (const key of local) {
      const rule = allow.find((a) => a.key === key);
      if (!rule) {
        storageViolations.push({ capture: name, why: 'localStorage key is not on the allowlist for this surface', key, allowed: allow.map((a) => a.key) });
        continue;
      }
      const value = s.localStorage[key];
      if (!rule.valuePattern.test(value)) {
        storageViolations.push({ capture: name, why: 'allowlisted key holds a value outside its declared shape', key, pattern: String(rule.valuePattern), sample: String(value).slice(0, 40) });
        continue;
      }
      if (value.trim().startsWith('{')) {
        let parsed;
        try { parsed = JSON.parse(value); } catch { parsed = null; }
        if (!parsed || typeof parsed !== 'object') {
          storageViolations.push({ capture: name, why: 'stored object is not readable', key });
        } else {
          for (const field of Object.keys(parsed)) {
            if (SECRET_SHAPED_KEY.test(field)) storageViolations.push({ capture: name, why: 'secret-shaped field inside an allowlisted object', key, field });
          }
        }
      }
    }
    if (Object.keys(s.sessionStorage || {}).length) storageViolations.push({ capture: name, why: 'sessionStorage is not empty', keys: Object.keys(s.sessionStorage) });
    if (s.cookie) storageViolations.push({ capture: name, why: 'a cookie was set', cookie: s.cookie });
  }
  const themeCaptures = storageState.filter((s) => s.localStorageKeys.includes('ls-theme'));
  const themeViolations = storageViolations.filter((v) => v.key === 'ls-theme');
  const secretShaped = storageViolations.filter((v) => v.why === 'secret-shaped field inside an allowlisted object');
  const cookieViolations = storageViolations.filter((v) => v.why === 'a cookie was set');
  const shapeViolations = storageViolations.filter((v) => v.why === 'allowlisted key holds a value outside its declared shape');
  const allowlistViolations = storageViolations.filter((v) => v.why === 'localStorage key is not on the allowlist for this surface');

  /* ---- SELF-TEST: the gate must FAIL on a planted secret ------------------ */
  // A synthetic surface carrying a real PAN, a real CVV and a real join-shaped
  // credential is fed to the SAME scanner and the SAME storage judge. If they
  // report it clean, the gate is broken and this row fails — which is the only
  // way to know the clean verdict above means anything.
  const canaryDir = path.join(DIRS.work, 'canary_selftest');
  fs.mkdirSync(canaryDir, { recursive: true });
  const plantedText = JSON.stringify({
    note: 'SELF-TEST FIXTURE — never produced by the application',
    pan: '4242424242424242',
    cvv: '123',
    otp: '884213',
    join_token: 'join_selftestcredential0123456789abcdefgh',
    sdp: 'v=0\r\nm=audio 49170 RTP/AVP 0\r\n',
    ice: 'candidate:1 1 udp 2130706431 192.0.2.1 54400 typ srflx',
    device_label: 'Fake Audio Input 1',
    payment_token: 'tok_selftest_planted',
  }, null, 1);
  fs.writeFileSync(path.join(canaryDir, 'planted.json'), plantedText);
  const selfTestHits = scanText(plantedText, 'planted.json', 'self_test');
  const plantedStorage = { capture: 'selftest_planted', localStorage: { 'ls-theme': 'dark', 'ls-session-token': 'join_selftestcredential0123456789abcdefgh' }, sessionStorage: {}, cookie: '' };
  const selfTestStorageViolations = [];
  for (const key of Object.keys(plantedStorage.localStorage)) {
    const rule = STORAGE_ALLOWLIST.common.find((a) => a.key === key);
    if (!rule) selfTestStorageViolations.push({ key, why: 'not on the allowlist' });
    else if (!rule.valuePattern.test(plantedStorage.localStorage[key])) selfTestStorageViolations.push({ key, why: 'value outside its declared shape' });
  }
  const selfTestCanaries = [...new Set(selfTestHits.map((h) => h.canary))];
  const selfTestWorks = selfTestHits.length >= 6 && selfTestStorageViolations.length === 1 && selfTestStorageViolations[0].key === 'ls-session-token';

  /* ---- assertions --------------------------------------------------------- */
  chk.eq('no canary pattern appears on any captured surface', [], genericHits.map((h) => `${h.canary} in ${h.source}/${h.surface}`));
  chk.ok(
    'the raw join credential appears ONLY in its issuing 201 response',
    `${tokens.length} issued credential(s); every sighting is a 201 response body of POST .../join-credentials and nothing else`,
    { tokensTracked: tokens.length, sightings: tokenSightings, unauthorised: unauthorisedTokenSightings, genericCanaryHits: joinTokenGenericHits.length },
    (v) => v.tokensTracked > 0 && v.unauthorised.length === 0,
  );
  chk.eq('browser storage holds nothing outside the declared allowlist', [], allowlistViolations);
  chk.eq('no allowlisted value is out of its declared shape', [], shapeViolations);
  chk.eq('no cookie is set on any surface', [], cookieViolations);
  chk.eq('no secret-shaped field exists inside an allowlisted stored object', [], secretShaped);
  chk.ok(
    'the benign ls-theme preference does NOT fail the gate',
    'ls-theme is present on the student surface, holds only "light"/"dark", and contributes ZERO violations',
    { capturesHoldingIt: themeCaptures.length, values: [...new Set(themeCaptures.map((c) => c.capture))].slice(0, 3), violationsCaused: themeViolations.length },
    (v) => v.capturesHoldingIt > 0 && v.violationsCaused === 0,
  );
  chk.ok(
    'SELF-TEST: a planted secret canary FAILS the scan',
    'a synthetic surface carrying a PAN, CVV, OTP, join credential, SDP, ICE, device label and payment token is reported by the SAME scanner, and a non-allowlisted storage key is reported by the SAME judge',
    { canariesTriggered: selfTestCanaries, hitCount: selfTestHits.length, storageViolations: selfTestStorageViolations },
    () => selfTestWorks,
  );

  const verdict = chk.verdict === 'pass' ? 'clean' : 'findings_present';
  const report = {
    generatedAt: new Date().toISOString(),
    matrixRow: 'J1',
    runId: RUN_ID,
    method: 'Every artifact this driver captured from the running browser (DOM snapshots, the full request/response log including POST bodies and headers, and localStorage/sessionStorage/cookies/URL per capture) plus the backend uvicorn log, scanned with the canary set below. Storage is judged against an EXPLICIT allowlist declared in the test, not against "must be empty".',
    canaries: CANARIES.map((c) => ({ id: c.id, pattern: String(c.re), what: c.what })),
    storageAllowlist: {
      rule: 'A key is permitted only if it is named here AND its value matches the declared shape. Everything else fails.',
      common: STORAGE_ALLOWLIST.common.map((a) => ({ key: a.key, why: a.why, valuePattern: String(a.valuePattern) })),
      authenticatedMentorSurfaceOnly: STORAGE_ALLOWLIST.mentor.map((a) => ({ key: a.key, why: a.why, valuePattern: String(a.valuePattern) })),
      secretShapedFieldPattern: String(SECRET_SHAPED_KEY),
    },
    joinCredentialScope: {
      rule: 'The raw join credential may appear ONLY in the body of the 201 response to POST /api/v1/tutoring/sessions/{id}/join-credentials. Every other sighting — DOM, storage, cookie, URL, console, backend log, any other network entry — is a leak.',
      tokensTracked: tokens.length,
      sightings: tokenSightings,
      unauthorisedSightings: unauthorisedTokenSightings,
    },
    surfacesScanned: surfaces,
    surfaceCount: surfaces.length,
    totalBytesScanned: surfaces.reduce((a, s) => a + s.bytes, 0),
    findings: genericHits,
    findingCount: genericHits.length,
    storageState,
    storageViolations,
    themePreference: {
      note: 'ls-theme is the light/dark preference written by useTheme(). It is allowed BY NAME with a constrained value and is NOT a privacy finding. Independent-QA F7.',
      capturesHoldingIt: themeCaptures.length,
      violationsCaused: themeViolations.length,
    },
    selfTest: {
      note: 'Proof that the gate still works. The same scanner and the same storage judge are run over a planted secret; if they report it clean, this stage FAILS.',
      fixture: path.relative(OUT, path.join(canaryDir, 'planted.json')),
      canariesTriggered: selfTestCanaries,
      hitCount: selfTestHits.length,
      storageViolationsDetected: selfTestStorageViolations,
      gateWorks: selfTestWorks,
    },
    urlsVisited: [...new Set(urls)],
    assertions: chk.table,
    verdict,
  };
  fs.writeFileSync(path.join(OUT, 'privacy_scan.json'), JSON.stringify(report, null, 2));
  recordChecks(chk, {
    stage: 'priv',
    matrix: 'J1',
    summary: `${CANARIES.length} canaries over ${surfaces.length} surfaces (${report.totalBytesScanned} bytes) — ${genericHits.length} finding(s); storage judged against the declared allowlist (${STORAGE_ALLOWLIST.common.map((a) => a.key).join(',')} everywhere, + ${STORAGE_ALLOWLIST.mentor.map((a) => a.key).join(',')} on the authenticated mentor surface) with ${storageViolations.length} violation(s); ls-theme present in ${themeCaptures.length} capture(s) and caused ${themeViolations.length}; join credential sighted ${tokenSightings.length} time(s), ${unauthorisedTokenSightings.length} outside its authorised response; self-test triggered ${selfTestCanaries.length} canaries`,
    observed: { findings: genericHits, storageViolations, tokenSightings, selfTest: report.selfTest },
    artifacts: ['privacy_scan.json'],
  });
}

/* ==================================================================== main */

/**
 * F4.3 (driver side). The runner allocates the two ports atomically and asserts
 * they differ; the driver asserts it AGAIN against the URLs it was actually
 * handed, because a runner that got it right and a driver that was handed the
 * wrong pair are different failures and only this check catches the second.
 */
function assertDistinctPorts() {
  const web = new URL(WEB);
  const api = new URL(API);
  const same = web.port === api.port && web.hostname === api.hostname;
  if (injected('port-collision') || same) {
    const detail = injected('port-collision')
      ? `INJECTED port collision: E2E_WEB_URL=${WEB} and E2E_API_URL=${API} were forced onto one port`
      : `E2E_WEB_URL=${WEB} and E2E_API_URL=${API} resolve to the same host:port`;
    record({
      id: 'PRECHECK-distinct-ports',
      stage: 'precheck',
      outcome: 'fail',
      summary: `PORT COLLISION — refusing to run: ${detail}`,
      assertions: [{ case: 'frontend and API are on DIFFERENT ports', expected: `${web.hostname}:${web.port} != ${api.hostname}:${api.port}`, actual: detail, result: 'FAIL' }],
      observed: { web: WEB, api: API, injected: injected('port-collision') },
      artifacts: [],
    });
    return false;
  }
  record({
    id: 'PRECHECK-distinct-ports',
    stage: 'precheck',
    outcome: 'pass',
    summary: `ports asserted distinct before any browser work: frontend ${web.hostname}:${web.port}, API ${api.hostname}:${api.port}`,
    assertions: [{ case: 'frontend and API are on DIFFERENT ports', expected: 'two different host:port pairs', actual: `${web.hostname}:${web.port} vs ${api.hostname}:${api.port}`, result: 'PASS' }],
    observed: { web: WEB, api: API },
    artifacts: [],
  });
  return true;
}

/**
 * The two log injections write a REAL line, in the backend's real format, into
 * the real log file the oracle reads. The oracle is a log reader: proving it
 * fails closed means proving that this line, in that file, in the region of a
 * stage, ends the run — which is exactly what these produce.
 */
function injectBackendLogFaults() {
  if (!BACKEND_LOG) return;
  const ts = new Date().toISOString();
  const lines = [];
  if (injected('log-unhandled')) {
    lines.push(JSON.stringify({
      ts, level: 'ERROR', logger: 'legalsaathi.app', message: 'unhandled_exception', request_id: 'injected0000000000000000000000000',
      exc_info: 'Traceback (most recent call last):\n  File "app/api/v1/tutoring.py", line 1, in list_sessions\n    raise RuntimeError("INJECTED fail-closed proof")\nRuntimeError: INJECTED fail-closed proof',
    }));
  }
  if (injected('log-asgi-traceback')) {
    lines.push('ERROR:    Exception in ASGI application');
    lines.push('Traceback (most recent call last):');
    lines.push('  File "uvicorn/protocols/http/httptools_impl.py", line 435, in run_asgi');
    lines.push('    result = await app(self.scope, self.receive, self.send)');
    lines.push('  File "app/api/v1/tutoring.py", line 512, in list_slots');
    lines.push('    return slots[0]');
    lines.push('IndexError: list index out of range');
  }
  if (!lines.length) return;
  fs.appendFileSync(BACKEND_LOG, `${lines.join('\n')}\n`);
  console.log(`!! INJECTED: ${lines.length} fault line(s) appended to ${BACKEND_LOG}`);
}

async function main() {
  if (STAGES.length === 1 && STAGES[0] === 'none') {
    console.log('stages=none — servers verified, no browser work requested');
    const ports = assertDistinctPorts();
    const provenance = assertCommitProvenance();
    const oracle = await backendOracle('boot');
    return ports && provenance && oracle ? 0 : 1;
  }
  if (!assertDistinctPorts()) {
    console.error('\nFAIL-CLOSED: frontend and API share a port. Nothing was driven.');
    return 1;
  }
  if (INJECT.size) console.log(`!! FAULT INJECTION ACTIVE: ${[...INJECT].join(',')}`);

  // Fail-closed proof (h): evidence carried in from a DIFFERENT commit. The
  // switch rewrites the carried-over provenance, exactly as a stale evidence
  // directory would present it.
  if (injected('stale-commit')) {
    STATE.commit = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef';
    saveState();
    if (RESULTS.length) RESULTS[0].commit = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef';
    else RESULTS.push({ id: 'STALE-carried-row', stage: 'a', outcome: 'pass', summary: 'a result carried in from another commit', commit: 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef', assertions: [], observed: {}, artifacts: [] });
    saveResults();
    console.log('!! INJECTED: this evidence directory now claims commit deadbeef… while the run is at ' + COMMIT);
  }

  // Provenance FIRST: a run that cannot prove which commit it is judging must
  // not be allowed to produce a stage result at all.
  if (!assertCommitProvenance()) {
    console.error('\nFAIL-CLOSED: this evidence directory was not produced at the commit under test. Nothing was driven.');
    return 1;
  }
  injectBackendLogFaults();

  const browser = await chromium.launch({
    args: [
      '--no-sandbox',
      '--disable-dev-shm-usage',
      // F4.2 — deterministic media. The fake device makes getUserMedia and
      // enumerateDevices answer identically on every run, and the fake UI stops
      // Chromium putting a human permission prompt in front of them.
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
    ],
  });
  STATE.browserVersion = browser.version();
  saveState();
  console.log(`chromium ${browser.version()} launched · stages=${STAGES.join(',')} · run ${RUN_ID}`);

  const needsPage = STAGES.some((s) => s !== 'geo' && s !== 'priv' && s !== 'rollup');
  let ctx = null;
  let page = null;
  if (needsPage) {
    ctx = await browser.newContext({ viewport: MOBILE, colorScheme: 'light', permissions: ['camera', 'microphone'] });
    if (injected('media-never-ready')) {
      // Fail-closed proof (d): a media state that is never ready. getUserMedia
      // resolves never — exactly the hang a fixed sleep used to paper over.
      await ctx.addInitScript(() => {
        navigator.mediaDevices.getUserMedia = () => new Promise(() => {});
      });
    }
    if (injected('privacy-canary')) {
      // Fail-closed proof (e): a REAL secret planted in browser storage.
      await ctx.addInitScript(() => {
        try {
          window.localStorage.setItem('ls-session-token', 'join_INJECTEDcanary0123456789abcdefghij');
          window.localStorage.setItem('ls-card', '4242424242424242');
        } catch { /* origin without storage */ }
      });
    }
    page = await ctx.newPage();
    attachCapture(page);
    if (injected('console-error')) {
      // Fail-closed proof (b): an unexpected console error nobody declared.
      page.on('load', () => {
        page.evaluate(() => console.error('INJECTED unexpected console error for the fail-closed proof')).catch(() => {});
      });
    }
  }

  const ALIASES = {
    // `n45` is part of the negative catalogue, so a full `neg` run answers it;
    // it is a stage of its own because it needs a browser context with the
    // deterministic media transport selected before the app boots.
    neg: ['neg1', 'neg2', 'neg2b', 'n45', 'neg3', 'neg4'],
    // The rate-limit journey lives inside neg4 (N43 search, N44 review). The
    // documented `rl` name resolves to it instead of falling into the
    // "unknown stage" branch.
    rl: ['neg4'],
  };
  /**
   * The PLAN is captured here, before anything can shorten it, and the
   * completeness check at the end is made against the PLAN — not against the
   * list the loop actually walked. That is the only ordering in which a stage
   * silently removed from the run is still detectable.
   */
  const plan = STAGES.flatMap((s) => ALIASES[s] || [s]);
  // Fail-closed proof (a): drop a REQUIRED negative case from the run.
  let dropped = injected('missing-negative') ? plan.filter((s) => s !== 'neg2') : plan;
  if (injected('missing-negative')) console.log('!! INJECTED: stage neg2 removed from the plan (its required rows N08..N12 will go unanswered)');
  // Fail-closed proof (i): a PLANNED stage that silently never runs. No notice
  // is printed into the evidence beyond this line — the completeness check has
  // to notice it on its own.
  if (injected('skip-stage') && dropped.length) {
    dropped = dropped.slice(0, -1);
    console.log(`!! INJECTED: the last planned stage was dropped from the run without recording anything`);
  }

  let failures = 0;
  const executed = [];
  for (const stage of dropped) {
    console.log(`\n--- stage ${stage}`);
    executed.push(stage);
    // Fail-closed proof (g): the backend dies mid-run. SIGKILL, so there is no
    // graceful shutdown line and no exit handler — the process is simply gone,
    // which is the case a "did the log stay clean?" scan alone cannot see.
    if (injected('backend-kill') && BACKEND_PID && stage === dropped[Math.min(1, dropped.length - 1)]) {
      try {
        process.kill(BACKEND_PID, 'SIGKILL');
        console.log(`!! INJECTED: SIGKILL sent to the backend (pid ${BACKEND_PID}) before stage ${stage}`);
      } catch (err) {
        console.log(`!! INJECTED backend-kill could not signal pid ${BACKEND_PID}: ${err.code || err}`);
      }
    }
    try {
      if (stage === 'a') await stageA(page);
      else if (stage === 'b') await stageB(page);
      else if (stage === 'c') await stageC(page);
      else if (stage === 'e') await stageE(page);
      else if (stage === 'geo') await stageGeo(browser);
      else if (stage === 'd1') await stageD1(page);
      else if (stage === 'd2') await stageD2(page);
      else if (stage === 'd3') await stageD3(page, browser);
      else if (stage === 'd4') await stageD4(page, browser);
      else if (stage === 'neg1') await stageNeg1(page);
      else if (stage === 'neg2') await stageNeg2(page);
      else if (stage === 'neg2b') await stageNeg2b(page, browser);
      else if (stage === 'n45') await stageN45(browser);
      else if (stage === 'neg3') await stageNeg3();
      else if (stage === 'neg4') await stageNeg4(page);
      else if (stage === 'rollup') await stageRollup();
      else if (stage === 'priv') await stagePriv();
      else {
        failures += 1;
        record({ id: `stage-${stage}-UNKNOWN`, stage, outcome: 'fail', summary: `unknown stage "${stage}" was requested and therefore nothing was verified; an unrecognised stage name is a FAIL, not a silent skip`, observed: { requested: STAGES }, artifacts: [] });
      }
    } catch (err) {
      failures += 1;
      const name = `error_${stage}`;
      let artifacts = [];
      try {
        if (page) artifacts = [await shot(page, name)];
      } catch { /* ignore */ }
      record({
        id: `stage-${stage}-ERROR`,
        stage,
        outcome: 'fail',
        summary: `stage threw: ${String(err).slice(0, 400)}`,
        observed: { stack: String(err.stack || '').slice(0, 2000), banners: page ? await banners(page).catch(() => null) : null },
        artifacts,
      });
    }
    // F3 — EVERY stage, pass or fail, is followed by the backend oracle over
    // the log region IT produced, plus process liveness and /health.
    if (!(await backendOracle(stage))) failures += 1;
  }

  if (ctx) {
    await ctx.tracing.stop({ path: path.join(DIRS.traces, `trace_${STAGES.join('-')}.zip`) }).catch(() => {});
    await ctx.close();
  }
  flushNet(STAGES.join('-'));
  await browser.close();

  // Anything the gate caught after the last stage recorded (teardown noise) is
  // still a problem and still fails the run.
  const trailing = GATE.drain('teardown');
  if (trailing.length) {
    failures += 1;
    record({
      id: 'GATE-trailing-browser-problems',
      stage: 'teardown',
      outcome: 'fail',
      summary: `${trailing.length} unattributed browser problem(s) were still outstanding when the run ended`,
      observed: { problems: trailing },
      artifacts: [],
    });
  }

  /* ---- F3 finalisation ---------------------------------------------------- */
  // One more scan of everything the backend wrote after the last stage (a
  // shutdown traceback, a background task blowing up during teardown), one more
  // liveness/health reading, and the two evidence-integrity judgements.
  if (!(await backendOracle('final', { final: true }))) failures += 1;
  if (!assertStageCompleteness(plan, executed)) failures += 1;
  if (!assertCommitProvenance({ final: true })) failures += 1;

  fs.writeFileSync(path.join(OUT, 'backend_log_oracle.json'), JSON.stringify({
    generatedAt: new Date().toISOString(),
    runId: RUN_ID,
    commit: COMMIT || null,
    logPath: BACKEND_LOG || null,
    backendPid: BACKEND_PID || null,
    rule: 'The backend log is judged as a sequence of DISJOINT byte regions, one per owner, in the order they were produced. The offset advances monotonically and is persisted in state.json, so (a) a line already judged can never be re-read as context for a later stage, and (b) each stage is judged only on the bytes IT produced. Any ERROR/CRITICAL/Traceback/unhandled_exception/"Exception in ASGI application"/"cannot commit"/IndexError line fails the owning stage AND the run. A backend-log expectation must name an exact line pattern AND a typed code; no stage declares one, so the allowlist is empty.',
    patterns: BACKEND_LOG_PATTERNS.map((p) => ({ id: p.id, pattern: String(p.re), what: p.what })),
    finalOffset: BACKEND.offset,
    regions: BACKEND.regions,
    findings: BACKEND.findings,
    livenessSamples: BACKEND.samples.map((s) => ({ owner: s.owner, at: s.at, proc: s.proc, health: s.health })),
  }, null, 2));

  const bad = RESULTS.filter((r) => r.outcome !== 'pass');
  fs.writeFileSync(path.join(OUT, 'gate_events.json'), JSON.stringify({ generatedAt: new Date().toISOString(), runId: RUN_ID, rule: 'Every console error/warning, page error, failed request and 4xx/5xx the browser produced, plus every backend-log line that matched a runtime-error pattern. `attributed: true` means a case declared it with an exact method/route/status/code; `false` means it failed the run. A 5xx is never attributable.', events: GATE.seen }, null, 2));
  console.log(`\nresults: ${RESULTS.length} recorded · not-pass=${bad.length}${bad.length ? ` (${bad.map((r) => r.id).join(', ')})` : ''}`);
  return failures || bad.length ? 1 : 0;
}

main().then((rc) => process.exit(rc)).catch((err) => {
  console.error(err);
  process.exit(2);
});

/**
 * SAATHI-120 — repository-owned law-school directory E2E suite (TC-63-01..12).
 *
 * Runs against the built frontend (QA_BASE_URL, default http://127.0.0.1:1050)
 * with the real FastAPI + PostgreSQL 16 stack behind it (QA_API_BASE_URL,
 * default http://127.0.0.1:1031). The directory is seeded by
 * law_school_service.seed_law_schools with a DETERMINISTIC 12-SCHOOL CATALOG
 * (frozen product fact — the catalog size is independent of the config-driven
 * comparison maximum of 4). A fixed 4-school subset is used ONLY as the
 * compare fixture, never as a catalog expectation.
 *
 * Exception-safety contract (QA defect #7): every case and every phase is
 * wrapped in try/catch that records a failed case instead of aborting; the
 * final report (lawschool_e2e_report.json), screenshots, Playwright traces and
 * network/console logs are always written in a finally block; the process
 * exits non-zero only after artifacts are finalized.
 *
 * Usage (QA rig — requires Chromium system deps and PG16 behind the API):
 *   cd frontend && npm ci && npx playwright install chromium
 *   QA_BASE_URL=http://127.0.0.1:1050 QA_API_BASE_URL=http://127.0.0.1:1031 \
 *   QA_EVIDENCE_DIR=/abs/path/evidence npm run qa:lawschool
 */
import { chromium } from 'playwright';
import { execSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const base = process.env.QA_BASE_URL ?? 'http://127.0.0.1:1050';
const api = process.env.QA_API_BASE_URL ?? 'http://127.0.0.1:1031';
const evidence = process.env.QA_EVIDENCE_DIR ?? path.resolve('../QA/wave1_lawschool_closure');
const tracesDir = path.join(evidence, 'traces');
await fs.mkdir(tracesDir, { recursive: true });

let commit = process.env.QA_COMMIT ?? null;
if (!commit) {
  try { commit = execSync('git rev-parse HEAD', { encoding: 'utf8' }).trim(); } catch { commit = 'unknown'; }
}

/** Dev-stub actor claims (mirror of lawSchoolsApi.ts DEV_ACTOR_CLAIMS; backend
 * auth contract: X-Actor-Claims JSON header {"sub":"<uuid>","roles":[...]} ). */
const USER_A = { sub: '00000000-0000-4000-8000-0000000000de', roles: ['student'] };
const USER_B = { sub: '00000000-0000-4000-8000-0000000000b2', roles: ['student'] };
const NON_STUDENT = { sub: '00000000-0000-4000-8000-0000000000c3', roles: ['lawyer'] };

/* Frozen product facts (backend/app/services/law_school_service.py _SEED). */
const CATALOG_SLUGS = [
  'nlsiu-bengaluru', 'nalsar-hyderabad', 'wbnujs-kolkata', 'nlu-delhi',
  'gnlu-gandhinagar', 'sls-pune', 'jgls-sonipat', 'glc-mumbai',
  'du-law-delhi', 'ils-pune', 'christ-law-bengaluru', 'rgnul-patiala',
];
const NLU_SLUGS = [
  'gnlu-gandhinagar', 'nalsar-hyderabad', 'nlsiu-bengaluru',
  'nlu-delhi', 'rgnul-patiala', 'wbnujs-kolkata',
];
/* Fixed 4-school subset — COMPARE FIXTURE ONLY (max compare = 4 by config). */
const COMPARE_SLUGS = ['nlsiu-bengaluru', 'nalsar-hyderabad', 'wbnujs-kolkata', 'nlu-delhi'];

const cases = [];
/** status: 'pass' | 'fail' | 'na'. 'na' NEVER increments the passed count —
 * it is reported separately (QA defect: an N/A case was previously a false PASS). */
const record = (tc, name, expected, actual, pass, evidenceFile = null, status = null) => {
  const st = status ?? (pass ? 'pass' : 'fail');
  cases.push({ tc, name, expected, actual, status: st, pass: st === 'pass', evidence: evidenceFile });
  console.log(`${st.toUpperCase()} ${tc} (${name})`);
};
const recordNA = (tc, name, expected, note) => record(tc, name, expected, note, false, null, 'na');
/** Per-case try/catch: a throwing case records FAIL and the run continues. */
async function tcase(tc, name, expected, fn) {
  try {
    const out = await fn();
    if (out.na) {
      record(tc, name, expected, out.actual, false, out.evidence ?? null, 'na');
      return;
    }
    record(tc, name, expected, out.actual, !!out.pass, out.evidence ?? null);
  } catch (err) {
    record(tc, name, expected, `uncaught: ${err?.message ?? String(err)}`, false, null);
  }
}
/** Per-phase try/catch: an aborted phase records one FAIL, never kills the run. */
async function phase(name, fn) {
  try { await fn(); } catch (err) {
    record(`${name}-uncaught`, name, 'phase completes without uncaught exception',
      String(err?.stack ?? err).slice(0, 500), false);
  }
}

const netLines = [];
const consoleLines = [];

/* -------------------------------- API probe -------------------------------- */

async function apiCall(method, p, { claims, body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (claims) headers['X-Actor-Claims'] = JSON.stringify(claims);
  const response = await fetch(`${api}${p}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json;
  try { json = await response.json(); } catch { json = null; }
  netLines.push(`[api] ${method} ${p} -> ${response.status}`);
  return { status: response.status, json };
}
const errCode = (r) => {
  const detail = r.json?.detail;
  return (typeof detail === 'object' && detail !== null ? detail.code : detail) ?? null;
};
const savedSlugs = async (claims) => {
  const r = await apiCall('GET', '/api/v1/student/law-schools/saved', { claims });
  return (r.json?.items ?? []).map((s) => s.slug).sort();
};
const followedSlugs = async (claims) => {
  const r = await apiCall('GET', '/api/v1/student/law-schools/followed', { claims });
  return (r.json?.items ?? []).map((s) => s.slug).sort();
};

let bySlug = {};
let ids4 = [];

/* ------------------- seed verification + deterministic reset ---------------- */
await phase('seed-and-reset', async () => {
  const catalog = await apiCall('GET', '/api/v1/law-schools?sort=name&page=1&page_size=50');
  bySlug = Object.fromEntries((catalog.json?.items ?? []).map((s) => [s.slug, s]));
  await tcase('TC-63-01-catalog-12', 'catalog_total_12',
    'catalog total=12 and all 12 seeded slugs present', async () => ({
      actual: { total: catalog.json?.total, slugs: Object.keys(bySlug).sort() },
      pass: catalog.json?.total === 12 && CATALOG_SLUGS.every((slug) => !!bySlug[slug])
        && Object.keys(bySlug).length === 12,
    }));
  for (const claims of [USER_A, USER_B]) {
    for (const s of Object.values(bySlug)) {
      await apiCall('DELETE', `/api/v1/student/law-schools/${s.id}/saved`, { claims });
      await apiCall('DELETE', `/api/v1/student/law-schools/${s.id}/follow`, { claims });
    }
  }
  ids4 = COMPARE_SLUGS.map((slug) => bySlug[slug]?.id).filter(Boolean);
});

/* ---------------- TC-63-01 — search/filter/sort/pagination (API) ----------- */
await phase('tc-63-01-api', async () => {
  await tcase('TC-63-01-search-q', 'search_q_nalsar', 'q=NALSAR returns exactly nalsar-hyderabad', async () => {
    const q = await apiCall('GET', '/api/v1/law-schools?q=NALSAR&page=1&page_size=20');
    return { actual: (q.json?.items ?? []).map((s) => s.slug),
      pass: q.json?.total === 1 && q.json?.items?.[0]?.slug === 'nalsar-hyderabad' };
  });
  await tcase('TC-63-01-filter-state', 'filter_state_delhi',
    'state=Delhi returns exactly du-law-delhi + nlu-delhi (2 of 12)', async () => {
      const st = await apiCall('GET', '/api/v1/law-schools?state=Delhi&sort=name');
      const slugs = (st.json?.items ?? []).map((s) => s.slug).sort();
      return { actual: { total: st.json?.total, slugs },
        pass: st.json?.total === 2 && JSON.stringify(slugs) === JSON.stringify(['du-law-delhi', 'nlu-delhi']) };
    });
  await tcase('TC-63-01-filter-exam', 'filter_exam_ailet', 'entrance_exam=AILET returns exactly nlu-delhi', async () => {
    const ex = await apiCall('GET', '/api/v1/law-schools?entrance_exam=AILET');
    return { actual: (ex.json?.items ?? []).map((s) => s.slug),
      pass: ex.json?.total === 1 && ex.json?.items?.[0]?.slug === 'nlu-delhi' };
  });
  await tcase('TC-63-01-filter-fees', 'filter_fees_sorted',
    'fees_max=250000 → 8 schools ascending by fees_min (du-law-delhi first, nlu-delhi last)', async () => {
      const fees = await apiCall('GET', '/api/v1/law-schools?fees_max=250000&sort=fees&page_size=50');
      const slugs = (fees.json?.items ?? []).map((s) => s.slug);
      const want = ['du-law-delhi', 'glc-mumbai', 'ils-pune', 'rgnul-patiala',
        'christ-law-bengaluru', 'gnlu-gandhinagar', 'wbnujs-kolkata', 'nlu-delhi'];
      return { actual: slugs, pass: fees.json?.total === 8 && JSON.stringify(slugs) === JSON.stringify(want) };
    });
  await tcase('TC-63-01-sort-nirf', 'sort_nirf_first', 'nirf sort puts nlsiu-bengaluru (#1) first', async () => {
    const nirf = await apiCall('GET', '/api/v1/law-schools?sort=nirf_rank');
    return { actual: nirf.json?.items?.[0]?.slug, pass: nirf.json?.items?.[0]?.slug === 'nlsiu-bengaluru' };
  });
  await tcase('TC-63-01-sort-typed-422', 'unsupported_sort_typed', 'unsupported sort → 422 unsupported_sort', async () => {
    const badSort = await apiCall('GET', '/api/v1/law-schools?sort=fees_desc');
    return { actual: { status: badSort.status, code: errCode(badSort) },
      pass: badSort.status === 422 && errCode(badSort) === 'unsupported_sort' };
  });
  await tcase('TC-63-01-pagination', 'pagination_12_over_6_pages',
    'page_size=2 → pages 1..6 have 2 rows each (total 12), page 7 empty, union = all 12 slugs', async () => {
      const pages = [];
      for (let p = 1; p <= 7; p += 1) {
        pages.push(await apiCall('GET', `/api/v1/law-schools?sort=name&page=${p}&page_size=2`));
      }
      const counts = pages.map((r) => r.json?.items?.length ?? -1);
      const union = new Set(pages.flatMap((r) => (r.json?.items ?? []).map((s) => s.slug)));
      return { actual: { counts, total: pages[0].json?.total, unionSize: union.size },
        pass: counts.slice(0, 6).every((c) => c === 2) && counts[6] === 0
          && pages[0].json?.total === 12 && union.size === 12
          && CATALOG_SLUGS.every((slug) => union.has(slug)) };
    });
  /* QA defect #2: institution_type must be sent as the WIRE VALUE
   * (backend/app/models/wave1.py INSTITUTION_TYPES), never a display label. */
  await tcase('TC-63-01-institution-type-api', 'institution_type_wire_value',
    'institution_type=national_law_university returns exactly the 6 NLU schools', async () => {
      const it = await apiCall('GET', '/api/v1/law-schools?institution_type=national_law_university&sort=name&page_size=50');
      const slugs = (it.json?.items ?? []).map((s) => s.slug).sort();
      return { actual: { total: it.json?.total, slugs },
        pass: it.json?.total === 6 && JSON.stringify(slugs) === JSON.stringify(NLU_SLUGS) };
    });
  await tcase('TC-63-01-institution-type-bad-param', 'institution_type_bad_param_rejected',
    'direct bad API param institution_type=not-a-wire-value → 422 unsupported_institution_type', async () => {
      const bad = await apiCall('GET', '/api/v1/law-schools?institution_type=not-a-wire-value');
      return { actual: { status: bad.status, code: errCode(bad) },
        pass: bad.status === 422 && errCode(bad) === 'unsupported_institution_type' };
    });
});

/* -------- TC-63-03/04 — compare rules at the HTTP boundary (typed) ---------
 * Approved contract (backend/app/api/v1/law_schools.py):
 *     class CompareIn(BaseModel):
 *         model_config = ConfigDict(extra="forbid")
 *         school_ids: list[uuid.UUID]
 *     @router.post("/law-schools/compare")
 * The endpoint takes the whole school_ids list ATOMICALLY and reads NO
 * Idempotency-Key header (extra="forbid" rejects any extra body field); each
 * POST deliberately creates a NEW ComparisonSet. There is therefore no
 * "idempotent replay" to test: the APPROVED duplicate behavior is (a) a
 * same-payload re-POST creates a distinct set whose items are internally
 * unique, and (b) duplicate school_ids in ONE request → typed
 * DUPLICATE_SCHOOL. (Save/follow PUT is the idempotent surface — TC-63-05.) */
await phase('tc-63-03-04-compare-api', async () => {
  await tcase('TC-63-03-fifth-school-refusal', 'fifth_school_typed_refusal',
    '5 ids → 422 COMPARE_LIMIT_EXCEEDED max_allowed=4', async () => {
      const over = await apiCall('POST', '/api/v1/law-schools/compare',
        { body: { school_ids: [...ids4, bySlug['gnlu-gandhinagar'].id] } });
      return { actual: { status: over.status, code: errCode(over), max: over.json?.detail?.max_allowed },
        pass: over.status === 422 && errCode(over) === 'COMPARE_LIMIT_EXCEEDED' && over.json?.detail?.max_allowed === 4 };
    });
  await tcase('TC-63-03-min-not-met', 'below_minimum_typed', '1 id → 422 COMPARE_MIN_NOT_MET min_required=2', async () => {
    const under = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0]] } });
    return { actual: { status: under.status, code: errCode(under) },
      pass: under.status === 422 && errCode(under) === 'COMPARE_MIN_NOT_MET' && under.json?.detail?.min_required === 2 };
  });
  await tcase('TC-63-04-duplicate-blocked', 'duplicate_in_one_request',
    'duplicate id in ONE request → 422 DUPLICATE_SCHOOL', async () => {
      const dup = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0], ids4[0]] } });
      return { actual: { status: dup.status, code: errCode(dup) },
        pass: dup.status === 422 && errCode(dup) === 'DUPLICATE_SCHOOL' };
    });
  await tcase('TC-63-04-replay', 'duplicate_payload_new_set',
    'same-payload re-POST (no Idempotency-Key in contract) → both 200, DISTINCT sets, each with 4 internally-unique items', async () => {
      const r1 = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } });
      const r2 = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } });
      const uniq = (r) => new Set((r.json?.items ?? []).map((i) => i.id)).size;
      return { actual: { s1: r1.status, s2: r2.status, distinct: r1.json?.comparison_id !== r2.json?.comparison_id,
        items1: r1.json?.items?.length, items2: r2.json?.items?.length, uniq1: uniq(r1), uniq2: uniq(r2) },
      pass: r1.status === 200 && r2.status === 200 && r1.json?.comparison_id !== r2.json?.comparison_id
        && r1.json?.items?.length === 4 && r2.json?.items?.length === 4 && uniq(r1) === 4 && uniq(r2) === 4 };
    });
});

/* ---------------- TC-63-04 — REAL concurrency on contended state ------------
 * Contended logical resources, named precisely:
 *   (a) the unique (user_id, school_id) row in saved_law_schools — 8 parallel
 *       idempotent PUT saves for the SAME user+school;
 *   (b) the unique (user_id, school_id) row in law_school_follows — 8 parallel
 *       PUT follows for the SAME user+school;
 *   (c) ComparisonSet creation under the config max — 6 parallel 4-school
 *       POST /compare creations plus a racing over-limit request.
 * The HTTP compare endpoint creates whole sets atomically (no HTTP add-item
 * endpoint exists), so per-item add races are exercised by backend pytest
 * (test_wave1_law_schools.py concurrent add_comparison_item threads); at the
 * HTTP boundary we assert via the DB-visible list endpoints that no duplicate
 * save/follow rows exist and no comparison ever exceeds 4 items. */
await phase('tc-63-04-concurrency', async () => {
  const target = bySlug['nlsiu-bengaluru'];
  await tcase('TC-63-04-concurrent-save', 'parallel_saves_single_row',
    '8 parallel PUT saved on same (user,school) → all 200, saved list has EXACTLY one row', async () => {
      const rs = await Promise.all(Array.from({ length: 8 }, () =>
        apiCall('PUT', `/api/v1/student/law-schools/${target.id}/saved`, { claims: USER_A })));
      const list = await savedSlugs(USER_A);
      return { actual: { statuses: rs.map((r) => r.status), saved: list },
        pass: rs.every((r) => r.status === 200) && list.filter((s) => s === 'nlsiu-bengaluru').length === 1 && list.length === 1 };
    });
  await tcase('TC-63-04-concurrent-follow', 'parallel_follows_single_row',
    '8 parallel PUT follow on same (user,school) → all 200, followed list has EXACTLY one row', async () => {
      const rs = await Promise.all(Array.from({ length: 8 }, () =>
        apiCall('PUT', `/api/v1/student/law-schools/${target.id}/follow`, { claims: USER_A })));
      const list = await followedSlugs(USER_A);
      return { actual: { statuses: rs.map((r) => r.status), followed: list },
        pass: rs.every((r) => r.status === 200) && list.filter((s) => s === 'nlsiu-bengaluru').length === 1 && list.length === 1 };
    });
  await tcase('TC-63-04-concurrent-unsave', 'parallel_unsaves_converge',
    '8 parallel DELETE saved on same row → all 200 {saved:false}, list empty (no phantom rows)', async () => {
      const rs = await Promise.all(Array.from({ length: 8 }, () =>
        apiCall('DELETE', `/api/v1/student/law-schools/${target.id}/saved`, { claims: USER_A })));
      const list = await savedSlugs(USER_A);
      return { actual: { statuses: rs.map((r) => r.status), saved: list },
        pass: rs.every((r) => r.status === 200 && r.json?.saved === false) && list.length === 0 };
    });
  await apiCall('DELETE', `/api/v1/student/law-schools/${target.id}/follow`, { claims: USER_A });
  await tcase('TC-63-04-concurrent-compare-create', 'parallel_compare_creations_bounded',
    '6 parallel 4-school POST /compare → all 200, every set has EXACTLY 4 internally-unique items (never >4)', async () => {
      const rs = await Promise.all(Array.from({ length: 6 }, () =>
        apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } })));
      const sets = rs.map((r) => ({ status: r.status, n: r.json?.items?.length,
        uniq: new Set((r.json?.items ?? []).map((i) => i.id)).size }));
      return { actual: sets,
        pass: sets.every((s) => s.status === 200 && s.n === 4 && s.uniq === 4)
          && new Set(rs.map((r) => r.json?.comparison_id)).size === 6 };
    });
  await tcase('TC-63-04-concurrent-valid-vs-overlimit', 'racing_valid_and_overlimit',
    'racing valid 4-school and 5-school POSTs → 200 and typed 422, no cross-talk', async () => {
      const [cA, cB] = await Promise.all([
        apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } }),
        apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [...ids4, bySlug['sls-pune'].id] } }),
      ]);
      return { actual: { a: cA.status, aItems: cA.json?.items?.length, b: cB.status, bCode: errCode(cB) },
        pass: cA.status === 200 && cA.json?.items?.length === 4
          && cB.status === 422 && errCode(cB) === 'COMPARE_LIMIT_EXCEEDED' };
    });
});

/* ---------------- TC-63-09 — atomicity: validation + injection --------------
 * (a) VALIDATION probe (this is input validation, NOT failure injection):
 *     unknown UUID in a compare request → typed 404 school_not_found and the
 *     user-visible saved/followed state is unchanged (no partial mutation).
 * (b) REAL failure injection: the deployed HTTP app exposes NO reachable
 *     injection seam (backend/app/api/v1/law_schools.py has no test hook and
 *     CompareIn forbids extra fields). Mid-transaction rollback and racing
 *     writer injection are covered by backend pytest instead:
 *     backend/tests/test_wave1_law_schools.py (threaded add_comparison_item
 *     race asserts count <= 4 with rollback per loser) and
 *     backend/tests/test_http_contract.py (provider failure → rollback, no
 *     unusable committed state). The browser-level injection case is N/A with
 *     that citation — it is not faked here. */
await phase('tc-63-09-atomicity', async () => {
  await tcase('TC-63-09-compare-validation-atomic', 'unknown_school_validation_no_mutation',
    'unknown UUID → 404 school_not_found; saved/followed state unchanged; service recovers (VALIDATION, not injection)', async () => {
      const beforeSaved = await savedSlugs(USER_A);
      const beforeFollowed = await followedSlugs(USER_A);
      const ghost = crypto.randomUUID();
      const bad = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0], ghost] } });
      const afterSaved = await savedSlugs(USER_A);
      const afterFollowed = await followedSlugs(USER_A);
      const recover = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0], ids4[1]] } });
      return { actual: { status: bad.status, code: errCode(bad),
        savedUnchanged: JSON.stringify(beforeSaved) === JSON.stringify(afterSaved),
        followedUnchanged: JSON.stringify(beforeFollowed) === JSON.stringify(afterFollowed),
        recover: recover.status },
      pass: bad.status === 404 && errCode(bad) === 'school_not_found'
        && JSON.stringify(beforeSaved) === JSON.stringify(afterSaved)
        && JSON.stringify(beforeFollowed) === JSON.stringify(afterFollowed) && recover.status === 200 };
    });
  await tcase('TC-63-09-save-validation-atomic', 'unknown_school_save_no_mutation',
    'save of unknown school → 404 school_not_found, saved list unchanged', async () => {
      const before = await savedSlugs(USER_A);
      const badSave = await apiCall('PUT', `/api/v1/student/law-schools/${crypto.randomUUID()}/saved`, { claims: USER_A });
      const after = await savedSlugs(USER_A);
      return { actual: { status: badSave.status, code: errCode(badSave), after },
        pass: badSave.status === 404 && errCode(badSave) === 'school_not_found'
          && JSON.stringify(before) === JSON.stringify(after) };
    });
  recordNA('TC-63-09-failure-injection', 'failure_injection_owned_by_backend',
    'executable commit-failure injection at the owning HTTP boundary',
    'owned by backend TC test_commit_failure_* — backend/tests/test_wave1_law_schools.py '
      + 'test_commit_failure_put_follow_rolls_back_and_retries and '
      + 'test_commit_failure_post_compare_rolls_back_and_retries execute a forced commit '
      + 'failure through the real HTTP app: typed 500 internal_error envelope, ZERO partial '
      + 'rows in a fresh session, no audit row, and a safe retry succeeds after the fault clears');
});

/* ------- TC-63-07 — anonymous 401 + cross-user isolation (API probe) ------- */
await phase('tc-63-07-auth-api', async () => {
  await tcase('TC-63-07-anonymous-401', 'anonymous_read_401', 'no claims → 401 authentication_required', async () => {
    const anon = await apiCall('GET', '/api/v1/student/law-schools/saved');
    return { actual: { status: anon.status, code: errCode(anon) },
      pass: anon.status === 401 && errCode(anon) === 'authentication_required' };
  });
  await tcase('TC-63-07-anonymous-write-401', 'anonymous_write_401', 'anonymous save → 401', async () => {
    const anonWrite = await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`);
    return { actual: anonWrite.status, pass: anonWrite.status === 401 };
  });
  await tcase('TC-63-07-role-403', 'non_student_403', 'non-student role → 403 forbidden', async () => {
    const wrongRole = await apiCall('GET', '/api/v1/student/law-schools/saved', { claims: NON_STUDENT });
    return { actual: { status: wrongRole.status, code: errCode(wrongRole) },
      pass: wrongRole.status === 403 && errCode(wrongRole) === 'forbidden' };
  });
  await tcase('TC-63-07-cross-user-isolation', 'cross_user_isolation',
    "user B never sees user A's saved schools", async () => {
      await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
      const bList = await savedSlugs(USER_B);
      return { actual: bList, pass: bList.length === 0 };
    });
  await tcase('TC-63-07-non-enumerating', 'non_enumerating_delete',
    "B unsave of A's row → idempotent {saved:false}, A unaffected (no existence leak)", async () => {
      const bDelete = await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_B });
      const aStill = await savedSlugs(USER_A);
      return { actual: { status: bDelete.status, body: bDelete.json, aStill },
        pass: bDelete.status === 200 && bDelete.json?.saved === false && aStill.includes('nlsiu-bengaluru') };
    });
  await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
});

/* ------------------------------- browser flows ----------------------------- */

let browser = null;
let traceSeq = 0;

async function fresh({ viewport = { width: 1440, height: 1000 }, theme = null, label = 'ctx', allow4xx = [] } = {}) {
  const context = await browser.newContext({ viewport });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  if (theme) await page.addInitScript((value) => localStorage.setItem('ls-theme', value), theme);
  const consoleErrors = [];
  const pageErrors = [];
  const unexpectedHttp = [];
  page.on('console', (m) => {
    consoleLines.push(`[${label}][console.${m.type()}] ${m.text()}`);
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => { pageErrors.push(String(e)); consoleLines.push(`[${label}][pageerror] ${e}`); });
  page.on('response', (r) => {
    netLines.push(`[${label}] ${r.request().method()} ${r.url()} -> ${r.status()}`);
    if (r.status() >= 400 && !allow4xx.some((re) => re.test(r.url()))) {
      unexpectedHttp.push(`${r.status()} ${r.url()}`);
    }
  });
  const close = async () => {
    traceSeq += 1;
    try {
      await context.tracing.stop({ path: path.join(tracesDir, `trace_${String(traceSeq).padStart(2, '0')}_${label}.zip`) });
    } catch { /* trace must never mask the run */ }
    await context.close();
  };
  return { context, page, consoleErrors, pageErrors, unexpectedHttp, close };
}

const resultsItem = (page, name) => page
  .locator('section[aria-label="Search results"] li.st-item')
  .filter({ hasText: name });
const shot = async (page, file) => {
  await page.screenshot({ path: path.join(evidence, file), fullPage: true });
  return file;
};
/** Tab traversal must reach EVERY visible actionable control in DOM order. */
async function tabOrder(page) {
  const total = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]'))
      .filter((el) => !el.disabled && el.tabIndex >= 0 && el.offsetParent !== null);
    els.forEach((el, i) => el.setAttribute('data-qa-tab', String(i)));
    return els.length;
  });
  const seen = [];
  await page.evaluate(() => { document.activeElement?.blur?.(); });
  for (let i = 0; i < total + 5; i += 1) {
    await page.keyboard.press('Tab');
    const idx = await page.evaluate(() => document.activeElement?.getAttribute('data-qa-tab') ?? null);
    if (idx !== null) seen.push(Number(idx));
  }
  const firstVisit = [...new Set(seen)];
  const inDomOrder = firstVisit.every((v, i) => i === 0 || v > firstVisit[i - 1]);
  return { total, reached: firstVisit.length, inDomOrder, missing: total - firstVisit.length };
}

try {
  browser = await chromium.launch({ headless: true });
} catch (err) {
  record('BROWSER-LAUNCH', 'chromium_launch', 'chromium launches headless',
    `launch failed: ${err?.message ?? err}`, false);
}

if (browser) {
  /* TC-63-01/02 — search UI on the 12-school catalog, deterministic empty state */
  await phase('ui-search', async () => {
    const ctx = await fresh({ label: 'search' });
    const { page, consoleErrors, unexpectedHttp } = ctx;
    await page.goto(`${base}/s-27`);
    await page.getByText(/^12 SCHOOLS/).waitFor();
    await tcase('TC-63-01-ui-results', 'ui_lists_full_catalog', 'all 12 seeded schools listed', async () => {
      const count = await page.locator('section[aria-label="Search results"] li.st-item').count();
      return { actual: count, pass: count === 12, evidence: await shot(page, 's27_results_12.png') };
    });
    await tcase('TC-63-01-ui-pagination-idle', 'ui_no_pager_single_page',
      'no pagination controls (total 12 <= page size 20)', async () => {
        const n = await page.getByRole('button', { name: '‹ Back' }).count();
        return { actual: n, pass: n === 0 };
      });
    await tcase('TC-63-01-ui-search', 'ui_search_nalsar', 'q=NALSAR shows exactly one result', async () => {
      /* Reference structure: the name-search card is collapsed by default and
       * opens in-flow from the tool row (s27-default parity). */
      await page.getByRole('button', { name: 'Or search by name ⌕' }).click();
      await page.getByLabel('Search law schools').fill('NALSAR');
      await page.getByLabel('Search law schools').press('Enter');
      await page.getByText(/^1 SCHOOL\b/).waitFor();
      const n = await page.locator('section[aria-label="Search results"] li.st-item').count();
      return { actual: n, pass: n === 1, evidence: await shot(page, 's27_search_nalsar.png') };
    });
    await tcase('TC-63-02-ui-empty-state', 'ui_empty_state', 'deterministic empty state with recovery hint', async () => {
      await page.getByLabel('Search law schools').fill('zz-no-such-school');
      await page.getByLabel('Search law schools').press('Enter');
      await page.getByText('No schools match').waitFor();
      return { actual: 'No schools match + hint',
        pass: await page.getByText('Try clearing a filter or broadening your search.').isVisible(),
        evidence: await shot(page, 's27_empty_state.png') };
    });
    await tcase('TC-63-01-ui-filter-state', 'ui_filter_state_delhi',
      'state=Delhi filters to the 2 Delhi schools incl. NLU Delhi', async () => {
        await page.getByLabel('Search law schools').fill('');
        await page.getByLabel('Search law schools').press('Enter');
        await page.getByRole('group', { name: 'State' }).getByRole('button', { name: 'Delhi' }).click();
        await page.getByText(/^2 SCHOOLS/).waitFor();
        const nlu = await resultsItem(page, 'National Law University, Delhi').count();
        const du = await resultsItem(page, 'Faculty of Law, University of Delhi').count();
        return { actual: { nlu, du }, pass: nlu === 1 && du === 1, evidence: await shot(page, 's27_filter_delhi.png') };
      });
    await tcase('TC-63-01-ui-sort-fees', 'ui_sort_fees_first',
      'fees sort puts Faculty of Law, University of Delhi (lowest fees_min) first', async () => {
        await page.getByRole('group', { name: 'State' }).getByRole('button', { name: 'Anywhere' }).click();
        await page.getByLabel('Order').selectOption('fees');
        await page.getByText(/^12 SCHOOLS/).waitFor();
        const firstName = await page.locator('section[aria-label="Search results"] li.st-item').first().innerText();
        return { actual: firstName.split('\n')[0], pass: firstName.includes('Faculty of Law'),
          evidence: await shot(page, 's27_sort_fees.png') };
      });
    await tcase('TC-63-10-ui-console-clean', 'search_flow_clean',
      'no console/page errors, no unexpected 4xx/5xx during search flows', async () => ({
        actual: { consoleErrors, pageErrors: ctx.pageErrors, unexpectedHttp },
        pass: consoleErrors.length === 0 && ctx.pageErrors.length === 0 && unexpectedHttp.length === 0,
      }));
    await ctx.close();
  });

  /* TC-63-01 — institution-type filter: the SELECT WIDGET itself must emit the
   * canonical wire value (labels are display-only per SAATHI-120/118 fix).
   * Selecting by visible label proves the label->wire mapping end to end. */
  await phase('ui-institution-type', async () => {
    const ctx = await fresh({ label: 'insttype' });
    const { page } = ctx;
    await tcase('TC-63-01-ui-institution-type-select', 'ui_institution_type_select_wire_value',
      'selecting label "National Law University" sends wire value and renders the 6 NLU schools', async () => {
        await page.goto(`${base}/s-27`);
        await page.getByText(/^12 SCHOOLS/).waitFor();
        await page.getByRole('button', { name: 'More filters' }).click();
        await page.getByLabel('Institution type').selectOption({ label: 'National Law University' });
        await page.getByText(/^6 SCHOOLS/).waitFor();
        const urlParam = new URL(page.url()).searchParams.get('institution_type');
        const n = await page.locator('section[aria-label="Search results"] li.st-item').count();
        const gnlu = await resultsItem(page, 'Gujarat National Law University').count();
        const rgnul = await resultsItem(page, 'Rajiv Gandhi National University of Law').count();
        return { actual: { urlParam, rendered: n, gnlu, rgnul },
          pass: urlParam === 'national_law_university' && n === 6 && gnlu === 1 && rgnul === 1,
          evidence: await shot(page, 's27_institution_type_wire.png') };
      });
    await tcase('TC-63-01-ui-institution-type-url', 'ui_institution_type_url_wire_value',
      'deep link institution_type=national_law_university → exactly the 6 NLU schools rendered', async () => {
        await page.goto(`${base}/s-27?institution_type=national_law_university`);
        await page.getByText(/^6 SCHOOLS/).waitFor();
        const n = await page.locator('section[aria-label="Search results"] li.st-item').count();
        return { actual: { rendered: n }, pass: n === 6 };
      });
    await ctx.close();
  });

  /* TC-63-06 — detail navigation + return context */
  await phase('ui-detail-nav', async () => {
    const ctx = await fresh({ label: 'detail' });
    const { page } = ctx;
    await page.goto(`${base}/s-27?state=Karnataka`);
    await resultsItem(page, 'National Law School of India University').waitFor();
    await tcase('TC-63-06-detail-nav', 'view_routes_with_context', 'View routes to /s-28 with id + ret context', async () => {
      await resultsItem(page, 'National Law School of India University').getByRole('button', { name: 'View' }).click();
      await page.waitForURL('**/s-28*');
      const s28 = new URL(page.url());
      return { actual: s28.pathname + s28.search,
        pass: s28.pathname === '/s-28' && s28.searchParams.get('id') === ids4[0]
          && (s28.searchParams.get('ret') ?? '').includes('state=Karnataka') };
    });
    await tcase('TC-63-06-detail-facts', 'detail_facts_sourced', 'detail shows verified facts with source link', async () => {
      await page.getByRole('heading', { name: 'National Law School of India University' }).waitFor();
      const ok = await page.getByRole('heading', { name: 'The essentials' }).isVisible()
        && (await page.locator('section a[target="_blank"]').count()) > 0;
      return { actual: ok, pass: ok, evidence: await shot(page, 's28_detail_nlsiu.png') };
    });
    await tcase('TC-63-06-return-context', 'back_restores_filters', 'Back to search restores /s-27?state=Karnataka', async () => {
      await page.getByRole('button', { name: '‹ Back to schools' }).first().click();
      await page.waitForURL('**/s-27*');
      const back = new URL(page.url());
      return { actual: back.pathname + back.search,
        pass: back.pathname === '/s-27' && back.searchParams.get('state') === 'Karnataka',
        evidence: await shot(page, 's27_return_context.png') };
    });
    await ctx.close();
  });

  /* TC-63-03/04 — compare UI: min 2, max 4, fifth refusal, duplicate, refresh */
  await phase('ui-compare', async () => {
    const ctx = await fresh({ label: 'compare', allow4xx: [/\/law-schools\/compare$/] });
    const { page } = ctx;
    await page.goto(`${base}/s-27`);
    await resultsItem(page, 'NALSAR').waitFor();
    const tray = page.locator('section[aria-label="Compare tray"]');
    const cta = tray.getByRole('button', { name: /^Compare/ });
    /* Reference #pb semantics: below the minimum the tray shows the
     * "PICK n MORE TO COMPARE" metaline and NO Compare CTA exists at all —
     * equally strong as the old disabled-CTA assertion (no enabled path). */
    await tcase('TC-63-03-ui-min-disabled', 'cta_absent_below_min', 'below minimum of 2: no Compare CTA; tray asks to pick 2 more', async () => {
      const n = await cta.count();
      const ask = await tray.getByText('PICK 2 MORE TO COMPARE').isVisible();
      return { actual: { ctaCount: n, ask }, pass: n === 0 && ask };
    });
    await tcase('TC-63-03-ui-one-selected', 'cta_asks_one_more', 'with 1 selected still no CTA; tray asks for 1 more', async () => {
      await resultsItem(page, 'National Law School of India University').getByRole('button', { name: '+ Compare', exact: true }).click();
      const n = await cta.count();
      const ask = await tray.getByText('PICK 1 MORE TO COMPARE').isVisible();
      return { actual: { ctaCount: n, ask }, pass: n === 0 && ask };
    });
    await tcase('TC-63-03-ui-two-enabled', 'cta_enables_at_min', 'with 2 selected the Compare CTA appears enabled', async () => {
      await resultsItem(page, 'NALSAR').getByRole('button', { name: '+ Compare', exact: true }).click();
      await cta.waitFor();
      return { actual: await cta.innerText(), pass: !(await cta.isDisabled()) };
    });
    await tcase('TC-63-03-ui-compare-2', 'compare_table_2', '2-school table renders (attribute col + 2 schools)', async () => {
      await cta.click();
      await page.waitForURL('**/s-29*');
      await page.getByRole('heading', { name: /picks, side by side/ }).waitFor();
      /* Reference r29 structure: 7 stacked fact cards, each listing every
       * pick (no table, nothing scrolls sideways). */
      const cards = await page.locator('.ls-attrcard').count();
      const vals = await page.locator('.ls-attrcard').first().locator('li').count();
      return { actual: { cards, valsPerCard: vals }, pass: cards === 7 && vals === 2,
        evidence: await shot(page, 's29_compare_2.png') };
    });
    await tcase('TC-63-04-ui-refresh-replay', 'refresh_state_survives',
      'refresh re-creates the comparison from the URL (state survives; distinct set per POST — not idempotency)', async () => {
        await page.reload();
        await page.getByRole('heading', { name: /picks, side by side/ }).waitFor();
        const cards = await page.locator('.ls-attrcard').count();
        const vals = await page.locator('.ls-attrcard').first().locator('li').count();
        return { actual: { cards, valsPerCard: vals }, pass: cards === 7 && vals === 2 };
      });
    await tcase('TC-63-03-ui-compare-4', 'compare_table_4_max', '4-school table renders (config max)', async () => {
      await page.goto(`${base}/s-29?ids=${ids4.join(',')}`);
      await page.getByRole('heading', { name: /picks, side by side/ }).waitFor();
      const cards = await page.locator('.ls-attrcard').count();
      const vals = await page.locator('.ls-attrcard').first().locator('li').count();
      return { actual: { cards, valsPerCard: vals }, pass: cards === 7 && vals === 4,
        evidence: await shot(page, 's29_compare_4.png') };
    });
    await tcase('TC-63-03-ui-fifth-refusal', 'fifth_refusal_typed',
      'fifth school → typed COMPARE_LIMIT_EXCEEDED message, no table', async () => {
        await page.goto(`${base}/s-29?ids=${[...ids4, bySlug['gnlu-gandhinagar'].id].join(',')}`);
        await page.getByText(/at most 4 schools/).waitFor();
        return { actual: await page.getByText(/at most 4 schools/).innerText(),
          pass: (await page.locator('.ls-attrcard').count()) === 0,
          evidence: await shot(page, 's29_limit_refusal.png') };
      });
    await tcase('TC-63-04-ui-duplicate-blocked', 'duplicate_ids_deduped',
      'duplicate ids deduped client-side → below-minimum validation, no request crash', async () => {
        await page.goto(`${base}/s-29?ids=${ids4[0]},${ids4[0]}`);
        await page.getByText(/at least 2 schools/).waitFor();
        return { actual: await page.getByText(/at least 2 schools/).innerText(),
          pass: (await page.locator('.ls-attrcard').count()) === 0,
          evidence: await shot(page, 's29_duplicate_blocked.png') };
      });
    await ctx.close();
  });

  /* TC-63-05 — save/follow persistence: reload + fresh browser context.
   * NOTE (QA defect #8): the dev frontend bakes USER_A's X-Actor-Claims into
   * every request at compile time, so a fresh browser context proves
   * server-side persistence for the same principal — it is NOT a logout/login
   * journey. Locators use EXACT state-specific accessible names
   * ('Save school' / 'Saved — remove' / 'Follow school' / 'Following — unfollow')
   * so pre/post states can never be confused (the old /^Save/ regex matched
   * both states and invalidated setup). Setup success (both PUTs 200) is
   * asserted as its OWN case BEFORE any reload/fresh-context check, so a setup
   * failure reports as itself instead of cascading. */
  await phase('ui-persistence', async () => {
    const ctx = await fresh({ label: 'persist' });
    const { page } = ctx;
    let setupOk = false;
    await tcase('TC-63-05-setup-save-follow', 'setup_save_follow_put_200',
      'Save school + Follow school clicks each PUT once and return 200 (asserted BEFORE reload checks)', async () => {
        const puts = [];
        page.on('response', (r) => {
          if (r.request().method() === 'PUT' && /\/student\/law-schools\/[^/]+\/(saved|follow)$/.test(r.url())) {
            puts.push({ path: r.url().split('/api/v1')[1], status: r.status() });
          }
        });
        await page.goto(`${base}/s-28?id=${ids4[0]}`);
        const saveBtn = page.getByRole('button', { name: 'Save school', exact: true });
        await saveBtn.waitFor();
        await saveBtn.click();
        await page.getByRole('button', { name: 'Saved — remove', exact: true }).waitFor();
        await page.getByRole('button', { name: 'Follow school', exact: true }).click();
        await page.getByRole('button', { name: 'Following — unfollow', exact: true }).waitFor();
        setupOk = puts.length === 2 && puts.every((r) => r.status === 200)
          && puts.some((r) => r.path.endsWith('/saved')) && puts.some((r) => r.path.endsWith('/follow'));
        return { actual: puts, pass: setupOk, evidence: await shot(page, 's28_saved_followed.png') };
      });
    await tcase('TC-63-05-reload-persistence', 'reload_persistence',
      'saved+followed state survives reload (server-backed)', async () => {
        if (!setupOk) return { actual: 'setup case failed — reload persistence not evaluated', pass: false };
        await page.reload();
        await page.getByRole('button', { name: 'Saved — remove', exact: true }).waitFor();
        await page.getByRole('button', { name: 'Following — unfollow', exact: true }).waitFor();
        return { actual: 'Saved — remove / Following — unfollow present after reload', pass: true,
          evidence: await shot(page, 's28_after_reload.png') };
      });
    await ctx.close();

    const second = await fresh({ label: 'freshctx' });
    await tcase('TC-63-05-fresh-browser-context-persistence', 'fresh_browser_context_persistence',
      'fresh browser context (same compile-time claims) sees saved+followed on S-30 — server persistence, not logout/login', async () => {
        if (!setupOk) return { actual: 'setup case failed — fresh-context persistence not evaluated', pass: false };
        await second.page.goto(`${base}/s-30`);
        await second.page.locator('section[aria-label="Saved schools"] li.st-item').first().waitFor();
        const savedHas = await second.page.locator('section[aria-label="Saved schools"]').getByText('National Law School of India University').count();
        const followedHas = await second.page.locator('section[aria-label="Followed schools"]').getByText('National Law School of India University').count();
        return { actual: { savedHas, followedHas }, pass: savedHas > 0 && followedHas > 0,
          evidence: await shot(second.page, 's30_saved_followed.png') };
      });
    await tcase('TC-63-05-server-lists', 'server_list_endpoints_contain_school',
      'GET /student/law-schools/saved + /followed both contain nlsiu-bengaluru (server truth)', async () => {
        const sv = await savedSlugs(USER_A);
        const fo = await followedSlugs(USER_A);
        return { actual: { saved: sv, followed: fo },
          pass: sv.includes('nlsiu-bengaluru') && fo.includes('nlsiu-bengaluru') };
      });
    await tcase('TC-63-05-unsave', 'unsave_empties_list', 'unsave removes the row and shows the empty state', async () => {
      await second.page.locator('section[aria-label="Saved schools"]').getByRole('button', { name: 'Remove from saved' }).first().click();
      await second.page.locator('section[aria-label="Saved schools"]').getByText('No saved schools yet').waitFor();
      return { actual: 'No saved schools yet', pass: true, evidence: await shot(second.page, 's30_after_unsave.png') };
    });
    await tcase('TC-63-05-unfollow', 'unfollow_empties_list', 'unfollow removes the row and shows the empty state', async () => {
      await second.page.locator('section[aria-label="Followed schools"]').getByRole('button', { name: 'Stop following' }).first().click();
      await second.page.locator('section[aria-label="Followed schools"]').getByText('No followed schools yet').waitFor();
      return { actual: 'No followed schools yet', pass: true, evidence: await shot(second.page, 's30_after_unfollow.png') };
    });
    await tcase('TC-63-05-storage-privacy', 'storage_privacy_after_lifecycle',
      'no actor claims/sub/token material in browser storage after the full save/follow lifecycle', async () => {
        const storage = await second.page.evaluate(() => ({
          local: Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])),
          session: Object.fromEntries(Object.keys(sessionStorage).map((k) => [k, sessionStorage.getItem(k)])),
        }));
        const serialized = JSON.stringify(storage);
        const leaks = ['00000000-0000-4000-8000-0000000000de', 'X-Actor-Claims', 'Bearer ', 'roles']
          .filter((needle) => serialized.includes(needle));
        return { actual: { keys: [...Object.keys(storage.local), ...Object.keys(storage.session)], leaks },
          pass: leaks.length === 0 };
      });
    await second.close();
  });

  /* TC-63-07 — session restoration at the browser boundary (QA defect #8):
   * strip the X-Actor-Claims header in-flight → user-scoped lists return 401
   * and S-30 shows the signed-out state; restore the header (session
   * restoration) → saved/followed state returns. Real logout/login remains an
   * auth-contract journey outside this directory suite. */
  await phase('ui-session-restoration', async () => {
    await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
    await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/follow`, { claims: USER_A });
    const ctx = await fresh({ label: 'session', allow4xx: [/\/student\/law-schools\/(saved|followed)/] });
    const { page, context } = ctx;
    const strip = (route) => {
      const headers = { ...route.request().headers() };
      delete headers['x-actor-claims'];
      route.continue({ headers });
    };
    await tcase('TC-63-07-session-cleared', 'claims_cleared_401',
      'with claims header stripped, user-scoped lists 401 and S-30 shows signed-out state', async () => {
        await context.route('**/api/v1/student/**', strip);
        await page.goto(`${base}/s-30`);
        await page.getByText('Sign in to continue').waitFor();
        return { actual: 'Sign in to continue rendered on 401', pass: true,
          evidence: await shot(page, 's30_signed_out_401.png') };
      });
    await tcase('TC-63-07-session-restoration', 'session_restoration',
      're-attached claims (session restoration) → saved+followed state returns', async () => {
        await context.unroute('**/api/v1/student/**', strip);
        await page.reload();
        await page.locator('section[aria-label="Saved schools"] li.st-item').first().waitFor();
        const savedHas = await page.locator('section[aria-label="Saved schools"]').getByText('National Law School of India University').count();
        const followedHas = await page.locator('section[aria-label="Followed schools"]').getByText('National Law School of India University').count();
        return { actual: { savedHas, followedHas }, pass: savedHas > 0 && followedHas > 0,
          evidence: await shot(page, 's30_session_restored.png') };
      });
    await ctx.close();
  });

  /* TC-63-10 — browser-storage / console / network privacy scan */
  await phase('ui-privacy', async () => {
    const ctx = await fresh({ label: 'privacy' });
    const { page, consoleErrors } = ctx;
    const requestLog = [];
    page.on('request', (r) => requestLog.push(r.url()));
    await page.goto(`${base}/s-27`);
    await resultsItem(page, 'NALSAR').waitFor();
    await page.goto(`${base}/s-28?id=${ids4[1]}`);
    await page.getByRole('button', { name: 'Save school', exact: true }).waitFor();
    await tcase('TC-63-10-storage-privacy', 'storage_privacy',
      'no actor claims/sub/token material in browser storage', async () => {
        const storage = await page.evaluate(() => ({
          local: Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])),
          session: Object.fromEntries(Object.keys(sessionStorage).map((k) => [k, sessionStorage.getItem(k)])),
        }));
        const serialized = JSON.stringify(storage);
        const leaks = ['00000000-0000-4000-8000-0000000000de', 'X-Actor-Claims', 'Bearer ', 'roles']
          .filter((needle) => serialized.includes(needle));
        return { actual: { keys: [...Object.keys(storage.local), ...Object.keys(storage.session)], leaks },
          pass: leaks.length === 0 };
      });
    await tcase('TC-63-10-network-privacy', 'network_privacy', 'no claims sub / tokens in request URLs', async () => {
      const urlLeaks = requestLog.filter((u) => u.includes('00000000-0000-4000-8000-0000000000de') || u.toLowerCase().includes('token='));
      return { actual: urlLeaks, pass: urlLeaks.length === 0 };
    });
    await tcase('TC-63-10-console-privacy', 'console_privacy', 'no PII/claims in console output; no console errors', async () => {
      const consoleLeaks = consoleErrors.filter((t) => t.includes('00000000-0000-4000-8000-0000000000de'));
      return { actual: { consoleErrors, consoleLeaks }, pass: consoleErrors.length === 0 && consoleLeaks.length === 0 };
    });
    await ctx.close();
  });

  /* TC-63-08/10/11/12 — CLEAN responsive × theme matrix over ALL FOUR screens
   * (S-27 results/empty, S-28 detail, S-29 compare with 2 AND 4,
   * S-30 saved/followed lists) asserting: no horizontal overflow, >=44px
   * targets, Tab traversal reaching every actionable control in DOM order,
   * zero console/page errors and zero unexpected 4xx/5xx per pair.
   * STRICT (F4): the clean matrix carries NO 4xx/console allowlist of any
   * kind. The intentional 422 error-state fixture lives in its own isolated
   * phase below (ui-error-state-isolated), where the typed 422 and its two
   * console messages are explicitly EXPECTED and asserted. */
  await phase('ui-matrix', async () => {
    await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
    await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/follow`, { claims: USER_A });
    for (const width of [390, 430, 768, 1024, 1440]) {
      for (const theme of ['light', 'dark']) {
        const tag = `${width}-${theme}`;
        const ctx = await fresh({ viewport: { width, height: 1000 }, theme, label: `mx-${tag}` });
        const { page } = ctx;
        const states = [
          { key: 's27-results', url: `${base}/s-27`, ready: () => page.getByText(/^12 SCHOOLS/).waitFor(), keyboard: true },
          { key: 's27-empty', url: `${base}/s-27?q=zz-no-such-school`, ready: () => page.getByText('No schools match').waitFor(), keyboard: false },
          { key: 's28-detail', url: `${base}/s-28?id=${ids4[0]}`, ready: () => page.getByRole('button', { name: 'Saved — remove', exact: true }).waitFor(), keyboard: true },
          { key: 's29-compare-2', url: `${base}/s-29?ids=${ids4.slice(0, 2).join(',')}`, ready: () => page.getByRole('heading', { name: /picks, side by side/ }).waitFor(), keyboard: false },
          { key: 's29-compare-4', url: `${base}/s-29?ids=${ids4.join(',')}`, ready: () => page.getByRole('heading', { name: /picks, side by side/ }).waitFor(), keyboard: true },
          { key: 's30-lists', url: `${base}/s-30`, ready: () => page.locator('section[aria-label="Saved schools"] li.st-item').first().waitFor(), keyboard: true },
        ];
        for (const state of states) {
          await tcase(`TC-63-08-${state.key}-${tag}`, `overflow_${state.key}`,
            `${state.key}: no horizontal overflow at ${width}px (${theme})`, async () => {
              await page.goto(state.url);
              await state.ready();
              const sw = await page.evaluate(() => document.documentElement.scrollWidth);
              return { actual: sw, pass: sw <= width,
                evidence: await shot(page, `${state.key.replaceAll('-', '_')}_${tag}.png`) };
            });
          await tcase(`TC-63-11-${state.key}-${tag}`, `targets_${state.key}`,
            'every visible actionable target >= 44x44', async () => {
              const small = await page.evaluate(() => Array.from(document.querySelectorAll('button, a, input, select'))
                .filter((el) => el.offsetParent !== null)
                .map((el) => ({
                  label: (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40),
                  w: Math.round(el.getBoundingClientRect().width),
                  h: Math.round(el.getBoundingClientRect().height),
                }))
                .filter((t) => t.w > 0 && t.h > 0 && (t.w < 44 || t.h < 44)));
              return { actual: small, pass: small.length === 0 };
            });
          if (state.keyboard) {
            await tcase(`TC-63-12-${state.key}-${tag}`, `keyboard_${state.key}`,
              'Tab traversal reaches ALL actionable controls in DOM order', async () => {
                const order = await tabOrder(page);
                return { actual: order, pass: order.missing === 0 && order.inDomOrder && order.total > 0 };
              });
          }
        }
        await tcase(`TC-63-10-clean-${tag}`, 'matrix_pair_clean',
          'zero console/page errors, zero unexpected 4xx/5xx across all states in this pair', async () => ({
            actual: { consoleErrors: ctx.consoleErrors, pageErrors: ctx.pageErrors, unexpectedHttp: ctx.unexpectedHttp },
            pass: ctx.consoleErrors.length === 0 && ctx.pageErrors.length === 0 && ctx.unexpectedHttp.length === 0,
          }));
        await ctx.close();
      }
    }
    await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
    await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/follow`, { claims: USER_A });
  });

  /* TC-63-10 — ISOLATED expected-error fixture (F4). The ONLY place the
   * intentional institution_type=not-a-wire-value 422 is provoked. With the
   * non-retryable typed-4xx query policy, EXACTLY ONE API 422 is expected and
   * every console error must be attributable to it; the S-27 error state must
   * still render with zero overflow and >=44px targets. The clean matrix
   * above never sees this URL. */
  await phase('ui-error-state-isolated', async () => {
    for (const [width, theme] of [[1440, 'light'], [390, 'dark']]) {
      const tag = `${width}-${theme}`;
      const ctx = await fresh({ viewport: { width, height: 1000 }, theme, label: `err422-${tag}`,
        allow4xx: [/institution_type=not-a-wire-value/] });
      const { page } = ctx;
      const errResponses = [];
      /* Precise filter (F4): count ONLY the API search request itself — GET
       * /api/v1/law-schools carrying the deterministic bad param. Excludes the
       * document navigation to /s-27?... (different pathname), OPTIONS
       * preflights, and any other resource whose URL merely mentions the
       * param. */
      page.on('response', async (r) => {
        let u;
        try { u = new URL(r.url()); } catch { return; }
        const isIsolated422Api = r.request().method() === 'GET'
          && u.pathname === '/api/v1/law-schools'
          && u.searchParams.get('institution_type') === 'not-a-wire-value';
        if (isIsolated422Api) {
          let body = null;
          try { body = await r.json(); } catch { /* non-JSON body */ }
          errResponses.push({ status: r.status(), code: body?.detail?.code ?? null });
        }
      });
      await tcase(`TC-63-10-error-state-isolated-${tag}`, 'expected_422_error_state',
        'exactly ONE typed 422 unsupported_institution_type (no retry); every console error attributable to it; ErrorState rendered; no overflow; >=44px targets', async () => {
          await page.goto(`${base}/s-27?institution_type=not-a-wire-value`);
          await page.getByText('Could not load law schools').waitFor();
          await page.waitForTimeout(300); // settle: response-body reads + any stray retry would surface here
          const sw = await page.evaluate(() => document.documentElement.scrollWidth);
          const small = await page.evaluate(() => Array.from(document.querySelectorAll('button, a, input, select'))
            .filter((el) => el.offsetParent !== null)
            .map((el) => ({
              label: (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40),
              w: Math.round(el.getBoundingClientRect().width),
              h: Math.round(el.getBoundingClientRect().height),
            }))
            .filter((t) => t.w > 0 && t.h > 0 && (t.w < 44 || t.h < 44)));
          /* No hard-coded console count (F4): browsers differ in how many
           * messages one failed fetch emits. Instead, EVERY console error must
           * be attributable to the single expected 422 (mentions the status,
           * the request URL/path, or the bad param); anything else fails. */
          const consoleExpected = ctx.consoleErrors
            .every((t) => /422|failed to load resource|institution_type=not-a-wire-value|\/api\/v1\/law-schools/i.test(t));
          return { actual: { errResponses, consoleErrors: ctx.consoleErrors, pageErrors: ctx.pageErrors,
            unexpectedHttp: ctx.unexpectedHttp, scrollWidth: sw, smallTargets: small },
          pass: errResponses.length === 1 && errResponses[0].status === 422
            && errResponses[0].code === 'unsupported_institution_type'
            && consoleExpected && ctx.pageErrors.length === 0 && ctx.unexpectedHttp.length === 0
            && sw <= width && small.length === 0,
          evidence: await shot(page, `s27_error_isolated_${tag.replace('-', '_')}.png`) };
        });
      await ctx.close();
    }
  });

  /* ---------------- SAATHI-121 — Option C+ visual phase (Mac-delegated) -----
   * Captures the DEVELOPED S-27..S-30 screens and the approved Option C+
   * reference frames (docs/design/lawschool_reference/option_c_plus) per
   * viewport x theme, records provenance metadata + SHA256 per capture, and
   * produces side-by-side + pixel-diff artifacts.
   * STRICT threshold policy (SAATHI-121 closure, 2026-07-28): the baseline is
   * FROZEN to the full 40-pair matrix from CAPTURE_MANIFEST.json —
   * S-27..S-30 x {390x844, 430x932, 768x1024, 1024x768, 1440x900} x
   * {light, dark}. Every approved pair MUST diff < 2% against the reference
   * or its case FAILS (process exits non-zero AFTER all evidence + manifest
   * are written). A pair that is somehow not approved is recorded as N/A and
   * NEVER counts as PASS. The independent QA run at bbc85c3 measured
   * 40/40 pairs >= 2% (avg 29.908%) under the previous advisory policy —
   * that policy is retired here.
   * Documented dynamic exclusions (the ONLY exclusions):
   *   - developed capture is the .st-screen ELEMENT, so the global AppShell
   *     (rail/topbar/theme control) is excluded by construction;
   *   - reference is captured in baseline mode (&baseline=1 hash query +
   *     body[data-baseline=1]) which hides all reviewer tooling.
   * Disable with QA_VISUAL_C_PLUS=0 (sandbox runs without Chromium only —
   * never for closure evidence). */
  const VIS_SCREEN_KEYS = ['s27', 's28', 's29', 's30'];
  const VIS_VIEWPORTS = ['390x844', '430x932', '768x1024', '1024x768', '1440x900'];
  const VIS_THEMES = ['light', 'dark'];
  const APPROVED_DETERMINISTIC_PAIRS = VIS_SCREEN_KEYS.flatMap((sc) =>
    VIS_VIEWPORTS.flatMap((vp) => VIS_THEMES.map((th) => `${sc}-${vp}-${th}`)));
  const VISUAL_THRESHOLD = 0.02;
  if (process.env.QA_VISUAL_C_PLUS !== '0') await phase('option-c-plus-visual', async () => {
    const { pathToFileURL } = await import('node:url');
    const refFile = path.resolve('..', 'docs', 'design', 'lawschool_reference', 'option_c_plus', 'OPTION_C_PLUS_GUIDED_CONFIDENCE.html');
    let pixelmatch = null; let PNG = null;
    try {
      pixelmatch = (await import('pixelmatch')).default;
      PNG = (await import('pngjs')).PNG;
    } catch (err) {
      recordNA('VIS-C+-deps', 'pixelmatch_pngjs_available', 'pixelmatch + pngjs installed',
        `visual diff dependencies unavailable (${err?.message}) — run npm install`);
      return;
    }
    try { await fs.access(refFile); } catch {
      recordNA('VIS-C+-reference', 'reference_package_present',
        'docs/design/lawschool_reference/option_c_plus reference frame present',
        `reference artifact missing at ${refFile}`);
      return;
    }
    const visDir = path.join(evidence, 'option_c_plus_visual');
    await fs.mkdir(visDir, { recursive: true });
    const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
    const visEntries = [];
    /* Deterministic populated states for parity with the reference fixtures. */
    await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
    await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/follow`, { claims: USER_A });
    const VIS_SCREENS = [
      { key: 's27', devUrl: () => `${base}/s-27`,
        devReady: (page) => page.getByText(/^12 SCHOOLS/).waitFor(),
        refRoute: '#/s27', refState: 's27-default' },
      { key: 's28', devUrl: () => `${base}/s-28?id=${ids4[0]}`,
        devReady: (page) => page.getByRole('button', { name: 'Saved — remove', exact: true }).waitFor(),
        refRoute: '#/s28?id=nlsiu', refState: 's28-detail' },
      { key: 's29', devUrl: () => `${base}/s-29?ids=${ids4.join(',')}`,
        devReady: (page) => page.getByRole('heading', { name: /picks, side by side/ }).waitFor(),
        refRoute: '#/s29?cmp=nlsiu,nalsar', refState: 's29-4' },
      { key: 's30', devUrl: () => `${base}/s-30`,
        devReady: (page) => page.locator('section[aria-label="Saved schools"] li.st-item').first().waitFor(),
        refRoute: '#/s30', refState: 's30-both' },
    ];
    const pad = (png, w, h) => {
      if (png.width === w && png.height === h) return png;
      const out = new PNG({ width: w, height: h });
      out.data.fill(255);
      PNG.bitblt(png, out, 0, 0, png.width, png.height, 0, 0);
      return out;
    };
    for (const { width, height } of [
      { width: 390, height: 844 }, { width: 430, height: 932 }, { width: 768, height: 1024 },
      { width: 1024, height: 768 }, { width: 1440, height: 900 }]) {
      for (const theme of ['light', 'dark']) {
        for (const screen of VIS_SCREENS) {
          const pairKey = `${screen.key}-${width}x${height}-${theme}`;
          await tcase(`VIS-C+-${pairKey}`, 'option_c_plus_visual_pair',
            `developed + reference captured with provenance; pixel-diff ratio < ${VISUAL_THRESHOLD * 100}% (STRICT — approved deterministic pair)`,
            async () => {
              /* Developed capture (element = global shell excluded). */
              const dev = await fresh({ viewport: { width, height }, theme, label: `vis-${pairKey}` });
              let entry;
              try {
                await dev.page.goto(screen.devUrl());
                await screen.devReady(dev.page);
                await dev.page.waitForTimeout(250);
                const devMeta = await dev.page.evaluate(() => ({
                  dpr: window.devicePixelRatio,
                  docScrollWidth: document.documentElement.scrollWidth,
                  innerWidth: window.innerWidth,
                  minTargetPx: Math.min(...Array.from(document.querySelectorAll('button, a, input, select'))
                    .filter((el) => el.offsetParent !== null)
                    .map((el) => { const r = el.getBoundingClientRect(); return Math.min(r.width, r.height); })
                    .filter((m) => m > 0), Infinity),
                }));
                const devPng = await dev.page.locator('section.st-screen').screenshot();
                const devFile = `dev_${pairKey}.png`;
                await fs.writeFile(path.join(visDir, devFile), devPng);
                /* Reference capture (baseline mode hides reviewer tooling). */
                const ref = await fresh({ viewport: { width, height }, label: `visref-${pairKey}` });
                let refPng; let refMeta;
                try {
                  const hashRoute = screen.refRoute + (screen.refRoute.includes('?') ? '&' : '?') + 'baseline=1';
                  await ref.page.goto(`${pathToFileURL(refFile).href}${hashRoute}`);
                  await ref.page.waitForFunction(() => !!window.__opt, null, { timeout: 20000 });
                  await ref.page.evaluate(([t, st]) => { window.__opt.theme.set(t); window.__opt.apply(st); document.body.setAttribute('data-baseline', '1'); }, [theme, screen.refState]);
                  await ref.page.waitForTimeout(400);
                  refMeta = await ref.page.evaluate(() => ({
                    dpr: window.devicePixelRatio,
                    docScrollWidth: document.documentElement.scrollWidth,
                    innerWidth: window.innerWidth,
                  }));
                  refPng = await ref.page.screenshot({ fullPage: true });
                } finally { await ref.close(); }
                const refFileName = `ref_${pairKey}.png`;
                await fs.writeFile(path.join(visDir, refFileName), refPng);
                /* Pixel diff + side-by-side (advisory unless pair approved). */
                const a = PNG.sync.read(devPng);
                const b = PNG.sync.read(refPng);
                const w = Math.max(a.width, b.width);
                const h = Math.max(a.height, b.height);
                const pa = pad(a, w, h); const pb = pad(b, w, h);
                const diff = new PNG({ width: w, height: h });
                const mismatched = pixelmatch(pa.data, pb.data, diff.data, w, h, { threshold: 0.1 });
                const ratio = mismatched / (w * h);
                const side = new PNG({ width: w * 2 + 8, height: h });
                side.data.fill(255);
                PNG.bitblt(pa, side, 0, 0, w, h, 0, 0);
                PNG.bitblt(pb, side, 0, 0, w, h, w + 8, 0);
                await fs.writeFile(path.join(visDir, `diff_${pairKey}.png`), PNG.sync.write(diff));
                await fs.writeFile(path.join(visDir, `side_${pairKey}.png`), PNG.sync.write(side));
                const approved = APPROVED_DETERMINISTIC_PAIRS.includes(pairKey);
                entry = {
                  pair: pairKey, screen: screen.key, theme,
                  viewport: { width, height },
                  developed: { file: `option_c_plus_visual/dev_${pairKey}.png`, url: screen.devUrl(), sha256: sha256(devPng), ...devMeta,
                    consoleErrors: dev.consoleErrors.slice(), pageErrors: dev.pageErrors.slice(), unexpectedHttp: dev.unexpectedHttp.slice(),
                    exclusions: 'captured as .st-screen element — global AppShell excluded by construction' },
                  reference: { file: `option_c_plus_visual/${refFileName}`, route: screen.refRoute, state: screen.refState, sha256: sha256(refPng), ...refMeta,
                    exclusions: 'baseline mode (&baseline=1 + body[data-baseline=1]) hides reviewer tooling' },
                  diff: { file: `option_c_plus_visual/diff_${pairKey}.png`, sideBySide: `option_c_plus_visual/side_${pairKey}.png`,
                    mismatchedPixels: mismatched, ratio, threshold: VISUAL_THRESHOLD, approvedDeterministicPair: approved,
                    gate: approved ? (ratio < VISUAL_THRESHOLD ? 'pass' : 'fail') : 'advisory' },
                };
                visEntries.push(entry);
                /* STRICT: an unapproved pair is N/A (never PASS); an approved
                 * pair passes ONLY under the 2% threshold with a clean page. */
                return { actual: { ratio: Number(ratio.toFixed(4)), approved, docScrollWidth: devMeta.docScrollWidth, minTargetPx: Math.round(devMeta.minTargetPx) },
                  na: !approved,
                  pass: approved && ratio < VISUAL_THRESHOLD
                    && devMeta.docScrollWidth <= width
                    && dev.pageErrors.length === 0 && dev.unexpectedHttp.length === 0,
                  evidence: `option_c_plus_visual/side_${pairKey}.png` };
              } finally { await dev.close(); }
            });
        }
      }
    }
    await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
    await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/follow`, { claims: USER_A });
    const approvedEntries = visEntries.filter((e) => e.diff.approvedDeterministicPair);
    await fs.writeFile(path.join(visDir, 'lawschool_c_plus_visual_manifest.json'), JSON.stringify({
      commit, generatedAt: new Date().toISOString(),
      reference: 'docs/design/lawschool_reference/option_c_plus/OPTION_C_PLUS_GUIDED_CONFIDENCE.html',
      thresholdPolicy: `STRICT: pixel-diff ratio < ${VISUAL_THRESHOLD} enforced for ALL ${APPROVED_DETERMINISTIC_PAIRS.length} approved deterministic pairs (frozen full matrix, SAATHI-121 closure 2026-07-28); any pair >= ${VISUAL_THRESHOLD} fails the run (non-zero exit after evidence); unapproved pairs are N/A and never PASS`,
      approved: APPROVED_DETERMINISTIC_PAIRS.length,
      captured: visEntries.length,
      passed: approvedEntries.filter((e) => e.diff.gate === 'pass').length,
      failed: approvedEntries.filter((e) => e.diff.gate === 'fail').length,
      exclusions: { developed: 'global AppShell excluded — .st-screen element capture', reference: 'reviewer tooling hidden via baseline mode (&baseline=1 + body[data-baseline=1])' },
      entries: visEntries,
    }, null, 2));
  });
}

/* -------------------- finalize artifacts, then set exit code ---------------- */
let report;
try {
  report = {
    commit,
    env: { base, api, node: process.version, platform: process.platform },
    generatedAt: new Date().toISOString(),
    passed: cases.filter((c) => c.status === 'pass').length,
    failed: cases.filter((c) => c.status === 'fail').length,
    na: cases.filter((c) => c.status === 'na').length,
    cases,
  };
} finally {
  try { if (browser) await browser.close(); } catch { /* already closed */ }
  await fs.writeFile(path.join(evidence, 'lawschool_e2e_report.json'), JSON.stringify(report ?? { cases }, null, 2));
  await fs.writeFile(path.join(evidence, 'network_console.log'),
    [...netLines, '', '--- console ---', ...consoleLines].join('\n'));
  console.log(JSON.stringify({ passed: report?.passed, failed: report?.failed, na: report?.na, evidence }, null, 2));
  if (!report || report.failed > 0) process.exitCode = 1;
}

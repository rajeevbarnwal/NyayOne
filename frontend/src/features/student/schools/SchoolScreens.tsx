import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useNavigationType, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { StudentScreen, SelectField, Checkbox } from '../components';
import { useTheme } from '../../../hooks/useTheme';
import {
  searchLawSchools,
  getLawSchoolDetail,
  compareLawSchools,
  saveLawSchool,
  unsaveLawSchool,
  followLawSchool,
  unfollowLawSchool,
  listSavedLawSchools,
  listFollowedLawSchools,
  addToCompareSelection,
  compareSelectionState,
  LawSchoolsApiError,
  isRetryableLawSchoolsError,
  COMPARE_MIN,
  DEFAULT_COMPARE_MAX,
  COMPARE_LIMIT_EXCEEDED,
  COMPARE_MIN_NOT_MET,
  DUPLICATE_SCHOOL,
  SCHOOL_NOT_FOUND,
  type LawSchoolDetail,
  type LawSchoolSearchParams,
  type LawSchoolSort,
  type LawSchoolSummary,
} from '../lib/lawSchoolsApi';

/**
 * Query retry policy (F4): never retry typed 4xx (deterministic verdicts such
 * as 422 unsupported_institution_type — a retry would duplicate the observable
 * error); allow at most one retry for network failures / 5xx. Overrides the
 * global queryClient `retry: 1`.
 */
const lawSchoolsRetry = (failureCount: number, error: unknown): boolean =>
  isRetryableLawSchoolsError(error) && failureCount < 1;

/* ---------------- Option C+ STRUCTURAL integration (SAATHI-118/120/121) ----
 * Reference package: docs/design/lawschool_reference/option_c_plus (approved
 * "Guided Confidence" direction, corrections 2026-07-27). This file
 * replicates the reference frame STRUCTURE per screen — scoped top header +
 * wordmark, guided step header and sticky pick tray (S-27), identity block +
 * essentials fact list (S-28), stacked per-fact attribute cards with an
 * in-flow "Differences only" switch (S-29), distinct Saved/Following groups
 * (S-30), fixed bottom tab bar — not just the palette. Structure source of
 * truth: OPTION_C_PLUS_GUIDED_CONFIDENCE.html (template r27/r28/r29/r30).
 * All functional behaviour is unchanged: real API adapter, typed errors,
 * compare 2/4/5/duplicate semantics, idempotent save/follow, URL state.
 * No AppShell/App.tsx/global nav edits — everything here renders inside the
 * .st-screen feature region that the visual gate captures.
 * -------------------------------------------------------------------------- */

/**
 * F1 — deterministic destination scroll/focus. A forward navigation (PUSH or
 * REPLACE) presents the destination from its heading: scroll to top, then move
 * focus to the screen heading (tabindex=-1, preventScroll — headings carry no
 * aria-live, so there is no double announcement). Browser Back/Forward (POP)
 * is left to native scroll restoration, so the prior position is preserved.
 * Runs once per screen mount — same-route re-renders never steal focus.
 */
function useRouteArrival(screenKey: string): void {
  const navType = useNavigationType();
  useEffect(() => {
    if (navType === 'POP') return; // Back/Forward: browser restores scroll
    window.scrollTo(0, 0);
    const heading = document.querySelector<HTMLElement>('.st-lawschool h1');
    if (heading) {
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
    // Mount-only per screen (deps intentionally exclude navType): re-running
    // on param-driven re-renders would steal focus from form controls.
  }, [screenKey]);
}

/** Monograms only (frozen decision): 2-letter serif initials, no logos. */
function monogram(name: string): string {
  const words = name.split(/[\s,]+/).filter((w) => /^[A-Za-z]/.test(w));
  return ((words[0]?.[0] ?? '') + (words[1]?.[0] ?? '')).toUpperCase();
}

/** Compact display handle for S-29 chips/fact rows (reference uses seeded
 * shorts like "NLSIU"; the live catalogue derives an equivalent handle). */
function shortName(name: string): string {
  const words = name.split(/[\s,]+/).filter(Boolean);
  const allCaps = words.find((w) => /^[A-Z]{3,}$/.test(w));
  if (allCaps) return allCaps;
  const stop = new Set(['of', 'the', 'and', 'for']);
  return words
    .filter((w) => !stop.has(w.toLowerCase()) && /^[A-Za-z]/.test(w))
    .map((w) => w[0].toUpperCase())
    .join('')
    .slice(0, 6);
}

function lakhText(n: number): string {
  return `₹${(n / 100000).toFixed(1).replace(/\.0$/, '')} L`;
}

function feesText(s: LawSchoolSummary): string {
  const fmt = (n: number) => `₹${n.toLocaleString('en-IN')}`;
  return `${fmt(s.feesMin)}–${fmt(s.feesMax)}/yr`;
}

/* ------------------------- compare tray (ids only) ------------------------- */
/* In-memory module store (profileStore pattern) — opaque school ids + display */
/* names only; never persisted to browser storage.                             */

interface TrayEntry {
  id: string;
  name: string;
}

let compareTray: TrayEntry[] = [];

function readCompareTray(): TrayEntry[] {
  return compareTray;
}

function writeCompareTray(entries: TrayEntry[]): TrayEntry[] {
  compareTray = entries;
  return entries;
}

/* ------------------------------ URL helpers -------------------------------- */

const SEARCH_KEYS = [
  'q',
  'state',
  'institution_type',
  'degree',
  'accreditation',
  'entrance_exam',
  'fees_max',
  'sort',
  'page',
  'page_size',
] as const;

/** Extract only the S-27 search/filter keys as a return-context query string. */
function searchContext(sp: URLSearchParams): string {
  const keep = new URLSearchParams();
  for (const key of SEARCH_KEYS) {
    const value = sp.get(key);
    if (value) keep.set(key, value);
  }
  return keep.toString();
}

function isSort(value: string | null): value is LawSchoolSort {
  return value === 'name' || value === 'fees' || value === 'nirf_rank';
}

function paramsFromUrl(sp: URLSearchParams): LawSchoolSearchParams {
  const feesMaxRaw = sp.get('fees_max');
  const feesMax = feesMaxRaw ? Number(feesMaxRaw) : NaN;
  const pageRaw = Number(sp.get('page') ?? '1');
  /* page_size is a supported wire param (backend-validated 1..50). The visual
   * oracle pins the S-27 baseline to the reference pagination state
   * (6 records/page — see scripts/lawschool_fixture_contract.json); default
   * stays 20 for normal navigation. */
  const pageSizeRaw = Number(sp.get('page_size') ?? '20');
  return {
    q: sp.get('q') ?? undefined,
    state: sp.get('state') ?? undefined,
    institutionType: sp.get('institution_type') ?? undefined,
    degree: sp.get('degree') ?? undefined,
    accreditation: sp.get('accreditation') ?? undefined,
    entranceExam: sp.get('entrance_exam') ?? undefined,
    feesMax: Number.isFinite(feesMax) && feesMax > 0 ? feesMax : undefined,
    sort: isSort(sp.get('sort')) ? (sp.get('sort') as LawSchoolSort) : undefined,
    page: Number.isInteger(pageRaw) && pageRaw > 0 ? pageRaw : 1,
    pageSize: Number.isInteger(pageSizeRaw) && pageSizeRaw >= 1 && pageSizeRaw <= 50 ? pageSizeRaw : 20,
  };
}

/* --------------------- Option C+ shared structural frame ------------------- */

/**
 * Reference frame chrome (template `.top` header + `.tabbar`), scoped to the
 * law-school feature region — NOT the global AppShell. The reference baseline
 * captures include this header (wordmark + Theme control) and the bottom tab
 * bar, so the developed screens must carry the same structure inside
 * `.st-screen` for the 40-pair visual gate.
 */
function LsShell({
  active,
  ctx,
  children,
}: {
  active: 's27' | 's29' | 's30';
  ctx?: string;
  children: ReactNode;
}) {
  const { toggleTheme } = useTheme();
  const dirTo = `/s-27${ctx ? `?${ctx}` : ''}`;
  return (
    <>
      <header className="ls-top">
        <div className="ls-wm">
          <span className="ls-mk" aria-hidden="true">§</span> LegalSaathi
          <span className="ls-sub">Find your law school · Option C+ · Guided Confidence</span>
        </div>
        <span className="ls-flex1" />
        <button type="button" className="ls-ibtn" aria-label="Switch colour theme" onClick={toggleTheme}>
          Theme
        </button>
      </header>
      {children}
      <nav className="ls-tabbar" aria-label="Law school sections">
        <Link to={dirTo} aria-current={active === 's27' ? 'page' : undefined}>
          <span aria-hidden="true">⌂</span>Directory
        </Link>
        <Link to="/s-29" aria-current={active === 's29' ? 'page' : undefined}>
          <span aria-hidden="true">⇄</span>Compare
        </Link>
        <Link to="/s-30" aria-current={active === 's30' ? 'page' : undefined}>
          <span aria-hidden="true">★</span>My schools
        </Link>
      </nav>
    </>
  );
}

/** Reference `.skel` loading blocks (motion spec: shimmer gated by
 * prefers-reduced-motion in CSS; markup is a plain aria-busy container). */
function Skel({ h, maxW, mt }: { h: number; maxW?: number; mt?: number }) {
  return <div className="ls-skel" style={{ height: h, maxWidth: maxW, marginTop: mt }} />;
}

/** Reference `.chp` choice chip — aria-pressed authoritative; the check glyph
 * renders only when selected and is aria-hidden (F2). */
function Chip({ pressed, label, onClick }: { pressed: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" className="ls-chp" aria-pressed={pressed} onClick={onClick}>
      {pressed && <span className="ls-ckg" aria-hidden="true">✓ </span>}
      {label}
    </button>
  );
}

function LsTags({ followed }: { followed?: boolean }) {
  return (
    <div className="ls-tags">
      <span className="ls-tag ls-tag--v"><span className="ls-gl" aria-hidden="true" />Verified source</span>
      <span className="ls-tag ls-tag--warn"><span className="ls-gl" aria-hidden="true" />Sample data · prototype</span>
      {followed && <span className="ls-tag ls-tag--teal"><span className="ls-gl" aria-hidden="true" />Following</span>}
    </div>
  );
}

const RESPONSIBLE_COPY =
  'Verify every fact on the institution’s official website before acting on it. '
  + 'This directory shows sample directory data with source context; it is not admission guidance.';
const DPDP_COPY =
  'Saved and followed lists are stored against your account under the DPDP Act, 2023 — export or delete them anytime in Privacy.';
const FOLLOW_COPY =
  'Following marks a school for future verified updates. Prototype: no notifications are sent.';

function SignInPrompt() {
  const nav = useNavigate();
  return (
    <div className="ls-panelbox" role="alert">
      <h2>Sign in to continue</h2>
      <p>You need to be signed in as a student to use this area. Your lists are private to your account.</p>
      <button type="button" className="btn ls-solid tap" onClick={() => nav('/s-03')}>
        Go to sign in
      </button>
    </div>
  );
}

function QueryFailure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error instanceof LawSchoolsApiError && error.status === 401) {
    return <SignInPrompt />;
  }
  const detail = error instanceof LawSchoolsApiError
    ? `The directory service reported: ${error.code}. Your selections were not changed.`
    : 'Network problem — check your connection and try again. Your selections were not changed.';
  return (
    <div className="ls-panelbox" role="alert">
      <h2>Could not load law schools</h2>
      <p>{detail}</p>
      <button type="button" className="btn ls-solid tap" onClick={onRetry}>Try again</button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* S-27 — Guided search & filter (reference r27 structure)                     */
/* -------------------------------------------------------------------------- */

const STATES = ['Delhi', 'Karnataka', 'Maharashtra', 'Tamil Nadu', 'Telangana', 'Uttar Pradesh', 'West Bengal'];
/* Filter options emit canonical WIRE values (query params); labels are display-only.
 * institution_type wire values are frozen in backend/app/models/wave1.py INSTITUTION_TYPES. */
const INSTITUTION_TYPES: Array<{ value: string; label: string }> = [
  { value: 'national_law_university', label: 'National Law University' },
  { value: 'government', label: 'Government' },
  { value: 'private', label: 'Private' },
  { value: 'deemed', label: 'Deemed' },
];
const DEGREES = [
  { value: 'BA LLB (Hons)', label: 'BA LLB (Hons.)' },
  'BBA LLB', 'LLB', 'LLM',
];
const ACCREDITATIONS = ['NAAC A++', 'NAAC A+', 'NAAC A', 'BCI approved'];
const ENTRANCE_EXAMS = [
  'CLAT', 'AILET',
  { value: 'LSAT-India', label: 'LSAT—India' },
  'MH CET Law', 'Own exam',
];
/* Guided budget bands (reference stephead step 2) — values are the same
 * fees_max WIRE param the free-form filter uses. */
const FEE_BANDS: Array<[string, string]> = [
  ['', 'No limit'],
  ['240000', 'Up to ₹2.4 L'],
  ['280000', 'Up to ₹2.8 L'],
  ['330000', 'Up to ₹3.3 L'],
];
const SORT_LABELS: Record<LawSchoolSort, string> = {
  name: 'A–Z',
  fees: 'LOWEST FEES',
  nirf_rank: 'NIRF RANK',
};

export function SchoolSearch() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const params = useMemo(() => paramsFromUrl(sp), [sp]);
  const [qInput, setQInput] = useState(params.q ?? '');
  const [tray, setTray] = useState<TrayEntry[]>(readCompareTray);
  const [trayMsg, setTrayMsg] = useState<string | null>(null);
  /* Reference r27: the name search and the advanced filters are collapsed by
   * default (s27-default state) and open in-flow from the tool row. */
  const [showSearch, setShowSearch] = useState(Boolean(params.q));
  const [showFilters, setShowFilters] = useState(false);

  const query = useQuery({
    queryKey: ['law-schools', searchContext(sp)],
    queryFn: () => searchLawSchools(params),
    retry: lawSchoolsRetry,
  });

  const compareMax = query.data?.compareMax ?? DEFAULT_COMPARE_MAX;
  const trayIds = tray.map((t) => t.id);
  const selection = compareSelectionState(trayIds, compareMax);
  const ctx = searchContext(sp);

  function setParam(key: string, value: string): void {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setSp(next);
  }

  function addToTray(school: LawSchoolSummary): void {
    const result = addToCompareSelection(trayIds, school.id, compareMax);
    if (!result.ok) {
      setTrayMsg(
        result.reason === 'duplicate'
          ? `${school.name} is already in your comparison — each school can appear once.`
          : `You can compare up to ${result.maxAllowed} schools — remove one first. Nothing was changed.`,
      );
      return;
    }
    setTrayMsg(null);
    setTray(writeCompareTray([...tray, { id: school.id, name: school.name }]));
  }

  function removeFromTray(id: string): void {
    setTrayMsg(null);
    setTray(writeCompareTray(tray.filter((t) => t.id !== id)));
  }

  const total = query.data?.total ?? 0;
  const pageSize = query.data?.pageSize ?? 20;
  const page = query.data?.page ?? params.page ?? 1;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const whereDone = Boolean(params.state);
  const budgetDone = params.feesMax !== undefined;
  const answered = whereDone || budgetDone;
  const sortKey: LawSchoolSort = params.sort ?? 'name';

  /** Evidence-led "Matches" line — built ONLY from the user's own answers. */
  function whyMatch(s: LawSchoolSummary): string[] {
    const why: string[] = [];
    if (params.state && s.state === params.state) why.push(`${params.state} — your pick`);
    if (params.feesMax !== undefined && s.feesMax <= params.feesMax) {
      why.push(`fees within ${lakhText(params.feesMax)} (sample)`);
    }
    return why;
  }

  useRouteArrival('S-27');

  return (
    <StudentScreen screenId="S-27" className="st-lawschool st-lawschool--s27">
      <LsShell active="s27" ctx={ctx}>
        <div className="ls-wrap">
          {/* Step-3 pick tray — reference #pb: in-flow sticky band, never an overlay. */}
          <section className="ls-pickbar" aria-label="Compare tray">
            <span className="ls-pickbar__t">Step 3 · {tray.length} of {compareMax} picked</span>
            <span className="ls-bar" aria-hidden="true">
              <i style={{ width: `${(tray.length / compareMax) * 100}%` }} />
            </span>
            {selection.canCompare ? (
              <button
                type="button"
                className="btn ls-ind tap"
                onClick={() => nav(`/s-29?ids=${trayIds.join(',')}${ctx ? `&ret=${encodeURIComponent(ctx)}` : ''}`)}
              >
                Compare {tray.length} →
              </button>
            ) : (
              <span className="ls-metaline">PICK {selection.missingForMin} MORE TO COMPARE</span>
            )}
            <span className="ls-metaline">CATALOGUE {query.data ? total : '…'} · LIMIT (CONFIG) {compareMax}</span>
          </section>

          <p className="ls-metaline ls-mt14">S-27 · GUIDED SEARCH · SAMPLE DATA</p>
          <h1 className="ls-lede">Let’s find your law school.</h1>
          <p className="ls-stand">
            Answer two quick questions — or skip straight to the list. Every fact shows its source,
            and nothing here is a ranking.
          </p>

          {trayMsg && (
            <div className="ls-banner ls-banner--warn" role="status">
              <span className="ls-k">Compare</span><span>{trayMsg}</span>
            </div>
          )}

          {/* Guided three-step journey header (frozen decision: S-27 only). */}
          <div className="ls-stephead" role="group" aria-label="Guided steps" data-testid="ls-guided-steps">
            <div className="ls-srow">
              <div className="ls-stp" data-done={whereDone ? 1 : 0} data-cur={whereDone ? 0 : 1}>
                <span className="ls-n" aria-hidden="true">{whereDone ? '✓' : '1'}</span>
                <div>
                  <div className="ls-l">Where?</div>
                  <div className="ls-s">{params.state ?? 'Anywhere'}</div>
                </div>
              </div>
              <div className="ls-stp" data-done={budgetDone ? 1 : 0} data-cur={whereDone && !budgetDone ? 1 : 0}>
                <span className="ls-n" aria-hidden="true">{budgetDone ? '✓' : '2'}</span>
                <div>
                  <div className="ls-l">Budget</div>
                  <div className="ls-s">{params.feesMax !== undefined ? `Up to ${lakhText(params.feesMax)}` : 'No limit'}</div>
                </div>
              </div>
              <div className="ls-stp" data-done={tray.length >= COMPARE_MIN ? 1 : 0} data-cur={whereDone && budgetDone ? 1 : 0}>
                <span className="ls-n" aria-hidden="true">{tray.length >= COMPARE_MIN ? '✓' : '3'}</span>
                <div>
                  <div className="ls-l">Pick {COMPARE_MIN}–{compareMax}</div>
                  <div className="ls-s">{tray.length} picked</div>
                </div>
              </div>
            </div>
          </div>

          {/* Two guided question cards (reference .duo). */}
          <div className="ls-duo">
            <section className="ls-qcard">
              <h2>Where would you like to study?</h2>
              <p className="ls-why">We’ll show schools in that state first.</p>
              <div className="ls-chips" role="group" aria-label="State">
                <Chip pressed={!params.state} label="Anywhere" onClick={() => setParam('state', '')} />
                {STATES.map((s) => (
                  <Chip key={s} pressed={params.state === s} label={s} onClick={() => setParam('state', s)} />
                ))}
              </div>
            </section>
            <section className="ls-qcard">
              <h2>What yearly fee feels comfortable?</h2>
              <p className="ls-why">Sample fee bands — always confirm on the school’s site.</p>
              <div className="ls-chips" role="group" aria-label="Budget">
                {FEE_BANDS.map(([value, label]) => (
                  <Chip
                    key={label}
                    pressed={(params.feesMax !== undefined ? String(params.feesMax) : '') === value}
                    label={label}
                    onClick={() => setParam('fees_max', value)}
                  />
                ))}
              </div>
            </section>
          </div>

          {/* Tool row: in-flow search/filters disclosure + Order select. */}
          <div className="ls-toolrow">
            <button
              type="button"
              className="btn ls-ghost tap"
              aria-expanded={showSearch}
              onClick={() => setShowSearch((v) => !v)}
            >
              {showSearch ? 'Hide search' : 'Or search by name ⌕'}
            </button>
            <button
              type="button"
              className="btn ls-ghost tap"
              aria-expanded={showFilters}
              onClick={() => setShowFilters((v) => !v)}
            >
              {showFilters ? 'Hide filters' : 'More filters'}
            </button>
            <span className="ls-flex1" />
            <label className="ls-lb ls-lb--inline" htmlFor="ls-sort">Order</label>
            <select
              id="ls-sort"
              className="ls-in ls-in--auto"
              value={sortKey}
              onChange={(e) => setParam('sort', e.target.value)}
            >
              <option value="name">A to Z</option>
              <option value="fees">Lowest fees first</option>
              <option value="nirf_rank">NIRF rank</option>
            </select>
          </div>

          {(showSearch || params.q) && (
            <section className="ls-qcard ls-mt10">
              <form
                role="search"
                onSubmit={(e) => {
                  e.preventDefault();
                  setParam('q', qInput.trim());
                }}
              >
                <label className="ls-lb" htmlFor="ls-q">Search by name, city or state</label>
                <div className="ls-qrow">
                  <input
                    id="ls-q"
                    className="ls-in ls-in--grow"
                    type="search"
                    value={qInput}
                    onChange={(e) => setQInput(e.target.value)}
                    placeholder="e.g. NLSIU or Kolkata"
                    aria-label="Search law schools"
                  />
                  <button type="submit" className="btn ls-solid tap">Search</button>
                </div>
              </form>
            </section>
          )}

          {showFilters && (
            <section className="ls-qcard ls-mt10" aria-label="More filters">
              <h2>More filters</h2>
              <p className="ls-why">Every filter sends its canonical wire value — labels are display-only.</p>
              <div className="ls-filtergrid">
                <SelectField id="f-type" label="Institution type" value={params.institutionType ?? ''} onChange={(v) => setParam('institution_type', v)} options={INSTITUTION_TYPES} />
                <SelectField id="f-degree" label="Degree" value={params.degree ?? ''} onChange={(v) => setParam('degree', v)} options={DEGREES} />
                <SelectField id="f-accr" label="Accreditation" value={params.accreditation ?? ''} onChange={(v) => setParam('accreditation', v)} options={ACCREDITATIONS} />
                <SelectField id="f-exam" label="Entrance exam" value={params.entranceExam ?? ''} onChange={(v) => setParam('entrance_exam', v)} options={ENTRANCE_EXAMS} />
                <label className="st-field" htmlFor="f-fees">
                  <span className="st-field__label">Max fees (₹/yr)</span>
                  <input
                    id="f-fees"
                    className="ls-in"
                    type="number"
                    min={0}
                    value={params.feesMax ?? ''}
                    onChange={(e) => setParam('fees_max', e.target.value)}
                  />
                </label>
              </div>
            </section>
          )}

          <section aria-label="Search results">
            {query.isPending && (
              <div className="ls-cards ls-mt16" aria-busy="true" aria-label="Loading schools">
                {[1, 2, 3].map((k) => (
                  <div className="ls-card" key={k}>
                    <Skel h={22} maxW={280} />
                    <Skel h={14} maxW={200} mt={10} />
                    <Skel h={48} mt={12} />
                  </div>
                ))}
              </div>
            )}
            {query.isError && <QueryFailure error={query.error} onRetry={() => void query.refetch()} />}
            {query.data && (
              <p className="ls-metaline ls-mt16" role="status">
                {total} SCHOOL{total === 1 ? '' : 'S'}
                {answered ? ' · MATCHING YOUR ANSWERS' : ''}
                {params.q ? ` · “${params.q.toUpperCase()}”` : ''}
                {' · ORDER: '}
                {SORT_LABELS[sortKey]}
              </p>
            )}
            {query.data && query.data.items.length === 0 && (
              <div className="ls-panelbox">
                <h2>No schools match</h2>
                <p>Try clearing a filter or broadening your search.</p>
                <button
                  type="button"
                  className="btn ls-solid tap"
                  onClick={() => {
                    setQInput('');
                    setSp(new URLSearchParams());
                  }}
                >
                  Start over
                </button>
              </div>
            )}
            {query.data && query.data.items.length > 0 && (
              <ul className="ls-cards">
                {query.data.items.map((s) => {
                  const inTray = trayIds.includes(s.id);
                  const why = whyMatch(s);
                  return (
                    <li className="st-item ls-card" key={s.id}>
                      <div className="ls-hd">
                        <span className="ls-mg" aria-hidden="true">{monogram(s.name)}</span>
                        <h3 className="ls-name">
                          <Link to={`/s-28?id=${encodeURIComponent(s.id)}${ctx ? `&ret=${encodeURIComponent(ctx)}` : ''}`}>
                            {s.name}
                          </Link>
                        </h3>
                      </div>
                      <p className="ls-metaline ls-mt2">
                        {s.state.toUpperCase()} · {s.institutionType.toUpperCase()}
                      </p>
                      {why.length > 0 && (
                        <div className="ls-match">
                          <span aria-hidden="true">✓ </span>Matches: {why.join(' · ')}
                        </div>
                      )}
                      <ul className="ls-plain">
                        <li><span className="ls-b" aria-hidden="true" />Costs about <b>&nbsp;{feesText(s)}&nbsp;</b> (sample)</li>
                        <li><span className="ls-b" aria-hidden="true" />Admission through {s.entranceExam}</li>
                        <li>
                          <span className="ls-b" aria-hidden="true" />
                          {s.nirfRank !== null ? <>NIRF rank <b>&nbsp;#{s.nirfRank}&nbsp;</b> (sample)</> : 'Not NIRF-ranked (sample)'}
                        </li>
                      </ul>
                      <LsTags />
                      <div className="ls-acts">
                        <button
                          type="button"
                          className={`btn tap ls-cmp${inTray ? ' ls-ind' : ''}`}
                          aria-pressed={inTray}
                          disabled={!inTray && selection.atLimit}
                          onClick={() => (inTray ? removeFromTray(s.id) : addToTray(s))}
                        >
                          {inTray ? <><span aria-hidden="true">✓ </span>Picked to compare</> : '+ Compare'}
                        </button>
                        <button
                          type="button"
                          className="btn tap"
                          onClick={() => nav(`/s-28?id=${encodeURIComponent(s.id)}${ctx ? `&ret=${encodeURIComponent(ctx)}` : ''}`)}
                        >
                          View
                        </button>
                      </div>
                      <p className="ls-src">Source: institution website · sample directory data · verify before applying</p>
                    </li>
                  );
                })}
              </ul>
            )}
            {query.data && pageCount > 1 && (
              <nav className="ls-pager" aria-label="Pagination">
                <button type="button" className="btn tap" disabled={page <= 1} onClick={() => setParam('page', String(page - 1))}>
                  ‹ Back
                </button>
                <span className="ls-metaline" aria-live="polite">PAGE {page} OF {pageCount}</span>
                <button type="button" className="btn tap" disabled={page >= pageCount} onClick={() => setParam('page', String(page + 1))}>
                  More ›
                </button>
              </nav>
            )}
          </section>
          <div className="ls-foot">{RESPONSIBLE_COPY}</div>
        </div>
      </LsShell>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-28 — School profile (reference r28 structure)                             */
/* -------------------------------------------------------------------------- */

export function SchoolDetail() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const qc = useQueryClient();
  const id = sp.get('id') ?? '';
  const ret = sp.get('ret') ?? '';
  const [notifyOptIn, setNotifyOptIn] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tray, setTray] = useState<TrayEntry[]>(readCompareTray);
  const trayIds = tray.map((t) => t.id);

  const query = useQuery({
    queryKey: ['law-school', id],
    queryFn: () => getLawSchoolDetail(id),
    enabled: id !== '',
    retry: lawSchoolsRetry,
  });

  const saveMut = useMutation({
    mutationFn: (saved: boolean) => (saved ? unsaveLawSchool(id) : saveLawSchool(id)),
    onSuccess: (res) => {
      setActionError(null);
      qc.setQueryData<LawSchoolDetail>(['law-school', id], (d) => (d ? { ...d, saved: res.saved } : d));
      void qc.invalidateQueries({ queryKey: ['law-schools-saved'] });
    },
    onError: (err) => setActionError(errText(err, 'Could not update saved state.')),
  });

  const followMut = useMutation({
    mutationFn: (followed: boolean) => (followed ? unfollowLawSchool(id) : followLawSchool(id, notifyOptIn)),
    onSuccess: (res) => {
      setActionError(null);
      qc.setQueryData<LawSchoolDetail>(['law-school', id], (d) => (d ? { ...d, followed: res.followed } : d));
      void qc.invalidateQueries({ queryKey: ['law-schools-followed'] });
    },
    onError: (err) => setActionError(errText(err, 'Could not update follow state.')),
  });

  function errText(err: unknown, fallback: string): string {
    if (err instanceof LawSchoolsApiError && err.status === 401) return 'Sign in to save or follow schools.';
    return fallback;
  }

  function toggleCompare(d: LawSchoolDetail): void {
    if (trayIds.includes(d.id)) {
      setTray(writeCompareTray(readCompareTray().filter((t) => t.id !== d.id)));
      return;
    }
    const result = addToCompareSelection(trayIds, d.id, DEFAULT_COMPARE_MAX);
    if (!result.ok) {
      setActionError(`You can compare up to ${result.maxAllowed ?? DEFAULT_COMPARE_MAX} schools — remove one first. Nothing was changed.`);
      return;
    }
    setActionError(null);
    setTray(writeCompareTray([...readCompareTray(), { id: d.id, name: d.name }]));
  }

  const back = () => nav(ret ? `/s-27?${ret}` : '/s-27');

  useRouteArrival('S-28');

  const notFound = query.error instanceof LawSchoolsApiError && query.error.code === SCHOOL_NOT_FOUND;
  const d = query.data;

  return (
    <StudentScreen screenId="S-28" className="st-lawschool">
      <LsShell active="s27" ctx={ret}>
        <div className="ls-wrap">
          <p className="ls-metaline ls-mt14">S-28 · SCHOOL PROFILE</p>
          {!id && (
            <div className="ls-panelbox">
              <h2>No school in this link</h2>
              <p>This link is incomplete — no school was specified.</p>
              <button type="button" className="btn ls-solid tap" onClick={back}>Go to the directory</button>
            </div>
          )}
          {id !== '' && query.isPending && (
            <div aria-busy="true">
              <Skel h={30} maxW={320} mt={12} />
              <Skel h={180} mt={14} />
            </div>
          )}
          {query.isError && (notFound ? (
            <div className="ls-panelbox">
              <h2>We couldn’t find that school</h2>
              <p>It may have been removed from the directory or the link is out of date.</p>
              <button type="button" className="btn ls-solid tap" onClick={back}>Go to the directory</button>
            </div>
          ) : (
            <QueryFailure error={query.error} onRetry={() => void query.refetch()} />
          ))}
          {d && (
            <>
              <button type="button" className="btn ls-ghost ls-back tap" onClick={back}>
                ‹ Back to schools
              </button>
              <div className="ls-idrow">
                <span className="ls-mg ls-mg--lg" aria-hidden="true">{monogram(d.name)}</span>
                <div>
                  <h1 className="ls-lede ls-lede--profile">{d.name}</h1>
                  <p className="ls-stand">{d.state} · {d.institutionType} · {d.accreditation}.</p>
                </div>
              </div>
              <LsTags followed={d.followed} />
              <div className="ls-acts ls-acts--profile">
                {/* SAATHI-120 QA (TC-63-05): exact, state-specific accessible names so
                    assistive tech and test locators can never confuse the pre/post
                    states ("Save" is a prefix of "Saved ✓"). */}
                <button
                  type="button"
                  className="btn tap ls-save"
                  aria-pressed={d.saved}
                  aria-label={d.saved ? 'Saved — remove' : 'Save school'}
                  disabled={saveMut.isPending}
                  onClick={() => saveMut.mutate(d.saved)}
                >
                  {d.saved ? <><span aria-hidden="true">★ </span>Saved</> : 'Save'}
                </button>
                <button
                  type="button"
                  className="btn tap ls-follow"
                  aria-pressed={d.followed}
                  aria-label={d.followed ? 'Following — unfollow' : 'Follow school'}
                  disabled={followMut.isPending}
                  onClick={() => followMut.mutate(d.followed)}
                >
                  {d.followed ? <><span aria-hidden="true">✓ </span>Following</> : 'Follow'}
                </button>
                <button
                  type="button"
                  className={`btn tap ls-cmp${trayIds.includes(d.id) ? ' ls-ind' : ''}`}
                  aria-pressed={trayIds.includes(d.id)}
                  onClick={() => toggleCompare(d)}
                >
                  {trayIds.includes(d.id) ? <><span aria-hidden="true">✓ </span>In compare</> : '+ Compare'}
                </button>
              </div>
              {/* Corrected Follow wording (independent review, 2026-07-27): no
                  implied notification queue. The opt-in flag is still sent to
                  the follow endpoint unchanged (functional behaviour kept). */}
              <p className="ls-helper ls-followcopy">{FOLLOW_COPY}</p>
              {!d.followed && (
                <Checkbox id="follow-notify" label="Include admission updates if notifications launch" checked={notifyOptIn} onChange={setNotifyOptIn} />
              )}
              {actionError && <p className="ls-err" role="alert">{actionError}</p>}
              <section className="ls-qcard ls-mt16" aria-label="The essentials">
                <h2>The essentials</h2>
                <p className="ls-why">Plain answers first · every value carries its source.</p>
                {[
                  { key: 'exam', label: 'Entrance exam', value: <>{d.entranceExam}</> },
                  { key: 'fees', label: 'Fee band (sample)', value: <>{feesText(d)}</> },
                  { key: 'nirf', label: 'NIRF rank (sample)', value: <>{d.nirfRank !== null ? `#${d.nirfRank}` : 'Not ranked'}</> },
                  {
                    key: 'progs',
                    label: 'Programmes',
                    value: (
                      <>{d.programmes.length ? d.programmes.map((p) => `${p.degree} (${p.durationYears} yrs)`).join(' · ') : 'Not listed'}</>
                    ),
                  },
                ].map((row) => (
                  <div className="ls-fact" key={row.key}>
                    <div className="ls-fact__l">{row.label}</div>
                    <div className="ls-fact__v">{row.value}</div>
                    <p className="ls-src">Source: institution website · sample directory data</p>
                  </div>
                ))}
                {d.facts.map((f) => (
                  <div className="ls-fact" key={f.key}>
                    <div className="ls-fact__l">{f.key}</div>
                    <div className="ls-fact__v">{f.value}</div>
                    <p className="ls-src">
                      Source: <a href={f.sourceUrl} target="_blank" rel="noopener noreferrer">{f.sourceName}</a> · retrieved {f.retrievedAt}
                    </p>
                  </div>
                ))}
                {d.facts.length === 0 && (
                  <p className="ls-stand ls-mt10">
                    No further verified facts are published yet — we only show facts with a source and verification date.
                  </p>
                )}
                <div className="ls-helper ls-mt12">
                  <b>What’s “NIRF rank”?</b> NIRF is the government’s National Institutional Ranking
                  Framework. We show a rank only where NIRF (Law) publishes one — never our own ranking.
                </div>
              </section>
            </>
          )}
          <div className="ls-foot">{RESPONSIBLE_COPY} {DPDP_COPY}</div>
        </div>
      </LsShell>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-29 — Compare (reference r29: stacked fact cards, no sideways scroll)      */
/* -------------------------------------------------------------------------- */

export function SchoolCompare() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const ret = sp.get('ret') ?? '';
  const idsParam = sp.get('ids');
  const ids = useMemo(
    () => (idsParam
      ? [...new Set(idsParam.split(',').filter(Boolean))]
      : readCompareTray().map((t) => t.id)),
    [idsParam],
  );

  // Direct-link/refresh handling: mirror a tray-derived selection into the URL
  // so the comparison survives refresh and can be shared.
  useEffect(() => {
    if (!idsParam && ids.length > 0) {
      const next = new URLSearchParams(sp);
      next.set('ids', ids.join(','));
      setSp(next, { replace: true });
    }
  }, [idsParam, ids, sp, setSp]);

  const query = useQuery({
    queryKey: ['law-schools-compare', ids.join(',')],
    queryFn: () => compareLawSchools(ids),
    enabled: ids.length >= COMPARE_MIN,
    retry: false,
  });

  const compareMax = query.data?.compareMax ?? DEFAULT_COMPARE_MAX;
  /* "Differences only" — frozen decision: OFF by default. Pure client-side
   * view filter over the server comparison result; never mutates the set. */
  const [diffOnly, setDiffOnly] = useState(false);

  useRouteArrival('S-29');

  function removeSchool(id: string): void {
    const nextIds = ids.filter((s) => s !== id);
    writeCompareTray(readCompareTray().filter((t) => t.id !== id));
    const next = new URLSearchParams(sp);
    next.set('ids', nextIds.join(','));
    setSp(next, { replace: true });
  }

  const back = () => nav(ret ? `/s-27?${ret}` : '/s-27');

  function compareError(error: unknown) {
    if (error instanceof LawSchoolsApiError) {
      if (error.status === 401) return <SignInPrompt />;
      if (error.code === COMPARE_LIMIT_EXCEEDED) {
        const max = error.maxAllowed ?? compareMax;
        return (
          <div className="ls-panelbox" role="alert">
            <h2>Comparison is limited to {max} schools</h2>
            <p>You can compare at most {max} schools — remove {Math.max(1, ids.length - max)} and try again. Nothing was changed by this attempt.</p>
            <button type="button" className="btn ls-solid tap" onClick={back}>Back to the list</button>
          </div>
        );
      }
      if (error.code === COMPARE_MIN_NOT_MET) {
        return <BelowMin min={error.minRequired ?? COMPARE_MIN} max={compareMax} onBack={back} />;
      }
      if (error.code === DUPLICATE_SCHOOL) {
        return (
          <div className="ls-banner ls-banner--warn" role="alert">
            <span className="ls-k">Already picked</span>
            <span>The same school is selected twice — remove the duplicate.</span>
          </div>
        );
      }
      if (error.code === SCHOOL_NOT_FOUND) {
        return (
          <div className="ls-banner ls-banner--risk" role="alert">
            <span className="ls-k">Not found</span>
            <span>One of the selected schools is no longer in the directory — remove it and retry.</span>
          </div>
        );
      }
    }
    return <QueryFailure error={error} onRetry={() => void query.refetch()} />;
  }

  function rowDiffers(row: { value: (i: LawSchoolDetailLike) => string }): boolean {
    const items = query.data?.items ?? [];
    return items.length >= 2 && new Set(items.map((i) => row.value(i))).size > 1;
  }

  const rows: Array<{ label: string; value: (i: LawSchoolDetailLike) => string }> = [
    { label: 'State', value: (i) => i.state },
    { label: 'Institution type', value: (i) => i.institutionType },
    { label: 'Accreditation', value: (i) => i.accreditation },
    { label: 'Entrance exam', value: (i) => i.entranceExam },
    { label: 'Fees (per year)', value: (i) => feesText(i) },
    { label: 'NIRF rank', value: (i) => (i.nirfRank !== null ? `#${i.nirfRank}` : 'Not ranked') },
    {
      label: 'Programmes',
      value: (i) => (i.programmes.length ? i.programmes.map((p) => `${p.degree} (${p.durationYears} yrs)`).join(', ') : 'Not listed'),
    },
  ];

  const visibleRows = diffOnly ? rows.filter((row) => rowDiffers(row)) : rows;
  const items = query.data?.items ?? [];

  return (
    <StudentScreen screenId="S-29" className="st-lawschool">
      <LsShell active="s29" ctx={ret}>
        <div className="ls-wrap">
          <p className="ls-metaline ls-mt14">S-29 · COMPARE YOUR PICKS</p>
          {ids.length < COMPARE_MIN && <BelowMin min={COMPARE_MIN} max={compareMax} onBack={back} />}
          {ids.length >= COMPARE_MIN && query.isPending && (
            <>
              <h1 className="ls-lede">Getting your comparison ready…</h1>
              <div aria-busy="true"><Skel h={280} mt={16} /></div>
            </>
          )}
          {ids.length >= COMPARE_MIN && query.isError && compareError(query.error)}
          {query.data && (
            <>
              <h1 className="ls-lede">Your {items.length} picks, side by side.</h1>
              <div className="ls-pnum">
                <span className="ls-n ls-n--on" aria-hidden="true">1</span>
                <span className="ls-pl">Picked {items.length} of {query.data.compareMax}</span>
                <span className="ls-n ls-n--on" aria-hidden="true">2</span>
                <span className="ls-pl">Compare each fact below</span>
              </div>
              <div className="ls-cmprow">
                {items.map((i) => (
                  <span className="ls-chp ls-chp--on ls-chp--static" key={i.id}>
                    <span className="ls-ckg" aria-hidden="true">✓ </span>{shortName(i.name)}
                    <button
                      type="button"
                      className="ls-ibtn ls-x"
                      aria-label={`Remove ${i.name} from comparison`}
                      onClick={() => removeSchool(i.id)}
                    >
                      ✕
                    </button>
                  </span>
                ))}
                <button type="button" className="btn ls-ghost tap" onClick={back}>
                  + add (max {query.data.compareMax})
                </button>
                <span className="ls-flex1" />
                <button
                  type="button"
                  className="ls-tgl"
                  aria-pressed={diffOnly}
                  onClick={() => setDiffOnly((v) => !v)}
                >
                  <span className="ls-sw" aria-hidden="true" />
                  Differences only
                </button>
              </div>
              <p className="ls-metaline ls-mt10">
                EACH FACT CARD LISTS ALL YOUR PICKS — NOTHING SCROLLS SIDEWAYS.
                {diffOnly ? ` ${visibleRows.length} OF ${rows.length} FACTS DIFFER ·` : ''} SAMPLE DATA
              </p>
              <div className="ls-cards" data-cmp-cards="1">
                {visibleRows.map((row) => {
                  const differs = rowDiffers(row);
                  return (
                    <div className="ls-attrcard" data-differ={differs ? 1 : 0} key={row.label}>
                      <div className="ls-al">
                        {row.label}
                        {differs
                          ? <span className="ls-dbadge">values differ</span>
                          : <span className="ls-metaline">same for all</span>}
                      </div>
                      <ul className="ls-vals">
                        {items.map((i) => (
                          <li key={i.id}><span>{shortName(i.name)}</span><b>{row.value(i)}</b></li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
              {diffOnly && visibleRows.length === 0 && (
                <p className="ls-stand ls-mt12">Every compared fact is the same for the selected schools.</p>
              )}
            </>
          )}
          <div className="ls-foot">Server enforces the compare limits · figures cite official sources. {RESPONSIBLE_COPY}</div>
        </div>
      </LsShell>
    </StudentScreen>
  );
}

/** Reference below-minimum panel (r29): two-step pnum + return CTA. */
function BelowMin({ min, max, onBack }: { min: number; max: number; onBack: () => void }) {
  return (
    <div className="ls-panelbox">
      <h2>Pick one more school</h2>
      <p>Pick at least {min} schools to compare — comparison needs a minimum of two.</p>
      <div className="ls-pnum ls-pnum--center">
        <span className="ls-n ls-n--on" aria-hidden="true">1</span>
        <span className="ls-pl">Pick {min}–{max} schools</span>
        <span className="ls-n" aria-hidden="true">2</span>
        <span className="ls-pl">Compare</span>
      </div>
      <button type="button" className="btn ls-solid tap ls-mt16" onClick={onBack}>Back to the list</button>
    </div>
  );
}

interface LawSchoolDetailLike extends LawSchoolSummary {
  programmes: Array<{ degree: string; durationYears: number }>;
}

/* -------------------------------------------------------------------------- */
/* S-30 — My schools: Saved + Following groups (reference r30 structure)       */
/* -------------------------------------------------------------------------- */

export function SchoolSavedFollowed() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const qc = useQueryClient();
  const ret = sp.get('ret') ?? '';

  const savedQ = useQuery({ queryKey: ['law-schools-saved'], queryFn: listSavedLawSchools, retry: lawSchoolsRetry });
  const followedQ = useQuery({ queryKey: ['law-schools-followed'], queryFn: listFollowedLawSchools, retry: lawSchoolsRetry });

  const unsaveMut = useMutation({
    mutationFn: (id: string) => unsaveLawSchool(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['law-schools-saved'] }),
  });
  const unfollowMut = useMutation({
    mutationFn: (id: string) => unfollowLawSchool(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['law-schools-followed'] }),
  });

  const authError = [savedQ.error, followedQ.error].find(
    (e) => e instanceof LawSchoolsApiError && e.status === 401,
  );

  useRouteArrival('S-30');

  const browse = () => nav(ret ? `/s-27?${ret}` : '/s-27');

  function group(
    title: string,
    ariaLabel: string,
    q: typeof savedQ | typeof followedQ,
    actionLabel: string,
    onAction: (id: string) => void,
    actionPending: boolean,
    emptyText: string,
    identityClass: string,
  ) {
    return (
      <section className={`ls-sect ${identityClass}`} aria-label={ariaLabel}>
        <h2 className="ls-h2">{title} <span className="ls-metaline">· {q.data ? q.data.length : '…'}</span></h2>
        {q.isPending && <div aria-busy="true"><Skel h={120} mt={10} /></div>}
        {q.isError && <QueryFailure error={q.error} onRetry={() => void q.refetch()} />}
        {q.data && q.data.length === 0 && (
          <div className="ls-card ls-card--empty">
            <p className="ls-stand">{emptyText}</p>
            <button type="button" className="btn ls-solid tap" onClick={browse}>Browse schools</button>
          </div>
        )}
        {q.data && q.data.length > 0 && (
          <ul className="ls-cards">
            {q.data.map((s) => (
              <li className="st-item ls-card" key={s.id}>
                <div className="ls-hd">
                  <span className="ls-mg" aria-hidden="true">{monogram(s.name)}</span>
                  <h3 className="ls-name">
                    <Link to={`/s-28?id=${encodeURIComponent(s.id)}${ret ? `&ret=${encodeURIComponent(ret)}` : ''}`}>
                      {s.name}
                    </Link>
                  </h3>
                </div>
                <p className="ls-metaline ls-mt2">
                  {s.state.toUpperCase()} · {feesText(s).toUpperCase()} (SAMPLE) · VERIFIED SOURCE
                </p>
                <div className="ls-acts">
                  <button type="button" className="btn tap" disabled={actionPending} onClick={() => onAction(s.id)}>
                    {actionLabel}
                  </button>
                  <button
                    type="button"
                    className="btn ls-ghost tap"
                    onClick={() => nav(`/s-28?id=${encodeURIComponent(s.id)}${ret ? `&ret=${encodeURIComponent(ret)}` : ''}`)}
                  >
                    View
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  return (
    <StudentScreen screenId="S-30" className="st-lawschool">
      <LsShell active="s30" ctx={ret}>
        <div className="ls-wrap">
          <p className="ls-metaline ls-mt14">S-30 · MY SCHOOLS</p>
          {authError ? (
            <SignInPrompt />
          ) : (
            <>
              <h1 className="ls-lede">My schools.</h1>
              <p className="ls-stand">Only you can see these. {FOLLOW_COPY}</p>
              {group(
                'Saved', 'Saved schools', savedQ, 'Remove from saved',
                (id) => unsaveMut.mutate(id), unsaveMut.isPending,
                'No saved schools yet — tap Save on any school to keep it here.', 'ls-sect--saved',
              )}
              {group(
                'Following', 'Followed schools', followedQ, 'Stop following',
                (id) => unfollowMut.mutate(id), unfollowMut.isPending,
                'No followed schools yet — follow a school to mark it for future verified updates.', 'ls-sect--followed',
              )}
            </>
          )}
          <div className="ls-foot">{DPDP_COPY} Saved and Following are private to your account · notification preferences will live in Settings (S-18) when notifications launch.</div>
        </div>
      </LsShell>
    </StudentScreen>
  );
}

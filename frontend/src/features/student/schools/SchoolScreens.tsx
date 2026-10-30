import { S27SearchScreen } from './S27SearchScreen';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useNavigationType, useSearchParams } from 'react-router-dom';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useStudentMutation as useMutation } from '../lib/useStudentMutation';
import { StudentScreen } from '../components';
import { useTheme } from '../../../hooks/useTheme';
import {
  getLawSchoolDetail,
  compareLawSchools,
  saveLawSchool,
  unsaveLawSchool,
  followLawSchool,
  unfollowLawSchool,
  listSavedLawSchools,
  listFollowedLawSchools,
  addToCompareSelection,
  LawSchoolsApiError,
  isRetryableLawSchoolsError,
  COMPARE_MIN,
  DEFAULT_COMPARE_MAX,
  COMPARE_LIMIT_EXCEEDED,
  COMPARE_MIN_NOT_MET,
  DUPLICATE_SCHOOL,
  SCHOOL_NOT_FOUND,
  type LawSchoolDetail,
  type LawSchoolSummary,
} from '../lib/lawSchoolsApi';
import {
  COMPARE_ROWS,
  FACT_LABELS,
  S28_FACT_KEY_ORDER,
  compareRowValue,
  factSourceLine,
  feesInrBand,
  feesLakhBand,
  institutionTypeLabel,
  monogramText,
  shortHandle,
  verifiedText,
  referenceSourceFoot,
  REFERENCE_RESPONSIBLE_COPY,
  type CompareFormatInput,
} from './lawschoolFormat.mjs';

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

/* Monograms + short display handles come from the APPROVED reference
 * taxonomy (lawschoolFormat.mjs APPROVED_SHORT_HANDLES): reference mono()
 * derives the 2-letter serif monogram from the approved short, so 'NALSAR
 * University of Law' renders 'NA' (not word initials). */

/**
 * Reference display extras derived from each school's REAL fact rows
 * (location / established / intake) plus its saved flag — the reference
 * S-27 card metaline ('CITY, STATE · SINCE est'), seats fact and S-30 card
 * metaline city are fact-backed, not summary columns. One cached detail
 * query per visible card; every value remains real API data.
 */
interface SchoolExtras {
  cityState: string | null;
  established: string | null;
  seats: string | null;
  saved: boolean | null;
}

const stripSample = (v: string): string => v.replace(/ \(sample\)$/, '');

function extrasOf(d: LawSchoolDetail | undefined): SchoolExtras {
  if (!d) return { cityState: null, established: null, seats: null, saved: null };
  const fact = (key: string): string | undefined => d.facts.find((f) => f.key === key)?.value;
  const location = fact('location');
  const cityState = location ? stripSample(location) : null;
  const established = fact('established');
  const intake = fact('intake');
  return {
    cityState,
    established: established ? (/^\d{4}/.exec(established)?.[0] ?? null) : null,
    seats: intake ? (/^\d+/.exec(intake)?.[0] ?? null) : null,
    saved: d.saved,
  };
}

export const SCHOOL_DETAIL_READINESS_FAILED = 'SCHOOL_DETAIL_READINESS_FAILED';

/** Stable first-seen deduplication prevents duplicate React Query observer keys. */
export function stableUniqueSchoolIds(ids: string[]): string[] {
  return [...new Set(ids)];
}

/** One canonical S-27/S-30 detail destination preserving the search return context. */
export function lawSchoolDetailPath(id: string, returnContext: string): string {
  return `/s-28?id=${encodeURIComponent(id)}${returnContext ? `&ret=${encodeURIComponent(returnContext)}` : ''}`;
}

/** Frozen S-30 contract: state (not city) + unchanged fee/sample/verification copy. */
export function schoolListMetaline(s: LawSchoolSummary): string {
  return `${s.state.toUpperCase()} · ${feesLakhBand(s.feesMin, s.feesMax).toUpperCase()} (SAMPLE) · ${verifiedText().toUpperCase()}`;
}

interface SchoolExtrasResult {
  byId: Record<string, SchoolExtras>;
  status: 'pending' | 'ready' | 'error';
  failedIds: string[];
  queryIds: string[];
}

function useSchoolExtras(ids: string[]): SchoolExtrasResult {
  const queryIds = stableUniqueSchoolIds(ids);
  const results = useQueries({
    queries: queryIds.map((id) => ({
      queryKey: ['law-school', id],
      queryFn: () => getLawSchoolDetail(id),
      retry: lawSchoolsRetry,
      staleTime: 60_000,
    })),
  });
  const byId: Record<string, SchoolExtras> = {};
  queryIds.forEach((id, i) => { byId[id] = extrasOf(results[i]?.data); });
  const failedIds = queryIds.filter((_, i) => results[i]?.isError);
  const settled = results.every((result) => result.isSuccess || result.isError);
  return {
    byId,
    status: failedIds.length > 0 ? 'error' : settled ? 'ready' : 'pending',
    failedIds,
    queryIds,
  };
}

/* Shared-formatter delegates (SAATHI-118 F2): the SAME functions feed the
 * fixture contract projection and the reference generator, so INR-raw vs
 * lakh can never diverge between the developed UI and the reference frame. */

/** INR-raw band (reference r28 fee band / r29 fees row). */
function feesText(s: LawSchoolSummary): string {
  return feesInrBand(s.feesMin, s.feesMax);
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
          <span className="ls-mk" aria-hidden="true">§</span> NyayOne
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

function LsTags({ followed }: { followed?: boolean }) {
  return (
    <div className="ls-tags">
      <span className="ls-tag ls-tag--v"><span className="ls-gl" aria-hidden="true" />{verifiedText()}</span>
      <span className="ls-tag ls-tag--warn"><span className="ls-gl" aria-hidden="true" />Sample data · prototype</span>
      {followed && <span className="ls-tag ls-tag--teal"><span className="ls-gl" aria-hidden="true" />Following</span>}
    </div>
  );
}

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

export function SchoolSearch() {
  return <S27SearchScreen readSelection={readCompareTray} writeSelection={writeCompareTray}/>;
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

  /* Follow keeps the persisted opt-in wire flag (default true) — the approved
   * S-28 state carries no separate notification checkbox; the Follow action
   * IS the opt-in per the corrected reference copy. */
  const followMut = useMutation({
    mutationFn: (followed: boolean) => (followed ? unfollowLawSchool(id) : followLawSchool(id, true)),
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
  const ex28 = extrasOf(d);

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
                <span className="ls-mg ls-mg--lg" aria-hidden="true">{monogramText(d.name)}</span>
                <div>
                  <h1 className="ls-lede ls-lede--profile">{d.name}</h1>
                  <p className="ls-stand">
                    {ex28.cityState ?? d.state} · {institutionTypeLabel(d.institutionType)} · teaching law since {ex28.established ?? '—'}.
                  </p>
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
                    <p className="ls-src">{referenceSourceFoot()}</p>
                  </div>
                ))}
                {[...d.facts]
                  .sort((a, b) => {
                    const rank = (k: string): number => {
                      const i = S28_FACT_KEY_ORDER.indexOf(k);
                      return i < 0 ? S28_FACT_KEY_ORDER.length : i;
                    };
                    return rank(a.key) - rank(b.key);
                  })
                  .map((f) => (
                    <div className="ls-fact" key={f.key}>
                      <div className="ls-fact__l">{FACT_LABELS[f.key] ?? f.key}</div>
                      <div className="ls-fact__v">{f.value}</div>
                      <p className="ls-src">
                        {/* Reference source-row density: frozen-fixture wording with the
                            fact's REAL retrieved_at date; the provenance link stays live
                            (target-size met via layout-neutral padding, see student.css). */}
                        {f.sourceUrl
                          ? <a href={f.sourceUrl} target="_blank" rel="noopener noreferrer">{factSourceLine(f.retrievedAt)}</a>
                          : factSourceLine(f.retrievedAt)}
                      </p>
                    </div>
                  ))}
                {d.facts.length === 0 && (
                  <p className="ls-stand ls-mt10">
                    No further verified facts are published yet — we only show facts with a source and verification date.
                  </p>
                )}
                <div className="ls-helper ls-mt12">
                  <b>What’s “NIRF band”?</b> NIRF is the government’s National Institutional Ranking
                  Framework. We show a band only where NIRF (Law) publishes one — never our own
                  ranking. Rank shown only where NIRF (Law) publishes it · sample rank for prototype.
                </div>
              </section>
            </>
          )}
          <div className="ls-foot">{REFERENCE_RESPONSIBLE_COPY} {DPDP_COPY}</div>
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

  /* APPROVED 13-row S-29 schema (SAATHI-63/118 final closure): State,
   * Institution type, Accreditation, Entrance exam, Fees, NIRF rank,
   * Programmes, Established, Location, Intake, Hostel, Legal aid clinics,
   * Moot teams — order, labels and value formatting come from the SHARED
   * formatter (lawschoolFormat.mjs) that also drives the fixture contract
   * and the reference generator. */
  const toFormatInput = (i: LawSchoolDetailLike): CompareFormatInput => ({
    state: i.state,
    institutionType: i.institutionType,
    accreditation: i.accreditation,
    entranceExam: i.entranceExam,
    feesMin: i.feesMin,
    feesMax: i.feesMax,
    nirfRank: i.nirfRank,
    programmes: i.programmes,
    facts: Object.fromEntries(i.facts.map((f) => [f.key, f.value])),
  });
  const rows: Array<{ label: string; value: (i: LawSchoolDetailLike) => string }> = COMPARE_ROWS.map(
    ({ key, label }) => ({ label, value: (i: LawSchoolDetailLike) => compareRowValue(key, toFormatInput(i)) }),
  );

  const visibleRows = diffOnly ? rows.filter((row) => rowDiffers(row)) : rows;
  const items = query.data?.items ?? [];

  return (
    <StudentScreen screenId="S-29" className="st-lawschool st-lawschool--s29">
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
                    <span className="ls-ckg" aria-hidden="true">✓ </span>{shortHandle(i.name)}
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
                {`EACH FACT CARD LISTS ALL YOUR PICKS — NOTHING SCROLLS SIDEWAYS. ${diffOnly ? `${visibleRows.length} OF ${rows.length} FACTS DIFFER · ` : ''}${verifiedText().toUpperCase()} · SAMPLE DATA`}
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
                          <li key={i.id}><span>{shortHandle(i.name)}</span><b>{row.value(i)}</b></li>
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
          <div className="ls-foot">{referenceSourceFoot()}<br />{REFERENCE_RESPONSIBLE_COPY}</div>
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
  facts: Array<{ key: string; value: string }>;
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

  const extras30 = useSchoolExtras([
    ...(savedQ.data ?? []).map((s) => s.id),
    ...(followedQ.data ?? []).map((s) => s.id),
  ]);
  const listsSettled = savedQ.isSuccess && followedQ.isSuccess;
  const listFailed = savedQ.isError || followedQ.isError;
  const s30Readiness = listFailed
    ? 'error'
    : listsSettled
      ? extras30.status
      : 'pending';

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
                  <span className="ls-mg" aria-hidden="true">{monogramText(s.name)}</span>
                  <h3 className="ls-name">
                    <Link to={`/s-28?id=${encodeURIComponent(s.id)}${ret ? `&ret=${encodeURIComponent(ret)}` : ''}`}>
                      {s.name}
                    </Link>
                  </h3>
                </div>
                <p className="ls-metaline ls-mt2">
                  {schoolListMetaline(s)}
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
        <div
          className="ls-wrap"
          data-qa-lawschool-ready={s30Readiness === 'ready' ? 'true' : undefined}
          data-qa-lawschool-readiness-error={s30Readiness === 'error' ? SCHOOL_DETAIL_READINESS_FAILED : undefined}
          data-qa-lawschool-failed-ids={extras30.failedIds.length > 0 ? extras30.failedIds.join(',') : undefined}
        >
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
          <div className="ls-foot">{DPDP_COPY}</div>
        </div>
      </LsShell>
    </StudentScreen>
  );
}

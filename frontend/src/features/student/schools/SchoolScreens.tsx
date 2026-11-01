import { S29ComparisonScreen } from './S29ComparisonScreen';
import { S28DetailScreen } from './S28DetailScreen';
import { S27SearchScreen } from './S27SearchScreen';
import { useEffect, type ReactNode } from 'react';
import { Link, useNavigate, useNavigationType, useSearchParams } from 'react-router-dom';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useStudentMutation as useMutation } from '../lib/useStudentMutation';
import { StudentScreen } from '../components';
import { useTheme } from '../../../hooks/useTheme';
import {
  getLawSchoolDetail,
  unsaveLawSchool,
  unfollowLawSchool,
  listSavedLawSchools,
  listFollowedLawSchools,
  LawSchoolsApiError,
  isRetryableLawSchoolsError,
  type LawSchoolDetail,
  type LawSchoolSummary,
} from '../lib/lawSchoolsApi';
import {
  feesLakhBand,
  monogramText,
  verifiedText,
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
  return <S28DetailScreen readSelection={readCompareTray} writeSelection={writeCompareTray}/>;
}

/* -------------------------------------------------------------------------- */
/* S-29 — Compare (reference r29: stacked fact cards, no sideways scroll)      */
/* -------------------------------------------------------------------------- */

export function SchoolCompare() {
  return <S29ComparisonScreen readSelection={readCompareTray} writeSelection={writeCompareTray}/>;
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

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { StudentScreen, SelectField, Checkbox, DpdpFootnote } from '../components';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  StatusBadge,
  ValidationState,
} from '../../../components/ui/primitives';
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
 * S5 law-school directory screens (SAATHI-63 / SAATHI-118): S-27 search,
 * S-28 detail, S-29 compare, S-30 saved & followed. Server state comes from
 * lawSchoolsApi via the shared TanStack Query client; screen state (query,
 * filters, page, selection, return context) lives in the URL so refresh and
 * direct links work, matching the router pattern in screens.tsx.
 */

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
    pageSize: 20,
  };
}

function feesText(s: LawSchoolSummary): string {
  const fmt = (n: number) => `₹${n.toLocaleString('en-IN')}`;
  return `${fmt(s.feesMin)}–${fmt(s.feesMax)}/yr`;
}

/* ------------------------------ shared views ------------------------------- */

function ModuleHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div>
      <p className="st-eyebrow">{eyebrow}</p>
      <h1 className="st-h1">{title}</h1>
      {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

function SignInPrompt() {
  const nav = useNavigate();
  return (
    <div className="ui-state" role="alert">
      <p className="ui-state__eyebrow">Signed out</p>
      <p className="ui-state__title">Sign in to continue</p>
      <div className="ui-state__body">
        You need to be signed in as a student to use this area.
      </div>
      <div className="ui-state__action">
        <button type="button" className="btn tap" onClick={() => nav('/s-03')}>
          Go to sign in
        </button>
      </div>
    </div>
  );
}

function QueryFailure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error instanceof LawSchoolsApiError && error.status === 401) {
    return <SignInPrompt />;
  }
  const detail = error instanceof LawSchoolsApiError
    ? `The directory service reported: ${error.code}.`
    : 'Network problem — check your connection and try again.';
  return <ErrorState title="Could not load law schools" detail={detail} onRetry={onRetry} />;
}

/* -------------------------------------------------------------------------- */
/* S-27 — Search & filter                                                      */
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
const SORTS: Array<{ value: LawSchoolSort; label: string }> = [
  { value: 'name', label: 'Name' },
  { value: 'fees', label: 'Fees' },
  { value: 'nirf_rank', label: 'NIRF rank' },
];

export function SchoolSearch() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const params = useMemo(() => paramsFromUrl(sp), [sp]);
  const [qInput, setQInput] = useState(params.q ?? '');
  const [tray, setTray] = useState<TrayEntry[]>(readCompareTray);
  const [trayMsg, setTrayMsg] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ['law-schools', searchContext(sp)],
    queryFn: () => searchLawSchools(params),
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
          ? `${school.name} is already in your comparison.`
          : `You can compare up to ${result.maxAllowed} schools — remove one first.`,
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

  return (
    <StudentScreen screenId="S-27">
      <div className="st-stack">
        <ModuleHead eyebrow="Law schools · S5" title="Find your law school" sub="search · filter · compare · follow" />
        <form
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            setParam('q', qInput.trim());
          }}
        >
          <input
            className="st-search"
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Search by name, city or slug…"
            aria-label="Search law schools"
          />
        </form>

        <div className="st-grid">
          <SelectField id="f-state" label="State" value={params.state ?? ''} onChange={(v) => setParam('state', v)} options={STATES} />
          <SelectField id="f-type" label="Institution type" value={params.institutionType ?? ''} onChange={(v) => setParam('institution_type', v)} options={INSTITUTION_TYPES} />
          <SelectField id="f-degree" label="Degree" value={params.degree ?? ''} onChange={(v) => setParam('degree', v)} options={DEGREES} />
          <SelectField id="f-accr" label="Accreditation" value={params.accreditation ?? ''} onChange={(v) => setParam('accreditation', v)} options={ACCREDITATIONS} />
          <SelectField id="f-exam" label="Entrance exam" value={params.entranceExam ?? ''} onChange={(v) => setParam('entrance_exam', v)} options={ENTRANCE_EXAMS} />
          <label className="st-field" htmlFor="f-fees">
            <span className="st-field__label">Max fees (₹/yr)</span>
            <input
              id="f-fees"
              className="st-input"
              type="number"
              min={0}
              value={params.feesMax ?? ''}
              onChange={(e) => setParam('fees_max', e.target.value)}
            />
          </label>
        </div>

        <div className="st-tabsrow" role="group" aria-label="Sort results">
          {SORTS.map((s) => (
            <button
              key={s.value}
              type="button"
              className="st-chip"
              aria-pressed={params.sort === s.value}
              onClick={() => setParam('sort', params.sort === s.value ? '' : s.value)}
            >
              Sort: {s.label}
            </button>
          ))}
          <button type="button" className="st-chip" onClick={() => nav(`/s-30${ctx ? `?ret=${encodeURIComponent(ctx)}` : ''}`)}>
            Saved &amp; followed
          </button>
        </div>

        <section className="st-panel" aria-label="Compare tray">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Compare</h2>
            <span className="st-metatag">{tray.length} of {compareMax} selected · min {COMPARE_MIN}</span>
          </div>
          {tray.length === 0 ? (
            <p className="st-item__meta">Add {COMPARE_MIN}–{compareMax} schools to compare them side by side.</p>
          ) : (
            <div className="st-chips">
              {tray.map((t) => (
                <button key={t.id} type="button" className="st-chip" onClick={() => removeFromTray(t.id)} aria-label={`Remove ${t.name} from comparison`}>
                  {t.name} ✕
                </button>
              ))}
            </div>
          )}
          {trayMsg && <ValidationState message={trayMsg} />}
          <div className="st-actions">
            <button
              type="button"
              className="btn btn--primary tap"
              disabled={!selection.canCompare}
              aria-disabled={!selection.canCompare}
              onClick={() => nav(`/s-29?ids=${trayIds.join(',')}${ctx ? `&ret=${encodeURIComponent(ctx)}` : ''}`)}
            >
              Compare {tray.length >= COMPARE_MIN ? `${tray.length} schools` : `(select ${selection.missingForMin} more)`}
            </button>
          </div>
        </section>

        <section className="st-panel" aria-label="Search results">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Results</h2>
            <span className="st-metatag">{query.data ? `${total} found` : '…'}</span>
          </div>
          {query.isPending && <LoadingState label="Loading law schools…" />}
          {query.isError && <QueryFailure error={query.error} onRetry={() => void query.refetch()} />}
          {query.data && query.data.items.length === 0 && (
            <EmptyState title="No schools match" hint="Try clearing a filter or broadening your search." />
          )}
          {query.data && query.data.items.length > 0 && (
            <ul className="st-list">
              {query.data.items.map((s) => (
                <li className="st-item" key={s.id}>
                  <div>
                    <div>{s.name}</div>
                    <div className="st-item__meta">
                      {s.state} · {s.institutionType} · {s.entranceExam} · <span className="st-price">{feesText(s)}</span>
                      {s.nirfRank !== null && ` · NIRF #${s.nirfRank}`}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                    <StatusBadge status="info" label={s.accreditation} />
                    <button
                      type="button"
                      className="btn tap"
                      aria-pressed={trayIds.includes(s.id)}
                      disabled={!trayIds.includes(s.id) && selection.atLimit}
                      onClick={() => (trayIds.includes(s.id) ? removeFromTray(s.id) : addToTray(s))}
                    >
                      {trayIds.includes(s.id) ? 'In compare' : 'Compare'}
                    </button>
                    <button type="button" className="btn tap" onClick={() => nav(`/s-28?id=${encodeURIComponent(s.id)}${ctx ? `&ret=${encodeURIComponent(ctx)}` : ''}`)}>
                      View
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {query.data && pageCount > 1 && (
            <div className="st-actions st-actions--split" style={{ marginTop: 'var(--space-3)' }}>
              <button type="button" className="btn tap" disabled={page <= 1} onClick={() => setParam('page', String(page - 1))}>
                Previous
              </button>
              <span className="st-metatag" aria-live="polite">Page {page} of {pageCount}</span>
              <button type="button" className="btn tap" disabled={page >= pageCount} onClick={() => setParam('page', String(page + 1))}>
                Next
              </button>
            </div>
          )}
        </section>
        <DpdpFootnote>Directory facts cite official sources · verify before applying</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-28 — School detail (facts, sources, save & follow)                        */
/* -------------------------------------------------------------------------- */

export function SchoolDetail() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const qc = useQueryClient();
  const id = sp.get('id') ?? '';
  const ret = sp.get('ret') ?? '';
  const [notifyOptIn, setNotifyOptIn] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ['law-school', id],
    queryFn: () => getLawSchoolDetail(id),
    enabled: id !== '',
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

  const back = () => nav(ret ? `/s-27?${ret}` : '/s-27');

  if (!id) {
    return (
      <StudentScreen screenId="S-28">
        <div className="st-stack">
          <ModuleHead eyebrow="Law schools · S5" title="School detail" />
          <ValidationState message="No school selected — open one from search." />
          <div className="st-actions">
            <button type="button" className="btn tap" onClick={back}>Back to search</button>
          </div>
        </div>
      </StudentScreen>
    );
  }

  const notFound = query.error instanceof LawSchoolsApiError && query.error.code === SCHOOL_NOT_FOUND;
  const d = query.data;

  return (
    <StudentScreen screenId="S-28">
      <div className="st-stack">
        <ModuleHead eyebrow="Law schools · S5" title={d?.name ?? 'School detail'} sub={d ? `${d.state} · ${d.institutionType}` : undefined} />
        {query.isPending && <LoadingState label="Loading school…" />}
        {query.isError && (notFound
          ? <EmptyState title="School not found" hint="It may have been removed from the directory." action={<button type="button" className="btn tap" onClick={back}>Back to search</button>} />
          : <QueryFailure error={query.error} onRetry={() => void query.refetch()} />)}
        {d && (
          <div className="st-grid">
            <section className="st-panel">
              <div className="st-panel__head">
                <h2 className="st-panel__title">At a glance</h2>
                <StatusBadge status="info" label={d.accreditation} />
              </div>
              <ul className="st-list">
                <li className="st-item"><div><div>Entrance exam</div><div className="st-item__meta">{d.entranceExam}</div></div></li>
                <li className="st-item"><div><div>Fees</div><div className="st-item__meta"><span className="st-price">{feesText(d)}</span></div></div></li>
                <li className="st-item"><div><div>NIRF rank</div><div className="st-item__meta">{d.nirfRank !== null ? `#${d.nirfRank}` : 'Not ranked'}</div></div></li>
                <li className="st-item">
                  <div>
                    <div>Programmes</div>
                    <div className="st-item__meta">
                      {d.programmes.length ? d.programmes.map((p) => `${p.degree} (${p.durationYears} yrs)`).join(' · ') : 'Not listed'}
                    </div>
                  </div>
                </li>
              </ul>
              <div className="st-actions" style={{ marginTop: 'var(--space-3)' }}>
                <button type="button" className="btn tap" aria-pressed={d.saved} disabled={saveMut.isPending} onClick={() => saveMut.mutate(d.saved)}>
                  {d.saved ? 'Saved ✓' : 'Save'}
                </button>
                <button type="button" className="btn tap" aria-pressed={d.followed} disabled={followMut.isPending} onClick={() => followMut.mutate(d.followed)}>
                  {d.followed ? 'Following ✓' : 'Follow'}
                </button>
              </div>
              {!d.followed && (
                <Checkbox id="follow-notify" label="Notify me about admission updates" checked={notifyOptIn} onChange={setNotifyOptIn} />
              )}
              {actionError && <ValidationState message={actionError} />}
            </section>
            <section className="st-panel">
              <h2 className="st-panel__title">Verified facts &amp; sources</h2>
              {d.facts.length === 0 ? (
                <EmptyState title="No facts published yet" />
              ) : (
                <ul className="st-list">
                  {d.facts.map((f) => (
                    <li className="st-item" key={f.key}>
                      <div>
                        <div>{f.key}</div>
                        <div className="st-item__meta">
                          {f.value} · <a href={f.sourceUrl} target="_blank" rel="noopener noreferrer">{f.sourceName}</a> · retrieved {f.retrievedAt}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
        <div className="st-actions st-actions--split">
          <button type="button" className="btn tap" onClick={back}>Back to search</button>
          <button type="button" className="btn tap" onClick={() => nav(`/s-30${ret ? `?ret=${encodeURIComponent(ret)}` : ''}`)}>
            Saved &amp; followed
          </button>
        </div>
        <DpdpFootnote>Facts carry their official source and retrieval date · verify before relying</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-29 — Compare (aligned table, min/max/duplicate rules)                     */
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
        return <ValidationState message={`You can compare at most ${max} schools — remove ${Math.max(1, ids.length - max)} and try again.`} />;
      }
      if (error.code === COMPARE_MIN_NOT_MET) {
        return <ValidationState message={`Select at least ${error.minRequired ?? COMPARE_MIN} schools to compare.`} />;
      }
      if (error.code === DUPLICATE_SCHOOL) {
        return <ValidationState message="The same school is selected twice — remove the duplicate." />;
      }
      if (error.code === SCHOOL_NOT_FOUND) {
        return <ValidationState message="One of the selected schools is no longer in the directory — remove it and retry." />;
      }
    }
    return <QueryFailure error={error} onRetry={() => void query.refetch()} />;
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

  return (
    <StudentScreen screenId="S-29">
      <div className="st-stack">
        <ModuleHead
          eyebrow="Law schools · S5"
          title="Compare schools"
          sub={`comparing ${ids.length} · minimum ${COMPARE_MIN} · maximum ${compareMax}`}
        />
        {ids.length < COMPARE_MIN && (
          <>
            <ValidationState message={`Select at least ${COMPARE_MIN} schools from search to compare (up to ${compareMax}).`} />
            <div className="st-actions">
              <button type="button" className="btn tap" onClick={back}>Back to search</button>
            </div>
          </>
        )}
        {ids.length >= COMPARE_MIN && query.isPending && <LoadingState label="Building comparison…" />}
        {ids.length >= COMPARE_MIN && query.isError && compareError(query.error)}
        {query.data && (
          <section className="st-panel" aria-label="Comparison table">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Side by side</h2>
              <span className="st-metatag">{query.data.items.length} of max {query.data.compareMax}</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="st-table">
                <thead>
                  <tr>
                    <th scope="col">Attribute</th>
                    {query.data.items.map((i) => (
                      <th scope="col" key={i.id}>
                        {i.name}
                        <div>
                          <button type="button" className="st-chip" onClick={() => removeSchool(i.id)} aria-label={`Remove ${i.name} from comparison`}>
                            Remove ✕
                          </button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.label}>
                      <th scope="row">{row.label}</th>
                      {query.data.items.map((i) => (
                        <td key={i.id}>{row.value(i)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={back}>Back to search</button>
        </div>
        <DpdpFootnote>Server enforces the compare limits · figures cite official sources</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

interface LawSchoolDetailLike extends LawSchoolSummary {
  programmes: Array<{ degree: string; durationYears: number }>;
}

/* -------------------------------------------------------------------------- */
/* S-30 — Saved & followed                                                     */
/* -------------------------------------------------------------------------- */

export function SchoolSavedFollowed() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const qc = useQueryClient();
  const ret = sp.get('ret') ?? '';

  const savedQ = useQuery({ queryKey: ['law-schools-saved'], queryFn: listSavedLawSchools });
  const followedQ = useQuery({ queryKey: ['law-schools-followed'], queryFn: listFollowedLawSchools });

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

  function list(
    label: string,
    q: typeof savedQ | typeof followedQ,
    actionLabel: string,
    onAction: (id: string) => void,
    actionPending: boolean,
    emptyHint: string,
  ) {
    return (
      <section className="st-panel" aria-label={label}>
        <div className="st-panel__head">
          <h2 className="st-panel__title">{label}</h2>
          <span className="st-metatag">{q.data ? `${q.data.length}` : '…'}</span>
        </div>
        {q.isPending && <LoadingState label={`Loading ${label.toLowerCase()}…`} />}
        {q.isError && <QueryFailure error={q.error} onRetry={() => void q.refetch()} />}
        {q.data && q.data.length === 0 && <EmptyState title={`No ${label.toLowerCase()} yet`} hint={emptyHint} />}
        {q.data && q.data.length > 0 && (
          <ul className="st-list">
            {q.data.map((s) => (
              <li className="st-item" key={s.id}>
                <div>
                  <div>{s.name}</div>
                  <div className="st-item__meta">
                    {s.state} · {s.entranceExam} · <span className="st-price">{feesText(s)}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                  <button type="button" className="btn tap" onClick={() => nav(`/s-28?id=${encodeURIComponent(s.id)}${ret ? `&ret=${encodeURIComponent(ret)}` : ''}`)}>
                    View
                  </button>
                  <button type="button" className="btn tap" disabled={actionPending} onClick={() => onAction(s.id)}>
                    {actionLabel}
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
    <StudentScreen screenId="S-30">
      <div className="st-stack">
        <ModuleHead eyebrow="Law schools · S5" title="Saved & followed" sub="your shortlist and admission updates" />
        {authError ? (
          <SignInPrompt />
        ) : (
          <>
            {list('Saved schools', savedQ, 'Unsave', (id) => unsaveMut.mutate(id), unsaveMut.isPending, 'Save schools from search or detail to build a shortlist.')}
            {list('Followed schools', followedQ, 'Unfollow', (id) => unfollowMut.mutate(id), unfollowMut.isPending, 'Follow a school to get admission updates.')}
          </>
        )}
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => nav(ret ? `/s-27?${ret}` : '/s-27')}>
            Back to search
          </button>
        </div>
        <DpdpFootnote>Follow notifications honour your notification settings (S-18)</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

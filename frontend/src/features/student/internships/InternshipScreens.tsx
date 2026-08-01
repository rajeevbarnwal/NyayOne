import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { StatusBadge, EmptyState, ValidationState } from '../../../components/ui/primitives';
import {
  filterListings,
  toggleSave,
  stipendText,
  stepForStatus,
  statusChip,
  newApplicationRef,
  validateApplicationPdf,
  validateCoverNote,
  saveSubmittedApplication,
  loadSubmittedApplications,
  loadLatestSubmittedApplication,
  loadSavedListingIds,
  saveSavedListingIds,
  APPLICATION_STAGES,
  SAMPLE_LISTINGS,
  SAMPLE_APPLICATIONS,
  type StipendFilter,
  type Application,
} from '../lib/internships';

function ModuleHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div>
      <p className="st-eyebrow">{eyebrow}</p>
      <h1 className="st-h1">{title}</h1>
      {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* S-20 — Browse & filter                                                      */
/* -------------------------------------------------------------------------- */
export function InternshipBrowse() {
  const nav = useNavigate();
  const [query, setQuery] = useState('');
  const [stipend, setStipend] = useState<StipendFilter>('any');
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [saved, setSaved] = useState<string[]>(() => loadSavedListingIds() ?? SAMPLE_LISTINGS.filter((listing) => listing.verified).map((listing) => listing.id));
  const results = useMemo(() => filterListings(SAMPLE_LISTINGS, { query, stipend, verifiedOnly }), [query, stipend, verifiedOnly]);
  const listingRow = (l: (typeof SAMPLE_LISTINGS)[number]) => (
    <li className="st-item" key={l.id}>
      <div>
        <div>{l.role} — {l.org}</div>
        <div className="st-item__meta">
          {l.location} · <span className="st-price">{stipendText(l)}</span> · deadline {l.deadline}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
        <StatusBadge status={l.verified ? 'ok' : 'info'} label={l.verified ? 'Verified listing' : 'Open'} />
        <button type="button" className="btn tap" aria-pressed={saved.includes(l.id)} onClick={() => setSaved((current) => {
          const next = toggleSave(current, l.id);
          saveSavedListingIds(next);
          return next;
        })}>
          {saved.includes(l.id) ? 'Saved' : 'Save'}
        </button>
        <button type="button" className="btn tap" onClick={() => nav('/s-21')}>View</button>
      </div>
    </li>
  );

  return (
    <StudentScreen screenId="S-20">
      <div className="st-stack">
        <ModuleHead eyebrow="Internships · S4" title="Internship Hub" sub="discover · filter · save" />
        <input
          className="st-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search role, city, stipend…"
          aria-label="Search internships"
        />
        <div className="st-tabsrow" role="group" aria-label="Filters">
          {(['any', 'paid', 'unpaid'] as StipendFilter[]).map((s) => (
            <button key={s} type="button" className="st-chip" aria-pressed={stipend === s} onClick={() => setStipend(s)}>
              {s === 'any' ? 'All stipends' : s === 'paid' ? 'Stipend' : 'Unpaid'}
            </button>
          ))}
          <button type="button" className="st-chip" aria-pressed={verifiedOnly} onClick={() => setVerifiedOnly((v) => !v)}>
            Verified only
          </button>
        </div>

        <section className="st-panel" aria-label="Open listings">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Open listings</h2>
            <span className="st-metatag">{results.length} shown</span>
          </div>
          {results.length === 0 ? (
            <EmptyState title="No matching listings" hint="Try clearing filters or a different search." />
          ) : (
            <>
              <ul className="st-list">{results.slice(0, 1).map(listingRow)}</ul>
              {results.length > 1 && (
                <details className="v34c-mobile-disclosure">
                  <summary>More listings <span>{results.length - 1} more</span></summary>
                  <ul className="st-list">{results.slice(1).map(listingRow)}</ul>
                </details>
              )}
            </>
          )}
        </section>
        <DpdpFootnote>Source: firm career pages · unverified · not affiliated</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-21 — Internship detail                                                    */
/* -------------------------------------------------------------------------- */
export function InternshipDetail() {
  const nav = useNavigate();
  const l = SAMPLE_LISTINGS[0];
  return (
    <StudentScreen screenId="S-21">
      <div className="st-stack">
        <ModuleHead eyebrow="Internships · S4" title={l.role} sub={l.org} />
        <div className="st-grid">
          <section className="st-panel">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Role</h2>
              <span className="st-metatag">sample listing</span>
            </div>
            <p>{l.description}</p>
            <div className="st-chips" style={{ marginTop: 'var(--space-3)' }}>
              {l.tags.map((t) => (
                <span key={t} className="status status--info">
                  <span className="ui-badge__mark" aria-hidden>
                    i
                  </span>
                  {t}
                </span>
              ))}
            </div>
          </section>
          <section className="st-panel">
            <h2 className="st-panel__title">Eligibility &amp; dates</h2>
            <p className="st-item__meta">{l.eligibility}</p>
            <div className="st-actions">
              <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-22')}>
                Apply now
              </button>
              <button type="button" className="btn tap" onClick={() => nav('/s-20')}>
                Back to listings
              </button>
            </div>
          </section>
        </div>
        <DpdpFootnote>{l.sourceLabel}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-22 — Apply (validation/error)                                             */
/* -------------------------------------------------------------------------- */
export function InternshipApply() {
  const nav = useNavigate();
  const [stage, setStage] = useState<'answers' | 'documents' | 'review'>('answers');
  const [cover, setCover] = useState('I am a 4th-year student at NLSIU focused on disputes, with a moot and legal-aid clinic behind me.');
  const [resume, setResume] = useState<File | null>(null);
  const [transcript, setTranscript] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  function validateAnswers(): boolean {
    const coverError = validateCoverNote(cover);
    setErrors((current) => ({ ...current, cover: coverError ?? '' }));
    return coverError === null;
  }

  function validateDocuments(): boolean {
    const nextErrors: Record<string, string> = {};
    const resumeError = validateApplicationPdf(resume, 'Résumé');
    const transcriptError = validateApplicationPdf(transcript, 'Transcript');
    if (resumeError) nextErrors.resume = resumeError;
    if (transcriptError) nextErrors.transcript = transcriptError;
    setErrors((current) => ({ ...current, resume: nextErrors.resume ?? '', transcript: nextErrors.transcript ?? '' }));
    return Object.keys(nextErrors).length === 0;
  }

  function goTo(next: 'answers' | 'documents' | 'review'): void {
    if (next === 'answers') { setStage(next); return; }
    if (!validateAnswers()) { setStage('answers'); return; }
    if (next === 'review' && !validateDocuments()) { setStage('documents'); return; }
    setStage(next);
  }

  function submit() {
    const coverOk = validateAnswers();
    const documentsOk = validateDocuments();
    if (!coverOk || !documentsOk) { setStage(!coverOk ? 'answers' : 'documents'); return; }
    const ref = newApplicationRef();
    saveSubmittedApplication({
      id: ref,
      listingId: 'cam',
      org: 'Cyril Amarchand Mangaldas',
      role: 'Summer Associate',
      meta: `Mumbai · submitted ${new Date().toLocaleDateString('en-IN')}`,
      status: 'applied',
      note: `Reference ${ref}`,
    });
    nav('/s-23');
  }
  return (
    <StudentScreen screenId="S-22">
      <div className="st-stack">
        <ModuleHead eyebrow="Cyril Amarchand Mangaldas · Summer Associate" title="Resume, transcript, cover note" sub="Three deliberate steps · nothing leaves LegalSaathi until review and send" />
        <div className="v34c-stages" role="tablist" aria-label="Application steps">
          {(['answers', 'documents', 'review'] as const).map((name, index) => (
            <button key={name} type="button" role="tab" aria-selected={stage === name} onClick={() => goTo(name)}>
              {index + 1} · {name === 'answers' ? 'Answers' : name === 'documents' ? 'Documents' : 'Review'}
              {name === 'documents' && (!resume || !transcript) && <small>files required</small>}
            </button>
          ))}
        </div>
        {stage === 'answers' && (
          <section className="st-panel" aria-label="Application answers">
            <h2 className="st-panel__title">Why this role</h2>
            <label className="st-field" htmlFor="app-cover">
              <span className="st-field__label">Cover note</span>
              <textarea id="app-cover" className="st-input" style={{ minHeight: 132 }} value={cover} maxLength={251} onChange={(e) => { setCover(e.target.value); setErrors((current) => ({ ...current, cover: '' })); }} aria-describedby={errors.cover ? 'app-cover-error app-cover-count' : 'app-cover-count'} />
              <span className="st-field__help" id="app-cover-count">{cover.trim().length} / 250 · minimum 50 characters</span>
              {errors.cover && <span id="app-cover-error"><ValidationState message={errors.cover} /></span>}
            </label>
            <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={() => goTo('documents')}>Continue to documents</button></div>
          </section>
        )}
        {stage === 'documents' && (
          <section className="st-panel" aria-label="Application documents">
            <h2 className="st-panel__title">Documents</h2>
            <p className="st-item__meta">PDF metadata is checked here. The server must still content-inspect every upload before submission.</p>
            <label className="st-field" htmlFor="app-resume">
              <span className="st-field__label">Résumé (PDF)</span>
              <input id="app-resume" className="st-input" type="file" accept="application/pdf,.pdf" onChange={(e) => { setResume(e.target.files?.[0] ?? null); setErrors((current) => ({ ...current, resume: '' })); }} aria-describedby={errors.resume ? 'app-resume-error' : undefined} />
              <span className="st-field__help">PDF only · non-empty · maximum 5 MB.</span>
              {errors.resume && <span id="app-resume-error"><ValidationState message={errors.resume} /></span>}
            </label>
            <label className="st-field" htmlFor="app-transcript">
              <span className="st-field__label">Transcript (PDF)</span>
              <input id="app-transcript" className="st-input" type="file" accept="application/pdf,.pdf" onChange={(e) => { setTranscript(e.target.files?.[0] ?? null); setErrors((current) => ({ ...current, transcript: '' })); }} aria-describedby={errors.transcript ? 'app-transcript-error' : undefined} />
              <span className="st-field__help">PDF only · non-empty · maximum 5 MB.</span>
              {errors.transcript && <span id="app-transcript-error"><ValidationState message={errors.transcript} /></span>}
            </label>
            <div className="st-actions st-actions--split"><button type="button" className="btn tap" onClick={() => setStage('answers')}>Back to answers</button><button type="button" className="btn btn--primary tap" onClick={() => goTo('review')}>Review application</button></div>
          </section>
        )}
        {stage === 'review' && (
          <section className="st-panel" aria-label="Review application">
            <h2 className="st-panel__title">Review before sending</h2>
            <div className="st-setrow"><div><div className="st-setrow__label">Cover note</div><div className="st-setrow__sub">{cover.trim().length} characters · ready</div></div></div>
            <div className="st-setrow"><div><div className="st-setrow__label">Résumé</div><div className="st-setrow__sub">{resume?.name ?? 'Missing'}</div></div></div>
            <div className="st-setrow"><div><div className="st-setrow__label">Transcript</div><div className="st-setrow__sub">{transcript?.name ?? 'Missing'}</div></div></div>
            <div className="st-actions st-actions--split"><button type="button" className="btn tap" onClick={() => setStage('documents')}>Back to documents</button><button type="button" className="btn btn--primary tap" onClick={submit}>Submit application</button></div>
          </section>
        )}
        <DpdpFootnote>Documents leave LegalSaathi only when you submit</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-23 — Confirmation (success)                                               */
/* -------------------------------------------------------------------------- */
export function InternshipConfirm() {
  const nav = useNavigate();
  const submitted = useMemo(() => loadLatestSubmittedApplication(), []);
  const ref = submitted?.id ?? 'Pending reference';
  return (
    <StudentScreen screenId="S-23" className="st-authwrap">
      <div className="st-card">
        <p className="st-card__kicker">Application submitted</p>
        <h1 className="st-card__title">You’ve applied — CAM Summer Associate</h1>
        <p className="st-card__sub">
          Reference <span className="st-price">#{ref}</span>.
        </p>
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-24')}>
            Open tracker
          </button>
        </div>
      </div>
    </StudentScreen>
  );
}

function Stepper({ current }: { current: number }) {
  return (
    <div className="st-steps" aria-label={`Stage ${current} of ${APPLICATION_STAGES.length}`}>
      {APPLICATION_STAGES.map((s, i) => {
        const n = i + 1;
        const cls = n < current ? 'st-steps__node--done' : n === current ? 'st-steps__node--now' : '';
        return (
          <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {i > 0 && <span className="st-steps__sep" aria-hidden />}
            <span className={`st-steps__node ${cls}`}>
              <span className="st-steps__dot" aria-hidden />
              {s}
            </span>
          </span>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* S-24 — Application tracker (status)                                         */
/* -------------------------------------------------------------------------- */
export function InternshipTracker() {
  const nav = useNavigate();
  const apps = [...loadSubmittedApplications(), ...SAMPLE_APPLICATIONS];
  const applicationRow = (a: Application) => {
    const chip = statusChip(a.status);
    return (
      <li className={`st-item${a.status === 'closed' ? ' st-item--dim' : ''}`} key={a.id}>
        <div>
          <div>{a.org}</div>
          <div className="st-item__meta">{a.role} · {a.meta}</div>
          <Stepper current={stepForStatus(a.status)} />
          {a.note && <div className="st-item__meta">{a.note}</div>}
        </div>
        <StatusBadge status={chip.kind} label={a.status === 'action_needed' ? 'Upload transcript' : chip.label} />
      </li>
    );
  };
  return (
    <StudentScreen screenId="S-24">
      <div className="st-stack">
        <ModuleHead eyebrow="Internships · S4" title="Internship Hub" sub="Discover, apply and track — status by shape + label, never colour alone" />
        <div className="st-tabsrow" role="tablist" aria-label="Internship views">
          <button role="tab" aria-selected className="st-tab">Tracker</button>
          <button role="tab" aria-selected={false} className="st-tab" onClick={() => nav('/s-20')}>Discover</button>
          <button role="tab" aria-selected={false} className="st-tab" onClick={() => nav('/s-25')}>Saved</button>
        </div>
        <section className="st-panel" aria-label="Your applications">
          <h2 className="st-panel__title">Your applications</h2>
          <ul className="st-list">{apps.slice(0, 1).map(applicationRow)}</ul>
          {apps.length > 1 && (
            <details className="v34c-mobile-disclosure">
              <summary>Earlier applications <span>{apps.length - 1} more</span></summary>
              <ul className="st-list">{apps.slice(1).map(applicationRow)}</ul>
            </details>
          )}
        </section>
        <DpdpFootnote>Source: firm career pages · external listings, unverified · not affiliated. Applications leave only when you submit</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-25 — Saved internships                                                    */
/* -------------------------------------------------------------------------- */
export function InternshipSaved() {
  const nav = useNavigate();
  const [savedIds, setSavedIds] = useState<string[]>(() => loadSavedListingIds() ?? SAMPLE_LISTINGS.filter((listing) => listing.verified).map((listing) => listing.id));
  const saved = SAMPLE_LISTINGS.filter((listing) => savedIds.includes(listing.id));
  function remove(id: string): void {
    const next = savedIds.filter((savedId) => savedId !== id);
    setSavedIds(next);
    saveSavedListingIds(next);
  }
  return (
    <StudentScreen screenId="S-25">
      <div className="st-stack">
        <ModuleHead eyebrow="Internships · S4" title="Saved internships" sub="synced to your account" />
        <section className="st-panel">
          <h2 className="st-panel__title">Saved</h2>
          {saved.length === 0 ? <EmptyState title="No saved internships yet" hint="Browse listings and save the ones you like." /> : <ul className="st-list">
            {saved.map((l) => (
              <li className="st-item" key={l.id}>
                <div>
                  <div>{l.role} — {l.org}</div>
                  <div className="st-item__meta">{l.location} · <span className="st-price">{stipendText(l)}</span></div>
                </div>
                <div className="st-actions"><button type="button" className="btn tap" onClick={() => remove(l.id)}>Remove</button><button type="button" className="btn tap" onClick={() => nav('/s-21')}>View</button></div>
              </li>
            ))}
          </ul>}
        </section>
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => nav('/s-26')}>See empty state</button>
        </div>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-26 — Empty / no saved                                                     */
/* -------------------------------------------------------------------------- */
export function InternshipEmpty() {
  const nav = useNavigate();
  return (
    <StudentScreen screenId="S-26">
      <div className="st-stack">
        <ModuleHead eyebrow="Internships · S4" title="Saved internships" />
        <EmptyState
          title="No saved internships yet"
          hint="Browse listings and save the ones you like."
          action={
            <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-20')}>
              Browse listings
            </button>
          }
        />
      </div>
    </StudentScreen>
  );
}

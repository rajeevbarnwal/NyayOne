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
  saveSubmittedApplication,
  loadSubmittedApplications,
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
  const [saved, setSaved] = useState<string[]>([]);
  const results = useMemo(() => filterListings(SAMPLE_LISTINGS, { query, stipend, verifiedOnly }), [query, stipend, verifiedOnly]);

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
            <ul className="st-list">
              {results.map((l) => (
                <li className="st-item" key={l.id}>
                  <div>
                    <div>
                      {l.role} — {l.org}
                    </div>
                    <div className="st-item__meta">
                      {l.location} · <span className="st-price">{stipendText(l)}</span> · deadline {l.deadline}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                    <StatusBadge status={l.verified ? 'ok' : 'info'} label={l.verified ? 'Verified listing' : 'Open'} />
                    <button type="button" className="btn tap" aria-pressed={saved.includes(l.id)} onClick={() => setSaved((s) => toggleSave(s, l.id))}>
                      {saved.includes(l.id) ? 'Saved' : 'Save'}
                    </button>
                    <button type="button" className="btn tap" onClick={() => nav('/s-21')}>
                      View
                    </button>
                  </div>
                </li>
              ))}
            </ul>
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
  const [cover, setCover] = useState('I am a 4th-year student at NLSIU focused on disputes…');
  const [resume, setResume] = useState<File | null>(null);
  const [transcript, setTranscript] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  function submit() {
    const nextErrors: Record<string, string> = {};
    const resumeError = validateApplicationPdf(resume, 'Résumé');
    const transcriptError = validateApplicationPdf(transcript, 'Transcript');
    if (resumeError) nextErrors.resume = resumeError;
    if (transcriptError) nextErrors.transcript = transcriptError;
    if (!cover.trim()) nextErrors.cover = 'Cover note is required.';
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
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
        <ModuleHead eyebrow="Internships · S4" title="Apply — CAM Summer Associate" />
        <section className="st-panel">
          <h2 className="st-panel__title">Your application</h2>
          <label className="st-field" htmlFor="app-resume">
            <span className="st-field__label">Résumé (PDF)</span>
            <input id="app-resume" className="st-input" type="file" accept="application/pdf,.pdf" onChange={(e) => setResume(e.target.files?.[0] ?? null)} aria-describedby={errors.resume ? 'app-resume-error' : undefined} />
            <span className="st-field__help">PDF only · maximum 5 MB.</span>
            {errors.resume && <span id="app-resume-error"><ValidationState message={errors.resume} /></span>}
          </label>
          <label className="st-field" htmlFor="app-cover">
            <span className="st-field__label">Cover note</span>
            <textarea id="app-cover" className="st-input" style={{ minHeight: 96, padding: 'var(--space-3)' }} value={cover} onChange={(e) => setCover(e.target.value)} />
            {errors.cover && <ValidationState message={errors.cover} />}
          </label>
          <label className="st-field" htmlFor="app-transcript">
            <span className="st-field__label">Transcript (PDF)</span>
            <input id="app-transcript" className="st-input" type="file" accept="application/pdf,.pdf" onChange={(e) => setTranscript(e.target.files?.[0] ?? null)} aria-describedby={errors.transcript ? 'app-transcript-error' : undefined} />
            <span className="st-field__help">PDF only · maximum 5 MB.</span>
            {errors.transcript && <span id="app-transcript-error"><ValidationState message={errors.transcript} /></span>}
          </label>
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={submit}>
              Submit application
            </button>
          </div>
        </section>
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
  const ref = useMemo(() => newApplicationRef(), []);
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
          <ul className="st-list">
            {apps.map((a: Application) => {
              const chip = statusChip(a.status);
              return (
                <li className={`st-item${a.status === 'closed' ? ' st-item--dim' : ''}`} key={a.id}>
                  <div>
                    <div>{a.org}</div>
                    <div className="st-item__meta">
                      {a.role} · {a.meta}
                    </div>
                    <Stepper current={stepForStatus(a.status)} />
                    {a.note && <div className="st-item__meta">{a.note}</div>}
                  </div>
                  <StatusBadge status={chip.kind} label={a.status === 'action_needed' ? 'Upload transcript' : chip.label} />
                </li>
              );
            })}
          </ul>
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
  // Demonstrates the saved list; empty variant is S-26.
  const saved = SAMPLE_LISTINGS.filter((l) => l.verified);
  return (
    <StudentScreen screenId="S-25">
      <div className="st-stack">
        <ModuleHead eyebrow="Internships · S4" title="Saved internships" sub="synced to your account" />
        <section className="st-panel">
          <h2 className="st-panel__title">Saved</h2>
          <ul className="st-list">
            {saved.map((l) => (
              <li className="st-item" key={l.id}>
                <div>
                  <div>{l.role} — {l.org}</div>
                  <div className="st-item__meta">{l.location} · <span className="st-price">{stipendText(l)}</span></div>
                </div>
                <button type="button" className="btn tap" onClick={() => nav('/s-21')}>View</button>
              </li>
            ))}
          </ul>
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

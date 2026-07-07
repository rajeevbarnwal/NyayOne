import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { GuardrailNotice, SourceVersionPill, StatusBadge } from '../../../components/ui/primitives';
import {
  orderTracks,
  syllabusFor,
  sourcePillText,
  SAMPLE_ITEMS_LABEL,
  SAMPLE_LAW_LABEL,
  ESTIMATED_PERCENTILE_LABEL,
  TRACK_NOTE_ENROLLED,
  type ExamTrack,
} from '../lib/exam';

function Head({ title, sub }: { title: string; sub?: string }) {
  return (
    <div>
      <p className="st-eyebrow">Exam Prep · S11</p>
      <h1 className="st-h1">{title}</h1>
      {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

const ACCURACY: Array<[string, number, boolean]> = [
  ['Legal Reasoning', 88, false],
  ['Reasoning', 81, false],
  ['English', 76, false],
  ['GK & Current Affairs', 64, true],
];

/* S-55 — Exam overview / track switcher (default) */
export function ExamOverview() {
  const nav = useNavigate();
  const tracks = orderTracks('law_ug');
  const [active, setActive] = useState<ExamTrack>(tracks[0]);
  return (
    <StudentScreen screenId="S-55">
      <div className="st-stack">
        <Head title={`Exam Prep Hub · ${active}`} sub="Persona-aware — tracks are ordered for your segment" />
        <div className="st-tabsrow" role="tablist" aria-label="Exam tracks">
          {tracks.map((t) => (
            <button key={t} role="tab" aria-selected={active === t} className="st-tab" onClick={() => setActive(t)}>
              {t}
            </button>
          ))}
          <button role="tab" aria-selected={false} className="st-tab">Analytics</button>
        </div>

        <div className="st-metarow">
          <SourceVersionPill source={sourcePillText(syllabusFor(active).meta.version)} />
        </div>

        <GuardrailNotice>{TRACK_NOTE_ENROLLED}</GuardrailNotice>

        <div className="st-grid">
          <section className="st-panel">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Timed mock · {active}</h2>
              <span className="st-metatag">{SAMPLE_ITEMS_LABEL}</span>
            </div>
            <p>Prelims mock — 100 questions</p>
            <p className="st-item__meta">2 hours · Law, GK &amp; current affairs, reasoning</p>
            <div className="st-actions">
              <button type="button" className="btn btn--primary tap">Start timed mock</button>
            </div>
            <p className="st-item__meta" style={{ marginTop: 'var(--space-3)' }}>
              {ESTIMATED_PERCENTILE_LABEL} · best 91.2 · avg 84.0
            </p>
          </section>

          <section className="st-panel">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Passage practice · Legal Reasoning</h2>
              <span className="st-metatag">{SAMPLE_LAW_LABEL}</span>
            </div>
            <p style={{ fontFamily: 'var(--font-serif)' }}>
              A promises to gift B ₹10,000 out of natural love, in a registered document. Enforceable?
            </p>
            <p className="st-item__meta">Q1 · APPLY THE PRINCIPLE</p>
            <div className="st-actions">
              <button type="button" className="btn tap">A — No, gifts always need consideration</button>
              <button type="button" className="btn tap">B — Yes, it falls within an excepted case</button>
            </div>
          </section>
        </div>

        <section className="st-panel" aria-label="Accuracy by section">
          <h2 className="st-panel__title">Accuracy by section</h2>
          <ul className="st-list">
            {ACCURACY.map(([label, pct, flag]) => (
              <li className="st-item" key={label}>
                <div>{label}</div>
                <StatusBadge status={flag ? 'warn' : 'ok'} label={`${pct}%`} />
              </li>
            ))}
          </ul>
        </section>

        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => nav('/s-60')}>View syllabus map</button>
        </div>
        <DpdpFootnote>Analytics are educational feedback from sample cohort data — not official scoring or a selection guarantee</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* S-60 — Syllabus map (source-versioned) */
export function ExamSyllabus() {
  const nav = useNavigate();
  const [track, setTrack] = useState<ExamTrack>('CLAT');
  const s = syllabusFor(track);
  return (
    <StudentScreen screenId="S-60">
      <div className="st-stack">
        <Head title="Syllabus map" sub="source-versioned" />
        <div className="st-tabsrow" role="tablist" aria-label="Track">
          {(['CLAT', 'AIBE', 'Judiciary'] as ExamTrack[]).map((t) => (
            <button key={t} role="tab" aria-selected={track === t} className="st-tab" onClick={() => setTrack(t)}>
              {t}
            </button>
          ))}
        </div>
        <section className="st-panel">
          <div className="st-panel__head">
            <h2 className="st-panel__title">{s.meta.pattern}</h2>
            <SourceVersionPill source={sourcePillText(s.meta.version)} />
          </div>
          <p>Each topic links to digests, drills and mocks.</p>
          <GuardrailNotice>Syllabi vary by cycle. Verify against the official notification before you rely on any topic list.</GuardrailNotice>
        </section>
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => nav('/s-55')}>Back to Exam Hub</button>
        </div>
        <DpdpFootnote>Content is source-versioned and sample/illustrative — no official exam claim without a verified source</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

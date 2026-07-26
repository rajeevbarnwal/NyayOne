import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { GuardrailNotice, SourceVersionPill, StatusBadge } from '../../../components/ui/primitives';
import {
  orderTracks,
  syllabusFor,
  sourcePillText,
  evaluateAnswers,
  revisionQueue,
  SAMPLE_ITEMS_LABEL,
  SAMPLE_LAW_LABEL,
  SAMPLE_SCORING_LABEL,
  EXPLANATION_SAMPLE_LABEL,
  VERIFY_CITATION_LABEL,
  SAMPLE_COHORT_LABEL,
  ESTIMATED_PERCENTILE_LABEL,
  ANALYTICS_DISCLAIMER,
  TRACK_NOTE_ENROLLED,
  SAMPLE_MOCK,
  SAMPLE_RESULT,
  ANALYTICS_SECTIONS,
  MOCK_TOTAL,
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
          <button role="tab" aria-selected={false} className="st-tab" onClick={() => nav('/s-59')}>Analytics</button>
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
              <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-56')}>Start timed mock</button>
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

/* -------------------------------------------------------------------------- */
/* S-56 — Timed mock runner                                                    */
/* -------------------------------------------------------------------------- */
export function ExamMock() {
  const nav = useNavigate();
  const q = SAMPLE_MOCK[0];
  const [answers, setAnswers] = useState<Record<string, number>>({ [q.id]: q.correctIndex });
  const answered = Object.keys(answers).length;
  const pct = Math.round((24 / MOCK_TOTAL) * 100);
  return (
    <StudentScreen screenId="S-56">
      <div className="st-stack">
        <Head title="Timed mock · in progress" sub="24 of 100" />
        <div className="st-grid">
          <section className="st-panel">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Question 24 of {MOCK_TOTAL}</h2>
              <span className="st-metatag">28:14 · {SAMPLE_ITEMS_LABEL}</span>
            </div>
            <p style={{ fontFamily: 'var(--font-serif)' }}>{q.prompt}</p>
            <div className="st-actions" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              {q.options.map((o, i) => (
                <button key={o} type="button" className="btn tap" aria-pressed={answers[q.id] === i} style={{ justifyContent: 'flex-start' }} onClick={() => setAnswers((a) => ({ ...a, [q.id]: i }))}>
                  {String.fromCharCode(65 + i)} · {o}
                </button>
              ))}
            </div>
            <div className="st-actions st-actions--split">
              <button type="button" className="btn tap">Previous</button>
              <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-57')}>Finish &amp; submit</button>
            </div>
          </section>
          <section className="st-panel">
            <h2 className="st-panel__title">Progress</h2>
            <div className="st-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Mock progress">
              <div className="st-progress__bar" style={{ width: `${pct}%` }} />
            </div>
            <p className="st-item__meta">{answered} answered · 3 flagged · {MOCK_TOTAL - 24} remaining</p>
          </section>
        </div>
        <DpdpFootnote>Sample items · not a real paper · source-versioned</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-57 — Mock result                                                          */
/* -------------------------------------------------------------------------- */
export function ExamResult() {
  const nav = useNavigate();
  const r = SAMPLE_RESULT;
  return (
    <StudentScreen screenId="S-57">
      <div className="st-stack">
        <Head title="Mock result" />
        <div className="st-grid">
          <section className="st-panel">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Mock result</h2>
              <span className="st-metatag">{SAMPLE_SCORING_LABEL}</span>
            </div>
            <div>
              <span className="st-ring">{r.score}</span> <span className="st-item__meta">/ {r.total}</span>
            </div>
            <div className="st-metarow">
              <StatusBadge status="ok" label={`Percentile ${r.estimatedPercentile}`} />
            </div>
            <p className="st-item__meta">{ESTIMATED_PERCENTILE_LABEL}.</p>
            <div className="st-actions">
              <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-58')}>Review questions</button>
            </div>
          </section>
          <section className="st-panel">
            <h2 className="st-panel__title">Section split</h2>
            <ul className="st-list">
              {r.sections.map((s) => (
                <li className="st-item" key={s.section}>
                  <div>{s.section}</div>
                  <StatusBadge status={s.weak ? 'warn' : 'ok'} label={`${s.accuracyPct}%`} />
                </li>
              ))}
            </ul>
          </section>
        </div>
        <DpdpFootnote>{ANALYTICS_DISCLAIMER}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-58 — Question review                                                      */
/* -------------------------------------------------------------------------- */
export function ExamReview() {
  const nav = useNavigate();
  // Demo: first answer wrong, second correct.
  const responses: Record<string, number> = { q12: 0, q13: 1 };
  const correct = evaluateAnswers(responses);
  return (
    <StudentScreen screenId="S-58">
      <div className="st-stack">
        <Head title="Question review" sub={`${correct} of ${SAMPLE_MOCK.length} correct`} />
        {SAMPLE_MOCK.map((q) => {
          const right = responses[q.id] === q.correctIndex;
          const label = q.explanationKind === 'citation' ? VERIFY_CITATION_LABEL : EXPLANATION_SAMPLE_LABEL;
          return (
            <section className="st-panel" key={q.id}>
              <div className="st-panel__head">
                <h2 className="st-panel__title">{q.id.toUpperCase()} · {q.section}</h2>
                <span className="st-metatag">{label}</span>
              </div>
              <div className="st-metarow">
                {right ? (
                  <StatusBadge status="ok" label="Correct" />
                ) : (
                  <>
                    <StatusBadge status="risk" label="Your answer wrong" />
                    <StatusBadge status="ok" label={`Correct: ${String.fromCharCode(65 + q.correctIndex)}`} />
                  </>
                )}
              </div>
              <p style={{ fontFamily: 'var(--font-serif)' }}>{q.explanation}</p>
            </section>
          );
        })}
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => nav('/s-59')}>View analytics</button>
        </div>
        <DpdpFootnote>Explanations are sample/illustrative — verify every citation against the official source</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-59 — Analytics                                                            */
/* -------------------------------------------------------------------------- */
export function ExamAnalytics() {
  const nav = useNavigate();
  const revise = revisionQueue(ANALYTICS_SECTIONS);
  return (
    <StudentScreen screenId="S-59">
      <div className="st-stack">
        <Head title="Analytics" sub="educational feedback only" />
        <div className="st-grid">
          <section className="st-panel">
            <h2 className="st-panel__title">Accuracy by section</h2>
            <ul className="st-list">
              {ANALYTICS_SECTIONS.map((s) => (
                <li className="st-item" key={s.section}>
                  <div>{s.section}</div>
                  <StatusBadge status={s.weak ? 'warn' : 'ok'} label={`${s.accuracyPct}%`} />
                </li>
              ))}
            </ul>
          </section>
          <section className="st-panel">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Trend</h2>
              <span className="st-metatag">{SAMPLE_COHORT_LABEL}</span>
            </div>
            <div className="st-ring">+6.2</div>
            <p className="st-item__meta">percentile, last 6 mocks</p>
            <p className="st-item__meta" style={{ marginTop: 'var(--space-3)' }}>Revise next: {revise.slice(0, 2).join(', ')}</p>
          </section>
        </div>
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => nav('/s-55')}>Back to Exam Hub</button>
        </div>
        <DpdpFootnote>{ANALYTICS_DISCLAIMER}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

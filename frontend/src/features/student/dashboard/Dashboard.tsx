import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { StatusBadge } from '../../../components/ui/primitives';
import {
  availableModules,
  upcomingModules,
  COMING_SOON_LABEL,
  CURRENT_RELEASE,
} from '../lib/dashboard';
import { profileTier, TIER_LABELS } from '../lib/profile';
import { getProfileDraft } from '../lib/profileStore';

const WEEK: Array<{ dow: string; date: number; event?: string }> = [
  { dow: 'MON', date: 6, event: 'Tutor 6:30p' },
  { dow: 'TUE', date: 7, event: 'Memorial II' },
  { dow: 'WED', date: 8, event: 'CAM 4:00p' },
  { dow: 'THU', date: 9, event: 'CLAT mock' },
  { dow: 'FRI', date: 10, event: 'Rent notice' },
  { dow: 'SAT', date: 11, event: 'Con-law grp' },
  { dow: 'SUN', date: 12 },
];

const NEXT_ACTIONS: Array<{ title: string; meta: string; chip: string; status: 'info' | 'warn' | 'ok' }> = [
  { title: 'Legal Reasoning — timed set', meta: 'Exam Prep · S11 · Today · 8:00 PM', chip: 'Timed 40 min', status: 'info' },
  { title: 'Memorial II — Constitutional Law Moot', meta: 'Moot · S8', chip: '2 days left', status: 'warn' },
  { title: 'Interview — Cyril Amarchand Mangaldas', meta: 'Internships · S4', chip: 'Confirmed', status: 'ok' },
  { title: 'Log 6 hrs — DLSA legal-aid camp', meta: 'Clinical · S12', chip: 'Pending faculty', status: 'warn' },
];

export function Dashboard() {
  const nav = useNavigate();
  const tier = profileTier(getProfileDraft());
  const live = availableModules(CURRENT_RELEASE);
  const soon = upcomingModules(CURRENT_RELEASE);

  return (
    <StudentScreen screenId="S-14" className="st-dash">
      <div className="st-dash__head">
        <h1>
          Good evening, Aditi. <span className="st-muted">— your week, one place.</span>
        </h1>
        <span className="st-badge">
          <span aria-hidden>✓</span> {TIER_LABELS[tier]}
        </span>
      </div>

      {/* Unified calendar strip */}
      <section className="st-panel" aria-label="Unified calendar this week">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Unified calendar · this week</h2>
          <button type="button" className="btn tap" onClick={() => nav('/s-90')}>
            Open calendar
          </button>
        </div>
        <div className="st-week">
          {WEEK.map((d) => (
            <div className="st-week__day" key={d.dow}>
              <div className="st-week__dow">
                {d.dow} {d.date}
              </div>
              {d.event && <div>{d.event}</div>}
            </div>
          ))}
        </div>
      </section>

      <div className="st-grid">
        {/* Next actions across modules */}
        <section className="st-panel" aria-label="Next actions across modules">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Next actions · across modules</h2>
          </div>
          <ul className="st-list">
            {NEXT_ACTIONS.map((a) => (
              <li className="st-item" key={a.title}>
                <div>
                  <div>{a.title}</div>
                  <div className="st-item__meta">{a.meta}</div>
                </div>
                <StatusBadge status={a.status} label={a.chip} />
              </li>
            ))}
          </ul>
        </section>

        {/* Momentum */}
        <section className="st-panel" aria-label="Momentum">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Momentum</h2>
          </div>
          <div className="st-ring" aria-hidden>
            82%
          </div>
          <div className="st-setrow__sub">Profile &amp; readiness</div>
          <p className="st-setrow__sub">Add Bar enrolment when eligible — optional &amp; private.</p>
          <div className="st-kpis">
            <div>
              <div className="st-kpi__n">12</div>
              <div className="st-kpi__l">day streak</div>
            </div>
            <div>
              <div className="st-kpi__n">62</div>
              <div className="st-kpi__l">clinical hrs</div>
            </div>
            <div>
              <div className="st-kpi__n">3</div>
              <div className="st-kpi__l">moots</div>
            </div>
          </div>
        </section>
      </div>

      {/* Explore modules — graceful degradation for unreleased tranches */}
      <section className="st-panel" aria-label="Explore modules">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Explore · {CURRENT_RELEASE} modules</h2>
        </div>
        <div className="st-grid">
          {live.map((m) => (
            <button key={m.id} type="button" className="btn tap" style={{ justifyContent: 'flex-start' }} onClick={() => nav(m.route)}>
              {m.label}
            </button>
          ))}
          {soon.map((m) => (
            <button
              key={m.id}
              type="button"
              className="btn tap"
              disabled
              aria-disabled="true"
              title={`${m.label} — ${COMING_SOON_LABEL} (${m.release})`}
              style={{ justifyContent: 'space-between', opacity: 0.7 }}
            >
              <span>{m.label}</span>
              <span className="st-item__meta">{COMING_SOON_LABEL}</span>
            </button>
          ))}
        </div>
      </section>

      <DpdpFootnote>Data minimised — your calendar &amp; activity stay private to you</DpdpFootnote>
    </StudentScreen>
  );
}

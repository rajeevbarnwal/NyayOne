import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { StatusBadge } from '../../../components/ui/primitives';
import {
  availableModules,
  upcomingModules,
  COMING_SOON_LABEL,
  CURRENT_RELEASE,
  profileCompletionPct,
} from '../lib/dashboard';
import { profileTier, TIER_LABELS } from '../lib/profile';
import { getProfileDraft } from '../lib/profileStore';
import { aggregate, localDateDisplay, localDateKey, localTime, sampleSourceResults, SOURCE_LABELS } from '../lib/calendar';
import { SAMPLE_ENTRIES, totalHours } from '../lib/clinical';

const DASHBOARD_WEEK_START = new Date('2026-07-19T00:00:00.000Z');

export function Dashboard() {
  const nav = useNavigate();
  const profile = getProfileDraft();
  const tier = profileTier(profile);
  const firstName = profile.fullName.trim().split(/\s+/)[0] || 'Student';
  const live = availableModules(CURRENT_RELEASE);
  const soon = upcomingModules(CURRENT_RELEASE);
  const events = aggregate(sampleSourceResults()).events;
  const week = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(DASHBOARD_WEEK_START);
    date.setUTCDate(date.getUTCDate() + i);
    const key = date.toISOString().slice(0, 10);
    const event = events.find((e) => localDateKey(e.startsAt, e.timezone) === key);
    return {
      dow: date.toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'UTC' }).toUpperCase(),
      date: date.getUTCDate(),
      event: event ? `${event.title} · ${localTime(event.startsAt, event.timezone)}` : undefined,
    };
  });
  const nextActions = events.slice(0, 4).map((e) => ({
    title: e.title,
    meta: `${SOURCE_LABELS[e.sourceType]} · ${localDateDisplay(e.startsAt, e.timezone)} · ${localTime(e.startsAt, e.timezone)}`,
    chip: e.status === 'deadline' ? 'Deadline' : e.status === 'tentative' ? 'Tentative' : 'Scheduled',
    status: (e.status === 'deadline' ? 'warn' : e.status === 'done' ? 'ok' : 'info') as 'info' | 'warn' | 'ok',
  }));
  const completion = profileCompletionPct(profile);
  const clinicalHours = totalHours(SAMPLE_ENTRIES);

  return (
    <StudentScreen screenId="S-14" className="st-dash">
      <div className="st-dash__head">
        <h1>
          Good evening, {firstName}. <span className="st-muted">— your week, one place.</span>
        </h1>
        <span className="st-badge">
          <span aria-hidden>✓</span> {TIER_LABELS[tier]}
        </span>
      </div>

      {/* Unified calendar strip */}
      <section className="st-panel" aria-label="Unified calendar this week">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Calendar · this week</h2>
          <button type="button" className="btn tap" onClick={() => nav('/s-90')}>
            Open calendar
          </button>
        </div>
        <div className="st-week">
          {week.map((d) => (
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
            {nextActions.map((a) => (
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
            {completion}%
          </div>
          <div className="st-setrow__sub">Profile &amp; readiness</div>
          <p className="st-setrow__sub">Add Bar enrolment when eligible — optional &amp; private.</p>
          <div className="st-kpis">
            <div>
              <div className="st-kpi__n">{events.length}</div>
              <div className="st-kpi__l">calendar events</div>
            </div>
            <div>
              <div className="st-kpi__n">{clinicalHours}</div>
              <div className="st-kpi__l">clinical hrs</div>
            </div>
            <div>
              <div className="st-kpi__n">{live.length}</div>
              <div className="st-kpi__l">active modules</div>
            </div>
          </div>
        </section>
      </div>

      {/* Explore modules — graceful degradation for unreleased tranches */}
      <section className="st-panel" aria-label="Explore modules">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Explore</h2>
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

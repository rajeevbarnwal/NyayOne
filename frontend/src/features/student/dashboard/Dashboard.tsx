import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
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
import { getStudentProfile, PROFILE_KEY } from '../lib/settingsApi';
import { aggregate, localDateDisplay, localDateKey, localTime, resolveEventBadge, sampleSourceResults, SOURCE_LABELS } from '../lib/calendar';
import { SAMPLE_ENTRIES, totalHours } from '../lib/clinical';

const DASHBOARD_WEEK_START = new Date('2026-07-19T00:00:00.000Z');

export function Dashboard() {
  const nav = useNavigate();
  const profile = getProfileDraft();
  const tier = profileTier(profile);

  const profileQuery = useQuery({
    queryKey: PROFILE_KEY,
    queryFn: getStudentProfile,
    retry: false,
  });
  const serverFirstName = profileQuery.data?.firstName;
  const firstName = profile.firstName?.trim() || profile.fullName?.trim()?.split(/\s+/)[0] || serverFirstName || 'Student';
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
  const nextActions = events.slice(0, 4).map((e) => {
    const badge = resolveEventBadge(e);
    return {
      title: e.title,
      meta: `${SOURCE_LABELS[e.sourceType]} · ${localDateDisplay(e.startsAt, e.timezone)} · ${localTime(e.startsAt, e.timezone)}`,
      chip: badge.label,
      status: badge.status,
    };
  });
  const completion = profileCompletionPct(profile);
  const clinicalHours = totalHours(SAMPLE_ENTRIES);

  return (
    <StudentScreen screenId="S-14" className="st-dash">
      <div className="st-dash__head">
        <div>
          <p className="st-eyebrow">Saturday · your week, one place</p>
          <h1>Good evening, {firstName}.</h1>
          <p className="st-metatag" style={{ marginTop: 8 }}>Your deadlines, sessions and applications stay together without exposing private activity.</p>
        </div>
        <span className={`st-badge ${completion < 100 ? 'st-badge--warning' : ''}`} style={completion < 100 ? { backgroundColor: '#fffbe6', borderColor: '#ffe58f', color: '#d46b08' } : undefined}>
          <span aria-hidden>{completion === 100 ? '✓' : '⚠️'}</span> {completion === 100 ? TIER_LABELS[tier] : `Profile incomplete (${completion}%)`}
        </span>
      </div>

      {completion < 100 && (
        <div style={{ backgroundColor: '#fffbe6', border: '1px solid #ffe58f', borderRadius: '8px', padding: '12px 16px', marginBottom: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <strong style={{ color: '#873800' }}>Your profile setup is {completion}% complete</strong>
            <p style={{ margin: '2px 0 0 0', fontSize: '13px', color: '#595959' }}>Finish setting up your academic details to unlock full internship applications.</p>
          </div>
          <button
            type="button"
            className="v34-submit-btn"
            style={{ width: 'auto', padding: '8px 16px', fontSize: '13px' }}
            onClick={() => nav(`/s-10?step=${!profile.college ? 'academic' : 'interests'}`)}
          >
            Finish Profile Setup
          </button>
        </div>
      )}

      {/* Unified calendar strip */}
      <details className="v34c-mobile-disclosure">
        <summary>Calendar · this week <span>7 days</span></summary>
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
      </details>

      <details className="v34c-mobile-disclosure">
        <summary>Actions &amp; momentum <span>{nextActions.length} actions</span></summary>
        <div className="st-grid">
        {/* Next actions across modules */}
        <section className="st-panel" aria-label="Next actions across modules">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Next actions · across modules</h2>
          </div>
          <ul className="st-list">
            {nextActions.slice(0, 2).map((a) => (
              <li className="st-item" key={a.title}>
                <div>
                  <div>{a.title}</div>
                  <div className="st-item__meta">{a.meta}</div>
                </div>
                <StatusBadge status={a.status} label={a.chip} />
              </li>
            ))}
          </ul>
          {nextActions.length > 2 && (
            <details className="v34c-disclosure">
              <summary>The week ahead <span>{nextActions.length - 2} more</span></summary>
              <ul className="st-list">
                {nextActions.slice(2).map((a) => (
                  <li className="st-item" key={a.title}>
                    <div><div>{a.title}</div><div className="st-item__meta">{a.meta}</div></div>
                    <StatusBadge status={a.status} label={a.chip} />
                  </li>
                ))}
              </ul>
            </details>
          )}
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
      </details>

      {/* Explore modules — graceful degradation for unreleased tranches */}
      <details className="v34c-mobile-disclosure">
        <summary>Explore modules <span>{live.length} available</span></summary>
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
      </details>

      <DpdpFootnote>Data minimised — your calendar &amp; activity stay private to you</DpdpFootnote>
    </StudentScreen>
  );
}

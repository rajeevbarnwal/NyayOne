import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { StudentScreen, DpdpFootnote } from '../components';
import { ErrorState, LoadingState, StatusBadge } from '../../../components/ui/primitives';
import {
  availableModules,
  upcomingModules,
  COMING_SOON_LABEL,
  CURRENT_RELEASE,
} from '../lib/dashboard';
import { profileErrorMessage, type DisabledProfileCapability } from '../lib/profileApi';
import { CompletionCard } from '../profile/ProfileScreens';
import { useStudentProfileProjection } from '../profile/profileHooks';
import { DEFAULT_TZ, localDateKey, localTime, SOURCE_LABELS, type CalendarEventStatus } from '../lib/calendar';
import { getCalendarViewPreferences, listCalendarEvents, type CalendarEventRecord } from '../lib/calendarApi';
import { SAMPLE_ENTRIES, totalHours } from '../lib/clinical';

export function dashboardWeekday(now: Date, timezone: string): string {
  return new Intl.DateTimeFormat('en-IN', { weekday: 'long', timeZone: timezone }).format(now);
}

export function calendarStatusPresentation(status: CalendarEventStatus): {
  chip: string;
  tone: 'info' | 'warn' | 'ok';
} {
  if (status === 'deadline') return { chip: 'Deadline', tone: 'warn' };
  if (status === 'tentative') return { chip: 'Tentative', tone: 'info' };
  if (status === 'done') return { chip: 'Done', tone: 'ok' };
  if (status === 'cancelled') return { chip: 'Cancelled', tone: 'warn' };
  return { chip: 'Scheduled', tone: 'info' };
}

export function dashboardModuleIsDisabled(
  moduleId: string,
  disabledCapabilities: readonly DisabledProfileCapability[],
): boolean {
  return moduleId === 'community' && disabledCapabilities.includes('community');
}

export function currentWeek(now = new Date(), timezone = DEFAULT_TZ) {
  // Convert the current instant to a calendar date in the product timezone,
  // then perform date-only arithmetic at UTC noon.  Noon avoids DST/date-edge
  // rollover while localDateKey remains the authority for event matching.
  const todayKey = localDateKey(now.toISOString(), timezone);
  const cursor = new Date(`${todayKey}T12:00:00.000Z`);
  const daysSinceMonday = (cursor.getUTCDay() + 6) % 7;
  cursor.setUTCDate(cursor.getUTCDate() - daysSinceMonday);
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(cursor);
    date.setUTCDate(cursor.getUTCDate() + index);
    return date;
  });
}

export function buildDashboardWeek(now: Date, timezone: string, events: readonly CalendarEventRecord[]) {
  return currentWeek(now, timezone).map((date) => {
    const key = date.toISOString().slice(0, 10);
    const event = events.find((item) => localDateKey(item.startsAt, timezone) === key);
    return {
      key,
      dow: date.toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'UTC' }).toUpperCase(),
      date: date.getUTCDate(),
      event: event ? `${event.title} · ${localTime(event.startsAt, timezone)}` : undefined,
    };
  });
}

export function Dashboard() {
  const nav = useNavigate();
  const location = useLocation();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const restoredPromptFocus = useRef(false);
  const profileQuery = useStudentProfileProjection();
  const firstName = profileQuery.data?.profile.personal.firstName || 'Student';
  const live = availableModules(CURRENT_RELEASE);
  const soon = upcomingModules(CURRENT_RELEASE);
  const calendarPreferences = useQuery({
    queryKey: ['calendar', 'view-preferences'],
    queryFn: getCalendarViewPreferences,
    retry: false,
  });
  const timezone = calendarPreferences.data?.timezone ?? DEFAULT_TZ;
  const calendar = useQuery({
    queryKey: ['calendar', 'dashboard-events', timezone],
    queryFn: () => listCalendarEvents({ timezone }),
    enabled: !calendarPreferences.isPending,
    retry: false,
  });
  const events = calendar.data?.items ?? [];
  const now = new Date();
  const week = buildDashboardWeek(now, timezone, events);
  const weekday = dashboardWeekday(now, timezone);
  const hour = Number(new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', hourCycle: 'h23', timeZone: timezone,
  }).format(now));
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const nextActions = events.slice(0, 4).map((e) => {
    const presentation = calendarStatusPresentation(e.status);
    return {
      title: e.title,
      meta: `${SOURCE_LABELS[e.sourceType]} · ${localDateKey(e.startsAt, timezone)} · ${localTime(e.startsAt, timezone)}`,
      chip: presentation.chip,
      status: presentation.tone,
    };
  });
  const completion = profileQuery.data?.completionPercent;
  const clinicalHours = totalHours(SAMPLE_ENTRIES);

  useEffect(() => {
    if (
      profileQuery.data
      && !restoredPromptFocus.current
      && Boolean((location.state as { focusProfilePromptDestination?: boolean } | null)?.focusProfilePromptDestination)
    ) {
      restoredPromptFocus.current = true;
      headingRef.current?.focus();
    }
  }, [location.state, profileQuery.data]);

  if (!profileQuery.data) {
    return (
      <StudentScreen screenId="S-14" className="st-dash">
        {profileQuery.isPending ? <LoadingState label="Loading your dashboard…" /> : (
          <ErrorState
            title="Could not load your profile"
            detail={profileErrorMessage(profileQuery.error)}
            onRetry={() => { void profileQuery.refetch(); }}
          />
        )}
      </StudentScreen>
    );
  }

  const profile = profileQuery.data;
  const accessibleLive = live.filter((module) => (
    !dashboardModuleIsDisabled(module.id, profile.disabledCapabilities)
  ));
  const restrictedLive = live.filter((module) => (
    dashboardModuleIsDisabled(module.id, profile.disabledCapabilities)
  ));
  const verificationLabel = profile.institutionalEmailStatus === 'verified'
    ? 'Institutional email verified'
    : 'Verification not complete';

  return (
    <StudentScreen screenId="S-14" className="st-dash">
      <div className="st-dash__head">
        <div>
          <p className="st-eyebrow">{weekday} · your week, one place</p>
          <h1 ref={headingRef} tabIndex={-1}>{greeting}, {firstName}.</h1>
          <p className="st-metatag" style={{ marginTop: 8 }}>Your deadlines, sessions and applications stay together without exposing private activity.</p>
        </div>
        <span className="st-badge">
          {verificationLabel}
        </span>
      </div>

      <CompletionCard projection={profile} />

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
              <div className="st-week__day" key={d.key}>
                <div className="st-week__dow">
                  {d.dow} {d.date}
                </div>
                {d.event && <div>{d.event}</div>}
              </div>
            ))}
          </div>
          {(calendarPreferences.isPending || calendar.isPending) && <p className="st-item__meta" role="status">Loading calendar…</p>}
          {(calendarPreferences.isError || calendar.isError) && <p className="st-item__meta" role="alert">Calendar preview is unavailable. Open Calendar to retry.</p>}
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
          <div className="st-ring" aria-label={`Profile ${completion}% complete`} data-testid="profile-momentum-percent">
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
              <div className="st-kpi__n">{accessibleLive.length}</div>
              <div className="st-kpi__l">active modules</div>
            </div>
          </div>
        </section>
        </div>
      </details>

      {/* Explore modules — graceful degradation for unreleased tranches */}
      <details className="v34c-mobile-disclosure">
        <summary>Explore modules <span>{accessibleLive.length} available</span></summary>
        <section className="st-panel" aria-label="Explore modules">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Explore</h2>
          </div>
          <div className="st-grid">
            {accessibleLive.map((m) => (
              <button key={m.id} type="button" className="btn tap" style={{ justifyContent: 'flex-start' }} onClick={() => nav(m.route)}>
                {m.label}
              </button>
            ))}
            {restrictedLive.map((m) => (
              <button
                key={m.id}
                type="button"
                className="btn tap"
                disabled
                aria-disabled="true"
                title={`${m.label} — restricted by your server-issued access policy`}
                style={{ justifyContent: 'space-between', opacity: 0.7 }}
              >
                <span>{m.label}</span>
                <span className="st-item__meta">Restricted</span>
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

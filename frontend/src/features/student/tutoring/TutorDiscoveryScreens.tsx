/**
 * S-31 `tutoring/search` and S-32 `tutoring/detail` (SAATHI-65, matrix A1-A3).
 *
 * Real screens against the P3 routes:
 *   S-31  GET /api/v1/tutors                        (filters, sort, pagination)
 *   S-32  GET /api/v1/tutors/{id}                   (verified claims + provenance)
 *         GET /api/v1/tutors/{id}/availability      (slots + retained timezone)
 *
 * Visual contract: docs/design/tutoring/option_c2_reference_v1 (families `list`
 * and `profile`). Two deliberate deviations, both because the approved frame
 * shows a value P3 does not publish — see the comments at USE OF THE RAIL and
 * FEE, below. Nothing is fabricated to fill the gap.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  getAvailability,
  getTutor,
  searchTutors,
  tutoringKeys,
  tutoringRetry,
  TUTOR_SORTS,
  type AvailabilitySlot,
  type TutorSearchParams,
  type TutorSort,
  type TutorSummary,
} from '../lib/tutoringApi';
import {
  DEFAULT_HOLD_MINUTES,
  DEFAULT_TIMEZONE,
  browserTimeZone,
  durationMinutes,
  normaliseSearch,
  slotTimeLabels,
} from '../lib/tutoringRules';
import {
  Banner,
  Chip,
  Disclosure,
  EmptyState,
  Ic,
  Kv,
  LoadingState,
  Portrait,
  TutoringScreen,
  TypedErrorState,
  monogram,
  useRouteArrival,
} from './TutoringPrimitives';

const PAGE_SIZE = 10;

const SORT_LABELS: Record<string, string> = {
  rating_desc: 'Highest rated',
  rating_asc: 'Lowest rated',
  experience_desc: 'Most experienced',
  experience_asc: 'Newest to practice',
  name_asc: 'Name A to Z',
  newest: 'Recently added',
};

function isSort(value: string | null): value is TutorSort {
  return TUTOR_SORTS.includes((value ?? '') as TutorSort);
}

/** Read the whole S-31 query state out of the URL, so it is shareable and back-able. */
function paramsFromUrl(sp: URLSearchParams): TutorSearchParams {
  const minRating = Number(sp.get('min_rating') ?? '');
  const minExperience = Number(sp.get('min_experience_years') ?? '');
  const offset = Number(sp.get('offset') ?? '0');
  return {
    q: normaliseSearch(sp.get('q')) || undefined,
    subject: sp.get('subject') ?? undefined,
    level: sp.get('level') ?? undefined,
    minRating: Number.isFinite(minRating) && minRating > 0 ? minRating : undefined,
    minExperienceYears:
      Number.isInteger(minExperience) && minExperience > 0 ? minExperience : undefined,
    verifiedOnly: sp.get('verified_only') === '1',
    sort: isSort(sp.get('sort')) ? (sp.get('sort') as TutorSort) : 'rating_desc',
    limit: PAGE_SIZE,
    offset: Number.isFinite(offset) && offset > 0 ? Math.floor(offset) : 0,
  };
}

function ratingText(tutor: TutorSummary): string {
  if (tutor.ratingAvg === null || tutor.ratingCount === 0) return 'No reviews yet';
  return `${tutor.ratingAvg} from ${tutor.ratingCount} ${tutor.ratingCount === 1 ? 'review' : 'reviews'}`;
}

function experienceText(years: number): string {
  if (years <= 0) return 'Experience not declared';
  return `${years} ${years === 1 ? 'year' : 'years'} in practice`;
}

/* ========================================================================== *
 * S-31 — tutor discovery
 * ========================================================================== */

export function TutorSearch() {
  const [sp, setSp] = useSearchParams();
  const params = useMemo(() => paramsFromUrl(sp), [sp]);
  const [draftQuery, setDraftQuery] = useState(params.q ?? '');
  useRouteArrival('S-31');

  useEffect(() => { setDraftQuery(params.q ?? ''); }, [params.q]);

  const query = useQuery({
    queryKey: tutoringKeys.tutors(params),
    queryFn: () => searchTutors(params),
    retry: tutoringRetry,
    staleTime: 30_000,
  });

  const setParam = (updates: Record<string, string | null>, resetPage = true): void => {
    const next = new URLSearchParams(sp);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    if (resetPage) next.delete('offset');
    setSp(next, { replace: false });
  };

  const clearAll = (): void => setSp(new URLSearchParams(), { replace: false });

  const activeFilterCount = [
    params.q, params.subject, params.level,
    params.minRating, params.minExperienceYears,
    params.verifiedOnly ? '1' : undefined,
  ].filter(Boolean).length;

  /*
   * USE OF THE RAIL — deliberate deviation from the approved frame.
   * The reference rail is a PRACTICE-AREA filter. P3 publishes no subject
   * vocabulary (`GET /tutors` returns no subject list and there is no taxonomy
   * route), and hard-coding five practice areas would put invented data on a
   * production screen. The rail composition is kept exactly and bound to the
   * one enumerated vocabulary the server DOES return: `allowed_sorts`. Subject
   * and level stay real, free-text server filters inside "Refine".
   */
  const sorts = query.data?.allowedSorts?.length ? query.data.allowedSorts : [...TUTOR_SORTS];

  const total = query.data?.total ?? 0;
  const shown = query.data?.items.length ?? 0;
  const offset = params.offset ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <TutoringScreen screenId="S-31">
      <div>
        <div className="tt-eyebrow">Digital chambers</div>
        <h1 className="tt-h tt-arrival">Learn live from practising advocates.</h1>
        <p className="tt-p" style={{ marginTop: '5px' }}>
          Verified mentors, a {DEFAULT_HOLD_MINUTES} minute hold while you pay, and free
          cancellation at 24 hours notice.
        </p>
      </div>

      <div className="tt-shead">
        <form
          className="tt-spill"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            setParam({ q: normaliseSearch(draftQuery) });
          }}
        >
          <label className="tt-sr" htmlFor="tt-q">Search mentors by subject, headline or name</label>
          <input
            id="tt-q"
            type="search"
            maxLength={120}
            placeholder="Search subject, headline or name"
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
          />
          <button className="tt-go" type="submit" aria-label="Search mentors">
            <Ic name="search" />
          </button>
        </form>

        <div className="tt-railwrap">
          <div className="tt-rails" role="group" aria-label="Sort results">
            {sorts.map((sort) => (
              <button
                key={sort}
                type="button"
                className="tt-rail"
                aria-pressed={params.sort === sort}
                onClick={() => setParam({ sort })}
              >
                <i aria-hidden />
                {SORT_LABELS[sort] ?? sort}
              </button>
            ))}
          </div>
        </div>
      </div>

      <Disclosure summary={`Refine${activeFilterCount ? ` (${activeFilterCount} active)` : ''}`} icon="dev">
        <div className="tt-grid2">
          <div className="tt-fld">
            <label htmlFor="tt-subject">Subject</label>
            <input
              id="tt-subject"
              className="tt-in"
              maxLength={80}
              defaultValue={params.subject ?? ''}
              onBlur={(event) => setParam({ subject: event.target.value.trim() || null })}
            />
          </div>
          <div className="tt-fld">
            <label htmlFor="tt-level">Level</label>
            <input
              id="tt-level"
              className="tt-in"
              maxLength={40}
              defaultValue={params.level ?? ''}
              onBlur={(event) => setParam({ level: event.target.value.trim() || null })}
            />
          </div>
          <div className="tt-fld">
            <label htmlFor="tt-minrating">Minimum rating</label>
            <select
              id="tt-minrating"
              className="tt-in tt-sel"
              value={params.minRating ? String(params.minRating) : ''}
              onChange={(event) => setParam({ min_rating: event.target.value || null })}
            >
              <option value="">Any rating</option>
              <option value="3">3 and above</option>
              <option value="4">4 and above</option>
              <option value="4.5">4.5 and above</option>
            </select>
          </div>
          <div className="tt-fld">
            <label htmlFor="tt-minexp">Minimum experience</label>
            <select
              id="tt-minexp"
              className="tt-in tt-sel"
              value={params.minExperienceYears ? String(params.minExperienceYears) : ''}
              onChange={(event) => setParam({ min_experience_years: event.target.value || null })}
            >
              <option value="">Any experience</option>
              <option value="3">3 years or more</option>
              <option value="5">5 years or more</option>
              <option value="10">10 years or more</option>
            </select>
          </div>
        </div>
        <button
          type="button"
          className="tt-btn"
          aria-pressed={params.verifiedOnly}
          onClick={() => setParam({ verified_only: params.verifiedOnly ? null : '1' })}
        >
          <Ic name="check" />
          {params.verifiedOnly ? 'Showing verified mentors only' : 'Show verified mentors only'}
        </button>
      </Disclosure>

      {query.isPending && <LoadingState what="mentors" />}

      {query.isError && (
        <TypedErrorState error={query.error} onRecover={() => query.refetch()} />
      )}

      {query.isSuccess && shown === 0 && (
        <EmptyState
          title="No mentors match that search"
          detail="Nothing matched these filters. Clear them to see every mentor, or search a broader subject."
          action={
            <button type="button" className="tt-btn tt-btn--block" onClick={clearAll}>
              Clear filters and show all mentors
            </button>
          }
        />
      )}

      {query.isSuccess && shown > 0 && (
        <>
          <p className="tt-p tt-muted">
            Showing {shown} of {total} {total === 1 ? 'mentor' : 'mentors'} · page {page}
          </p>
          {query.data.items.map((tutor, index) => (
            <TutorCard key={tutor.id} tutor={tutor} lead={index === 0 && offset === 0} />
          ))}
          <div className="tt-dockrow">
            <button
              type="button"
              className="tt-btn"
              disabled={offset === 0}
              onClick={() => setParam({ offset: String(Math.max(0, offset - PAGE_SIZE)) }, false)}
            >
              <Ic name="back" />
              Previous page
            </button>
            <button
              type="button"
              className="tt-btn"
              disabled={!query.data.hasMore}
              onClick={() => setParam({ offset: String(offset + PAGE_SIZE) }, false)}
            >
              Next page
            </button>
          </div>
        </>
      )}

      <p className="tt-svr">
        server-authoritative: result set, ranking, verification and rating aggregate ·
        the client never computes eligibility or price
      </p>
    </TutoringScreen>
  );
}

function TutorCard({ tutor, lead }: { tutor: TutorSummary; lead: boolean }) {
  const verified = tutor.verifiedIdentity && tutor.verifiedCredentials;
  return (
    <article className="tt-tut">
      <div className={`tt-tut__id ${lead ? '' : 'tt-tut__id--alt'}`.trim()}>
        <Portrait initials={monogram(tutor.displayName)} accent={lead} />
        <div style={{ minWidth: 0 }}>
          <div className="tt-tut__nm">{tutor.displayName}</div>
          <div className="tt-tut__rl">{tutor.headline ?? experienceText(tutor.experienceYears)}</div>
        </div>
      </div>
      <div className="tt-tut__bd">
        <div className="tt-chiprow">
          <Chip tone={verified ? 'g' : 'i'}>
            {verified
              ? 'Identity and credentials verified'
              : tutor.verifiedIdentity
                ? 'Identity verified'
                : 'Verification pending'}
          </Chip>
          <Chip tone="gd">{ratingText(tutor)}</Chip>
        </div>
        <div className="tt-row">
          <span>
            <span className="tt-hero">{tutor.experienceYears || '—'}</span>
            <span
              style={{
                display: 'block', fontSize: '11px',
                color: 'var(--tt-mut)', fontWeight: 700,
              }}
            >
              {experienceText(tutor.experienceYears)}
            </span>
          </span>
          <Link className={`tt-btn ${lead ? 'tt-btn--jade' : ''}`.trim()} to={`/s-32?tutor=${encodeURIComponent(tutor.id)}`}>
            <Ic name="cal" />
            View and book
          </Link>
        </div>
      </div>
    </article>
  );
}

/* ========================================================================== *
 * S-32 — tutor detail: verified claims, provenance, availability + timezone
 * ========================================================================== */

/** Zones a reader can ask the server to render availability in. */
const ZONE_CHOICES = [DEFAULT_TIMEZONE, 'Asia/Dubai', 'Europe/London', 'America/New_York', 'UTC'];

export function TutorDetail() {
  const [sp, setSp] = useSearchParams();
  const tutorId = sp.get('tutor') ?? '';
  const zone = sp.get('tz') ?? DEFAULT_TIMEZONE;
  const date = sp.get('date') ?? '';
  useRouteArrival(`S-32:${tutorId}`);

  const tutor = useQuery({
    queryKey: tutoringKeys.tutor(tutorId),
    queryFn: () => getTutor(tutorId),
    enabled: Boolean(tutorId),
    retry: tutoringRetry,
    staleTime: 60_000,
  });

  const availabilityParams = useMemo(
    () => ({ timezone: zone, ...(date ? { date } : {}), limit: 50 }),
    [zone, date],
  );
  const availability = useQuery({
    queryKey: tutoringKeys.availability(tutorId, availabilityParams),
    queryFn: () => getAvailability(tutorId, availabilityParams),
    enabled: Boolean(tutorId),
    retry: tutoringRetry,
    // Slot status moves under the reader, so this page is deliberately fresh.
    staleTime: 10_000,
  });

  const setParam = (key: string, value: string | null): void => {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value); else next.delete(key);
    setSp(next, { replace: true });
  };

  if (!tutorId) {
    return (
      <TutoringScreen screenId="S-32">
        <EmptyState
          title="No mentor selected"
          detail="Open a mentor from the list to see their verified claims and availability."
          action={<Link className="tt-btn tt-btn--block" to="/s-31">Back to mentors</Link>}
        />
      </TutoringScreen>
    );
  }

  return (
    <TutoringScreen screenId="S-32">
      <Link className="tt-btn" to="/s-31" style={{ alignSelf: 'flex-start' }}>
        <Ic name="back" />
        All mentors
      </Link>

      {tutor.isPending && <LoadingState what="this mentor" />}
      {tutor.isError && <TypedErrorState error={tutor.error} onRecover={() => tutor.refetch()} />}

      {tutor.isSuccess && (
        <>
          <section className="tt-phead">
            <div className="tt-phead__id">
              <Portrait initials={monogram(tutor.data.displayName)} accent />
              <div style={{ minWidth: 0 }}>
                <h1 className="tt-arrival">{tutor.data.displayName}</h1>
                <div className="tt-phead__sub">
                  {tutor.data.headline ?? experienceText(tutor.data.experienceYears)}
                </div>
              </div>
            </div>
            <div className="tt-phead__bd">
              <div className="tt-chiprow">
                <Chip tone={tutor.data.verifiedIdentity ? 'g' : 'i'}>
                  {tutor.data.verifiedIdentity ? 'Identity verified' : 'Identity not verified'}
                </Chip>
                <Chip tone={tutor.data.verifiedCredentials ? 'g' : 'i'}>
                  {tutor.data.verifiedCredentials
                    ? 'Credentials verified'
                    : 'Credentials not verified'}
                </Chip>
                <Chip tone="gd">{ratingText(tutor.data)}</Chip>
              </div>
              {tutor.data.subjects.length > 0 && (
                <div className="tt-chiprow">
                  {tutor.data.subjects.map((s) => (
                    <Chip key={`${s.subject}-${s.level}`} tone="i">
                      {s.subject} · {s.level}
                    </Chip>
                  ))}
                </div>
              )}
              <div className="tt-feebox">
                <span>
                  <span className="tt-hero">{tutor.data.experienceYears || '—'}</span>
                  <span
                    style={{
                      display: 'block', fontSize: '11px',
                      color: 'var(--tt-mut)', fontWeight: 700,
                    }}
                  >
                    {experienceText(tutor.data.experienceYears)}
                  </span>
                </span>
                <Chip tone={tutor.data.status === 'published' ? 'g' : 'i'}>
                  Profile {tutor.data.status}
                </Chip>
              </div>
            </div>
          </section>

          {/* A2 — verified claims WITH provenance, which is the point of this block. */}
          <Disclosure summary="Where these claims come from" icon="info" open>
            <Kv label="Source">{tutor.data.source.replace(/_/g, ' ')}</Kv>
            <Kv label="Source record">
              {tutor.data.sourceUrl
                ? <a href={tutor.data.sourceUrl} rel="noreferrer noopener" target="_blank">{tutor.data.sourceUrl}</a>
                : 'Not published'}
            </Kv>
            <Kv label="Retrieved">
              {tutor.data.retrievedAt
                ? new Date(tutor.data.retrievedAt).toLocaleString('en-IN')
                : 'Not recorded'}
            </Kv>
            <Kv label="Published reviews counted">
              {tutor.data.ratingAggregate.ratingCount}
            </Kv>
            {Object.entries(tutor.data.ratingAggregate.distribution)
              .sort((a, b) => Number(b[0]) - Number(a[0]))
              .map(([stars, count]) => (
                <Kv key={stars} label={`${stars} star${stars === '1' ? '' : 's'}`}>{count}</Kv>
              ))}
            <p className="tt-p tt-muted">
              The aggregate counts published reviews only, so a review awaiting moderation is not
              in this number.
            </p>
          </Disclosure>
        </>
      )}

      {/* A3 — availability in the slot's retained zone plus the reader's own zone. */}
      <section aria-labelledby="tt-avail">
        <h2 className="tt-h" id="tt-avail" style={{ marginBottom: '8px' }}>
          Availability
        </h2>
        <div className="tt-grid2" style={{ marginBottom: '10px' }}>
          <div className="tt-fld">
            <label htmlFor="tt-tz">Show times in</label>
            <select
              id="tt-tz"
              className="tt-in tt-sel"
              value={zone}
              onChange={(event) => setParam('tz', event.target.value)}
            >
              {ZONE_CHOICES.map((z) => <option key={z} value={z}>{z}</option>)}
            </select>
          </div>
          <div className="tt-fld">
            <label htmlFor="tt-date">On a single day</label>
            <input
              id="tt-date"
              className="tt-in"
              type="date"
              value={date}
              onChange={(event) => setParam('date', event.target.value || null)}
            />
          </div>
        </div>

        {availability.isPending && <LoadingState what="availability" />}
        {availability.isError && (
          <TypedErrorState error={availability.error} onRecover={() => availability.refetch()} />
        )}

        {availability.isSuccess && (
          <>
            {Object.entries(availability.data.localResolution).map(([bound, resolution]) => (
              resolution.classification === 'unique' ? null : (
                <Banner
                  key={bound}
                  tone="warn"
                  title={
                    resolution.classification === 'ambiguous'
                      ? 'That local time happens twice on this date'
                      : 'That local time does not exist on this date'
                  }
                  detail={
                    resolution.classification === 'ambiguous'
                      ? `The clocks go back, so ${resolution.requestedLocal} occurs twice. The earlier occurrence was used.`
                      : `The clocks go forward, so ${resolution.requestedLocal} is skipped. ${resolution.resolvedLocal} was used instead.`
                  }
                  code={resolution.classification.toUpperCase()}
                />
              )
            ))}

            {availability.data.slots.length === 0 ? (
              <EmptyState
                title="No open times in this window"
                detail="This mentor has nothing open here. Clear the day filter to see the next available times."
                action={
                  date
                    ? (
                      <button type="button" className="tt-btn tt-btn--block" onClick={() => setParam('date', null)}>
                        Show every open time
                      </button>
                    )
                    : undefined
                }
              />
            ) : (
              <div className="tt-slots">
                {availability.data.slots.map((slot) => (
                  <SlotButton key={slot.slotId} slot={slot} displayZone={availability.data.ianaTimezone} />
                ))}
              </div>
            )}

            <p className="tt-p tt-muted" style={{ marginTop: '10px' }}>
              Times are shown in {availability.data.ianaTimezone}, the zone kept with the slot.
              Your device is set to {browserTimeZone()}.
            </p>
          </>
        )}
      </section>

      <div className="tt-edu">
        <h4>What happens next?</h4>
        <p>
          Picking a time holds it for {DEFAULT_HOLD_MINUTES} minutes while you pay. Nobody else can
          take it during your hold, and nothing is charged until the payment provider confirms.
        </p>
      </div>

      <p className="tt-svr">
        server-authoritative: slot status and the booking hold TTL · slot ids are immutable and
        carry their own timezone
      </p>
    </TutoringScreen>
  );
}

function SlotButton({ slot, displayZone }: { slot: AvailabilitySlot; displayZone: string }) {
  const navigate = useNavigate();
  const bookable = slot.status === 'available';
  const labels = slotTimeLabels(slot.startUtc, slot.endUtc, displayZone);
  const minutes = slot.durationMinutes || durationMinutes(slot.startUtc, slot.endUtc);
  const statusWord =
    slot.status === 'available' ? 'Available'
      : slot.status === 'held' ? 'Held by another student'
        : slot.status === 'booked' ? 'Booked'
          : slot.status;
  return (
    <button
      type="button"
      className="tt-slotbtn"
      disabled={!bookable}
      aria-disabled={!bookable}
      onClick={() => navigate(
        `/s-33?slot=${encodeURIComponent(slot.slotId)}&tutor=${encodeURIComponent(slot.tutorId)}`,
      )}
    >
      <span className="tt-sl">
        {labels.sessionZone}
        <small>
          {minutes} minutes · {labels.sessionZoneLabel}
          {labels.readerZone ? ` · your time ${labels.readerZone}` : ''}
        </small>
      </span>
      <Chip tone={slot.status === 'available' ? 'g' : slot.status === 'held' ? 't' : 'r'}>
        {statusWord}
      </Chip>
    </button>
  );
}

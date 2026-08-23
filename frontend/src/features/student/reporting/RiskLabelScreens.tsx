import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MutableRefObject,
  type RefObject,
} from 'react';
import { useQuery } from '@tanstack/react-query';
import { useStudentMutation as useMutation } from '../lib/useStudentMutation';
import {
  Building2,
  Clock3,
  FileCheck2,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { InfoTooltip, StudentScreen } from '../components';
import {
  getPublicRiskLabels,
  newOrganisationResponseIdempotencyKey,
  organisationResponseErrorCopy,
  organisationResponseFailureState,
  publicRiskLabelsKey,
  riskLabelErrorCopy,
  riskLabelUnavailableState,
  submitOrganisationResponse,
  type PublicRiskLabel,
} from '../lib/riskLabelsApi';

const MAX_RESPONSE_LENGTH = 2_000;
const RISK_LABEL_RELEASE_ENABLED = (
  (import.meta as { env?: { VITE_INTERNSHIP_RISK_LABELS_ENABLED?: string } }).env
    ?.VITE_INTERNSHIP_RISK_LABELS_ENABLED ?? 'false'
) === 'true';
const useSafeLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;

function reviewedDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Review date unavailable';
  return date.toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata',
  });
}

function sourceTypeCopy(value: PublicRiskLabel['sourceType']): string {
  return value === 'moderated_aggregate' ? 'Moderated aggregate' : 'Approved aggregate';
}

export function validateOrganisationResponse(value: string): string | null {
  const trimmed = value.trim();
  // Match the backend's Unicode-code-point boundary. JavaScript's `.length`
  // counts UTF-16 code units, which would incorrectly reject 2,000 emoji even
  // though Python/Pydantic correctly treats them as 2,000 characters.
  const characterLength = Array.from(trimmed).length;
  if (characterLength < 1 || characterLength > MAX_RESPONSE_LENGTH) {
    return 'Use 1–2,000 characters for the organisation response or correction.';
  }
  const containsUnsafeControl = Array.from(value).some((character) => {
    const code = character.codePointAt(0) ?? 0;
    return character === '<' || character === '>'
      || code <= 8 || code === 11 || code === 12 || (code >= 14 && code <= 31) || code === 127;
  });
  if (containsUnsafeControl) return 'Remove unsupported control characters.';
  return null;
}

function SignalState({
  kind,
  title,
  detail,
  retry,
}: {
  kind: string;
  title: string;
  detail: string;
  retry?: () => void;
}) {
  return (
    <section className="rl-state" data-risk-label-state={kind} aria-live="polite">
      <span className="rl-state__mark" aria-hidden><ShieldCheck size={28} /></span>
      <div><h2>{title}</h2><p>{detail}</p></div>
      {retry && (
        <button className="btn rl-button" type="button" onClick={retry}>
          <RefreshCw size={18} aria-hidden /> Retry
        </button>
      )}
    </section>
  );
}

function LabelCard({ label }: { label: PublicRiskLabel }) {
  const badge = label.status === 'corrected' ? 'Approved correction' : 'Approved aggregate';
  const responseTitle = label.organisationResponse?.kind === 'correction'
    ? 'Approved organisation correction'
    : label.organisationResponse?.kind === 'appeal'
      ? 'Approved organisation appeal outcome'
      : 'Approved organisation response';
  return (
    <article className="rl-card" data-risk-label-id={label.id} data-risk-label-status={label.status}>
      <div className="rl-card__head">
        <span className="rl-badge"><ShieldCheck size={18} aria-hidden /> {badge}</span>
        <InfoTooltip
          label="How this signal was created"
          text="Only independently approved, corroborating reports inside the policy window contribute. Raw reports and reporter identities are never shown here."
        />
      </div>
      <h2>{label.neutralLabel}</h2>
      <div className="rl-provenance" aria-label="Signal provenance">
        <span><FileCheck2 size={17} aria-hidden /> {sourceTypeCopy(label.sourceType)}</span>
        <span><Clock3 size={17} aria-hidden /> Reviewed {reviewedDate(label.lastReviewedAt)}</span>
        <span data-count-suppressed={label.publicCount === null}>
          <LockKeyhole size={17} aria-hidden />
          {label.publicCount === null ? 'Count withheld for privacy' : `${label.publicCount} approved source reports`}
        </span>
      </div>
      {label.organisationResponse && (
        <section className="rl-response" aria-labelledby={`rl-response-${label.id}`}>
          <div className="rl-response__title">
            <MessageSquareText size={19} aria-hidden />
            <h3 id={`rl-response-${label.id}`}>{responseTitle}</h3>
          </div>
          <blockquote>{label.organisationResponse.text}</blockquote>
          <p>Moderation reviewed {reviewedDate(label.organisationResponse.lastReviewedAt)}</p>
        </section>
      )}
    </article>
  );
}

export function PublicRiskLabelPanel({
  organisationId,
  organisationName,
  compact = false,
  releaseEnabled = RISK_LABEL_RELEASE_ENABLED,
}: {
  organisationId?: string | null;
  organisationName?: string;
  compact?: boolean;
  /** Test/reference seam. Production defaults false until counsel/security release approval. */
  releaseEnabled?: boolean;
}) {
  const query = useQuery({
    queryKey: publicRiskLabelsKey(organisationId ?? 'unavailable'),
    queryFn: () => getPublicRiskLabels(organisationId!),
    enabled: Boolean(organisationId) && releaseEnabled,
    retry: false,
  });

  if (!releaseEnabled) {
    return compact ? null : (
      <SignalState
        kind="disabled"
        title="Public signals remain hidden"
        detail="Public organisation safety signals are disabled pending counsel, security and target-runtime release approval."
      />
    );
  }
  if (!organisationId) {
    return compact ? null : (
      <SignalState
        kind="empty"
        title="Choose an organisation"
        detail="Open this screen from an internship listing to check approved aggregate safety information."
      />
    );
  }
  if (query.isPending) {
    return <section className="rl-loading" role="status" aria-busy="true"><span aria-hidden /><p>Checking approved aggregate signals…</p></section>;
  }
  if (query.isError) {
    const unavailable = riskLabelUnavailableState(query.error);
    if (compact && unavailable === 'disabled') return null;
    const retry = unavailable === 'retryable' ? () => void query.refetch() : undefined;
    const titles = {
      disabled: 'Public signals remain hidden',
      insufficient: 'No publishable aggregate signal',
      approval_pending: 'Independent approval incomplete',
      permission: 'Signal unavailable',
      retryable: 'Could not check safety signals',
      unavailable: 'No public signal available',
    } as const;
    return <SignalState kind={unavailable} title={titles[unavailable]} detail={riskLabelErrorCopy(query.error)} retry={retry} />;
  }
  if (!query.data.available || query.data.labels.length === 0) {
    return compact ? null : (
      <SignalState
        kind="insufficient"
        title="No publishable aggregate signal"
        detail="No independently approved aggregate currently meets the privacy and publication rules."
      />
    );
  }

  return (
    <section className={`rl-projection${compact ? ' rl-projection--compact' : ''}`} data-risk-label-state="published">
      <header className="rl-projection__head">
        <div>
          <p className="rl-eyebrow">Independent, privacy-safe review</p>
          <h2>{organisationName ? `Safety signals for ${organisationName}` : 'Approved aggregate safety signals'}</h2>
          <p>Neutral public wording only. No individual allegation or reporter data is shown.</p>
        </div>
        {compact && <Link className="btn rl-button" to={`/s-88?organisation=${encodeURIComponent(organisationId)}`}>View provenance</Link>}
      </header>
      <div className="rl-list">{query.data.labels.map((label) => <LabelCard key={label.id} label={label} />)}</div>
    </section>
  );
}

export function InternshipRiskSignals() {
  const [params] = useSearchParams();
  const organisationId = params.get('organisation')?.trim() ?? '';
  return (
    <StudentScreen screenId="S-88" className="st-risk-labels">
      <main className="rl-shell">
        <header className="rl-hero">
          <div><p className="rl-eyebrow">Internship safety · S-88</p><h1>Understand approved safety signals</h1><p>Review only corroborated, moderated and independently approved aggregate information.</p></div>
          <div className="rl-hero__seal"><ShieldCheck size={28} aria-hidden /><div><strong>Privacy threshold enforced</strong><span>Small counts and raw reports stay hidden.</span></div></div>
        </header>
        <PublicRiskLabelPanel organisationId={organisationId} />
        <aside className="rl-policy" role="note"><LockKeyhole size={19} aria-hidden /><p><strong>Publication fails closed.</strong> When the feature flag, threshold or approval quorum is absent, LegalSaathi publishes no label.</p></aside>
        <div className="rl-actions"><Link className="btn" to="/s-20">Browse internships</Link></div>
      </main>
    </StudentScreen>
  );
}

function useSingleUseResponseToken(): MutableRefObject<string> {
  const location = useLocation();
  const navigate = useNavigate();
  const token = useRef<string | null>(null);
  if (token.current === null) {
    // The invitation is delivered in the URL fragment, which browsers do not
    // send in HTTP requests or Referrer headers. It is held only in memory and
    // removed before paint; it must never be accepted from the query string.
    const fragment = location.hash.startsWith('#') ? location.hash.slice(1) : location.hash;
    const params = new URLSearchParams(fragment);
    token.current = params.get('token')?.trim() ?? '';
  }
  useSafeLayoutEffect(() => {
    const fragment = location.hash.startsWith('#') ? location.hash.slice(1) : location.hash;
    const hashParams = new URLSearchParams(fragment);
    const searchParams = new URLSearchParams(location.search);
    // Query-string tokens are never accepted, but scrub the legacy parameter
    // immediately as defence in depth so it cannot survive in copied links or
    // later same-page navigation. Only a fragment token is captured in memory.
    const hadFragmentToken = hashParams.has('token');
    const hadQueryToken = searchParams.has('token');
    hashParams.delete('token');
    searchParams.delete('token');
    if (!hadFragmentToken && !hadQueryToken) return;
    const hash = hashParams.toString();
    const search = searchParams.toString();
    navigate({
      pathname: location.pathname,
      search: search ? `?${search}` : '',
      hash: hash ? `#${hash}` : '',
    }, { replace: true });
  }, [location.hash, location.pathname, location.search, navigate]);
  return token as MutableRefObject<string>;
}

export function OrganisationResponseSubmittedState({ focusRef }: { focusRef?: RefObject<HTMLDivElement | null> }) {
  return (
    <section className="rl-result rl-result--success" ref={focusRef} tabIndex={-1} role="status" data-response-state="moderation-pending">
      <span aria-hidden><FileCheck2 size={30} /></span><div><p className="rl-eyebrow">Submitted safely</p><h2>Moderation review is pending</h2><p>The response or correction is stored once and remains private until an authorised reviewer approves it. The invitation cannot be reused.</p></div>
    </section>
  );
}

export function OrganisationResponse({
  releaseEnabled = RISK_LABEL_RELEASE_ENABLED,
}: {
  releaseEnabled?: boolean;
  theme?: unknown;
  toggleTheme?: unknown;
} = {}) {
  const token = useSingleUseResponseToken();
  const [text, setText] = useState('');
  const [fieldError, setFieldError] = useState('');
  const idempotencyKey = useRef(newOrganisationResponseIdempotencyKey());
  const resultFocus = useRef<HTMLDivElement>(null);
  const mutation = useMutation({
    mutationFn: () => submitOrganisationResponse(token.current, text.trim(), idempotencyKey.current),
    onSuccess: () => {
      token.current = '';
      setText('');
      setFieldError('');
    },
    onError: (error) => {
      if (organisationResponseFailureState(error) === 'invitation-unavailable') {
        token.current = '';
      }
    },
  });
  useEffect(() => {
    if (mutation.isSuccess || mutation.isError) resultFocus.current?.focus();
  }, [mutation.isError, mutation.isSuccess]);
  const characterCount = useMemo(() => Array.from(text.trim()).length, [text]);
  const failureState = mutation.isError ? organisationResponseFailureState(mutation.error) : null;

  const changeText = (value: string) => {
    setText(value);
    setFieldError('');
    mutation.reset();
    idempotencyKey.current = newOrganisationResponseIdempotencyKey();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const error = validateOrganisationResponse(text);
    setFieldError(error ?? '');
    if (!error && token.current) mutation.mutate();
  };
  const startFreshSubmissionAttempt = () => {
    idempotencyKey.current = newOrganisationResponseIdempotencyKey();
    mutation.reset();
    setFieldError('');
  };

  return (
    <StudentScreen screenId="S-89" className="st-risk-labels">
      <main className="rl-shell rl-shell--response">
        <header className="rl-hero">
          <div><p className="rl-eyebrow">Right of reply · S-89</p><h1>Organisation response or correction</h1><p>A verified representative may submit a factual response. Every response is moderated before it can appear publicly.</p></div>
          <div className="rl-hero__seal"><Building2 size={28} aria-hidden /><div><strong>Independent moderation</strong><span>Submission never means automatic publication.</span></div></div>
        </header>

        {!releaseEnabled ? (
          <SignalState
            kind="disabled"
            title="Organisation responses are not open"
            detail="The right-of-reply workflow remains disabled until counsel, security and target-runtime release approval."
          />
        ) : mutation.isSuccess ? (
          <OrganisationResponseSubmittedState focusRef={resultFocus} />
        ) : failureState === 'invitation-unavailable' ? (
          <>
            <SignalState
              kind="invalid-invitation"
              title="This invitation is no longer available"
              detail={organisationResponseErrorCopy(mutation.error)}
            />
            <div className="rl-actions">
              <Link className="btn rl-button" to="/s-20">Return to internships</Link>
            </div>
          </>
        ) : !token.current && !mutation.isError ? (
          <>
            <SignalState kind="invalid-invitation" title="A verified invitation is required" detail="Open the single-use invitation supplied by LegalSaathi. Tokens are removed from the address and are never stored by this page." />
            <div className="rl-actions">
              <Link className="btn rl-button" to="/s-20">Return to internships</Link>
            </div>
          </>
        ) : (
          <form className="rl-response-form" onSubmit={submit} noValidate data-response-state={failureState ?? 'invited'}>
            <div className="rl-response-form__head"><span aria-hidden><MessageSquareText size={24} /></span><div><p className="rl-eyebrow">Single-use invitation</p><h2>Provide a factual response</h2><p>Address the aggregate signal without naming a reporter or repeating private allegations.</p></div></div>
            <label className="st-field" htmlFor="organisation-response-text">
              <span className="st-field__label">Organisation response or correction</span>
              <textarea
                id="organisation-response-text"
                className="st-input rl-response-input"
                value={text}
                aria-invalid={fieldError ? true : undefined}
                aria-describedby={`${fieldError ? 'organisation-response-error ' : ''}organisation-response-count`}
                onChange={(event) => changeText(event.target.value)}
              />
              <span className="st-field__help" id="organisation-response-count">{characterCount.toLocaleString('en-IN')} / 2,000 characters</span>
              {fieldError && <span className="ui-validation" role="alert" id="organisation-response-error"><span className="ui-validation__mark" aria-hidden>!</span> {fieldError}</span>}
            </label>
            {mutation.isError && (
              <div className="rl-error" role="alert" ref={resultFocus} tabIndex={-1} data-response-error-kind={failureState}>
                <strong>Response not submitted.</strong><span>{organisationResponseErrorCopy(mutation.error)}</span>
              </div>
            )}
            <div className="rl-actions">
              <button className="btn btn--primary rl-button" type="submit" disabled={mutation.isPending || failureState === 'conflict'}>
                <Send size={18} aria-hidden /> {mutation.isPending ? 'Submitting privately…' : 'Submit for moderation'}
              </button>
              {failureState === 'conflict' && (
                <button className="btn rl-button" type="button" onClick={startFreshSubmissionAttempt}>
                  <RefreshCw size={18} aria-hidden /> Start a fresh submission attempt
                </button>
              )}
            </div>
          </form>
        )}
        <aside className="rl-policy" role="note"><LockKeyhole size={19} aria-hidden /><p>The invitation token is sent only in a dedicated request header, cleared from the browser address and never written to browser storage.</p></aside>
      </main>
    </StudentScreen>
  );
}

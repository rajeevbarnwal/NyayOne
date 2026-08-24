import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  captureStudentMutationSequence,
  runStudentMutationStep,
  useStudentMutation as useMutation,
} from '../lib/useStudentMutation';
import { StudentScreen, TextField, SelectField, DpdpFootnote } from '../components';
import {
  ErrorState,
  LoadingState,
  StatusBadge,
  ValidationState,
} from '../../../components/ui/primitives';
import type { ThemeMode } from '../../../hooks/useTheme';
import { canSubmitDelete, DELETE_CONFIRM_PHRASE } from '../lib/dpdp';
import { startRecovery, verifyRecovery } from '../lib/registrationApi';
import { useOtpFlowState } from '../lib/useOtpFlowState';
import {
  getStudentSettings,
  updateStudentSettings,
  requestDataExport,
  requestAccountDeletion,
  getPrivacyRequest,
  SettingsApiError,
  SETTINGS_CONFLICT_CODE,
  type PrivacyConsentKind,
  type PrivacyRequestKind,
  type PrivacyRequestStatus,
  type StudentSettings,
  type StudentSettingsPatch,
  type ThemePreference,
} from '../lib/settingsApi';
import {
  consumeStudentAuthTransitionNotice,
  recordStudentAuthTransitionNotice,
} from '../lib/studentAuthTransitionNotice';

/**
 * S-18/S-19 are server-backed (SAATHI-58/SAATHI-391): GET/PATCH
 * /api/v1/student/settings with optimistic-concurrency (expected_version;
 * 409 conflict refetches and shows a non-blocking notice), and the DPDP
 * export/delete request flow with status polling. PII and workflow identifiers
 * never touch browser storage; the active polling reference is component-only.
 */

const SETTINGS_KEY = ['student-settings'] as const;
import { LANGUAGE_OPTIONS } from '../lib/catalog';

const LANGUAGES = LANGUAGE_OPTIONS;
const SETTINGS_WIDE_LAYOUT_QUERY = '(min-width: 821px)';

export function settingsDisclosuresOpen(
  matchMedia: ((query: string) => { matches: boolean }) | undefined,
): boolean {
  return matchMedia?.(SETTINGS_WIDE_LAYOUT_QUERY).matches === true;
}

function useWideSettingsLayout(): boolean {
  const [wide, setWide] = useState(() => settingsDisclosuresOpen(
    typeof window === 'undefined' ? undefined : window.matchMedia.bind(window),
  ));
  useEffect(() => {
    const media = window.matchMedia(SETTINGS_WIDE_LAYOUT_QUERY);
    const update = () => setWide(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return wide;
}

function Toggle({ id, on, onToggle, label, disabled }: { id: string; on: boolean; onToggle: () => void; label: string; disabled?: boolean }) {
  return (
    <button
      id={id}
      type="button"
      className="st-toggle"
      aria-pressed={on}
      aria-label={`${label}: ${on ? 'On' : 'Off'}`}
      disabled={disabled}
      onClick={onToggle}
    >
      {on ? 'On' : 'Off'}
    </button>
  );
}

function applyPatch(s: StudentSettings, patch: StudentSettingsPatch): StudentSettings {
  return {
    ...s,
    theme: patch.theme ?? s.theme,
    language: patch.language ?? s.language,
    notifEmail: patch.notifEmail ?? s.notifEmail,
    notifSms: patch.notifSms ?? s.notifSms,
    notifUpdates: patch.notifUpdates ?? s.notifUpdates,
    privacy: patch.privacy
      ? s.privacy.map((p) => patch.privacy?.find((n) => n.kind === p.kind) ?? p)
      : s.privacy,
  };
}

/** Shared optimistic settings PATCH with 409 conflict recovery. */
function useSettingsPatch() {
  const qc = useQueryClient();
  const [conflict, setConflict] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (input: { patch: StudentSettingsPatch; expectedVersion: number }) =>
      updateStudentSettings(input.patch, input.expectedVersion),
    onMutate: async (input) => {
      const fence = captureStudentMutationSequence();
      setConflict(null);
      setFailure(null);
      await runStudentMutationStep(
        fence,
        () => qc.cancelQueries({ queryKey: SETTINGS_KEY }),
      );
      const previous = qc.getQueryData<StudentSettings>(SETTINGS_KEY);
      if (previous) qc.setQueryData<StudentSettings>(SETTINGS_KEY, applyPatch(previous, input.patch));
      return { previous };
    },
    onError: (error, _input, context) => {
      if (context?.previous) qc.setQueryData<StudentSettings>(SETTINGS_KEY, context.previous);
      if (error instanceof SettingsApiError && error.status === 409 && error.code === SETTINGS_CONFLICT_CODE) {
        // Non-blocking: reload the authoritative copy and tell the user.
        setConflict('Settings changed on another device — showing the latest values. Reapply your change if needed.');
        void qc.invalidateQueries({ queryKey: SETTINGS_KEY });
        return;
      }
      setFailure('Could not save that change — check your connection and try again.');
    },
    onSuccess: (data) => {
      qc.setQueryData<StudentSettings>(SETTINGS_KEY, data);
    },
  });
  return { mutation, conflict, failure };
}

function SettingsNotices({ conflict, failure }: { conflict: string | null; failure: string | null }) {
  return (
    <>
      {conflict && (
        <div className="ui-banner ui-banner--warn" role="status">
          <span className="ui-banner__mark" aria-hidden>!</span>
          <span>{conflict}</span>
        </div>
      )}
      {failure && <ValidationState message={failure} />}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* S-18 — Notifications & appearance preferences (server-backed)               */
/* -------------------------------------------------------------------------- */
export function NotificationsSettings({ theme, toggleTheme }: { theme?: ThemeMode; toggleTheme?: () => void }) {
  const nav = useNavigate();
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: getStudentSettings });
  const { mutation, conflict, failure } = useSettingsPatch();
  const s = settings.data;

  function patch(p: StudentSettingsPatch): void {
    if (!s) return;
    mutation.mutate({ patch: p, expectedVersion: s.version });
  }

  function pickTheme(next: ThemePreference): void {
    patch({ theme: next });
    // Keep the shell theme in sync immediately for light/dark picks.
    if ((next === 'light' || next === 'dark') && theme && theme !== next) toggleTheme?.();
  }

  const signedOut = settings.error instanceof SettingsApiError && settings.error.status === 401;

  return (
    <StudentScreen screenId="S-18" className="st-set">
      <div className="st-set__head">
        <p className="st-eyebrow">Settings · notifications, theme and language</p>
        <h1 className="st-h1">How NyayOne reaches you</h1>
      </div>

      {settings.isPending && <LoadingState label="Loading your settings…" />}
      {settings.isError && (signedOut ? (
        <div className="ui-state" role="alert">
          <p className="ui-state__eyebrow">Signed out</p>
          <p className="ui-state__title">Sign in to manage settings</p>
          <div className="ui-state__action">
            <button type="button" className="btn tap" onClick={() => nav('/s-03')}>Go to sign in</button>
          </div>
        </div>
      ) : (
        <ErrorState title="Could not load settings" detail="Check your connection and retry." onRetry={() => void settings.refetch()} />
      ))}

      {s && (
        <>
          <SettingsNotices conflict={conflict} failure={failure} />
          <details className="v34c-mobile-disclosure">
            <summary>Notifications <span>3 preferences</span></summary>
            <section className="st-panel">
            <h2 className="st-panel__title">Notifications</h2>
            <div className="st-setrow">
              <div>
                <div className="st-setrow__label">Email notifications</div>
                <div className="st-setrow__sub">Deadlines, applications and account activity by email.</div>
              </div>
              <Toggle id="pref-email" on={s.notifEmail} label="Email notifications" onToggle={() => patch({ notifEmail: !s.notifEmail })} />
            </div>
            <div className="st-setrow">
              <div>
                <div className="st-setrow__label">SMS notifications</div>
                <div className="st-setrow__sub">Time-critical alerts to your registered mobile.</div>
              </div>
              <Toggle id="pref-sms" on={s.notifSms} label="SMS notifications" onToggle={() => patch({ notifSms: !s.notifSms })} />
            </div>
            <div className="st-setrow">
              <div>
                <div className="st-setrow__label">Product updates</div>
                <div className="st-setrow__sub">New features and followed-school admission updates.</div>
              </div>
              <Toggle id="pref-updates" on={s.notifUpdates} label="Product updates" onToggle={() => patch({ notifUpdates: !s.notifUpdates })} />
            </div>
            </section>
          </details>

          <details className="v34c-mobile-disclosure">
            <summary>Appearance &amp; language <span>{s.theme}</span></summary>
            <section className="st-panel">
            <h2 className="st-panel__title">Appearance &amp; language</h2>
            <div className="st-setrow">
              <div>
                <div className="st-setrow__label">Theme</div>
                <div className="st-setrow__sub">Chambers Dark for focused work · Clean Chambers Light for reading.</div>
              </div>
              <div className="st-seg" role="group" aria-label="Theme">
                {(['system', 'light', 'dark'] as ThemePreference[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    className="st-seg__btn"
                    aria-pressed={s.theme === t}
                    onClick={() => pickTheme(t)}
                  >
                    {t === 'system' ? 'System' : t === 'light' ? 'Light' : 'Dark'}
                  </button>
                ))}
              </div>
            </div>
            <SelectField
              id="pref-language"
              label="Language"
              value={s.language}
              onChange={(v) => v && patch({ language: v })}
              options={LANGUAGES}
            />
            </section>
          </details>
        </>
      )}

      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/s-19')}>
          Privacy &amp; DPDP controls
        </button>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-19 — Privacy & DPDP controls (server-backed with status polling)          */
/* -------------------------------------------------------------------------- */

const REQUEST_BADGE: Record<PrivacyRequestStatus, { s: 'ok' | 'warn' | 'risk' | 'info'; label: string }> = {
  pending: { s: 'info', label: 'Pending' },
  processing: { s: 'warn', label: 'Processing' },
  complete: { s: 'ok', label: 'Complete' },
  failed: { s: 'risk', label: 'Failed' },
  cancelled: { s: 'warn', label: 'Cancelled' },
};

const CONSENT_LABELS: Record<PrivacyConsentKind, { label: string; sub: string }> = {
  analytics: { label: 'Product analytics', sub: 'Anonymous usage metrics that improve the app.' },
  marketing: { label: 'Marketing messages', sub: 'Occasional offers and programme announcements.' },
  share_partners: { label: 'Share with partners', sub: 'Share limited profile data with education partners.' },
};

/** Poll a DPDP request until it leaves pending/processing. */
function usePrivacyRequestPolling(kind: PrivacyRequestKind) {
  const [requestId, setRequestId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ['privacy-request', kind, requestId],
    queryFn: () => getPrivacyRequest(requestId as string),
    enabled: requestId !== null,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === 'pending' || status === 'processing' ? 4000 : false;
    },
  });
  return {
    requestId,
    status: query.data?.status ?? (requestId !== null ? ('pending' as PrivacyRequestStatus) : null),
    statusError: query.isError,
    refetchStatus: () => void query.refetch(),
    track(id: string) {
      setRequestId(id);
    },
    clear() {
      setRequestId(null);
    },
  };
}

type DeleteStage = 'reauth-mobile' | 'reauth-otp' | 'confirm';
const RECOVERY_STATE_UNAVAILABLE = 'Re-authentication state is unavailable. No deletion can proceed until the server state check recovers.';

export function PrivacySettings() {
  const nav = useNavigate();
  const wideLayout = useWideSettingsLayout();
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: getStudentSettings });
  const { mutation: settingsMutation, conflict, failure } = useSettingsPatch();
  const s = settings.data;

  const exportPoll = usePrivacyRequestPolling('export');
  const deletePoll = usePrivacyRequestPolling('delete');

  const [showDelete, setShowDelete] = useState(false);
  const [stage, setStage] = useState<DeleteStage>('reauth-mobile');
  const [mobile, setMobile] = useState('');
  const [otp, setOtp] = useState('');
  const [typed, setTyped] = useState('');
  const [flowError, setFlowError] = useState<string | null>(() => {
    if (consumeStudentAuthTransitionNotice('account_deletion_confirmation_invalid')) {
      return `Confirmation must be exactly ${DELETE_CONFIRM_PHRASE}.`;
    }
    if (consumeStudentAuthTransitionNotice('account_deletion_failed')) {
      return 'Could not submit the deletion request — try again.';
    }
    return null;
  });
  const deletionInFlight = useRef(false);
  const [deletePending, setDeletePending] = useState(false);
  const recoveryFlow = useOtpFlowState();

  useEffect(() => {
    if (recoveryFlow.loadError) {
      setStage('reauth-mobile');
      setMobile('');
      setOtp('');
      setTyped('');
      setFlowError(RECOVERY_STATE_UNAVAILABLE);
      return;
    }
    if (recoveryFlow.state?.purpose === 'recovery') {
      if (recoveryFlow.state.status === 'verified') setStage('confirm');
      else if (recoveryFlow.state.status === 'pending') setStage('reauth-otp');
      setFlowError((current) => current === RECOVERY_STATE_UNAVAILABLE ? null : current);
      return;
    }
    if (recoveryFlow.state?.status === 'unavailable') {
      setStage('reauth-mobile');
      setOtp('');
      setTyped('');
    }
  }, [recoveryFlow.loadError, recoveryFlow.state]);

  const exportMut = useMutation({
    mutationFn: () => requestDataExport(),
    onSuccess: (res) => exportPoll.track(res.requestId),
  });

  const startMut = useMutation({
    mutationFn: () => startRecovery(mobile.trim()),
    onSuccess: (state) => {
      recoveryFlow.adopt(state);
      setStage(state.status === 'verified' ? 'confirm' : 'reauth-otp');
      setFlowError(null);
    },
    onError: () => setFlowError('Could not start re-authentication. Check the mobile number and retry.'),
  });

  const verifyMut = useMutation({
    mutationFn: () => verifyRecovery(otp.trim()),
    onSuccess: (state) => {
      recoveryFlow.adopt(state);
      if (state.status === 'verified' && state.purpose === 'recovery') {
        setStage('confirm');
        setFlowError(null);
      } else {
        setStage('reauth-mobile');
        setFlowError('The server did not confirm re-authentication. Start again.');
      }
    },
    onError: () => setFlowError('That code did not match. Try again.'),
  });

  async function submitAccountDeletion(): Promise<void> {
    if (deletionInFlight.current) return;
    deletionInFlight.current = true;
    setDeletePending(true);
    setFlowError(null);
    try {
      await requestAccountDeletion({ confirmation: typed.trim() });
      // This is a sanitized transition-owned completion, not an actor callback.
      // The adapter resolves only after the shared cookie is authoritatively
      // anonymous, so no stale private result crosses into the destination.
      recordStudentAuthTransitionNotice('account_deletion_accepted');
      nav('/s-03', { replace: true });
    } catch (error) {
      recordStudentAuthTransitionNotice(
        error instanceof SettingsApiError && error.status === 422
          ? 'account_deletion_confirmation_invalid'
          : 'account_deletion_failed',
      );
      deletionInFlight.current = false;
      setDeletePending(false);
      nav('/s-19', { replace: true });
    }
  }

  const reauthenticated = stage === 'confirm'
    && recoveryFlow.state?.status === 'verified'
    && recoveryFlow.state.purpose === 'recovery';
  const deleteReady = canSubmitDelete({ typedConfirmation: typed, reauthenticated })
    && !deletePending && deletePoll.status === null;

  function toggleConsent(kind: PrivacyConsentKind): void {
    if (!s) return;
    const entry = s.privacy.find((p) => p.kind === kind);
    if (!entry) return;
    settingsMutation.mutate({
      patch: { privacy: [{ kind, enabled: !entry.enabled }] },
      expectedVersion: s.version,
    });
  }

  function requestStatusRow(kind: PrivacyRequestKind, poll: ReturnType<typeof usePrivacyRequestPolling>) {
    if (poll.status === null) return null;
    const badge = REQUEST_BADGE[poll.status];
    return (
      <div className="ui-banner ui-banner--warn" role="status">
        <span className="ui-banner__mark" aria-hidden>i</span>
        <span>
          {kind === 'export' ? 'Export' : 'Deletion'} request <StatusBadge status={badge.s} label={badge.label} />
          {poll.statusError && ' · status check failed — '}
          {poll.statusError && (
            <button type="button" className="btn tap" onClick={poll.refetchStatus}>Retry</button>
          )}
          {(poll.status === 'complete' || poll.status === 'failed' || poll.status === 'cancelled') && (
            <button type="button" className="btn tap" onClick={poll.clear} style={{ marginLeft: 'var(--space-2)' }}>
              Dismiss
            </button>
          )}
        </span>
      </div>
    );
  }

  return (
    <StudentScreen screenId="S-19" className="st-set">
      <div className="st-set__head">
        <p className="st-eyebrow">Privacy · consent, export and deletion</p>
        <h1 className="st-h1">Your data, your decisions.</h1>
      </div>

      <details open={wideLayout} className="v34c-mobile-disclosure">
        <summary>Consent preferences <span>3 controls</span></summary>
        <section className="st-panel">
        <h2 className="st-panel__title">Consent preferences</h2>
        {settings.isPending && <LoadingState label="Loading consent preferences…" />}
        {settings.isError && (
          <ErrorState title="Could not load consent preferences" onRetry={() => void settings.refetch()} />
        )}
        {s && (
          <>
            <SettingsNotices conflict={conflict} failure={failure} />
            {s.privacy.map((p) => (
              <div className="st-setrow" key={p.kind}>
                <div>
                  <div className="st-setrow__label">{CONSENT_LABELS[p.kind].label}</div>
                  <div className="st-setrow__sub">{CONSENT_LABELS[p.kind].sub}</div>
                </div>
                <Toggle id={`consent-${p.kind}`} on={p.enabled} label={CONSENT_LABELS[p.kind].label} onToggle={() => toggleConsent(p.kind)} />
              </div>
            ))}
          </>
        )}
        </section>
      </details>

      <details open={wideLayout} className="v34c-mobile-disclosure">
        <summary>Data rights <span>export · delete</span></summary>
        <section className="st-panel">
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Download my data</div>
            <div className="st-setrow__sub">Export a copy of your account data.</div>
          </div>
          <button
            type="button"
            className="btn tap"
            disabled={exportMut.isPending || exportPoll.status === 'pending' || exportPoll.status === 'processing'}
            onClick={() => exportMut.mutate()}
          >
            {exportPoll.status === 'pending' || exportPoll.status === 'processing' ? 'Requested' : 'Export'}
          </button>
        </div>
        {exportMut.isError && <ValidationState message="Could not request the export — try again." />}
        {requestStatusRow('export', exportPoll)}
        {exportPoll.status === 'complete' && (
          <div className="ui-banner ui-banner--warn" role="status">
            <span className="ui-banner__mark" aria-hidden>✓</span>
            <span>Your export is ready — check your registered email for the secure download.</span>
          </div>
        )}

        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Data minimisation</div>
            <div className="st-setrow__sub">We collect only what personalises your experience.</div>
          </div>
        </div>

        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Delete account</div>
            <div className="st-setrow__sub">Requires re-authentication · typed confirmation.</div>
          </div>
          <button type="button" className="btn tap" onClick={() => setShowDelete((v) => !v)}>
            Delete…
          </button>
        </div>

        {requestStatusRow('delete', deletePoll)}

        {showDelete && deletePoll.status === null && (
          <div className="st-panel" style={{ marginTop: 'var(--space-3)', borderColor: 'var(--risk)' }}>
            <p className="st-setrow__sub">
              This permanently deletes your account. Re-authenticate with an OTP and type{' '}
              <strong>{DELETE_CONFIRM_PHRASE}</strong> to confirm. You can export your data first.
            </p>

            {stage === 'reauth-mobile' && (
              <>
                <TextField
                  id="del-mobile"
                  label="Registered mobile number"
                  value={mobile}
                  onChange={setMobile}
                  inputMode="tel"
                  help="We send a one-time code to re-verify it is you."
                />
                <div className="st-actions">
                  <button type="button" className="btn tap" disabled={recoveryFlow.loadError || startMut.isPending || mobile.trim() === ''} onClick={() => startMut.mutate()}>
                    {startMut.isPending ? 'Sending…' : 'Send code'}
                  </button>
                </div>
              </>
            )}

            {stage === 'reauth-otp' && (
              <>
                <TextField id="del-otp" label="One-time code" value={otp} onChange={setOtp} inputMode="numeric" />
                <div className="st-actions">
                  <button type="button" className="btn tap" disabled={verifyMut.isPending || otp.trim() === ''} onClick={() => verifyMut.mutate()}>
                    {verifyMut.isPending ? 'Verifying…' : 'Verify code'}
                  </button>
                </div>
              </>
            )}

            {stage === 'confirm' && (
              <>
                <p className="st-setrow__sub">
                  <StatusBadge status="ok" label="Re-authenticated" />
                </p>
                <TextField id="del-confirm" label={`Type ${DELETE_CONFIRM_PHRASE} to confirm`} value={typed} onChange={setTyped} />
                <div className="st-actions">
                  <button
                    type="button"
                    className="btn btn--primary tap"
                    disabled={!deleteReady}
                    aria-disabled={!deleteReady}
                    onClick={() => { if (deleteReady) void submitAccountDeletion(); }}
                  >
                    {deletePending ? 'Submitting…' : 'Delete my account'}
                  </button>
                </div>
              </>
            )}

            {flowError && <ValidationState message={flowError} />}
          </div>
        )}
        </section>
      </details>

      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/s-18')}>
          Back to settings
        </button>
      </div>

      <DpdpFootnote>Data-principal rights honoured · retention exceptions need counsel-approved policy</DpdpFootnote>
    </StudentScreen>
  );
}

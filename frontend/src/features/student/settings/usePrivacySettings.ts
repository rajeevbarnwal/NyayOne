import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useStudentSession } from '../../../app/authContext';
import { newRequestId } from '../../../lib/apiClient';
import { getStudentSettings, updateStudentSettings, requestDataExport, getPrivacyRequest, requestAccountDeletion, SettingsApiError, type PrivacyConsent } from '../lib/settingsApi';
import { startRecovery, verifyRecovery, RegistrationApiError } from '../lib/registrationApi';
import { useOtpFlowState } from '../lib/useOtpFlowState';
import { captureStudentMutationSequence, runStudentMutationStep, isStudentMutationCancellation } from '../lib/useStudentMutation';
import { useRequestSettlement, useRouteContinuation } from '../lib/routeContinuation';
import { consumeStudentAuthTransitionNotice, recordStudentAuthTransitionNotice } from '../lib/studentAuthTransitionNotice';
import { beginPrivacyChange, confirmPrivacySave, failPrivacyChange, loadPrivacySettings, readExportRequest, readExportStatus, shouldPollExport, privacyDeleteReady, type PrivacySettingsState } from './privacySettingsState';
import type { PrivacyDeletionState, PrivacyExportState } from './PrivacySettingsView';

const INITIAL: PrivacySettingsState = { phase: 'loading' };
const KEY = ['student-settings'] as const;

/** S-19 only: confirmed cache, one mutation per version, explicit conflict reload. */
function usePrivacyPreferences() {
  const session = useStudentSession();
  const qc = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: async () => loadPrivacySettings(await getStudentSettings()).settings!, enabled: session.phase === 'authenticated', retry: false, refetchOnWindowFocus: false });
  const [actionState, setState] = useState(INITIAL);
  const state = actionState.phase !== 'loading' ? actionState : query.isFetching || !query.isFetched ? INITIAL
    : query.isError ? failPrivacyChange(INITIAL, query.error) : loadPrivacySettings(query.data);
  const inFlight = useRef(false);
  const captureRoute = useRouteContinuation();
  const captureSettlement = useRequestSettlement();
  async function reload() {
    if (inFlight.current || session.phase !== 'authenticated') return;
    inFlight.current = true;
    const settledHere = captureSettlement();
    setState(INITIAL);
    try {
      const result = await query.refetch();
      if (settledHere()) setState(result.isError ? failPrivacyChange(INITIAL, result.error) : loadPrivacySettings(result.data));
    } finally { if (settledHere()) inFlight.current = false; }
  }
  async function change(consent: PrivacyConsent) {
    if (inFlight.current || session.phase !== 'authenticated') return;
    const next = beginPrivacyChange(state, consent);
    if (next === state || !next.settings) return;
    inFlight.current = true;
    const routeOwned = captureRoute(), settledHere = captureSettlement();
    const fence = captureStudentMutationSequence();
    setState(next);
    try {
      const data = await runStudentMutationStep(fence, () => updateStudentSettings({ privacy: [consent] }, next.settings!.version));
      const confirmed = confirmPrivacySave(next, data);
      qc.setQueryData(KEY, confirmed.settings);
      if (settledHere()) setState(routeOwned() ? confirmed : { ...confirmed, phase: 'loaded' });
    } catch (error) {
      if (!isStudentMutationCancellation(error) && settledHere()) setState(failPrivacyChange(next, error));
    } finally { if (settledHere()) inFlight.current = false; }
  }
  return { state, change, reload };
}

/** Only a current-visit request reference; failed checks retain last known truth.
 * The idempotency key survives retries of one request, not navigation/storage.
 */
function usePrivacyExport() {
  const session = useStudentSession();
  const [state, setState] = useState<PrivacyExportState>({ phase: 'idle' });
  const stateRef = useRef(state); stateRef.current = state;
  const inFlight = useRef(false), generation = useRef(0), requestKey = useRef<string | null>(null);
  const readFlight = useRef<{ generation: number; manual: boolean; promise: Promise<void> } | null>(null);
  const captureSettlement = useRequestSettlement();
  async function request() {
    const previous = stateRef.current;
    if (inFlight.current || (readFlight.current?.generation === generation.current && readFlight.current.manual) || session.phase !== 'authenticated' || (previous.phase !== 'not-found' && previous.request && shouldPollExport(previous.request.status))) return;
    inFlight.current = true;
    const current = ++generation.current, settledHere = captureSettlement();
    const fence = captureStudentMutationSequence();
    requestKey.current ??= newRequestId();
    setState({ phase: 'requesting' });
    try {
      const data = await runStudentMutationStep(fence, () => requestDataExport(requestKey.current!));
      const request = readExportRequest(data);
      requestKey.current = null;
      if (settledHere() && current === generation.current) setState({ phase: 'tracked', request });
    } catch (error) {
      if (!isStudentMutationCancellation(error) && settledHere() && current === generation.current) setState({ phase: 'request-failed' });
    } finally { if (settledHere()) inFlight.current = false; }
  }
  async function check(background = false) {
    const previous = stateRef.current;
    if (inFlight.current || session.phase !== 'authenticated' || !previous.request || previous.phase === 'not-found') return;
    // A manual check can join an automatic read, not issue a duplicate GET.
    // Only an explicit check enters the disabling/pending UI state.
    if (!background) setState({ ...previous, phase: 'checking' });
    if (readFlight.current?.generation === generation.current) {
      if (!background) readFlight.current.manual = true;
      return readFlight.current.promise;
    }
    const current = generation.current, settledHere = captureSettlement(), id = previous.request.requestId;
    const fence = captureStudentMutationSequence();
    const flight = { generation: current, manual: !background, promise: Promise.resolve() };
    readFlight.current = flight;
    flight.promise = (async () => {
      try {
        const data = await runStudentMutationStep(fence, () => getPrivacyRequest(id));
        const request = readExportStatus(data, id);
        if (settledHere() && current === generation.current) setState({ phase: 'tracked', request });
      } catch (error) {
        if (!isStudentMutationCancellation(error) && settledHere() && current === generation.current) setState({ ...previous, phase: error instanceof SettingsApiError && error.status === 404 ? 'not-found' : 'check-failed' });
      } finally { if (readFlight.current === flight) readFlight.current = null; }
    })();
    return flight.promise;
  }
  const checkRef = useRef(check); checkRef.current = check;
  useEffect(() => {
    // Terminal and failed-read states stop polling. A failed read is retried by
    // an explicit user action, never relabelled as a failed server request.
    if (state.phase !== 'tracked' || !state.request || !shouldPollExport(state.request.status)) return;
    const timer = window.setTimeout(() => { void checkRef.current(true); }, 4000);
    return () => window.clearTimeout(timer);
  }, [state]);
  function dismiss() {
    if (inFlight.current || (readFlight.current?.generation === generation.current && readFlight.current.manual)) return;
    // Dismissing a background read is local only. Its eventual response must
    // not resurrect the notice or replace a subsequently requested export.
    generation.current++;
    requestKey.current = null;
    setState({ phase: 'idle' });
  }
  return { state, request, check, dismiss };
}

const EMPTY_DELETE: PrivacyDeletionState = { stage: 'closed', mobile: '', code: '', typed: '', busy: false, authorityReady: false };
function initialDeletion(): PrivacyDeletionState {
  if (consumeStudentAuthTransitionNotice('account_deletion_confirmation_invalid')) return { ...EMPTY_DELETE, stage: 'mobile', error: 'confirmation' };
  if (consumeStudentAuthTransitionNotice('account_deletion_conflict')) return { ...EMPTY_DELETE, stage: 'mobile', error: 'conflict' };
  if (consumeStudentAuthTransitionNotice('account_deletion_reauth_required')) return { ...EMPTY_DELETE, stage: 'mobile', error: 'reauth' };
  if (consumeStudentAuthTransitionNotice('account_deletion_failed')) return { ...EMPTY_DELETE, stage: 'mobile', error: 'request' };
  return EMPTY_DELETE;
}
function usePrivacyDeletion() {
  const session = useStudentSession(), nav = useNavigate();
  const [draft, setDraft] = useState(initialDeletion);
  const inFlight = useRef(false), forceMobile = useRef(false);
  const route = useRouteContinuation(), settlement = useRequestSettlement();
  const open = draft.stage !== 'closed';
  const flow = useOtpFlowState(undefined, { enabled: open && session.phase === 'authenticated' });
  const capability = flow.state?.purpose === 'recovery' ? flow.state : null;
  const verifyReady = draft.error !== 'unavailable' && draft.error !== 'reauth' && !flow.loading && !flow.loadError && capability?.status === 'pending' && (capability.expiresInSeconds ?? 0) > 0 && (capability.lockedForSeconds ?? 0) === 0 && (capability.attemptsLeft ?? 0) > 0;
  // A deletion proof rejection remains authoritative until Start again. A
  // remount's recovery projection must not contradict it with Identity confirmed.
  const stage = !open ? 'closed' : flow.loadError || forceMobile.current || draft.error === 'reauth' ? 'mobile' : capability?.status === 'verified' ? 'confirm' : capability?.status === 'pending' ? 'code' : draft.stage;
  const state: PrivacyDeletionState = {
    ...draft, stage, verifyReady,
    authorityReady: draft.error !== 'reauth' && privacyDeleteReady('DELETE', capability, flow.loadError || flow.loading, inFlight.current),
    error: open && flow.loadError ? 'authority' : stage === 'code' && capability?.expiresInSeconds === 0 ? 'expired' : stage === 'code' && (capability?.lockedForSeconds ?? 0) > 0 ? 'locked' : draft.error,
  };
  const stateRef = useRef(state); stateRef.current = state;
  function openDelete() { if (!inFlight.current) { forceMobile.current = false; setDraft({ ...EMPTY_DELETE, stage: 'mobile' }); } }
  function closeDelete() { if (!inFlight.current) { forceMobile.current = false; setDraft(EMPTY_DELETE); } }
  function edit(key: 'mobile' | 'code' | 'typed', value: string) {
    if (inFlight.current) return;
    const normalized = key === 'code' ? value.replace(/[\s-]/g, '').replace(/\D/g, '').slice(0, 6) : key === 'mobile' ? value.replace(/\D/g, '').slice(0, 10) : value;
    setDraft(current => ({ ...current, [key]: normalized, error: undefined }));
  }
  async function startAgain() {
    if (inFlight.current) return;
    forceMobile.current = true;
    setDraft({ ...EMPTY_DELETE, stage: 'mobile' });
    // A failed authority read must recover before any mutation can resume.
    if (flow.loadError) await flow.refresh().catch(() => undefined);
  }
  async function recover(action: 'send' | 'verify') {
    const current = stateRef.current;
    if (inFlight.current || session.phase !== 'authenticated' || flow.loading || flow.loadError || current.stage === 'closed') return;
    if (action === 'send' && !/^[6-9]\d{9}$/.test(current.mobile)) { setDraft(d => ({ ...d, error: 'mobile' })); return; }
    if (action === 'verify' && (!/^\d{6}$/.test(current.code) || !current.verifyReady)) return;
    inFlight.current = true;
    const owned = route(), settled = settlement(), fence = captureStudentMutationSequence();
    setDraft(d => ({ ...d, busy: true, error: undefined }));
    try {
      const data = await runStudentMutationStep(fence, () => action === 'send' ? startRecovery(current.mobile) : verifyRecovery(current.code));
      if (settled()) {
        flow.adopt(data); forceMobile.current = false;
        setDraft(d => ({ ...d, code: '', typed: '', stage: data.status === 'verified' && data.purpose === 'recovery' ? 'confirm' : data.status === 'pending' && data.purpose === 'recovery' ? 'code' : 'mobile', error: data.purpose !== 'recovery' ? 'reauth' : undefined }));
      }
    } catch (error) {
      if (!isStudentMutationCancellation(error) && settled()) {
        if (error instanceof RegistrationApiError && error.otpState) flow.adopt(error.otpState);
        const code = error instanceof RegistrationApiError ? error.code : '';
        const rejected = error instanceof RegistrationApiError ? error.otpState : undefined;
        // A uniform recovery_failed does not disclose whether the flow expired,
        // locked or disappeared. Only a usable server projection permits retry.
        const retryable = rejected?.purpose === 'recovery' && rejected.status === 'pending' && (rejected.expiresInSeconds ?? 0) > 0 && (rejected.lockedForSeconds ?? 0) === 0 && (rejected.attemptsLeft ?? 0) > 0;
        setDraft(d => ({ ...d, error: code === 'recovery_failed' && !retryable ? 'unavailable' : error instanceof RegistrationApiError && error.status === 429 ? 'rate' : code === 'otp_expired' || code === 'flow_expired' ? 'expired' : action === 'send' ? 'start' : 'code' }));
      }
    } finally {
      // Never release a transport/authority lease because of a URL change.
      // Only UI busy state is settled, including same-component query changes.
      if (settled()) { inFlight.current = false; setDraft(d => ({ ...d, busy: false, ...(owned() ? {} : { code: '', typed: '' }) })); }
    }
  }
  async function submitAccountDeletion() {
    const current = stateRef.current;
    if (inFlight.current || session.phase !== 'authenticated' || current.stage !== 'confirm' || !privacyDeleteReady(current.typed, capability, flow.loadError || flow.loading, current.busy)) return;
    inFlight.current = true;
    const owned = route(), settled = settlement();
    setDraft(d => ({ ...d, busy: true, error: undefined }));
    try {
      // Preserve the established exclusive transition: adapter validates 202,
      // consumes proof server-side and confirms anonymous authority first.
      await requestAccountDeletion({ confirmation: current.typed });
      recordStudentAuthTransitionNotice('account_deletion_accepted');
      nav('/s-03', { replace: true });
    } catch (error) {
      // The auth transition can remount this route. Only sanitized notice
      // categories survive it; no mobile/code/request ID is persisted.
      recordStudentAuthTransitionNotice(error instanceof SettingsApiError && error.status === 422 ? 'account_deletion_confirmation_invalid' : error instanceof SettingsApiError && error.status === 409 ? 'account_deletion_conflict' : error instanceof SettingsApiError && error.status === 401 ? 'account_deletion_reauth_required' : 'account_deletion_failed');
      if (settled()) setDraft(d => ({ ...d, typed: '', error: error instanceof SettingsApiError && error.status === 409 ? 'conflict' : error instanceof SettingsApiError && error.status === 401 ? 'reauth' : error instanceof SettingsApiError && error.status === 422 ? 'confirmation' : 'request' }));
      if (owned()) nav('/s-19', { replace: true });
    } finally { if (settled()) { inFlight.current = false; setDraft(d => ({ ...d, busy: false })); } }
  }
  return { state, openDelete, closeDelete, edit, startAgain, recover, remove: submitAccountDeletion };
}

export function usePrivacySettings() {
  const preferences = usePrivacyPreferences(), exportFlow = usePrivacyExport(), deletion = usePrivacyDeletion();
  return { preferences, exportFlow, deletion };
}

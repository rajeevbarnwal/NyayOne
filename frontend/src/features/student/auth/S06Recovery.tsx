import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStudentSession } from '../../../app/authContext';
import { RegistrationApiError, cancelStudentOtp, completeRecovery, isMaskedMobileDestination, resendStudentOtp, startRecovery, verifyRecovery, type OtpFlowState } from '../lib/registrationApi';
import { isValidMobile } from '../lib/registration';
import { useOtpFlowState } from '../lib/useOtpFlowState';
import { S06R2, type S06R2State } from './S06R2';

export function canVerifyRecovery(state: OtpFlowState | null, code: string, busy: boolean, loadError: boolean) {
  return !busy && !loadError && /^\d{6}$/.test(code) && state?.status === 'pending'
    && state.purpose === 'recovery' && (state.attemptsLeft ?? 0) > 0
    && (state.expiresInSeconds ?? 0) > 0 && state.lockedForSeconds === 0;
}

export function recoveryView(state: OtpFlowState | null, view: S06R2State, loadError: boolean): S06R2State {
  if (view === 'success') return 'success';
  if (loadError || view === 'neterr') return 'neterr';
  if (state?.status === 'verified' && state.purpose === 'recovery') return 'neterr';
  if (view === 'submitting') return view;
  if (state?.status === 'pending' && state.purpose === 'recovery') {
    if ((state.lockedForSeconds ?? 0) > 0 || state.attemptsLeft === 0) return 'locked';
    if (state.expiresInSeconds === 0) return 'expired';
    if (view === 'cooldown') return state.resendAllowed ? 'challenge' : 'cooldown';
    return view === 'wrong' ? 'wrong' : 'challenge';
  }
  return view === 'invalidnum' ? 'invalidnum' : 'entry';
}

export async function runRecoveryCompletion(verify: () => Promise<OtpFlowState>, complete: () => Promise<OtpFlowState>, current: () => boolean): Promise<OtpFlowState> {
  const proof = await verify();
  if (!current()) throw new Error('recovery_abandoned');
  if (proof.status !== 'verified' || proof.purpose !== 'recovery') throw new Error('invalid_recovery_verification');
  const retired = await complete();
  if (!current()) throw new Error('recovery_abandoned');
  if (retired.status !== 'unavailable' || retired.purpose !== null) throw new Error('invalid_recovery_completion');
  return retired;
}

/** S-06 alone. Cookies/server projections own recovery; the view owns no identity cache. */
export function S06Recovery() {
  const navigate = useNavigate();
  const session = useStudentSession();
  const flow = useOtpFlowState(undefined, { enabled: session.phase === 'anonymous' });
  const [mobile, setMobile] = useState('');
  const [code, setCode] = useState('');
  const [view, setView] = useState<S06R2State>('entry');
  const [busy, setBusy] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const sessionPhase = useRef(session.phase);
  sessionPhase.current = session.phase;
  const mounted = useRef(true);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); pending.current = null; };
  }, []);

  const state = flow.state;
  const ready = session.phase === 'anonymous' && !flow.loading && !flow.loadError && state !== null;
  async function act(operation: (signal: AbortSignal, current: () => boolean) => Promise<void>) {
    if (pending.current || !mounted.current || sessionPhase.current !== 'anonymous') return;
    const focusOrigin = typeof document === 'undefined' ? null : document.activeElement;
    const keyboardOrigin = focusOrigin?.matches(':focus-visible') ?? false;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    const current = () => mounted.current && pending.current === controller && !controller.signal.aborted && sessionPhase.current === 'anonymous';
    try { await operation(controller.signal, current); }
    catch (error) {
      if (!current()) return;
      if (error instanceof RegistrationApiError && error.otpState) {
        flow.adopt(error.otpState);
        setView(error.otpState.status === 'pending' && error.otpState.purpose === 'recovery'
          ? error.code === 'resend_cooldown' ? 'cooldown' : 'wrong'
          : 'neterr');
      } else { setView('neterr'); }
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        if (mounted.current) {
          setBusy(false);
          // Restore a disabled/replaced keyboard control, but never steal focus
          // if the user deliberately moved elsewhere while the request ran.
          if (sessionPhase.current === 'anonymous' && keyboardOrigin
            && (document.activeElement === focusOrigin || document.activeElement === document.body)) {
            setFocusRequest(value => value + 1);
          }
        }
      }
    }
  }
  function send() {
    if (!ready || pending.current) return;
    if (!isValidMobile(mobile)) { setView('invalidnum'); return; }
    void act(async (signal, current) => {
      setView('submitting');
      const next = await startRecovery(mobile, signal);
      if (!current()) return;
      if (next.status !== 'pending' || next.purpose !== 'recovery') throw new Error('invalid_recovery_start');
      flow.adopt(next); setMobile(''); setCode(''); setView('challenge');
    });
  }
  function verify() {
    if (!canVerifyRecovery(state, code, busy, !ready)) return;
    void act(async (signal, current) => {
      const retired = await runRecoveryCompletion(() => verifyRecovery(code, signal), () => completeRecovery(signal), current);
      if (!current()) return;
      flow.adopt(retired); setCode(''); setMobile(''); setView('success');
    });
  }
  function resend() {
    if (!ready || state?.status !== 'pending' || state.purpose !== 'recovery' || !state.resendAllowed) return;
    void act(async (signal, current) => {
      const next = await resendStudentOtp(signal);
      if (!current()) return;
      if (next.status !== 'pending' || next.purpose !== 'recovery') throw new Error('invalid_recovery_resend');
      flow.adopt(next); setCode(''); setView('challenge');
    });
  }
  function changeNumber() {
    if (!ready) return;
    void act(async (signal, current) => {
      const retired = await cancelStudentOtp(signal);
      if (!current()) return;
      flow.adopt(retired); setMobile(''); setCode(''); setView('entry');
    });
  }
  function retry() {
    // A failed response may have reached the server. Read authority before any resend.
    void act(async (signal, current) => {
      const next = await flow.refresh();
      if (!current()) return;
      if (next.status === 'verified' && next.purpose === 'recovery') {
        const retired = await runRecoveryCompletion(async () => next, () => completeRecovery(signal), current);
        flow.adopt(retired); setCode(''); setMobile(''); setView('success');
      } else { setView('entry'); }
    });
  }
  function back() {
    pending.current?.abort(); pending.current = null;
    setMobile(''); setCode(''); navigate('/s-04', { replace: true });
  }
  return <S06R2 state={recoveryView(state, view, flow.loadError)} mobile={mobile} code={code}
    destinationMasked={isMaskedMobileDestination(state?.destinationMasked) ? `+91 ••••• ••${String(state?.destinationMasked).slice(-3)}` : null} expiresInSeconds={state?.expiresInSeconds ?? null}
    resendInSeconds={state?.resendInSeconds ?? null} attemptsLeft={state?.attemptsLeft ?? null}
    lockedForSeconds={state?.lockedForSeconds ?? null} busy={busy} authorityReady={ready} focusRequest={focusRequest}
    resendAllowed={state?.resendAllowed ?? false}
    onMobileChange={value => { setMobile(value); if (view === 'invalidnum') setView('entry'); }}
    onCodeChange={value => setCode(value.replace(/\D/g, '').slice(0, 6))} onSend={send} onVerify={verify} onResend={resend}
    onChangeNumber={changeNumber} onBack={back} onRetry={retry}/>;
}

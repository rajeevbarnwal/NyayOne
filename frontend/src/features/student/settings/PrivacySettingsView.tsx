import { useEffect, useRef, type ReactNode } from 'react';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { privacyRequestMessage, type ExportSnapshot, type PrivacySettingsState } from './privacySettingsState';
import type { PrivacyConsent } from '../lib/settingsApi';
import './S19Privacy.css';

export interface PrivacyExportState {
  phase: 'idle' | 'requesting' | 'tracked' | 'checking' | 'request-failed' | 'check-failed' | 'not-found';
  request?: ExportSnapshot;
}
export interface PrivacyDeletionState {
  stage: 'closed' | 'mobile' | 'code' | 'confirm';
  mobile: string;
  code: string;
  typed: string;
  busy: boolean;
  authorityReady: boolean;
  error?: 'mobile' | 'start' | 'rate' | 'code' | 'expired' | 'reauth' | 'confirmation' | 'conflict' | 'request' | 'authority';
}
export interface PrivacySettingsViewProps {
  state: PrivacySettingsState;
  exportState: PrivacyExportState;
  deletion: PrivacyDeletionState;
  onNavigate: (path: string) => void;
  onChange: (consent: PrivacyConsent) => void;
  onReload: () => void;
  onExport: () => void;
  onCheckExport: () => void;
  onDismissExport: () => void;
  onDeleteOpen: () => void;
  onDeleteClose: () => void;
  onMobile: (value: string) => void;
  onCode: (value: string) => void;
  onTyped: (value: string) => void;
  onSend: () => void;
  onVerify: () => void;
  onDelete: () => void;
  onStartAgain: () => void;
}

type IconName = 'guard' | 'back' | 'refresh' | 'check' | 'warn' | 'trash' | 'download' | 'lock' | 'login' | 'info' | 'clock' | 'shield';
function Icon({ name, size = 18, framed = false }: { name: IconName; size?: number; framed?: boolean }) {
  const line = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.9, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  const glyph = <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    {name === 'guard' && <><circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16"/><circle cx="9" cy="9" r="3.2" {...line} strokeWidth="1.8"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0" {...line} strokeWidth="1.8"/><path d="M17 8.5l4 1.6v2.6c0 2.3-1.7 4-4 5.1-.9-.4-1.7-1-2.4-1.6" {...line} strokeWidth="1.8"/></>}
    {name === 'back' && <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="M13.8 7.8 9.6 12l4.2 4.2" {...line}/></>}
    {name === 'check' && <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="m8 12.3 2.7 2.7 5.3-5.6" {...line}/></>}
    {name === 'refresh' && <><path d="M5 12a7 7 0 0 1 12-4.6M17.6 3.8v4h-4M19 12a7 7 0 0 1-12 4.6M6.4 20.2v-4h4" {...line}/><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".08"/></>}
    {name === 'warn' && <><path d="M12 4 21 20H3z" fill="currentColor" opacity=".16"/><path d="M12 4 21 20H3zM12 10v4.5M12 17.2v.3" {...line}/></>}
    {name === 'trash' && <><path d="M6 7h12l-1 13H7z" fill="currentColor" opacity=".14"/><path d="M6 7h12l-1 13H7zM4 7h16M9 7V4.5h6V7" {...line}/></>}
    {name === 'download' && <><path d="M12 3l1.9 5.3L19.2 10l-5.3 1.9L12 17.2l-1.9-5.3L4.8 10l5.3-1.7z" fill="currentColor" opacity=".18"/><path d="M12 3l1.9 5.3L19.2 10l-5.3 1.9L12 17.2l-1.9-5.3L4.8 10l5.3-1.7z" {...line} strokeWidth="1.7"/><path d="M18.6 15.6l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" fill="currentColor"/></>}
    {name === 'lock' && <><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="currentColor" opacity=".16"/><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/></>}
    {name === 'login' && <><path d="M10 4.5h6.5A1.5 1.5 0 0 1 18 6v12a1.5 1.5 0 0 1-1.5 1.5H10" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><circle cx="10" cy="12" r="7.5" fill="currentColor" opacity=".12"/><path d="M3.5 12H13M10 8.5 13.5 12 10 15.5" {...line}/></>}
    {name === 'info' && <><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M12 11v5M12 8v.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></>}
    {name === 'clock' && <><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M12 7.5V12l3 2" {...line}/></>}
    {name === 'shield' && <><path d="M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z" fill="currentColor" opacity=".14"/><path d="M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/><path d="m9.2 11.8 2 2 3.6-3.8" {...line} strokeWidth="1.8"/></>}
  </svg>;
  return framed ? <span className="v321-privacy__button-icon" aria-hidden="true">{glyph}</span> : glyph;
}
const CONSENTS = [
  ['analytics', 'Usage analytics', 'Lets NyayOne measure how features are used.'],
  ['marketing', 'Marketing messages', 'Messages about NyayOne programmes and offers.'],
  ['share_partners', 'Sharing with partners', 'Allows your data to be shared with partner organisations.'],
] as const;

function Action({ children, icon = 'refresh', onClick, disabled = false }: { children: ReactNode; icon?: IconName; onClick: () => void; disabled?: boolean }) {
  return <button type="button" className="v321-privacy__button" onClick={onClick} disabled={disabled}><Icon name={icon} framed/>{children}</button>;
}
function Notice({ title, children, actions, warning = false, tone = warning ? 'risk' : 'ind', icon = warning ? 'warn' : 'check' }: { title: string; children: ReactNode; actions?: ReactNode; warning?: boolean; tone?: 'risk' | 'warn' | 'ok' | 'ind'; icon?: IconName }) {
  return <div className={`v321-privacy__notice${warning ? ' is-warning' : ''} is-${tone}`} role={warning ? 'alert' : 'status'} tabIndex={-1}>
    <Icon name={icon}/><div><b>{title}</b><div>{children}</div>{actions && <div className="v321-privacy__notice-actions">{actions}</div>}</div>
  </div>;
}
const DELETE_ERRORS: Record<NonNullable<PrivacyDeletionState['error']>, [string, string]> = {
  mobile: ['Check the mobile number.', 'Enter the 10-digit mobile number registered to this account.'],
  start: ['Could not start re-authentication.', 'Check the mobile number and retry.'],
  rate: ['Too many codes requested.', 'Wait a few minutes, then try again.'],
  code: ['That code did not match.', 'Try again.'],
  expired: ['That code has expired.', 'Start again to get a new code.'],
  reauth: ['The server did not confirm re-authentication.', 'Start again.'],
  confirmation: ['Type DELETE in capital letters.', 'Nothing was deleted.'],
  conflict: ['Something changed on your account while this was processing.', 'Nothing was deleted. Wait a moment and try again.'],
  request: ['Could not submit the deletion request.', 'Nothing is confirmed. Check your connection and try again.'],
  authority: ['Re-authentication state is unavailable.', 'No deletion can proceed until the server state check recovers.'],
};

export function PrivacySettingsView(props: PrivacySettingsViewProps) {
  const { state, exportState, deletion: d } = props;
  const root = useRef<HTMLDivElement>(null);
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const restoreOverview = useRef(false);
  const restoreLoad = useRef(false);
  const previousStage = useRef(d.stage);
  useEffect(() => {
    if (previousStage.current !== d.stage) {
      if (d.stage === 'closed') restoreOverview.current = true;
      else stepHeading.current?.focus();
      previousStage.current = d.stage;
    }
    if (restoreOverview.current && d.stage === 'closed') {
      root.current?.querySelector<HTMLButtonElement>('[data-delete-open]')?.focus();
      restoreOverview.current = false;
    }
  }, [d.stage]);
  useEffect(() => {
    if (state.phase === 'loading') return;
    if (restoreLoad.current) {
      root.current?.querySelector<HTMLElement>('[role="alert"], [role="switch"]')?.focus();
      restoreLoad.current = false;
    }
    if (d.error || ['conflict', 'network', 'invalid'].includes(state.phase) || ['request-failed', 'check-failed', 'not-found'].includes(exportState.phase)) {
      root.current?.querySelector<HTMLElement>('[role="alert"]')?.focus();
    }
  }, [state, d.error, exportState]);
  const hardError = !state.settings && state.phase !== 'loading';
  const reload = () => { restoreLoad.current = true; props.onReload(); };
  const blocked = state.phase === 'saving' || state.phase === 'conflict';
  const exportBusy = exportState.phase === 'requesting' || exportState.phase === 'checking';
  const activeExport = exportState.request && ['pending', 'processing'].includes(exportState.request.status) && exportState.phase !== 'not-found';
  const exportMessage = exportState.request ? privacyRequestMessage(exportState.request.status) : undefined;
  const step = d.stage === 'mobile' ? 1 : d.stage === 'code' ? 2 : 3;
  const error = d.error ? DELETE_ERRORS[d.error] : undefined;
  const title = d.stage === 'mobile' ? 'Delete your account' : d.stage === 'code' ? 'Enter the code we sent' : 'Type DELETE to finish';
  const restartNeeded = d.error === 'expired' || d.error === 'reauth';
  const legacyOverview = state.phase === 'loading' || state.phase === 'session';
  const deletionError = error && (['mobile', 'code', 'confirmation'].includes(d.error!)
    ? <div className="v321-privacy__field-error" role="alert" tabIndex={-1}><span>{error[0]}</span>{' '}<span>{error[1]}</span></div>
    : <Notice warning tone={d.error === 'rate' || d.error === 'expired' ? 'warn' : 'risk'} icon={d.error === 'rate' || d.error === 'expired' ? 'clock' : 'warn'} title={error[0]} actions={restartNeeded || d.error === 'authority' ? <Action onClick={props.onStartAgain} disabled={d.busy}>{d.error === 'authority' ? 'Try again' : 'Start again'}</Action> : undefined}>{error[1]}</Notice>);
  return <div ref={root} className="v321-privacy" data-screen="S-19" data-privacy-state={state.phase} data-deletion-stage={d.stage}>
    <header className="v321-privacy__header">
      <span className="v321-privacy__desktop-brand"><NyayOneRevLLockup/></span>
      <span className="v321-privacy__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false"/><b>Privacy</b></span>
      <nav className="v321-privacy__nav" aria-label="Site"><button type="button" onClick={() => props.onNavigate('/s-14')}>Home</button>{['Research', 'Calendar', 'Careers'].map(label => <button type="button" disabled key={label}>{label}</button>)}<button type="button" onClick={() => props.onNavigate('/s-17')}>Profile</button></nav>
      <button type="button" className="v321-privacy__avatar" aria-label="P, Your profile" onClick={() => props.onNavigate('/s-17')}><span>P</span></button>
    </header>
    <div className="v321-privacy__layout"><main className="v321-privacy__body" id="main-content">
      <button type="button" className="v321-privacy__button v321-privacy__back" onClick={() => props.onNavigate('/s-17')}><Icon name="back" framed/>Profile</button>
      {d.stage === 'closed' ? <>
        <div><h1><span className="v321-privacy__heading-icon"><Icon name={legacyOverview ? 'shield' : 'guard'} size={20}/></span>Privacy preferences and requests.</h1><p className="v321-privacy__subtitle">{legacyOverview ? 'Each choice is separate and off unless you turn it on.' : 'Each choice is separate, off unless you turn it on, and saves as you change it.'}</p></div>
        {state.phase === 'loading' && <div className="v321-privacy__skeletons" role="status" aria-label="Loading consent preferences"><div/><div/></div>}
        {hardError && (state.phase === 'session' ? <div className="v321-privacy__error" role="alert" tabIndex={-1}>
          <span className="v321-privacy__error-icon" aria-hidden="true"><Icon name="lock" size={20}/></span>
          <h2>Your session ended.</h2><p>Sign in again to continue.</p><span className="v321-privacy__error-code">HTTP 401</span>
          <div className="v321-privacy__error-actions"><button type="button" className="v321-privacy__button is-primary" onClick={() => props.onNavigate('/s-03')}><Icon name="login" framed/>Sign in again</button></div>
        </div> : <Notice warning title={state.phase === 'forbidden' ? 'These settings are for student accounts.' : 'Could not load consent preferences.'} actions={<Action onClick={reload}>Try again</Action>}>Your choices have not been changed.</Notice>)}
        {state.settings && !hardError && state.phase !== 'loading' && <>
          <section className="v321-privacy__card v321-privacy__consents" aria-labelledby="S-19-consents"><h2 className="v321-privacy__eyebrow" id="S-19-consents">Consents</h2>
            {CONSENTS.map(([kind, label, help]) => {
              const confirmed = state.settings!.privacy.find(entry => entry.kind === kind)!.enabled;
              const pending = state.pendingConsent?.kind === kind ? state.pendingConsent.enabled : undefined;
              return <div className="v321-privacy__switch-row" key={kind}><div className="v321-privacy__switch-label"><b id={`S-19-${kind}-label`}>{label}</b><span id={`S-19-${kind}-help`}>{help}</span></div><button type="button" role="switch" className="v321-privacy__switch" aria-checked={pending ?? confirmed} aria-labelledby={`S-19-${kind}-label`} aria-describedby={`S-19-${kind}-help`} aria-disabled={blocked} aria-busy={pending !== undefined || undefined} onClick={() => { if (!blocked) props.onChange({ kind, enabled: !confirmed }); }}><span aria-hidden="true"/></button></div>;
            })}
            <div aria-live="polite" aria-atomic="true">
              {state.phase === 'saving' && <p className="v321-privacy__save-status" role="status">Saving…</p>}
              {state.phase === 'saved' && <p className="v321-privacy__save-status is-saved" role="status"><Icon name="check" size={16}/>Saved to your account.</p>}
              {state.phase === 'conflict' && <Notice warning tone="warn" icon="refresh" title="Your consents changed somewhere else." actions={<Action onClick={reload}>Reload</Action>}>Nothing was overwritten. Reload to see the current choices.</Notice>}
              {(state.phase === 'network' || state.phase === 'invalid') && <Notice warning title={state.phase === 'network' ? 'That change was not saved.' : 'The server did not accept this choice.'} actions={<Action onClick={() => state.retryConsent ? props.onChange(state.retryConsent) : props.onReload()}>Try again</Action>}>The switch is back where it was. Try again.</Notice>}
            </div>
          </section>
          <section className="v321-privacy__card v321-privacy__data" aria-labelledby="S-19-data"><h2 id="S-19-data" className="v321-privacy__eyebrow">Your data</h2>
            <div className="v321-privacy__data-row"><div><b>Request a copy of my data</b><p>The server prepares an export and reports its status.</p></div><Action icon="download" onClick={props.onExport} disabled={exportBusy || !!activeExport}>{exportState.phase === 'requesting' ? 'Requesting…' : 'Request a copy of my data'}</Action></div>
            {['request-failed', 'check-failed', 'not-found'].includes(exportState.phase) ? <Notice warning tone={exportState.phase === 'request-failed' ? 'risk' : 'warn'} icon={exportState.phase === 'not-found' ? 'info' : 'warn'} title={exportState.phase === 'not-found' ? 'That request was not found.' : exportState.phase === 'check-failed' ? 'Status check failed.' : 'Could not request the export.'} actions={<><Action onClick={exportState.phase === 'check-failed' ? props.onCheckExport : props.onExport}>{exportState.phase === 'check-failed' ? 'Check status' : 'Request again'}</Action><Action icon="back" onClick={props.onDismissExport}>Dismiss</Action></>}>
              {exportState.phase === 'check-failed' ? <>The request is still on the server; last confirmed status: {exportState.request?.status}. Check again in a moment.</> : exportState.phase === 'not-found' ? 'It may belong to another session. Request a new export if you still need one.' : 'Check your connection and try again.'}
            </Notice> : exportMessage && exportState.request && <Notice warning={exportState.request.status === 'failed'} tone={exportState.request.status === 'complete' ? 'ok' : exportState.request.status === 'failed' ? 'risk' : 'ind'} icon={exportState.request.status === 'pending' ? 'info' : exportState.request.status === 'processing' ? 'clock' : exportState.request.status === 'failed' ? 'warn' : 'check'} title={exportMessage.title} actions={<><Action onClick={exportState.request.status === 'failed' || exportState.request.status === 'cancelled' ? props.onExport : props.onCheckExport} disabled={exportBusy}>{exportState.request.status === 'failed' || exportState.request.status === 'cancelled' ? 'Request again' : 'Check status'}</Action><Action icon="back" onClick={props.onDismissExport} disabled={exportBusy}>Dismiss</Action></>}>{exportMessage.body} Reference <span className="v321-privacy__mono">{exportState.request.requestId}</span>.</Notice>}
            <div className="v321-privacy__data-row"><div><b>Delete my account</b><p>Confirm your mobile, enter a code, then type DELETE.</p></div><button type="button" data-delete-open className="v321-privacy__button" onClick={props.onDeleteOpen} disabled={state.phase === 'saving'}><Icon name="trash" framed/>Delete my account</button></div>
          </section>
        </>}
      </> : <section className="v321-privacy__card v321-privacy__deletion" aria-labelledby="S-19-delete-heading">
        <h1 id="S-19-delete-heading" ref={stepHeading} tabIndex={-1}><span className={`v321-privacy__heading-icon${d.stage !== 'code' ? ' is-danger' : ''}`}><Icon name={d.stage === 'code' ? 'guard' : 'trash'} size={20}/></span>{title}</h1>
        <ol className="v321-privacy__steps" aria-label="Deletion steps">{['Confirm your mobile', 'Enter the code', 'Type DELETE'].map((label, index) => <li key={label} aria-current={index + 1 === step ? 'step' : undefined} className={index + 1 < step ? 'is-done' : undefined}>{label}</li>)}</ol>
        {d.stage === 'mobile' && <p>When the server accepts this request your account is suspended at once and you are signed out everywhere. Erasure then runs on the server. This cannot be undone from NyayOne.</p>}
        {d.stage === 'code' && <p>Sent to the mobile number you entered. The code works once and expires soon.</p>}
        {d.stage === 'confirm' && d.authorityReady && <Notice tone="ok" title="Identity confirmed.">The server issued deletion authority for this visit only.</Notice>}
        {restartNeeded && deletionError}
        {!restartNeeded && <form className="v321-privacy__form" onSubmit={event => { event.preventDefault(); if (!d.busy) (d.stage === 'mobile' ? props.onSend : d.stage === 'code' ? props.onVerify : props.onDelete)(); }}>
          {d.stage === 'mobile' && <div className="v321-privacy__field"><label htmlFor="S-19-mobile">Registered mobile number</label><div className="v321-privacy__prefix"><span aria-hidden="true">+91</span><input id="S-19-mobile" type="tel" inputMode="numeric" autoComplete="tel-national" maxLength={10} value={d.mobile} onChange={event => props.onMobile(event.target.value)} aria-invalid={d.error === 'mobile' || undefined} aria-describedby="S-19-mobile-help" readOnly={d.busy}/></div><p id="S-19-mobile-help" className="v321-privacy__help">We send a six-digit code to this number to confirm it is you.</p></div>}
          {d.stage === 'code' && <div className="v321-privacy__field"><label htmlFor="S-19-code">Six-digit code</label><input id="S-19-code" className="v321-privacy__otp" inputMode="numeric" autoComplete="one-time-code" value={d.code} onChange={event => props.onCode(event.target.value)} aria-invalid={d.error === 'code' || undefined} aria-describedby="S-19-code-help" readOnly={d.busy}/><p id="S-19-code-help" className="v321-privacy__help">Six digits. Use the code sent to your registered mobile.</p></div>}
          {d.stage === 'confirm' && <div className="v321-privacy__field"><label htmlFor="S-19-confirm">Type DELETE to continue</label><input id="S-19-confirm" autoComplete="off" spellCheck={false} value={d.typed} onChange={event => props.onTyped(event.target.value)} aria-invalid={d.error === 'confirmation' || undefined} aria-describedby="S-19-confirm-help" readOnly={d.busy}/><p id="S-19-confirm-help" className="v321-privacy__help">Capital letters. This check stops accidental deletion.</p></div>}
          {deletionError}
          <button type="submit" className={`v321-privacy__button ${d.stage === 'confirm' ? 'is-danger' : 'is-primary'}`} disabled={d.busy || d.error === 'authority' || (d.stage === 'mobile' ? !/^[6-9]\d{9}$/.test(d.mobile) : d.stage === 'code' ? !/^\d{6}$/.test(d.code) : d.typed !== 'DELETE' || !d.authorityReady)}><Icon name={d.stage === 'mobile' ? 'guard' : d.stage === 'code' ? 'check' : 'trash'} framed/>{d.busy ? d.stage === 'mobile' ? 'Sending…' : d.stage === 'code' ? 'Verifying…' : 'Requesting account deletion…' : d.stage === 'mobile' ? 'Send code' : d.stage === 'code' ? 'Verify code' : 'Request account deletion'}</button>
        </form>}
        <Action icon="back" onClick={d.stage === 'code' ? props.onStartAgain : props.onDeleteClose} disabled={d.busy}>{d.stage === 'mobile' ? 'Back to privacy' : d.stage === 'code' ? 'Use a different number' : 'Keep my account'}</Action>
      </section>}
    </main><aside className="v321-privacy__aside" aria-label="Privacy context"><div className="v321-privacy__card"><div className="v321-privacy__eyebrow">Your rights</div><p>{legacyOverview ? 'Export and deletion run as server requests. This screen shows the status the server returns for the request you made on this visit.' : 'Consent changes save as you make them. Export and deletion are server requests; this screen shows only the status the server returns for this visit.'}</p></div></aside></div>
    <footer className="v321-privacy__footer"><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}

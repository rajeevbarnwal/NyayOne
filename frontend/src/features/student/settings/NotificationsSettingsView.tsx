import { useEffect, useRef } from 'react';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import type { NotificationPatch, NotificationSettingsState } from './notificationSettingsState';
import './S18Settings.css';

function SettingsIcon({ name, size = 18, framed = false }: { name: 'bell' | 'back' | 'guard' | 'warn' | 'lock' | 'login' | 'checkc' | 'refresh'; size?: number; framed?: boolean }) {
  const svg = <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    {name === 'bell' && <><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" fill="currentColor" opacity=".14"/><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M10 20.5a2 2 0 0 0 4 0" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}
    {name === 'back' && <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="M13.8 7.8 9.6 12l4.2 4.2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
    {name === 'guard' && <><circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16"/><circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/><path d="M17 8.5l4 1.6v2.6c0 2.3-1.7 4-4 5.1-.9-.4-1.7-1-2.4-1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>}
    {name === 'warn' && <><path d="M12 3 2 21h20Z" fill="currentColor" opacity=".14"/><path d="M12 3 2 21h20ZM12 9v5m0 3v.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></>}
    {name === 'lock' && <><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="currentColor" opacity=".16"/><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/></>}
    {name === 'login' && <><path d="M10 4.5h6.5A1.5 1.5 0 0 1 18 6v12a1.5 1.5 0 0 1-1.5 1.5H10" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><circle cx="10" cy="12" r="7.5" fill="currentColor" opacity=".12"/><path d="M3.5 12H13M10 8.5 13.5 12 10 15.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
    {name === 'checkc' && <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="m8 12.3 2.7 2.7 5.3-5.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
    {name === 'refresh' && <><path d="M5 12a7 7 0 0 1 12-4.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><path d="M17.6 3.8v4h-4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><path d="M19 12a7 7 0 0 1-12 4.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><path d="M6.4 20.2v-4h4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".08"/></>}
  </svg>;
  return framed ? <span className="v321-settings__button-icon" aria-hidden="true">{svg}</span> : svg;
}

const NOTIFICATIONS = [
  ['notifEmail', 'Email notifications', 'Deadlines, applications and account activity by email.'],
  ['notifSms', 'SMS notifications', 'Time-critical alerts to your registered mobile.'],
  ['notifUpdates', 'Product updates', 'New features and followed-school admission updates.'],
] as const;

export function NotificationsSettingsView({ state, onChange, onReload, onNavigate }: {
  state: NotificationSettingsState;
  onChange: (patch: NotificationPatch) => void;
  onReload: () => void;
  onNavigate: (route: string) => void;
}) {
  const { phase, settings: saved, pending } = state;
  const draft = saved ? { ...saved, ...pending } : undefined;
  const blocked = phase === 'saving' || phase === 'conflict';
  const error = useRef<HTMLDivElement>(null);
  const disclosure = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (phase === 'invalid' && disclosure.current) disclosure.current.open = true;
    if (['invalid', 'conflict', 'network'].includes(phase)) error.current?.focus();
  }, [state, phase]);
  const hardError = phase === 'session' || phase === 'forbidden' || (phase === 'network' && !saved);
  const legacyStateCopy = ['loading', 'session', 'forbidden'].includes(phase);
  const title = phase === 'session' ? 'Your session ended.' : phase === 'forbidden' ? 'These settings are for student accounts.' : 'Could not reach NyayOne.';
  return <div className="v321-settings" data-screen="S-18" data-settings-state={phase}>
    <header className="v321-settings__header">
      <span className="v321-settings__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-settings__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>Settings</b></span>
      <nav className="v321-settings__nav" aria-label="Site">
        <button type="button" onClick={() => onNavigate('/s-14')}>Home</button>
        {['Research', 'Calendar', 'Careers'].map(label => <button type="button" disabled key={label}>{label}</button>)}
        <button type="button" onClick={() => onNavigate('/s-17')}>Profile</button>
      </nav>
      {/* Settings has no name projection; do not invent the prototype identity. */}
      <button type="button" className="v321-settings__avatar" aria-label="P, Your profile" onClick={() => onNavigate('/s-17')}><span>P</span></button>
    </header>
    <div className="v321-settings__layout">
      <main className="v321-settings__body" id="main-content">
        <button type="button" className="v321-settings__button v321-settings__back" onClick={() => onNavigate('/s-17')}><SettingsIcon name="back" framed/>Profile</button>
        <div><h1><span className="v321-settings__heading-icon"><SettingsIcon name="bell" size={20}/></span>Notifications and appearance.</h1><p className="v321-settings__subtitle">{legacyStateCopy ? 'Saved to your account, not this device.' : 'Each change saves to your account as you make it.'}</p></div>
        {phase === 'loading' && <div className="v321-settings__skeletons" role="status" aria-label="Loading your settings"><div/><div/></div>}
        {hardError && <div className="v321-settings__error" role="alert" tabIndex={-1} ref={error}>
          <span className="v321-settings__error-icon" aria-hidden="true"><SettingsIcon name={phase === 'session' || phase === 'forbidden' ? 'lock' : 'warn'} size={20}/></span><h2>{title}</h2>
          <p>{phase === 'session' ? 'Sign in again to keep editing. Unsaved changes are not stored on this device.' : phase === 'forbidden' ? 'Your account does not have the student role, so these preferences are not available.' : 'Your settings could not be loaded. Check your connection and try again.'}</p>
          {phase !== 'network' && <span className="v321-settings__code">HTTP {phase === 'session' ? '401' : '403'}</span>}
          <div className="v321-settings__error-actions"><button type="button" className={`v321-settings__button${phase === 'session' ? ' is-primary' : ''}`} onClick={() => phase === 'session' ? onNavigate('/s-03') : phase === 'forbidden' ? onNavigate('/s-17') : onReload()}><SettingsIcon name={phase === 'session' ? 'login' : phase === 'forbidden' ? 'back' : 'refresh'} framed/>{phase === 'session' ? 'Sign in again' : phase === 'forbidden' ? 'Back to profile' : 'Try again'}</button></div>
        </div>}
        {draft && !hardError && phase !== 'loading' && <>
          <section className="v321-settings__card v321-settings__notifications" aria-labelledby="S-18-notifications">
            <h2 className="v321-settings__eyebrow" id="S-18-notifications">Notifications</h2>
            {NOTIFICATIONS.map(([key, label, help]) => <div className="v321-settings__switch-row" key={key}>
              <div className="v321-settings__switch-label"><b id={`S-18-${key}-label`}>{label}</b><span id={`S-18-${key}-help`}>{help}</span></div>
              <button type="button" role="switch" className="v321-settings__switch" aria-checked={draft[key]} aria-labelledby={`S-18-${key}-label`} aria-describedby={`S-18-${key}-help`} aria-disabled={blocked} aria-busy={pending?.[key] !== undefined || undefined} aria-invalid={state.invalidField === key || undefined} onClick={() => { if (!blocked) onChange({ [key]: !draft[key] }); }}><span aria-hidden="true"/></button>
            </div>)}
          </section>
          <details ref={disclosure} className="v321-settings__disclosure">
            <summary><span>Appearance and language</span><span className="v321-settings__summary-meta">{{ system: 'System', light: 'Light', dark: 'Dark' }[draft.theme]} · {draft.language === 'hi' ? 'हिन्दी' : 'English'}</span><span className="v321-settings__chevron"><SettingsIcon name="back"/></span></summary>
            <div className="v321-settings__disclosure-body">
              <div className="v321-settings__field"><div id="S-18-theme-label">Theme</div><div className="v321-settings__segment" role="group" aria-labelledby="S-18-theme-label">{(['system', 'light', 'dark'] as const).map(theme => <button type="button" key={theme} aria-pressed={draft.theme === theme} aria-disabled={blocked} onClick={() => { if (!blocked && draft.theme !== theme) onChange({ theme }); }}>{theme === 'system' ? 'System' : theme === 'light' ? 'Light' : 'Dark'}</button>)}</div><p className="v321-settings__help">Dark visuals are still being designed; choosing Dark saves the preference for later.</p></div>
              <div className="v321-settings__field"><div id="S-18-language-label">Interface language</div><div className="v321-settings__segment" role="group" aria-labelledby="S-18-language-label"><button type="button" aria-pressed={draft.language === 'en'} aria-disabled={blocked} onClick={() => { if (!blocked && draft.language !== 'en') onChange({ language: 'en' }); }}>English</button><button type="button" aria-pressed={draft.language === 'hi'} aria-disabled="true" aria-describedby="S-18-hindi-help">हिन्दी <span className="v321-settings__soon">Coming soon</span></button></div><p id="S-18-hindi-help" className="v321-settings__sr">Hindi interface is not available yet</p></div>
              {phase === 'invalid' && <div className="v321-settings__invalid" role="alert" tabIndex={-1} ref={error}>The server did not accept this value. Your previous choice is kept. Review {state.invalidField === 'language' ? 'the interface language' : 'the selected preference'} and try again.</div>}
            </div>
          </details>
          <div aria-live="polite" aria-atomic="true">
            {phase === 'saving' && <p className="v321-settings__save-status" role="status">Saving…</p>}
            {phase === 'saved' && <p className="v321-settings__save-status is-saved" role="status"><SettingsIcon name="checkc" size={16}/>Saved to your account.</p>}
          {(phase === 'conflict' || phase === 'network') && <div className={`v321-settings__notice is-${phase}`} role="alert" tabIndex={-1} ref={error}>
            <SettingsIcon name={phase === 'conflict' ? 'refresh' : 'warn'}/><div><b>{phase === 'conflict' ? 'Your settings changed somewhere else.' : 'That change was not saved.'}</b><span>{phase === 'conflict' ? 'Nothing was overwritten. Reload to see the current values, then make the change again.' : 'The switch is back where it was. Check your connection and try again.'}</span><div><button type="button" className="v321-settings__button" onClick={() => phase === 'network' && state.retryPatch ? onChange(state.retryPatch) : onReload()}><SettingsIcon name="refresh" framed/>{phase === 'conflict' ? 'Reload settings' : 'Try again'}</button></div></div>
          </div>}
          </div>
          <nav aria-label="Related"><button type="button" className="v321-settings__button" onClick={() => onNavigate('/s-19')}><SettingsIcon name="guard" framed/>Privacy preferences and requests</button></nav>
        </>}
      </main>
      <aside className="v321-settings__aside" aria-label="Settings context"><div className="v321-settings__card"><div className="v321-settings__eyebrow">How saving works</div><p>{legacyStateCopy ? 'Each save sends the version you started from. If your settings changed elsewhere first, the server refuses the save and nothing is overwritten.' : 'Each change is sent with the version you loaded. If your settings changed elsewhere first, the server refuses it and nothing is overwritten.'}</p></div></aside>
    </div>
    <footer className="v321-settings__footer"><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}

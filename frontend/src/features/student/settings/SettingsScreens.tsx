import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, TextField, DpdpFootnote } from '../components';
import type { ThemeMode } from '../../../hooks/useTheme';
import {
  canSubmitDelete,
  submitRequest,
  DELETE_CONFIRM_PHRASE,
  DEFAULT_NOTIFICATION_PREFS,
  type DataRequestStatus,
} from '../lib/dpdp';

function Toggle({ id, on, onToggle, label }: { id: string; on: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      id={id}
      type="button"
      className="st-toggle"
      aria-pressed={on}
      aria-label={`${label}: ${on ? 'On' : 'Off'}`}
      onClick={onToggle}
    >
      {on ? 'On' : 'Off'}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* S-18 — Notifications & appearance preferences                               */
/* -------------------------------------------------------------------------- */
export function NotificationsSettings({ theme, toggleTheme }: { theme?: ThemeMode; toggleTheme?: () => void }) {
  const nav = useNavigate();
  const [prefs, setPrefs] = useState(DEFAULT_NOTIFICATION_PREFS);
  return (
    <StudentScreen screenId="S-18" className="st-set">
      <div>
        <p className="st-eyebrow">Settings · S3</p>
        <h1 style={{ margin: '4px 0' }}>Notifications &amp; appearance</h1>
      </div>

      <section className="st-panel">
        <h2 className="st-panel__title">Notifications</h2>
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Deadline reminders</div>
            <div className="st-setrow__sub">Exam, moot and internship deadlines.</div>
          </div>
          <Toggle
            id="pref-deadline"
            on={prefs.deadlineReminders}
            label="Deadline reminders"
            onToggle={() => setPrefs((p) => ({ ...p, deadlineReminders: !p.deadlineReminders }))}
          />
        </div>
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Sensitive activity on lock screen</div>
            <div className="st-setrow__sub">Off by default — never shown on a locked device without your say-so.</div>
          </div>
          <Toggle
            id="pref-lock"
            on={prefs.lockscreenSensitiveActivity}
            label="Sensitive activity on lock screen"
            onToggle={() => setPrefs((p) => ({ ...p, lockscreenSensitiveActivity: !p.lockscreenSensitiveActivity }))}
          />
        </div>
      </section>

      <section className="st-panel">
        <h2 className="st-panel__title">Appearance</h2>
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Theme</div>
            <div className="st-setrow__sub">Chambers Dark for focused work · Clean Chambers Light for reading.</div>
          </div>
          <div className="st-seg" role="group" aria-label="Theme">
            <button
              type="button"
              className="st-seg__btn"
              aria-pressed={theme === 'light'}
              onClick={() => theme === 'dark' && toggleTheme?.()}
            >
              Light
            </button>
            <button
              type="button"
              className="st-seg__btn"
              aria-pressed={theme === 'dark'}
              onClick={() => theme === 'light' && toggleTheme?.()}
            >
              Dark
            </button>
          </div>
        </div>
      </section>

      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/s-19')}>
          Privacy &amp; DPDP controls
        </button>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-19 — Privacy & DPDP controls                                              */
/* -------------------------------------------------------------------------- */
export function PrivacySettings() {
  const [exportStatus, setExportStatus] = useState<DataRequestStatus>('idle');
  const [showDelete, setShowDelete] = useState(false);
  const [reauthed, setReauthed] = useState(false);
  const [typed, setTyped] = useState('');
  const [deleteStatus, setDeleteStatus] = useState<DataRequestStatus>('idle');

  const deleteReady = canSubmitDelete({ typedConfirmation: typed, reauthenticated: reauthed });

  function doExport() {
    const req = submitRequest('export', new Date().toISOString());
    setExportStatus(req.status);
  }
  function doDelete() {
    if (!deleteReady) return;
    const req = submitRequest('delete', new Date().toISOString());
    setDeleteStatus(req.status);
  }

  return (
    <StudentScreen screenId="S-19" className="st-set">
      <div>
        <p className="st-eyebrow">Settings &amp; Privacy · S3</p>
        <h1 style={{ margin: '4px 0' }}>Privacy &amp; data (DPDP)</h1>
      </div>

      <section className="st-panel">
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Download my data</div>
            <div className="st-setrow__sub">Export a copy of your account data.</div>
          </div>
          <button type="button" className="btn tap" onClick={doExport}>
            {exportStatus === 'requested' ? 'Requested' : 'Export'}
          </button>
        </div>
        {exportStatus === 'requested' && (
          <div className="ui-banner ui-banner--warn" role="status">
            <span className="ui-banner__mark" aria-hidden>
              i
            </span>
            <span>Export requested — we’ll notify you when your copy is ready.</span>
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

        {showDelete && (
          <div className="st-panel" style={{ marginTop: 'var(--space-3)', borderColor: 'var(--risk)' }}>
            <p className="st-setrow__sub">
              This permanently deletes your account. Re-authenticate and type <strong>{DELETE_CONFIRM_PHRASE}</strong> to confirm.
              You can export your data first.
            </p>
            <button
              type="button"
              className="st-toggle"
              aria-pressed={reauthed}
              onClick={() => setReauthed((v) => !v)}
              style={{ marginBottom: 'var(--space-3)' }}
            >
              {reauthed ? 'Re-authenticated' : 'Re-authenticate'}
            </button>
            <TextField id="del-confirm" label={`Type ${DELETE_CONFIRM_PHRASE} to confirm`} value={typed} onChange={setTyped} />
            <div className="st-actions">
              <button type="button" className="btn btn--primary tap" disabled={!deleteReady} aria-disabled={!deleteReady} onClick={doDelete}>
                Delete my account
              </button>
            </div>
            {deleteStatus === 'requested' && (
              <div className="ui-banner ui-banner--risk" role="alert">
                <span className="ui-banner__mark" aria-hidden>
                  !
                </span>
                <span>Deletion requested. A support ticket has been created to complete it.</span>
              </div>
            )}
          </div>
        )}
      </section>

      <DpdpFootnote>Data-principal rights honoured · retention exceptions need counsel-approved policy</DpdpFootnote>
    </StudentScreen>
  );
}

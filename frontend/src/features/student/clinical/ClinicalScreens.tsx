import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, TextField, SelectField, DpdpFootnote } from '../components';
import { StatusBadge, GuardrailNotice, PrivacyNotice } from '../../../components/ui/primitives';
import {
  validateEntry,
  totalHours,
  hoursByCategory,
  progressPct,
  statusChip,
  verificationSteps,
  exportSummary,
  canExport,
  CATEGORY_LABELS,
  CATEGORY_OPTIONS,
  TARGET_HOURS,
  COMPLIANCE_NOTE,
  EVIDENCE_PRIVACY,
  NON_OFFICIAL_TRANSCRIPT_WARNING,
  EXPORT_AUDIT_NOTE,
  SAMPLE_ENTRIES,
  type ClinicalCategory,
  type LogDraftInput,
} from '../lib/clinical';

function Head({ title, sub }: { title: string; sub?: string }) {
  return (
    <div>
      <p className="st-eyebrow">Clinical hours · S12</p>
      <h1 className="st-h1">{title}</h1>
      {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

/* S-61 — Clinical hours log (default) */
export function ClinicalLog() {
  const nav = useNavigate();
  const [cat, setCat] = useState<'all' | ClinicalCategory>('all');
  const byCat = useMemo(() => hoursByCategory(SAMPLE_ENTRIES), []);
  const total = totalHours(SAMPLE_ENTRIES);
  const pct = progressPct(SAMPLE_ENTRIES);
  const rows = SAMPLE_ENTRIES.filter((e) => cat === 'all' || e.category === cat);
  return (
    <StudentScreen screenId="S-61">
      <div className="st-stack">
        <Head title="Practical Training &amp; Clinical Hours" />
        <GuardrailNotice>{COMPLIANCE_NOTE}</GuardrailNotice>

        <div className="st-tabsrow" role="tablist" aria-label="Category filter">
          <button role="tab" aria-selected={cat === 'all'} className="st-tab" onClick={() => setCat('all')}>All · {SAMPLE_ENTRIES.length}</button>
          {CATEGORY_OPTIONS.map((c) => (
            <button key={c} role="tab" aria-selected={cat === c} className="st-tab" onClick={() => setCat(c)}>
              {CATEGORY_LABELS[c]} · {SAMPLE_ENTRIES.filter((e) => e.category === c).length}
            </button>
          ))}
        </div>

        <section className="st-panel" aria-label="Recent log">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Log · recent</h2>
            <button type="button" className="btn tap" onClick={() => nav('/s-62')}>Add entry</button>
          </div>
          <ul className="st-list">
            {rows.map((e) => {
              const chip = statusChip(e.status);
              return (
                <li className="st-item" key={e.id}>
                  <div>
                    <div>{e.activity}</div>
                    <div className="st-item__meta">
                      {CATEGORY_LABELS[e.category]} · {e.hours} hrs · {e.evidenceName ?? 'no evidence'} · {e.date}
                    </div>
                  </div>
                  <StatusBadge status={chip.kind} label={chip.label} />
                </li>
              );
            })}
          </ul>
        </section>

        <section className="st-panel" aria-label="Progress">
          <h2 className="st-panel__title">Progress</h2>
          <p className="st-item__meta">{total} / {TARGET_HOURS} hrs · Legal-aid {byCat.legal_aid} · Court {byCat.court} · Chamber {byCat.chamber} · Research {byCat.research}</p>
          <div className="st-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Hours progress">
            <div className="st-progress__bar" style={{ width: `${pct}%` }} />
          </div>
          <p className="st-item__meta">{pct}% · {TARGET_HOURS - total} hrs remaining</p>
        </section>

        <DpdpFootnote>{EVIDENCE_PRIVACY}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* S-62 — Add entry & evidence (validation) */
export function ClinicalAdd() {
  const nav = useNavigate();
  const [form, setForm] = useState<LogDraftInput>({ date: '2026-07-04', hours: '6.0', activity: 'DLSA legal-aid camp — Anekal taluk', category: 'legal_aid', verifier: 'prof@nls.ac.in' });
  const [evidence, setEvidence] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savedDraft, setSavedDraft] = useState(false);

  const set = (k: keyof LogDraftInput) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  function saveDraft() {
    // Draft is student-controlled; verifier not required. Offline-draft aware.
    setErrors(validateEntry(form, false));
    setSavedDraft(true);
  }
  function submit() {
    const e = validateEntry(form, true);
    setErrors(e);
    if (Object.keys(e).length === 0) nav('/s-61');
  }

  return (
    <StudentScreen screenId="S-62">
      <div className="st-stack">
        <Head title="Add entry" sub="minimal fields · DPDP" />
        <GuardrailNotice>We record and organise hours; your institution’s approval controls compliance.</GuardrailNotice>

        <section className="st-panel">
          <h2 className="st-panel__title">New entry</h2>
          <TextField id="cl-date" label="Date" value={form.date} onChange={set('date')} type="date" error={errors.date} />
          <TextField id="cl-hours" label="Hours" value={form.hours} onChange={set('hours')} inputMode="numeric" error={errors.hours} />
          <TextField id="cl-activity" label="Activity" value={form.activity} onChange={set('activity')} error={errors.activity} />
          <SelectField
            id="cl-category"
            label="Category"
            value={form.category}
            onChange={set('category')}
            options={CATEGORY_OPTIONS.map((c) => c)}
            error={errors.category}
            help="Institution-configurable: Legal-aid, Court, Chamber, Research."
          />
          <TextField id="cl-verifier" label="Verifier (faculty email)" value={form.verifier} onChange={set('verifier')} type="email" inputMode="email" error={errors.verifier} />
          <TextField id="cl-evidence" label="Evidence (optional for draft)" value={evidence} onChange={setEvidence} placeholder="Attach camp-letter.pdf" help="Shared only with the faculty verifier you choose." />
          {savedDraft && (
            <div className="ui-banner ui-banner--warn" role="status">
              <span className="ui-banner__mark" aria-hidden>i</span>
              <span>Draft saved locally — it will sync when you’re back online. Logs stay yours until you submit.</span>
            </div>
          )}
          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={saveDraft}>Save draft (offline)</button>
            <button type="button" className="btn btn--primary tap" onClick={submit}>Submit for verification</button>
          </div>
        </section>

        <PrivacyNotice>Evidence is shared only with the faculty verifier you choose; drafts stay on your device until synced.</PrivacyNotice>
        <DpdpFootnote>{EVIDENCE_PRIVACY}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

function Workflow({ status }: { status: 'submitted' | 'verified' }) {
  const steps = verificationSteps(status);
  return (
    <ol className="st-list" aria-label="Verification workflow">
      {steps.map((s) => (
        <li className="st-item" key={s.label}>
          <div>
            <div>{s.label}</div>
            <div className="st-item__meta">{s.detail}</div>
          </div>
          <StatusBadge
            status={s.state === 'done' ? 'ok' : s.state === 'now' ? 'warn' : 'info'}
            label={s.state === 'done' ? 'Done' : s.state === 'now' ? 'In review' : 'Pending'}
          />
        </li>
      ))}
    </ol>
  );
}

/* -------------------------------------------------------------------------- */
/* S-63 — Verification pending                                                 */
/* -------------------------------------------------------------------------- */
export function ClinicalPending() {
  const nav = useNavigate();
  return (
    <StudentScreen screenId="S-63" className="st-authwrap">
      <div className="st-card">
        <p className="st-card__kicker">Clinical hours · S12</p>
        <h1 className="st-card__title">Verification workflow · pending</h1>
        <div className="st-metarow">
          <StatusBadge status="warn" label="Awaiting verifier" />
        </div>
        <Workflow status="submitted" />
        <GuardrailNotice>We record and organise hours; your institution’s approval controls compliance.</GuardrailNotice>
        <div className="st-actions st-actions--split">
          <button type="button" className="btn tap" onClick={() => nav('/s-61')}>Back to log</button>
          <button type="button" className="btn tap" onClick={() => nav('/s-64')}>View verified</button>
        </div>
        <DpdpFootnote>{EVIDENCE_PRIVACY}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-64 — Verified & counted                                                   */
/* -------------------------------------------------------------------------- */
export function ClinicalVerified() {
  const nav = useNavigate();
  return (
    <StudentScreen screenId="S-64" className="st-authwrap">
      <div className="st-card">
        <p className="st-card__kicker">Entry verified &amp; counted</p>
        <h1 className="st-card__title">DLSA legal-aid camp</h1>
        <div className="st-metarow">
          <StatusBadge status="ok" label="Verified" />
        </div>
        <p className="st-card__sub">by faculty · 2 Jul · +6 hrs</p>
        <Workflow status="verified" />
        <div className="st-actions st-actions--split">
          <button type="button" className="btn tap" onClick={() => nav('/s-61')}>Back to log</button>
          <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-65')}>Export hours</button>
        </div>
        <DpdpFootnote>{EVIDENCE_PRIVACY}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-65 — Export & requirement progress                                        */
/* -------------------------------------------------------------------------- */
export function ClinicalExport() {
  const nav = useNavigate();
  const s = exportSummary(SAMPLE_ENTRIES);
  const [includeEvidence, setIncludeEvidence] = useState(false);
  const [reauthed, setReauthed] = useState(false);
  const ready = canExport({ includesEvidence: includeEvidence, reauthenticated: reauthed });
  return (
    <StudentScreen screenId="S-65" className="st-set">
      <div className="st-set__head">
        <p className="st-eyebrow">Clinical hours · S12</p>
        <h1 className="st-h1">Export</h1>
      </div>
      <section className="st-panel">
        <h2 className="st-panel__title">Export log</h2>
        <p className="st-item__meta">
          {s.totalHours} / {s.target} hrs · {s.entries} entries · {s.verifiedEntries} verified ({s.verifiedHours} hrs).
        </p>
        <div className="st-progress" role="progressbar" aria-valuenow={s.progressPct} aria-valuemin={0} aria-valuemax={100} aria-label="Requirement progress">
          <div className="st-progress__bar" style={{ width: `${s.progressPct}%` }} />
        </div>
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Include evidence files</div>
            <div className="st-setrow__sub">Requires re-authentication.</div>
          </div>
          <button type="button" className="st-toggle" aria-pressed={includeEvidence} onClick={() => setIncludeEvidence((v) => !v)}>
            {includeEvidence ? 'On' : 'Off'}
          </button>
        </div>
        {includeEvidence && (
          <button type="button" className="st-toggle" aria-pressed={reauthed} onClick={() => setReauthed((v) => !v)} style={{ marginBottom: 'var(--space-3)' }}>
            {reauthed ? 'Re-authenticated' : 'Re-authenticate'}
          </button>
        )}
        <div className="st-actions">
          <button type="button" className="btn tap" disabled={!ready} aria-disabled={!ready}>PDF report</button>
          <button type="button" className="btn tap" disabled={!ready} aria-disabled={!ready}>CSV</button>
          <button type="button" className="btn btn--primary tap" disabled={!ready} aria-disabled={!ready}>Send to institution</button>
        </div>
      </section>
      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/s-61')}>Back to log</button>
      </div>
      <p className="st-dpdp" role="note">{NON_OFFICIAL_TRANSCRIPT_WARNING}</p>
      <DpdpFootnote>{EXPORT_AUDIT_NOTE}</DpdpFootnote>
    </StudentScreen>
  );
}

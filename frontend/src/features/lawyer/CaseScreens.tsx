import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { TextField, SelectField, DpdpFootnote } from '../student/components';
import { StatusBadge, GuardrailNotice, PrivacyNotice, EmptyState, ValidationState } from '../../components/ui/primitives';
import {
  validateIntake, checkConflicts, decideConflict, canProceed,
  EMPTY_INTAKE, MATTER_TYPES, SAMPLE_REGISTER, CONFLICT_GUARDRAIL,
  type IntakeDraft, type ConflictResult,
} from './lib/intake';
import {
  applyClausePolicy, retainerComplete, FEE_CLAUSE_LABELS, RESTRICTED_CLAUSE_NOTICE, NO_GUARANTEE_NOTICE,
  SAMPLE_TEMPLATES, type FeeClause, type SigningStatus,
} from './lib/retainer';
import { initCase, sendWelcome, CASE_TABS, CONSENT_NOTICE, type CaseTab } from './lib/caseWorkspace';
import {
  newInvoice, canIssuePaymentLink, applyPaymentEvent, applyManualVerification, shouldAcknowledge,
  LEDGER_LABELS, GST_REVIEW_NOTICE, PAYMENT_VERIFY_NOTICE, type Invoice, type LedgerType,
} from './lib/billing';
import {
  DOC_STATE_LABELS, checklistProgress, SAMPLE_CHECKLIST, OCR_MACHINE_LABEL, DPDP_ACCESS_NOTICE,
  type DocState,
} from './lib/documents';
import {
  validateMatterFacts, createStubDraftingAssistant, DRAFT_TEMPLATES, SAMPLE_MATTER_FACTS,
  AI_DRAFT_LABEL, type MatterFacts, type DraftVersion,
} from './lib/drafting';
import {
  addComment, requestChanges, clientApprove, revokeReview, reviewAccessible,
  checklistClientApproved, sendReviewLink, CLIENT_APPROVAL_NOTE, REVIEW_STATUS_LABELS,
  type ReviewSession,
} from './lib/clientReview';
import { DraftWorkspaceService, workspaceIdFor } from './lib/draftWorkspace';
import { ReviewWorkspaceService } from './lib/reviewWorkspace';

/** Lightweight lawyer-module screen scaffold (Core has no v3.2 design yet). */
function CaseScreen({ eyebrow, title, sub, children, className }: { eyebrow: string; title: string; sub?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`st-screen ${className ?? 'st-stack'}`.trim()}>
      <div className={className === 'st-authwrap' ? '' : 'st-set__head'}>
        <p className="st-eyebrow">{eyebrow}</p>
        <h1 className="st-h1">{title}</h1>
        {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
      </div>
      {children}
    </section>
  );
}

const chip = (k: 'ok' | 'warn' | 'risk' | 'info') => k;

/* -------------------------------------------------------------------------- */
/* E01 (SAATHI-6) — Intake + conflict check                                    */
/* -------------------------------------------------------------------------- */
export function CaseIntake() {
  const nav = useNavigate();
  const [d, setD] = useState<IntakeDraft>(EMPTY_INTAKE);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ConflictResult | null>(null);
  const [reason, setReason] = useState('');
  const set = (k: keyof IntakeDraft) => (v: string) => setD((s) => ({ ...s, [k]: v }));

  function runCheck() {
    const e = validateIntake(d);
    setErrors(e);
    if (Object.keys(e).length) return;
    const matches = checkConflicts(d, SAMPLE_REGISTER);
    setResult(decideConflict(matches, new Date().toISOString(), 'adv.rao'));
  }
  function override() {
    if (!result) return;
    setResult(decideConflict(result.matches, new Date().toISOString(), 'adv.rao', { authorised: true, reason }));
  }

  return (
    <CaseScreen eyebrow="Case intake · E01" title="New matter — intake & conflict check">
      <section className="st-panel">
        <h2 className="st-panel__title">Parties &amp; matter</h2>
        <TextField id="in-client" label="Client name" value={d.clientName} onChange={set('clientName')} error={errors.clientName} />
        <TextField id="in-opp" label="Opponent name" value={d.opponentName} onChange={set('opponentName')} error={errors.opponentName} />
        <SelectField id="in-matter" label="Matter type" value={d.matterType} onChange={set('matterType')} options={MATTER_TYPES} error={errors.matterType} />
        <TextField id="in-court" label="Court preference" value={d.courtPreference} onChange={set('courtPreference')} />
        <TextField id="in-contact" label="Contact" value={d.contact} onChange={set('contact')} error={errors.contact} />
        <TextField id="in-source" label="Source" value={d.source} onChange={set('source')} help="How this matter reached the firm." />
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={runCheck}>Run conflict check</button>
        </div>
      </section>

      {result && (
        <section className="st-panel" aria-label="Conflict result">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Conflict result</h2>
            <StatusBadge
              status={result.decision === 'clear' ? chip('ok') : result.decision === 'overridden' ? chip('warn') : chip('risk')}
              label={result.decision === 'clear' ? 'Clear' : result.decision === 'overridden' ? 'Overridden' : 'Possible conflict'}
            />
          </div>
          <p className="st-item__meta">Checked by {result.checker} · {result.matches.length} match(es)</p>
          {result.matches.length > 0 && (
            <ul className="st-list">
              {result.matches.map((mm, i) => (
                <li className="st-item" key={i}>
                  <div>
                    <div>{mm.party.name} <span className="st-item__meta">({mm.party.role})</span></div>
                    <div className="st-item__meta">matches “{mm.against}”</div>
                  </div>
                  <StatusBadge status={mm.kind === 'exact' ? chip('risk') : chip('warn')} label={`${mm.kind} ${mm.score}`} />
                </li>
              ))}
            </ul>
          )}
          {result.decision === 'blocked' && (
            <>
              <GuardrailNotice>{CONFLICT_GUARDRAIL}</GuardrailNotice>
              <TextField id="ovr-reason" label="Authorised override reason" value={reason} onChange={setReason} help="Recorded to the immutable audit log." />
              <div className="st-actions st-actions--split">
                <button type="button" className="btn tap" disabled={!reason.trim()} aria-disabled={!reason.trim()} onClick={override}>Authorised override</button>
              </div>
            </>
          )}
          {canProceed(result) && (
            <div className="st-actions">
              <button type="button" className="btn btn--primary tap" onClick={() => nav('/case/retainer')}>Proceed to retainer</button>
            </div>
          )}
        </section>
      )}
      <DpdpFootnote>Conflict result, checker, timestamp and any override reason are written to an immutable audit log</DpdpFootnote>
    </CaseScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* E02 (SAATHI-8) — Retainer & fee agreement                                   */
/* -------------------------------------------------------------------------- */
const ALL_CLAUSES: FeeClause[] = ['fixed', 'hourly', 'retainer', 'contingent', 'success', 'proceeds_sharing', 'outcome_linked'];
export function CaseRetainer() {
  const nav = useNavigate();
  const [template, setTemplate] = useState(SAMPLE_TEMPLATES[0]);
  const [selected, setSelected] = useState<FeeClause[]>(['fixed']);
  const [status, setStatus] = useState<SigningStatus>('draft');
  const policy = useMemo(() => applyClausePolicy(selected), [selected]);

  function toggle(c: FeeClause) {
    setSelected((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]));
  }
  return (
    <CaseScreen eyebrow="Retainer · E02" title="Retainer & fee agreement">
      <section className="st-panel">
        <SelectField id="rt-tpl" label="Firm-approved template" value={template} onChange={setTemplate} options={SAMPLE_TEMPLATES} />
        <span className="st-field__label" id="fee-label">Fee clauses</span>
        <div className="st-chips" role="group" aria-labelledby="fee-label" style={{ marginBottom: 'var(--space-3)' }}>
          {ALL_CLAUSES.map((c) => {
            const blocked = policy.blocked.includes(c);
            return (
              <button key={c} type="button" className="st-chip" aria-pressed={selected.includes(c)} onClick={() => toggle(c)}
                title={blocked ? 'Blocked by default — requires Legal Counsel Review' : undefined}>
                {FEE_CLAUSE_LABELS[c]}
              </button>
            );
          })}
        </div>
        {policy.blocked.length > 0 && (
          <ValidationState message={`Blocked by default: ${policy.blocked.map((c) => FEE_CLAUSE_LABELS[c]).join(', ')}. Requires Legal Counsel Review to enable.`} />
        )}
        <GuardrailNotice>{RESTRICTED_CLAUSE_NOTICE} {NO_GUARANTEE_NOTICE}</GuardrailNotice>
      </section>

      <section className="st-panel">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Agreement preview &amp; signing</h2>
          <StatusBadge status={retainerComplete(status) ? chip('ok') : chip('info')} label={status.replace('_', ' ')} />
        </div>
        <p className="st-item__meta">Preview generated from “{template}” + matter data. Allowed clauses: {policy.allowed.map((c) => FEE_CLAUSE_LABELS[c]).join(', ') || '—'}.</p>
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={() => setStatus('awaiting_signature')}>Send for e-signature</button>
          <button type="button" className="btn tap" onClick={() => setStatus('uploaded')}>Upload signed copy</button>
          <button type="button" className="btn tap" onClick={() => setStatus('signed')}>Mark signed</button>
        </div>
        {retainerComplete(status) && (
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={() => nav('/case/new')}>Unlock case creation</button>
          </div>
        )}
      </section>
      <DpdpFootnote>Signed file hash, signer, time and source are stored; templates are firm/lawyer-owned</DpdpFootnote>
    </CaseScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* E03 (SAATHI-10) — Case workspace                                            */
/* -------------------------------------------------------------------------- */
export function CaseWorkspace() {
  const nav = useNavigate();
  const c = useMemo(() => initCase('Acme Textiles v. Sunrise Builders', new Date().toISOString()), []);
  const [tab, setTab] = useState<CaseTab>('timeline');
  const [optIn, setOptIn] = useState(false);
  const welcome = sendWelcome({ channel: 'whatsapp', optedIn: optIn, loggedAt: optIn ? new Date().toISOString() : null });
  const active = CASE_TABS.find((t) => t.id === tab)!;
  return (
    <CaseScreen eyebrow="Case workspace · E03" title={c.title} sub={`Reference ${c.ref}`}>
      <div className="st-tabsrow" role="tablist" aria-label="Case tabs">
        {CASE_TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className="st-tab" onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      <section className="st-panel" aria-label={active.label}>
        <h2 className="st-panel__title">{active.label}</h2>
        <EmptyState title={active.empty} hint="This tab fills up as the case progresses." />
      </section>
      <section className="st-panel">
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Client communication opt-in</div>
            <div className="st-setrow__sub">{CONSENT_NOTICE}</div>
          </div>
          <button type="button" className="st-toggle" aria-pressed={optIn} onClick={() => setOptIn((v) => !v)}>{optIn ? 'On' : 'Off'}</button>
        </div>
        <StatusBadge status={welcome.outcome === 'sent' ? chip('ok') : chip('info')} label={welcome.outcome === 'sent' ? 'Welcome queued' : 'Welcome held — no consent'} />
      </section>
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={() => nav('/case/advance')}>Request initial advance</button>
      </div>
      <DpdpFootnote>Appears under My Cases &amp; dashboard metrics; welcome comms logged with delivery status only after opt-in</DpdpFootnote>
    </CaseScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* E04 (SAATHI-12) — Advance & receipt                                         */
/* -------------------------------------------------------------------------- */
export function CaseAdvance() {
  const nav = useNavigate();
  const [ledger, setLedger] = useState<LedgerType>('court_fee_advance');
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [seen] = useState<Set<string>>(() => new Set());
  const [status, setStatus] = useState<Invoice['status'] | null>(null);

  function generate() { const inv = newInvoice(5000, ledger); setInvoice(inv); setStatus(inv.status); }
  function verifyServer(ok: boolean) {
    if (!invoice) return;
    const r = applyPaymentEvent(invoice, { invoiceId: invoice.id, providerRef: `evt-${Date.now()}`, serverVerified: ok }, seen);
    setStatus(r.status);
  }
  function manual(ok: boolean) { if (invoice) setStatus(applyManualVerification(invoice, ok)); }

  const statusChipKind = status === 'paid' ? chip('ok') : status === 'failed' ? chip('risk') : status === 'manual_review' ? chip('warn') : chip('info');
  return (
    <CaseScreen eyebrow="Advance · E04" title="Court/process fee advance">
      <section className="st-panel">
        <SelectField id="adv-ledger" label="Ledger type" value={LEDGER_LABELS[ledger]} onChange={(v) => {
          const key = (Object.keys(LEDGER_LABELS) as LedgerType[]).find((k) => LEDGER_LABELS[k] === v);
          if (key) setLedger(key);
        }} options={Object.values(LEDGER_LABELS)} help="Court-fee advance, court-fee proof and process fee are tracked separately." />
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={generate}>Generate invoice</button>
        </div>
      </section>
      {invoice && (
        <section className="st-panel" aria-label="Invoice">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Invoice {invoice.id}</h2>
            <StatusBadge status={statusChipKind} label={String(status).replace('_', ' ')} />
          </div>
          <p className="st-item__meta">₹{invoice.amount.toLocaleString('en-IN')} + GST {invoice.gstPct}% · {LEDGER_LABELS[invoice.ledgerType]}</p>
          <div className="st-actions">
            <button type="button" className="btn tap" disabled={!canIssuePaymentLink(invoice)} aria-disabled={!canIssuePaymentLink(invoice)}>Send payment link</button>
            <button type="button" className="btn tap" onClick={() => verifyServer(true)}>Server-verify payment</button>
            <button type="button" className="btn tap" onClick={() => verifyServer(false)}>Unverified event</button>
            <button type="button" className="btn tap" onClick={() => manual(true)}>Approve manual transfer</button>
          </div>
          {status && shouldAcknowledge(status) && (
            <div className="ui-banner ui-banner--warn" role="status">
              <span className="ui-banner__mark" aria-hidden>✓</span><span>Payment verified — receipt acknowledgement queued.</span>
            </div>
          )}
          <GuardrailNotice>{PAYMENT_VERIFY_NOTICE} {GST_REVIEW_NOTICE}</GuardrailNotice>
        </section>
      )}
      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/case/documents')}>Collect documents</button>
      </div>
      <DpdpFootnote>Client-side success is never trusted; ledger entries are typed and audited</DpdpFootnote>
    </CaseScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* E05 (SAATHI-14) — Document collection & classification                      */
/* -------------------------------------------------------------------------- */
export function CaseDocuments() {
  const nav = useNavigate();
  const [items] = useState(SAMPLE_CHECKLIST);
  const [confirmed, setConfirmed] = useState(false);
  const prog = checklistProgress(items);
  const stateChip = (s: DocState) => (s === 'received' ? chip('ok') : s === 'rejected' ? chip('risk') : s === 'needs_clarification' ? chip('warn') : chip('info'));
  return (
    <CaseScreen eyebrow="Documents · E05" title="Document collection & classification">
      <section className="st-panel">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Checklist</h2>
          <span className="st-metatag">{prog.received}/{prog.total} received</span>
        </div>
        <ul className="st-list">
          {items.map((it) => (
            <li className="st-item" key={it.key}>
              <div>{it.label}</div>
              <StatusBadge status={stateChip(it.state)} label={DOC_STATE_LABELS[it.state]} />
            </li>
          ))}
        </ul>
        <div className="st-actions">
          <button type="button" className="btn tap">Send secure upload link</button>
        </div>
      </section>
      <section className="st-panel">
        <div className="st-panel__head">
          <h2 className="st-panel__title">disputed-agreement.pdf</h2>
          <span className="st-metatag">{OCR_MACHINE_LABEL}</span>
        </div>
        <p className="st-item__meta">OCR: “…agreement dated 12 Mar 2024 between Acme Textiles and Sunrise Builders…”</p>
        <div className="st-actions st-actions--split">
          <StatusBadge status={confirmed ? chip('ok') : chip('warn')} label={confirmed ? 'Tags confirmed' : 'Awaiting lawyer confirmation'} />
          <button type="button" className="btn btn--primary tap" onClick={() => setConfirmed(true)}>Confirm tags</button>
        </div>
      </section>
      <PrivacyNotice>{DPDP_ACCESS_NOTICE}</PrivacyNotice>
      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/case/intake')}>Back to intake</button>
      </div>
      <DpdpFootnote>OCR is assistive only — confirm tags before legal reliance; links expire and carry no PII</DpdpFootnote>
    </CaseScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* E06 (SAATHI-16) — Draft plaint/petition with review controls                */
/* -------------------------------------------------------------------------- */
const DRAFT_CASE_ID = 'LS-CASE-2026-014';
export function CaseDraft() {
  const nav = useNavigate();
  const assistant = useMemo(() => createStubDraftingAssistant(), []);
  const svc = useMemo(() => new DraftWorkspaceService(), []);
  const wsId = workspaceIdFor(DRAFT_CASE_ID);
  const [ws, setWs] = useState(() => svc.create(DRAFT_CASE_ID, 'Acme Textiles v. Sunrise Builders'));
  const [facts, setFacts] = useState<MatterFacts>(SAMPLE_MATTER_FACTS);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [template, setTemplate] = useState(DRAFT_TEMPLATES[0]);
  const [editBody, setEditBody] = useState('');
  const setF = (k: keyof MatterFacts) => (v: string) => setFacts((s) => ({ ...s, [k]: v }));

  // Restore persisted workspace on mount (survives refresh/reload).
  useEffect(() => { setWs(svc.create(DRAFT_CASE_ID, 'Acme Textiles v. Sunrise Builders')); }, [svc]);

  const versions: DraftVersion[] = ws.versions;
  const latest = versions.length ? versions[versions.length - 1] : null;
  const isApproved = (id: string) => ws.approvals.some((a) => a.versionId === id);
  const exportable = svc.canExport(wsId);
  const awaitingApproval = !!latest && latest.aiGenerated && !isApproved(latest.id);

  function generate() {
    const e = validateMatterFacts(facts);
    setErrors(e);
    if (Object.keys(e).length) return;
    const gen = assistant.generate(facts, template);
    setWs(svc.addVersion(wsId, { authorId: 'assoc:1', createdAt: new Date().toISOString(), changeNote: 'AI-assisted draft', body: gen.body, aiGenerated: true, citations: gen.citations }));
  }
  function saveEdit() {
    if (!editBody.trim()) return;
    setWs(svc.addVersion(wsId, { authorId: 'lawyer:rao', createdAt: new Date().toISOString(), changeNote: 'Manual revision', body: editBody, aiGenerated: false }));
    setEditBody('');
  }
  function approve() {
    if (latest) setWs(svc.approve(wsId, latest.id, 'lawyer:rao', new Date().toISOString()));
  }
  function sendForReview() {
    svc.setCurrent(wsId); // hand the actual workspace to E07 (no seed)
    nav('/case/review');
  }

  return (
    <CaseScreen eyebrow="Drafting · E06" title="Draft plaint / petition" sub={`Workspace ${wsId}`}>
      <section className="st-panel">
        <h2 className="st-panel__title">Matter facts</h2>
        <SelectField id="dr-tpl" label="Template" value={template} onChange={setTemplate} options={DRAFT_TEMPLATES} />
        <TextField id="dr-parties" label="Parties" value={facts.parties} onChange={setF('parties')} error={errors.parties} />
        <TextField id="dr-reliefs" label="Reliefs sought" value={facts.reliefs} onChange={setF('reliefs')} error={errors.reliefs} />
        <TextField id="dr-juris" label="Court / jurisdiction" value={facts.jurisdiction} onChange={setF('jurisdiction')} error={errors.jurisdiction} />
        <TextField id="dr-sections" label="Provisions / sections" value={facts.sections} onChange={setF('sections')} />
        <TextField id="dr-issues" label="Issues" value={facts.issues} onChange={setF('issues')} />
        <TextField id="dr-lim" label="Limitation note" value={facts.limitationNote} onChange={setF('limitationNote')} />
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={generate}>Generate AI-assisted draft</button>
        </div>
      </section>

      {latest && (
        <section className="st-panel" aria-label="Current draft">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Draft v{latest.versionNo}</h2>
            <StatusBadge status={latest.aiGenerated ? chip('warn') : chip('info')} label={latest.aiGenerated ? 'AI-generated' : 'Manual'} />
          </div>
          {latest.aiGenerated && <GuardrailNotice>{AI_DRAFT_LABEL}</GuardrailNotice>}
          <pre className="st-pre" aria-label="Draft body">{latest.body}</pre>
          {latest.citations.length > 0 && (
            <ul className="st-list" aria-label="Source citations">
              {latest.citations.map((c) => (
                <li className="st-item" key={c.n}>
                  <div>[{c.n}] {c.title} · {c.ref}</div>
                  <span className="st-metatag">{c.sourceVersion}</span>
                </li>
              ))}
            </ul>
          )}
          <label className="st-field" htmlFor="dr-edit">
            <span className="st-field__label">Revise draft</span>
            <textarea id="dr-edit" className="st-input" rows={3} value={editBody} onChange={(e) => setEditBody(e.target.value)} />
          </label>
          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={saveEdit} disabled={!editBody.trim()} aria-disabled={!editBody.trim()}>Save revision</button>
            <button type="button" className="btn tap" onClick={approve}>Lawyer approve v{latest.versionNo}</button>
          </div>
          {awaitingApproval && <ValidationState message="AI-generated content cannot be exported for filing until a lawyer approves it." />}
        </section>
      )}

      <section className="st-panel">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Version history</h2>
          <span className="st-metatag">{versions.length} version(s)</span>
        </div>
        {versions.length === 0
          ? <EmptyState title="No versions yet" hint="Generate or write a draft to start the append-only history." />
          : (
            <ul className="st-list">
              {versions.map((v) => (
                <li className="st-item" key={v.id}>
                  <div>v{v.versionNo} · {v.changeNote}<div className="st-item__meta">{v.authorId} · {v.id}</div></div>
                  <StatusBadge status={isApproved(v.id) ? chip('ok') : chip('info')} label={isApproved(v.id) ? 'Approved' : 'Draft'} />
                </li>
              ))}
            </ul>
          )}
        <div className="st-actions st-actions--split">
          <button type="button" className="btn tap" disabled={!exportable} aria-disabled={!exportable} title={exportable ? undefined : 'Requires lawyer approval of the latest version'}>Export for filing</button>
          <button type="button" className="btn btn--primary tap" disabled={!exportable} aria-disabled={!exportable} onClick={sendForReview}>Send for client review</button>
        </div>
      </section>
      <DpdpFootnote>Versions persist across refresh; every version and comment is preserved; AI output is a draft, never filing-ready, until a verified lawyer approves the latest version</DpdpFootnote>
    </CaseScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* E07 (SAATHI-18) — Send draft for client review                              */
/* -------------------------------------------------------------------------- */
export function CaseReview() {
  const nav = useNavigate();
  const reviews = useMemo(() => new ReviewWorkspaceService(), []);
  const drafts = useMemo(() => new DraftWorkspaceService(), []);
  const [ctx, setCtx] = useState(() => reviews.resolve());
  const [optIn, setOptIn] = useState(false);
  const [comment, setComment] = useState('');

  // Resolve the current review context from the persisted workspace on mount
  // (retains the session/version binding across refresh; no seed version).
  useEffect(() => { setCtx(reviews.resolve()); }, [reviews]);
  const reload = () => setCtx(reviews.resolve());

  const notify = sendReviewLink({ channel: 'whatsapp', optedIn: optIn, loggedAt: optIn ? new Date().toISOString() : null });

  // E07 refuses to open when no lawyer-approved version exists.
  if (!ctx) {
    return (
      <CaseScreen eyebrow="Client review · E07" title="Send draft for client review">
        <section className="st-panel">
          <EmptyState title="No approved draft to review"
            hint="Approve a draft version in the drafting workspace first, then send it for client review." />
          <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={() => nav('/case/draft')}>Go to drafting</button></div>
        </section>
        <DpdpFootnote>A review can only open for a lawyer-approved draft version</DpdpFootnote>
      </CaseScreen>
    );
  }

  const session = ctx.session;
  const stale = ctx.stale;

  function openLink() {
    const now = Date.now();
    reviews.open(ctx!.workspaceId, `tok-${now}`, now, new Date().toISOString());
    reload();
  }
  function mutate(fn: (s: ReviewSession) => ReviewSession) {
    if (!session) return;
    reviews.update(ctx!.workspaceId, fn(session));
    reload();
  }
  function comm(kind: 'comment' | 'changes') {
    if (!comment.trim()) return;
    const now = Date.now(); const iso = new Date().toISOString();
    mutate((s) => (kind === 'comment' ? addComment(s, ctx!.latestVersionId, comment, now, iso) : requestChanges(s, ctx!.latestVersionId, comment, now, iso)));
    setComment('');
  }
  function approveClient() { mutate((s) => clientApprove(s, ctx!.latestVersionId, Date.now(), new Date().toISOString())); }
  function revoke() { mutate((s) => revokeReview(s, Date.now())); }
  // Create a newer draft version to exercise the stale-version guard.
  function bumpVersion() {
    drafts.addVersion(ctx!.workspaceId, { authorId: 'assoc:1', createdAt: new Date().toISOString(), changeNote: 'Post-review revision', body: 'Revised draft body', aiGenerated: false });
    reload();
  }

  const accessible = session ? reviewAccessible(session, Date.now()) : false;

  return (
    <CaseScreen eyebrow="Client review · E07" title="Send draft for client review" sub={`Bound to approved draft ${ctx.approvedVersionId}`}>
      <section className="st-panel">
        <div className="st-setrow">
          <div>
            <div className="st-setrow__label">Client channel opt-in</div>
            <div className="st-setrow__sub">The review link is only sent when channel consent is logged.</div>
          </div>
          <button type="button" className="st-toggle" aria-pressed={optIn} onClick={() => setOptIn((v) => !v)}>{optIn ? 'On' : 'Off'}</button>
        </div>
        <div className="st-actions st-actions--split">
          <button type="button" className="btn btn--primary tap" onClick={openLink}>Create secure review link</button>
          <StatusBadge status={notify === 'sent' ? chip('ok') : chip('info')} label={notify === 'sent' ? 'Link notification queued' : 'Held — no consent'} />
        </div>
      </section>

      {session ? (
        <section className="st-panel" aria-label="Review session">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Review session</h2>
            <StatusBadge status={session.status === 'approved' ? chip('ok') : session.status === 'revoked' || session.status === 'expired' ? chip('risk') : chip('info')} label={REVIEW_STATUS_LABELS[session.status]} />
          </div>
          <p className="st-item__meta">Link {session.link.url} · bound to {session.draftVersionId} · {accessible ? 'active' : 'not accessible'}</p>
          {stale && <ValidationState message="A newer draft version exists — this review is stale. Comments and approval stay on the original version and will not transfer." />}
          <label className="st-field" htmlFor="rv-comment">
            <span className="st-field__label">Client feedback</span>
            <textarea id="rv-comment" className="st-input" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={() => comm('comment')} disabled={!comment.trim()} aria-disabled={!comment.trim()}>Add comment</button>
            <button type="button" className="btn tap" onClick={() => comm('changes')} disabled={!comment.trim()} aria-disabled={!comment.trim()}>Request changes</button>
            <button type="button" className="btn tap" onClick={approveClient}>Client approve</button>
          </div>
          {session.comments.length > 0 && (
            <ul className="st-list" aria-label="Comments">
              {session.comments.map((c) => (
                <li className="st-item" key={c.id}><div>{c.body}</div><span className="st-metatag">{c.author} · {c.draftVersionId}</span></li>
              ))}
            </ul>
          )}
          {checklistClientApproved(session) && (
            <div className="ui-banner ui-banner--warn" role="status">
              <span className="ui-banner__mark" aria-hidden>✓</span><span>{CLIENT_APPROVAL_NOTE}</span>
            </div>
          )}
          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={bumpVersion}>Create newer draft version (stale test)</button>
            <button type="button" className="btn tap" onClick={revoke}>Revoke link</button>
          </div>
        </section>
      ) : (
        <section className="st-panel"><EmptyState title="No review session" hint="Create a secure link to send the approved draft for client review." /></section>
      )}
      <DpdpFootnote>Client approval records a product acknowledgement only — it is not filing authorisation; links expire, are revocable, and carry no PII</DpdpFootnote>
    </CaseScreen>
  );
}

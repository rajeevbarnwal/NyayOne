import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { hasRole, useAuth } from '../../app/authContext';
import {
  actOnModerationCase,
  createRiskCluster,
  getModerationCase,
  getRiskCluster,
  listModerationCases,
  type ModerationQueueItem,
} from './lib/moderationApi';

const CATEGORY_LABELS: Record<string, string> = {
  unpaid_mismatch: 'Unpaid or stipend mismatch',
  excessive_hours: 'Excessive hours',
  unsafe_environment: 'Unsafe environment',
  harassment: 'Harassment',
  discrimination: 'Discrimination',
  misleading_work: 'Misleading work',
  non_response: 'Organisation stopped responding',
  certificate_withheld: 'Certificate withheld',
  stipend_delay_exploitative: 'Stipend delay or exploitative work',
  positive_experience: 'Positive experience',
};

export function ModerationGuard({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const allowed = hasRole(auth, 'moderator') || hasRole(auth, 'admin');
  if (allowed) return <>{children}</>;
  return (
    <main className="mod-shell" data-testid="moderation-denied">
      <p className="mod-eyebrow">Restricted · internal workspace</p>
      <h1>Moderator sign-in required</h1>
      <div className="mod-notice" role="alert">
        No private report data is loaded until a moderator or administrator session is verified.
      </div>
    </main>
  );
}

function Header({ title, intro }: { title: string; intro: string }) {
  return (
    <header className="mod-header">
      <div><p className="mod-eyebrow">Internal · privacy-safe moderation</p><h1>{title}</h1><p>{intro}</p></div>
      <div className="mod-kill" role="status"><strong>Public labels off</strong><span>Internal decisions cannot publish an organisation label.</span></div>
    </header>
  );
}

function ErrorNotice({ error }: { error: unknown }) {
  const code = error instanceof Error ? error.message : 'moderation_unavailable';
  return <div className="mod-error" role="alert">The request failed safely: {code.replace(/_/g, ' ')}.</div>;
}

function CaseRow({ item, selected, onSelect }: { item: ModerationQueueItem; selected: boolean; onSelect: (checked: boolean) => void }) {
  return (
    <article className="mod-card">
      <div className="mod-card__top"><div><span className={`mod-state mod-state--${item.state}`}>{item.state.replace(/_/g, ' ')}</span><h2>{item.organisationName}</h2></div>
        {item.state === 'approved_aggregate_only' && <label className="mod-select"><input type="checkbox" checked={selected} onChange={(event) => onSelect(event.target.checked)} />Include in internal cluster</label>}
      </div>
      <p className="mod-tags">{item.categories.map((value) => CATEGORY_LABELS[value] ?? value).join(' · ')}</p>
      <dl className="mod-meta"><div><dt>Period</dt><dd>{item.experienceStartDate ?? '—'} to {item.experienceEndDate ?? '—'}</dd></div><div><dt>Clean evidence</dt><dd>{item.evidenceClean} of {item.evidenceTotal}</dd></div><div><dt>Version</dt><dd>{item.version}</dd></div></dl>
      <Link className="mod-button mod-button--quiet" to={`/moderation/internship-reports/${item.reportId}`}>Review private case</Link>
    </article>
  );
}

export function ModerationQueueScreen() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string[]>([]);
  const [category, setCategory] = useState('unsafe_environment');
  const query = useQuery({ queryKey: ['moderation-cases'], queryFn: () => listModerationCases(), retry: false });
  const cluster = useMutation({ mutationFn: () => createRiskCluster(selected, category), onSuccess: (item) => navigate(`/moderation/risk-clusters/${item.id}`) });
  const items = query.data ?? [];
  const toggle = (id: string, checked: boolean) => setSelected((current) => checked ? [...new Set([...current, id])] : current.filter((value) => value !== id));
  return (
    <main className="mod-shell" data-screen="MOD-01">
      <Header title="Internship report queue" intro="Review submitted reports without exposing reporter identity. Claim ownership before recording a decision." />
      <section className="mod-toolbar" aria-label="Moderation queue summary"><strong>{items.length} cases</strong><span>{items.filter((item) => item.state === 'pending').length} awaiting claim</span><span>{items.filter((item) => item.state === 'approved_aggregate_only').length} aggregate-approved</span></section>
      {query.isPending && <p role="status">Loading the private queue…</p>}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.isSuccess && items.length === 0 && (
        <section className="mod-notice" role="status" data-testid="moderation-empty">
          <strong>No reports need moderation.</strong>
          <span>The queue is clear. New private reports will appear here after submission.</span>
        </section>
      )}
      <div className="mod-grid">{items.map((item) => <CaseRow key={item.reportId} item={item} selected={selected.includes(item.reportId)} onSelect={(checked) => toggle(item.reportId, checked)} />)}</div>
      <section className="mod-cluster" aria-labelledby="mod-cluster-title">
        <div><p className="mod-eyebrow">Internal aggregate preview</p><h2 id="mod-cluster-title">Compare corroborating signals</h2></div>
        <p>Organisation alone is never enough. Every selected report must agree on organisation, category and the rolling time window, with distinct reporters counted server-side.</p>
        <label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}>{Object.entries(CATEGORY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button className="mod-button" type="button" disabled={selected.length < 2 || cluster.isPending} onClick={() => cluster.mutate()}>Build privacy-safe preview ({selected.length})</button>
        {cluster.isError && <ErrorNotice error={cluster.error} />}
      </section>
    </main>
  );
}

export function ModerationCaseScreen() {
  const { reportId = '' } = useParams();
  const client = useQueryClient();
  const [reason, setReason] = useState('Reviewed against the approved internal moderation policy.');
  const [pendingAction, setPendingAction] = useState<'needs_information' | 'approve_aggregate_only' | 'reject' | null>(null);
  const confirmationTrigger = useRef<HTMLButtonElement | null>(null);
  const query = useQuery({ queryKey: ['moderation-case', reportId], queryFn: () => getModerationCase(reportId), enabled: Boolean(reportId), retry: false });
  const action = useMutation({ mutationFn: (value: 'claim' | 'needs_information' | 'approve_aggregate_only' | 'reject') => actOnModerationCase(reportId, query.data!.version, value, value === 'claim' ? 'Beginning independent internal review.' : reason), onSuccess: async () => { await query.refetch(); await client.invalidateQueries({ queryKey: ['moderation-cases'] }); } });
  const item = query.data;
  const terminal = useMemo(() => item && ['approved_aggregate_only', 'rejected', 'needs_information'].includes(item.state), [item]);
  const actionLabels = {
    needs_information: 'request more information',
    approve_aggregate_only: 'approve aggregate-only use',
    reject: 'reject this report',
  } as const;
  useEffect(() => {
    if (!pendingAction) confirmationTrigger.current?.focus();
  }, [pendingAction]);
  const openConfirmation = (
    value: 'needs_information' | 'approve_aggregate_only' | 'reject',
    trigger: HTMLButtonElement,
  ) => {
    confirmationTrigger.current = trigger;
    setPendingAction(value);
  };
  const closeConfirmation = () => setPendingAction(null);
  const handleConfirmationKeys = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeConfirmation();
      return;
    }
    if (event.key !== 'Tab') return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled)')];
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <main className="mod-shell" data-screen="MOD-02">
      <div
        className="mod-case-background"
        data-moderation-background
        inert={pendingAction ? true : undefined}
        aria-hidden={pendingAction ? 'true' : undefined}
      >
        <Link className="mod-back" to="/moderation/internship-reports">← Queue</Link>
        <Header title="Private report review" intro="The narrative is visible here only for internal moderation. Reporter identity is not part of this projection." />
        {query.isPending && <p role="status">Loading the case…</p>}{query.isError && <ErrorNotice error={query.error} />}
        {item && <><section className="mod-detail"><div><span className={`mod-state mod-state--${item.state}`}>{item.state.replace(/_/g, ' ')}</span><h2>{item.organisationName}</h2><p>{item.listingApplicationRef}</p></div><dl className="mod-meta"><div><dt>Privacy</dt><dd>{item.privacyMode.replace(/_/g, ' ')}</dd></div><div><dt>Evidence scans</dt><dd>{item.scanStates.length ? item.scanStates.join(', ') : 'No files'}</dd></div><div><dt>Version</dt><dd>{item.version}</dd></div></dl></section>
          <section className="mod-narrative" aria-labelledby="mod-narrative-title"><h2 id="mod-narrative-title">Factual account</h2><p>{item.narrative}</p></section>
          {!terminal && <section className="mod-actions" aria-labelledby="mod-actions-title"><h2 id="mod-actions-title">Record an auditable action</h2>{item.state === 'pending' ? <button className="mod-button" type="button" disabled={action.isPending} onClick={() => action.mutate('claim')}>Claim this case</button> : <><label>Decision rationale (10–1,000 characters)<textarea value={reason} minLength={10} maxLength={1000} onChange={(event) => setReason(event.target.value)} /></label><div className="mod-action-row"><button className="mod-button mod-button--quiet" type="button" disabled={reason.trim().length < 10 || action.isPending} onClick={(event) => openConfirmation('needs_information', event.currentTarget)}>Request information</button><button className="mod-button" type="button" disabled={reason.trim().length < 10 || action.isPending} onClick={(event) => openConfirmation('approve_aggregate_only', event.currentTarget)}>Approve aggregate-only</button><button className="mod-button mod-button--danger" type="button" disabled={reason.trim().length < 10 || action.isPending} onClick={(event) => openConfirmation('reject', event.currentTarget)}>Reject report</button></div></>}{action.isError && <ErrorNotice error={action.error} />}</section>}</>}
      </div>
      {pendingAction && (
        <div className="mod-dialog-backdrop" role="presentation">
          <section className="mod-dialog" role="alertdialog" aria-modal="true" aria-labelledby="mod-confirm-title" aria-describedby="mod-confirm-copy" onKeyDown={handleConfirmationKeys}>
            <h2 id="mod-confirm-title">Confirm moderation action</h2>
            <p id="mod-confirm-copy">You are about to {actionLabels[pendingAction]}. The rationale and actor will be written to the append-only audit trail.</p>
            <div className="mod-action-row">
              <button className="mod-button mod-button--quiet" type="button" autoFocus onClick={closeConfirmation}>Go back</button>
              <button className="mod-button" type="button" disabled={action.isPending} onClick={() => {
                const confirmed = pendingAction;
                setPendingAction(null);
                action.mutate(confirmed);
              }}>Confirm {actionLabels[pendingAction]}</button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export function RiskClusterScreen() {
  const { clusterId = '' } = useParams();
  const query = useQuery({ queryKey: ['risk-cluster', clusterId], queryFn: () => getRiskCluster(clusterId), enabled: Boolean(clusterId), retry: false });
  const cluster = query.data;
  return (
    <main className="mod-shell" data-screen="MOD-03"><Link className="mod-back" to="/moderation/internship-reports">← Queue</Link><Header title="Privacy-safe risk preview" intro="This internal candidate is not a public label. Production publication remains fail-closed until its external approval gate is complete." />
      {query.isPending && <p role="status">Loading the aggregate preview…</p>}{query.isError && <ErrorNotice error={query.error} />}
      {cluster && <section className="mod-risk"><span className={`mod-state mod-state--${cluster.state}`}>{cluster.state}</span><h2>{cluster.neutralLabel}</h2><p>{cluster.organisationName} · {CATEGORY_LABELS[cluster.category] ?? cluster.category}</p><div className="mod-risk__numbers"><div><strong>{cluster.reportCount}</strong><span>source reports</span></div><div><strong>{cluster.distinctReporterCount}</strong><span>distinct reporters</span></div><div><strong>{cluster.publicCount ?? 'Suppressed'}</strong><span>public count</span></div></div><ul className="mod-checks"><li data-pass={cluster.thresholdMet}>Minimum distinct-report threshold</li><li data-pass={cluster.moderatorApproved}>Moderator approval</li><li data-pass={cluster.safetyLegalApproved}>Safety or legal approval</li><li data-pass="false">Public publication kill-switch: OFF</li></ul><p className="mod-notice"><strong>Not public.</strong> SAATHI-279 implementation and Product-approved safe defaults are complete. In production, <code>publication_ready</code> remains false until SAATHI-452 records Counsel/Policy and Security/Privacy approval and all target-runtime gates pass.</p></section>}
    </main>
  );
}

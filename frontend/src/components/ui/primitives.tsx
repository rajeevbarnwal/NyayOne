import type { ReactNode } from 'react';

/**
 * Reusable UI state + guardrail primitives (SAATHI-345). Token-driven (Option J),
 * 44px targets on actions, semantic status never color-only (icon/label + colour),
 * visible focus inherited from global.css. No external assets.
 */

type Status = 'ok' | 'warn' | 'risk' | 'info';
const STATUS_MARK: Record<Status, string> = { ok: '✓', warn: '!', risk: '✕', info: 'i' };

// --- generic state block ---
function StateBlock({
  role = 'status',
  eyebrow,
  title,
  children,
  action,
}: {
  role?: string;
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="ui-state" role={role}>
      {eyebrow && <p className="ui-state__eyebrow">{eyebrow}</p>}
      <p className="ui-state__title">{title}</p>
      {children && <div className="ui-state__body">{children}</div>}
      {action && <div className="ui-state__action">{action}</div>}
    </div>
  );
}

export function EmptyState({ title = 'Nothing here yet', hint, action }: { title?: string; hint?: string; action?: ReactNode }) {
  return <StateBlock eyebrow="Empty" title={title} action={action}>{hint}</StateBlock>;
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="ui-state" role="status" aria-live="polite" aria-busy="true">
      <span className="ui-spinner" aria-hidden /> <span>{label}</span>
    </div>
  );
}

export function ErrorState({ title = 'Something went wrong', detail, onRetry }: { title?: string; detail?: string; onRetry?: () => void }) {
  return (
    <StateBlock role="alert" eyebrow="Error" title={title}
      action={onRetry ? <button type="button" className="btn tap" onClick={onRetry}>Retry</button> : undefined}>
      {detail}
    </StateBlock>
  );
}

export function ValidationState({ message, fieldId }: { message: string; fieldId?: string }) {
  return (
    <p className="ui-validation" role="alert" id={fieldId ? `${fieldId}-error` : undefined}>
      <span className="ui-validation__mark" aria-hidden>!</span> {message}
    </p>
  );
}

export function RestrictedState({ reason = 'You do not have access to this area.' }: { reason?: string }) {
  return <StateBlock role="alert" title="Access restricted">{reason}</StateBlock>;
}

export function PendingVerificationState({ kind = 'student' }: { kind?: 'student' | 'lawyer' }) {
  return (
    <StateBlock eyebrow="Pending" title={`${kind === 'lawyer' ? 'Lawyer' : 'Student'} verification pending`}>
      Some features unlock once verification is complete.
    </StateBlock>
  );
}

export function ModerationBanner({ state, note }: { state: 'pending_review' | 'hidden' | 'removed' | 'escalated'; note?: string }) {
  const map = { pending_review: 'warn', hidden: 'warn', removed: 'risk', escalated: 'risk' } as const;
  return (
    <div className={`ui-banner ui-banner--${map[state]}`} role="status">
      <span className="ui-banner__mark" aria-hidden>{STATUS_MARK[map[state]]}</span>
      <span>Moderation: {state.replace('_', ' ')}{note ? ` — ${note}` : ''}</span>
    </div>
  );
}

export function StatusBadge({ status, label }: { status: Status; label: string }) {
  return (
    <span className={`status status--${status}`}>
      <span className="ui-badge__mark" aria-hidden>{STATUS_MARK[status]}</span>{label}
    </span>
  );
}

export function PrivacyNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="ui-notice ui-notice--info" role="note">
      <strong>Privacy.</strong> {children ?? 'We collect only what is needed and follow DPDP data-minimisation.'}
    </div>
  );
}

export function GuardrailNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="ui-notice ui-notice--warn" role="note">
      <strong>Study &amp; research assistance only, not legal advice.</strong>{' '}
      {children ?? 'Verify every citation against the official source before you rely on it.'}
    </div>
  );
}

export interface Citation {
  n: number;
  title: string;
  ref?: string;
  url?: string;
}
export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return <EmptyState title="No sources cited" />;
  return (
    <ol className="ui-citations" aria-label="Sources">
      {citations.map((c) => (
        <li key={c.n} className="ui-citations__item">
          <span className="ui-citations__n" aria-hidden>{c.n}</span>
          <span>
            <span className="ui-citations__title">{c.title}</span>
            {c.ref && <span className="ui-citations__ref"> · {c.ref}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function SourceVersionPill({ source, updated }: { source: string; updated?: string }) {
  return (
    <span className="ui-srcpill" title="Verify official notification">
      <span className="ui-srcpill__dot" aria-hidden />
      {source}{updated ? ` · ${updated}` : ''}
    </span>
  );
}

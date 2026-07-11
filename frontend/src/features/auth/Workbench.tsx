import { useState, type ReactNode } from 'react';

/**
 * Verification Workbench shell (Option B v3), rebuilt in the existing React
 * architecture + Option J tokens. Three panels on desktop (rail | action |
 * ledger); on < 1024px the rail becomes step chips and the ledger collapses
 * behind a toggle. Not a copy of the prototype HTML.
 */
export interface WorkbenchStep {
  readonly key: string;
  readonly label: string;
  readonly state: 'done' | 'active' | 'todo';
}
export interface Requirement {
  readonly label: string;
  readonly done: boolean;
}
export interface LedgerEntry {
  readonly label: string;
  readonly meta: string;
}

export function Workbench({
  brand,
  role,
  steps,
  requirements,
  ledger,
  policy,
  children,
}: {
  brand: string;
  role: string;
  steps: readonly WorkbenchStep[];
  requirements: readonly Requirement[];
  ledger: readonly LedgerEntry[];
  policy?: ReactNode;
  children: ReactNode;
}) {
  const [ledgerOpen, setLedgerOpen] = useState(false);
  return (
    <div className={`wb ${ledgerOpen ? 'wb--ledger-open' : ''}`.trim()}>
      <nav className="wb__panel wb__rail" aria-label="Verification flow">
        <p className="wb__brand">{brand}</p>
        <p className="wb__role">{role}</p>
        <ol className="wb__steps">
          {steps.map((s) => (
            <li key={s.key} className="wb__step" data-state={s.state}
              aria-current={s.state === 'active' ? 'step' : undefined}>
              <span className="wb__step__dot" aria-hidden />
              <span>{s.label}</span>
              {s.state === 'done' && <span className="sr-only"> (completed)</span>}
            </li>
          ))}
        </ol>
        <button type="button" className="btn tap wb__toggle" style={{ marginTop: 'var(--space-3)' }}
          aria-expanded={ledgerOpen} onClick={() => setLedgerOpen((v) => !v)}>
          {ledgerOpen ? 'Hide progress & ledger' : 'Show progress & ledger'}
        </button>
      </nav>

      <main className="wb__panel wb__main" aria-live="polite">
        {children}
      </main>

      <aside className="wb__panel wb__ledger" aria-label="Requirements and verification ledger">
        <div className="wb__ledgerhead">
          <span className="wb__ledgertitle">Requirements</span>
        </div>
        <ul className="wb__req">
          {requirements.map((r, i) => (
            <li key={i} data-done={r.done}>
              <span className="wb__req__mark" aria-hidden>{r.done ? '✓' : '•'}</span>
              <span>{r.label}{r.done && <span className="sr-only"> (done)</span>}</span>
            </li>
          ))}
        </ul>
        <div className="wb__ledgerhead">
          <span className="wb__ledgertitle">Verification ledger &amp; audit</span>
        </div>
        {ledger.length === 0 ? (
          <p className="wb__ledger__meta">No entries yet.</p>
        ) : (
          <div>
            {ledger.map((e, i) => (
              <div className="wb__ledger__entry" key={i}>
                <div>{e.label}</div>
                <div className="wb__ledger__meta">{e.meta}</div>
              </div>
            ))}
          </div>
        )}
        {policy && <div style={{ marginTop: 'var(--space-3)' }}>{policy}</div>}
      </aside>
    </div>
  );
}

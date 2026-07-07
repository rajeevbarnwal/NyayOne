import type { ReactNode } from 'react';
import { TraceabilityBanner } from '../../components/shell/TraceabilityBanner';

/**
 * Shared building blocks for the student screens (S-01…S-19). Token-driven,
 * accessible (labels tied to inputs, 44px targets, invalid state announced),
 * no external assets. Each screen wraps its content in <StudentScreen> so the
 * reviewer traceability banner and canonical screen ID stay consistent.
 */

export function StudentScreen({
  screenId,
  className,
  children,
}: {
  screenId: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`st-screen ${className ?? ''}`.trim()} data-screen={screenId}>
      <TraceabilityBanner screenId={screenId} />
      {children}
    </section>
  );
}

export function AuthCard({
  screenId,
  kicker,
  title,
  sub,
  children,
}: {
  screenId: string;
  kicker?: string;
  title: string;
  sub?: string;
  children: ReactNode;
}) {
  return (
    <StudentScreen screenId={screenId} className="st-authwrap">
      <div className="st-card">
        {kicker && <p className="st-card__kicker">{kicker}</p>}
        <h1 className="st-card__title">{title}</h1>
        {sub && <p className="st-card__sub">{sub}</p>}
        {children}
      </div>
    </StudentScreen>
  );
}

export function TextField({
  id,
  label,
  value,
  onChange,
  type = 'text',
  help,
  error,
  optional,
  placeholder,
  inputMode,
  autoComplete,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  help?: string;
  error?: string;
  optional?: string;
  placeholder?: string;
  inputMode?: 'text' | 'numeric' | 'tel' | 'email';
  autoComplete?: string;
}) {
  const errId = error ? `${id}-error` : undefined;
  const helpId = help ? `${id}-help` : undefined;
  return (
    <label className="st-field" htmlFor={id}>
      <span className="st-field__label">
        {label}
        {optional && <span className="st-field__opt"> · {optional}</span>}
      </span>
      <input
        id={id}
        className="st-input"
        type={type}
        value={value}
        placeholder={placeholder}
        inputMode={inputMode}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={[errId, helpId].filter(Boolean).join(' ') || undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {error ? (
        <span className="ui-validation" role="alert" id={errId}>
          <span className="ui-validation__mark" aria-hidden>
            !
          </span>{' '}
          {error}
        </span>
      ) : (
        help && (
          <span className="st-field__help" id={helpId}>
            {help}
          </span>
        )
      )}
    </label>
  );
}

export function SelectField({
  id,
  label,
  value,
  onChange,
  options,
  error,
  help,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
  error?: string;
  help?: string;
}) {
  const errId = error ? `${id}-error` : undefined;
  return (
    <label className="st-field" htmlFor={id}>
      <span className="st-field__label">{label}</span>
      <select
        id={id}
        className="st-select"
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={errId}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Select…</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      {error ? (
        <span className="ui-validation" role="alert" id={errId}>
          <span className="ui-validation__mark" aria-hidden>
            !
          </span>{' '}
          {error}
        </span>
      ) : (
        help && <span className="st-field__help">{help}</span>
      )}
    </label>
  );
}

export function Checkbox({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="st-field" htmlFor={id} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ width: 20, height: 20, marginTop: 2, flex: 'none' }}
      />
      <span className="st-setrow__sub" style={{ color: 'var(--text2)' }}>
        {label}
      </span>
    </label>
  );
}

export function DpdpFootnote({ children }: { children: ReactNode }) {
  return (
    <p className="st-dpdp" role="note">
      {children} · DPDP Act, 2023.
    </p>
  );
}

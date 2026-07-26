import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
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
  meta,
  brand,
  children,
}: {
  screenId: string;
  kicker?: string;
  title: string;
  sub?: string;
  /** Product-facing metadata / state chips shown under the kicker (e.g. status pill). */
  meta?: ReactNode;
  /** Brand-lockup screens (S-01/S-03) use a larger title. */
  brand?: boolean;
  children: ReactNode;
}) {
  return (
    <StudentScreen screenId={screenId} className="st-authwrap">
      <div className={`st-card ${brand ? 'st-card--brand' : ''}`.trim()}>
        {kicker && <p className="st-card__kicker">{kicker}</p>}
        <h1 className="st-card__title">{title}</h1>
        {meta && <div className="st-metarow">{meta}</div>}
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
  max,
  maxLength,
  labelAddon,
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
  /** Usability constraint for date inputs (YYYY-MM-DD). Domain validator stays authoritative. */
  max?: string;
  maxLength?: number;
  /** Optional adornment rendered beside the label (e.g. an info tooltip). */
  labelAddon?: ReactNode;
}) {
  const errId = error ? `${id}-error` : undefined;
  const helpId = help ? `${id}-help` : undefined;
  return (
    <label className="st-field" htmlFor={id}>
      <span className="st-field__label">
        {label}
        {optional && <span className="st-field__opt"> · {optional}</span>}
        {labelAddon}
      </span>
      <input
        id={id}
        className="st-input"
        type={type}
        value={value}
        placeholder={placeholder}
        inputMode={inputMode}
        autoComplete={autoComplete}
        max={max}
        maxLength={maxLength}
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
  // The whole row is a >=44x44 clickable label. The native checkbox stays a real
  // <input> (semantics + keyboard preserved) stretched over a 44x44 hit area; a
  // compact visual box shows the state and carries the focus ring.
  return (
    <label className="st-check" htmlFor={id}>
      <span className="st-check__control">
        <input
          id={id}
          className="st-check__input"
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="st-check__box" aria-hidden />
      </span>
      <span className="st-check__text">{label}</span>
    </label>
  );
}

/**
 * Accessible information control (SAATHI-388 / SAATHI-421). A real 44×44 button
 * that reveals `text` in a tooltip/popover via keyboard focus, pointer hover and
 * click; exposes expanded state; dismisses on Escape and focus/pointer exit. The
 * legal text is available here instead of as static helper text below the form.
 */
export function InfoTooltip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLSpanElement>(null);
  const panelId = useId();

  // Collision-aware placement: fixed to the viewport (escapes card/legend
  // coordinates), horizontally clamped to [16, viewport - width - 16], and
  // flipped above the trigger when there isn't room below. Recomputed on open,
  // resize and scroll so it never lands offscreen or over the name inputs/CTA.
  const reposition = useCallback(() => {
    const btn = btnRef.current;
    const panel = panelRef.current;
    if (!btn || !panel) return;
    const b = btn.getBoundingClientRect();
    const pw = panel.offsetWidth || 280;
    const ph = panel.offsetHeight || 96;
    const margin = 16;
    const left = Math.max(margin, Math.min(b.left, window.innerWidth - pw - margin));
    const placeAbove = window.innerHeight - b.bottom < ph + margin;
    const top = placeAbove ? Math.max(margin, b.top - ph - 8) : b.bottom + 8;
    setPos({ top, left });
  }, []);

  useLayoutEffect(() => { if (open) reposition(); }, [open, reposition]);
  useEffect(() => {
    if (!open) return undefined;
    const onMove = () => reposition();
    window.addEventListener('resize', onMove);
    window.addEventListener('scroll', onMove, true);
    return () => {
      window.removeEventListener('resize', onMove);
      window.removeEventListener('scroll', onMove, true);
    };
  }, [open, reposition]);

  const panelStyle: CSSProperties = {
    position: 'fixed',
    top: pos ? pos.top : -9999,
    left: pos ? pos.left : -9999,
    right: 'auto',
    maxWidth: 'min(280px, calc(100vw - 32px))',
  };

  return (
    <span
      className="st-info"
      style={{ display: 'inline-flex' }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={btnRef}
        type="button"
        className="st-info__btn tap"
        style={{ minWidth: 44, minHeight: 44, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        aria-label={label}
        aria-expanded={open}
        aria-controls={panelId}
        aria-describedby={open ? panelId : undefined}
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false);
        }}
      >
        <span aria-hidden>ⓘ</span>
      </button>
      <span
        ref={panelRef}
        id={panelId}
        role="tooltip"
        className={`st-info__panel${open ? ' st-info__panel--open' : ''}`}
        style={panelStyle}
        hidden={!open}
      >
        {text}
      </span>
    </span>
  );
}

export function DpdpFootnote({ children }: { children: ReactNode }) {
  return (
    <p className="st-dpdp" role="note">
      {children} · DPDP Act, 2023.
    </p>
  );
}

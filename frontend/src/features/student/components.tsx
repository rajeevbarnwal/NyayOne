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
  options: ReadonlyArray<string | { value: string; label: string }>;
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
        {options.map((raw) => {
          const o = typeof raw === 'string' ? { value: raw, label: raw } : raw;
          return (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          );
        })}
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

  // Collision-aware placement (fixed to the viewport, so it escapes card/legend
  // coordinates). We generate above/below candidates, clamp each horizontally to
  // a 16px margin, and REJECT any candidate whose rectangle intersects the form
  // inputs or the primary CTA (not just "inside viewport"). On ≤768 we prefer the
  // above-trigger candidate. If neither side is collision-free we fall back to a
  // centered, non-blocking placement rather than cover the form. Recomputed on
  // open, resize and scroll.
  const reposition = useCallback(() => {
    const btn = btnRef.current;
    const panel = panelRef.current;
    if (!btn || !panel) return;
    const b = btn.getBoundingClientRect();
    const pw = panel.offsetWidth || 280;
    const ph = panel.offsetHeight || 96;
    const m = 16;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const left = Math.max(m, Math.min(b.left, vw - pw - m));

    // Elements the panel must not cover: form fields + primary buttons nearby.
    const avoid = Array.from(
      document.querySelectorAll('input, select, .btn, button[type="button"].btn, .btn--primary'),
    ).filter((el) => el !== btn).map((el) => el.getBoundingClientRect());
    const intersects = (top: number) => {
      const r = { left, right: left + pw, top, bottom: top + ph };
      if (r.top < m || r.bottom > vh - m || r.left < m || r.right > vw - m) return true;
      return avoid.some((a) => !(r.right <= a.left || r.left >= a.right || r.bottom <= a.top || r.top >= a.bottom));
    };

    const aboveTop = b.top - ph - 8;
    const belowTop = b.bottom + 8;
    const order = vw <= 768 ? [aboveTop, belowTop] : [belowTop, aboveTop];
    const chosen = order.find((t) => !intersects(t));
    if (chosen !== undefined) {
      setPos({ top: chosen, left });
      return;
    }
    // Fallback: centered near the top, horizontally clamped — never over the form.
    setPos({ top: Math.max(m, Math.min(b.top - ph - 8, m)), left: Math.max(m, Math.min((vw - pw) / 2, vw - pw - m)) });
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
        // A pointer click is preceded by mouseenter on desktop. Setting open
        // explicitly avoids the old open-then-toggle-closed race.
        onClick={() => setOpen(true)}
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

export interface CountryOption {
  code: string;
  flag: string;
  name: string;
}

export const COUNTRY_CODES: CountryOption[] = [
  { code: '+91', flag: '🇮🇳', name: 'India' },
  { code: '+1', flag: '🇺🇸', name: 'USA/Canada' },
  { code: '+44', flag: '🇬🇧', name: 'UK' },
  { code: '+61', flag: '🇦🇺', name: 'Australia' },
  { code: '+65', flag: '🇸🇬', name: 'Singapore' },
  { code: '+971', flag: '🇦🇪', name: 'UAE' },
  { code: '+977', flag: '🇳🇵', name: 'Nepal' },
];

/** Auto-sanitizes pasted numbers: strips non-digits, leading +91/91, or leading 0 */
export function normalizeIndianMobile(raw: string, countryCode = '+91'): string {
  const digits = raw.replace(/\D/g, '');
  if (countryCode === '+91') {
    if (digits.length === 12 && digits.startsWith('91')) {
      return digits.slice(2);
    }
    if (digits.length === 11 && digits.startsWith('0')) {
      return digits.slice(1);
    }
  }
  return digits;
}

export function CountryCodeSelect({
  value,
  onChange,
  id = 'country-code-select',
}: {
  value: string;
  onChange: (code: string) => void;
  id?: string;
}) {
  return (
    <div className="st-country-select">
      <label htmlFor={id} className="sr-only">
        Country Code
      </label>
      <select
        id={id}
        className="st-country-select__select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Select Country Code"
      >
        {COUNTRY_CODES.map((c) => (
          <option key={c.code} value={c.code}>
            {c.flag} {c.code}
          </option>
        ))}
      </select>
      <span className="st-country-select__arrow" aria-hidden>
        ▾
      </span>
    </div>
  );
}

export function MobileInputField({
  id,
  label = 'Mobile number',
  value,
  onChange,
  countryCode = '+91',
  onCountryCodeChange,
  error,
  help,
  placeholder = '10-digit mobile number',
}: {
  id: string;
  label?: string;
  value: string;
  onChange: (val: string) => void;
  countryCode?: string;
  onCountryCodeChange?: (cc: string) => void;
  error?: string;
  help?: string;
  placeholder?: string;
}) {
  const errId = error ? `${id}-error` : undefined;
  const helpId = help ? `${id}-help` : undefined;

  function handleInputChange(rawVal: string) {
    const sanitized = normalizeIndianMobile(rawVal, countryCode);
    onChange(sanitized);
  }

  return (
    <div className="st-field st-field--mobile">
      <label className="st-field__label" htmlFor={id}>
        {label}
      </label>
      <div className="st-mobile-group">
        <CountryCodeSelect
          id={`${id}-country`}
          value={countryCode}
          onChange={(cc) => onCountryCodeChange?.(cc)}
        />
        <input
          id={id}
          className="st-input st-input--mobile"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          value={value}
          placeholder={placeholder}
          aria-invalid={error ? true : undefined}
          aria-describedby={[errId, helpId].filter(Boolean).join(' ') || undefined}
          onChange={(e) => handleInputChange(e.target.value)}
        />
      </div>
      {error && (
        <span className="ui-validation" role="alert" id={errId}>
          <span className="ui-validation__mark" aria-hidden>
            !
          </span>{' '}
          {error}
        </span>
      )}
      {help && !error && (
        <span className="st-field__help" id={helpId}>
          {help}
        </span>
      )}
    </div>
  );
}

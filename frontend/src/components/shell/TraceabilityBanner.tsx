import { getTrace } from '../../app/traceability';

/**
 * Reviewer/dev-safe traceability banner (SAATHI-344). Surfaces the canonical
 * screen ID, PRD epic/story mapping, release tranche, and persona applicability.
 * Only rendered for reviewers/devs — hidden in normal production builds — so it
 * never leaks internal mapping to end users.
 */
export function isReviewerMode(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    if (window.localStorage.getItem('ls-reviewer') === '1') return true;
  } catch {
    /* storage unavailable */
  }
  // Vite dev builds are reviewer-mode by default.
  return Boolean((import.meta as { env?: { DEV?: boolean } }).env?.DEV);
}

export function TraceabilityBanner({ screenId }: { screenId?: string }) {
  if (!screenId || !isReviewerMode()) return null;
  const t = getTrace(screenId);
  if (!t) return null;
  return (
    <aside className="ls-trace" role="note" aria-label="Screen traceability (reviewer)">
      <span className="ls-trace__id">{t.id}</span>
      <span className="ls-trace__seg">{t.epic} · {t.story}</span>
      <span className="ls-trace__pill">{t.release}</span>
      <span className="ls-trace__pill ls-trace__pill--persona">{t.persona}</span>
      <span className="ls-trace__src">v3.2 matrix</span>
    </aside>
  );
}

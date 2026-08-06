/**
 * Canonical implementation screen IDs S-01 to S-99.
 *
 * Authority: the Option J v3.2 design sitemap is the implementation authority for
 * screen IDs, routes, and Jira references (TDD v0.2 §2.1). PRD v0.4.2's suffixed/
 * gapped IDs are product-discovery references only. The v3.2 traceability matrix maps
 * PRD stories to these IDs:
 *   docs/design/v3.2/LegalSaathi Student Module Option J S01-S99 Traceability Matrix v3.2.md
 *
 * This is a FOUNDATION placeholder registry only — real screens are built per
 * release tranche in later tickets. Each entry currently renders a placeholder.
 */

export interface ScreenRoute {
  /** Canonical v3.2 screen ID, e.g. "S-01". */
  id: string;
  /** Route path, e.g. "/s-01". */
  path: string;
  /** Human label (placeholder until real screens are named in design tickets). */
  label: string;
}

export const TOTAL_SCREENS = 99;

/**
 * Feature-state labels for implemented tranches (placeholder label otherwise).
 * S5 law schools (SAATHI-63): S-27..S-30.
 * S6 Wave 2 tutoring (SAATHI-65 owns S-31..S-34, SAATHI-66 owns S-35).
 */
const FEATURE_STATE_LABELS: Record<string, string> = {
  'S-27': 'schools/search',
  'S-28': 'schools/detail',
  'S-29': 'schools/compare',
  'S-30': 'schools/saved-followed',
  'S-31': 'tutoring/search',
  'S-32': 'tutoring/detail',
  'S-33': 'tutoring/hold',
  'S-34': 'tutoring/detail',
  'S-35': 'tutoring/session',
  'S-82': 'wallet/list',
  'S-83': 'wallet/add',
  'S-84': 'wallet/pending',
  'S-85': 'wallet/share',
  'S-86': 'internship-report/create',
  'S-87': 'internship-report/status',
  'S-88': 'internship-risk/aggregate',
  'S-89': 'internship-risk/organisation-response',
  'S-90': 'calendar/month',
  'S-91': 'calendar/event',
  'S-92': 'calendar/conflicts',
  'S-93': 'calendar/reminders-export',
};

/** Generates the S-01 … S-99 canonical route registry. */
export const screenRoutes: ScreenRoute[] = Array.from(
  { length: TOTAL_SCREENS },
  (_, i) => {
    const num = String(i + 1).padStart(2, '0');
    const id = `S-${num}`;
    return {
      id,
      path: `/${id.toLowerCase()}`,
      label: FEATURE_STATE_LABELS[id] ?? `${id} (placeholder)`,
    };
  }
);

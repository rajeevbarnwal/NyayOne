/**
 * Dashboard module availability by release tranche (SAATHI-57 / S3.1).
 *
 * The R1 home dashboard must degrade gracefully: modules that belong to a later
 * release are shown as a safe "coming soon" state rather than a broken link or
 * error. Availability is derived purely from release rank so the dashboard has
 * no hard dependency on unbuilt modules.
 */

export type Release = 'R1' | 'R1.1' | 'R2' | 'R3';

export const CURRENT_RELEASE: Release = 'R1';

const RELEASE_ORDER: Release[] = ['R1', 'R1.1', 'R2', 'R3'];

export function releaseRank(r: Release): number {
  return RELEASE_ORDER.indexOf(r);
}

export type ModuleAvailability = 'available' | 'unavailable_not_released';

export interface DashboardModule {
  readonly id: string;
  readonly label: string;
  readonly release: Release;
  readonly route: string; // canonical S-XX route
}

/** Cross-module tiles surfaced on the student home dashboard. */
export const DASHBOARD_MODULES: readonly DashboardModule[] = [
  { id: 'calendar', label: 'Calendar', release: 'R1', route: '/s-90' },
  { id: 'internships', label: 'Internships', release: 'R1', route: '/s-20' },
  { id: 'clinical', label: 'Clinical Hours', release: 'R1', route: '/s-61' },
  { id: 'community', label: 'Community', release: 'R1', route: '/s-50' },
  { id: 'exam', label: 'Exam Prep', release: 'R1', route: '/s-55' },
  { id: 'research', label: 'AI Research', release: 'R2', route: '/s-36' },
  { id: 'tutors', label: 'Find a Tutor', release: 'R2', route: '/s-31' },
  { id: 'digests', label: 'Case Digests', release: 'R2', route: '/s-46' },
  { id: 'jobs', label: 'Career & Jobs', release: 'R2', route: '/s-66' },
  { id: 'groups', label: 'Study Groups', release: 'R1.1', route: '/s-75' },
  { id: 'schools', label: 'Law Schools', release: 'R3', route: '/s-27' },
  { id: 'wallet', label: 'Credential Wallet', release: 'R3', route: '/s-82' },
];

export function moduleAvailability(
  moduleRelease: Release,
  current: Release = CURRENT_RELEASE
): ModuleAvailability {
  return releaseRank(moduleRelease) <= releaseRank(current)
    ? 'available'
    : 'unavailable_not_released';
}

export function isModuleAvailable(
  m: DashboardModule,
  current: Release = CURRENT_RELEASE
): boolean {
  return moduleAvailability(m.release, current) === 'available';
}

export function availableModules(current: Release = CURRENT_RELEASE): DashboardModule[] {
  return DASHBOARD_MODULES.filter((m) => isModuleAvailable(m, current));
}

export function upcomingModules(current: Release = CURRENT_RELEASE): DashboardModule[] {
  return DASHBOARD_MODULES.filter((m) => !isModuleAvailable(m, current));
}

/** Safe copy for a not-yet-released tile (no dead ends). */
export const COMING_SOON_LABEL = 'Coming soon';

/** Percentage of the actual profile fields completed; no fabricated momentum. */
export function profileCompletionPct(profile: {
  fullName: string;
  dateOfBirth: string;
  college: string;
  yearOfStudy: string;
  enrolmentNumber: string;
  institutionalEmail: string;
  interests: readonly string[];
  careerGoal: string;
}): number {
  const fields = [
    profile.fullName,
    profile.dateOfBirth,
    profile.college,
    profile.yearOfStudy,
    profile.enrolmentNumber,
    profile.institutionalEmail,
    profile.interests.length ? 'selected' : '',
    profile.careerGoal,
  ];
  return Math.round((fields.filter((v) => v.trim().length > 0).length / fields.length) * 100);
}

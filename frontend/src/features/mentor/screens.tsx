import type { ComponentType } from 'react';
import { MENTOR_COMPLETION_SCREEN_ID, MentorSessionCompletion } from './MentorSessionScreens';

/**
 * Mentor / administrator routes for the Wave 2 tutoring module (SAATHI-66).
 *
 * These sit OUTSIDE the canonical student S-01..S-99 registry on purpose: that
 * registry is the v3.2 Student Module sitemap (`app/screenRegistry.ts`), and a
 * mentor action has no place in it. The convention followed here is the one the
 * lawyer module already uses (`features/lawyer/screens.tsx`): a small frozen
 * table of stable paths, each with its Jira reference and its guard flag, mapped
 * into the router in `app/App.tsx`.
 *
 * The ENTIRE mentor module is guarded. `guarded: true` wraps the route in
 * `MentorGuard`, so an anonymous / student / unverified actor never mounts a
 * session list or a completion control at all.
 */
export interface MentorRoute {
  readonly path: string;
  /** Screen id rendered in the tutoring screen bar and in `data-screen`. */
  readonly screenId: string;
  readonly jira: string;
  readonly Component: ComponentType;
  readonly guarded: boolean;
}

export const mentorRoutes: readonly MentorRoute[] = [
  {
    path: '/mentor/sessions',
    screenId: MENTOR_COMPLETION_SCREEN_ID,
    jira: 'SAATHI-66',
    Component: MentorSessionCompletion,
    guarded: true,
  },
];

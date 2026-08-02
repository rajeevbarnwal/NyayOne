import type { ComponentType } from 'react';
import { ModerationCaseScreen, ModerationQueueScreen, RiskClusterScreen } from './ModerationScreens';

export interface ModerationRoute {
  readonly path: string;
  readonly jira: 'SAATHI-274';
  readonly Component: ComponentType;
}

export const moderationRoutes: readonly ModerationRoute[] = [
  { path: '/moderation/internship-reports', jira: 'SAATHI-274', Component: ModerationQueueScreen },
  { path: '/moderation/internship-reports/:reportId', jira: 'SAATHI-274', Component: ModerationCaseScreen },
  { path: '/moderation/risk-clusters/:clusterId', jira: 'SAATHI-274', Component: RiskClusterScreen },
];


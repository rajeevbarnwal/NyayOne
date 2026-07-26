import type { ComponentType } from 'react';
import type { ThemeMode } from '../../hooks/useTheme';
import {
  Splash,
  Onboarding,
  AuthGate,
  LanguageSelect,
  Register,
  OtpVerify,
  OtpExpired,
  Lockout,
  EmailVerify,
  RestrictedDashboard,
} from './auth/AuthScreens';
import {
  ProfileStep1,
  ProfileStep2,
  ProfileStep3,
  ProfileDone,
  ProfileResume,
  ProfileView,
} from './profile/ProfileScreens';
import { Dashboard } from './dashboard/Dashboard';
import { NotificationsSettings, PrivacySettings } from './settings/SettingsScreens';
import {
  InternshipBrowse,
  InternshipDetail,
  InternshipApply,
  InternshipConfirm,
  InternshipTracker,
  InternshipSaved,
  InternshipEmpty,
} from './internships/InternshipScreens';
import {
  CommunityFeed,
  CommunityPost,
  CommunityCreate,
  CommunityReport,
  CommunityModerated,
} from './community/CommunityScreens';
import { ExamOverview, ExamSyllabus, ExamMock, ExamResult, ExamReview, ExamAnalytics } from './exam/ExamScreens';
import { ClinicalLog, ClinicalAdd, ClinicalPending, ClinicalVerified, ClinicalExport } from './clinical/ClinicalScreens';
import { CalendarMonth, CalendarAdd } from './calendar/CalendarScreens';

/** Props every student screen may receive from the shell (theme is shell-owned). */
export interface StudentScreenProps {
  theme?: ThemeMode;
  toggleTheme?: () => void;
}

/**
 * Canonical v3.2 screen-ID → implemented component map (S-01…S-19).
 * App renders the real component for a mapped ID and falls back to the
 * foundation ScreenPlaceholder for every other ID in the S-01…S-99 registry.
 */
export const studentScreens: Record<string, ComponentType<StudentScreenProps>> = {
  'S-01': Splash,
  'S-02': Onboarding,
  'S-03': AuthGate,
  'S-04': LanguageSelect,
  'S-05': Register,
  'S-06': OtpVerify,
  'S-07': OtpExpired,
  'S-08': Lockout,
  'S-09': ProfileStep1,
  'S-10': ProfileStep2,
  'S-11': ProfileStep3,
  'S-12': ProfileDone,
  'S-13': ProfileResume,
  'S-14': Dashboard,
  'S-15': EmailVerify,
  'S-16': RestrictedDashboard,
  'S-17': ProfileView,
  'S-18': NotificationsSettings,
  'S-19': PrivacySettings,
  // S4 internships (SAATHI-60/61)
  'S-20': InternshipBrowse,
  'S-21': InternshipDetail,
  'S-22': InternshipApply,
  'S-23': InternshipConfirm,
  'S-24': InternshipTracker,
  'S-25': InternshipSaved,
  'S-26': InternshipEmpty,
  // S10 community (SAATHI-74)
  'S-50': CommunityFeed,
  'S-51': CommunityPost,
  'S-52': CommunityCreate,
  'S-53': CommunityReport,
  'S-54': CommunityModerated,
  // S11 exam prep (SAATHI-147 + S11.2/3/5: SAATHI-152/157/167)
  'S-55': ExamOverview,
  'S-56': ExamMock,
  'S-57': ExamResult,
  'S-58': ExamReview,
  'S-59': ExamAnalytics,
  'S-60': ExamSyllabus,
  // S12 clinical hours (SAATHI-173 + S12.2/3: SAATHI-178/183)
  'S-61': ClinicalLog,
  'S-62': ClinicalAdd,
  'S-63': ClinicalPending,
  'S-64': ClinicalVerified,
  'S-65': ClinicalExport,
  // S19.1 cross-module calendar (SAATHI-286)
  'S-90': CalendarMonth,
  'S-91': CalendarAdd,
};

export const IMPLEMENTED_SCREEN_IDS = Object.keys(studentScreens);

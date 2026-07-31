import type { ComponentType } from 'react';
import type { ThemeMode } from '../../hooks/useTheme';
import {
  EmailVerify,
  RestrictedDashboard,
} from './auth/AuthScreens';
import {
  V34Splash,
  V34Onboarding,
  V34AuthGate,
  V34Login,
  V34LoginFailure,
  V34PasswordReset,
  V34VerifiedHome,
  V34Register,
  V34OtpVerify,
  V34ProfileStep1,
} from './auth/V34Screens';
import {
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
import {
  SchoolSearch,
  SchoolDetail,
  SchoolCompare,
  SchoolSavedFollowed,
} from './schools/SchoolScreens';
import { TutorSearch, TutorDetail } from './tutoring/TutorDiscoveryScreens';
import { BookingHoldScreen, SessionConfirmed } from './tutoring/BookingScreens';
import { SessionLifecycle } from './tutoring/SessionScreens';
import { ExamOverview, ExamSyllabus, ExamMock, ExamResult, ExamReview, ExamAnalytics } from './exam/ExamScreens';
import { ClinicalLog, ClinicalAdd, ClinicalPending, ClinicalVerified, ClinicalExport } from './clinical/ClinicalScreens';
import { CalendarMonth, CalendarAdd } from './calendar/CalendarScreens';
import {
  CredentialWallet,
  CredentialAdd,
  CredentialPending,
  CredentialShare,
} from './credentials/CredentialScreens';

/** Props every student screen may receive from the shell (theme is shell-owned). */
export interface StudentScreenProps {
  theme?: ThemeMode;
  toggleTheme?: () => void;
}

/**
 * Canonical screen-ID → implemented component map. S-01…S-10 use the
 * approved v3.4 Saffron Slate handoff; later screens retain their existing
 * contracts until Product supplies their corresponding v3.4 references.
 * App renders the real component for a mapped ID and falls back to the
 * foundation ScreenPlaceholder for every other ID in the S-01…S-99 registry.
 */
export const studentScreens: Record<string, ComponentType<StudentScreenProps>> = {
  'S-01': V34Splash,
  'S-02': V34Onboarding,
  'S-03': V34AuthGate,
  'S-04': V34Login,
  'S-05': V34LoginFailure,
  'S-06': V34PasswordReset,
  'S-07': V34VerifiedHome,
  'S-08': V34Register,
  'S-09': V34OtpVerify,
  'S-10': V34ProfileStep1,
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
  // S5 law schools (SAATHI-63): schools/search, schools/detail, schools/compare, schools/saved-followed
  'S-27': SchoolSearch,
  'S-28': SchoolDetail,
  'S-29': SchoolCompare,
  'S-30': SchoolSavedFollowed,
  // S6 Wave 2 tutoring: tutoring/search, tutoring/detail, tutoring/hold,
  // tutoring/detail (session), tutoring/session (SAATHI-65 + SAATHI-66)
  'S-31': TutorSearch,
  'S-32': TutorDetail,
  'S-33': BookingHoldScreen,
  'S-34': SessionConfirmed,
  'S-35': SessionLifecycle,
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
  // S17 credential trust (SAATHI-253/258): canonical S-82..S-85.
  'S-82': CredentialWallet,
  'S-83': CredentialAdd,
  'S-84': CredentialPending,
  'S-85': CredentialShare,
  // S19.1 cross-module calendar (SAATHI-286)
  'S-90': CalendarMonth,
  'S-91': CalendarAdd,
};

export const IMPLEMENTED_SCREEN_IDS = Object.keys(studentScreens);

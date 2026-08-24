import {
  type QueryFunctionContext,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationOptions,
} from '@tanstack/react-query';
import { useStudentMutation } from '../lib/useStudentMutation';
import {
  captureStudentContextFence,
  isStudentContextFenceCurrent,
  type StudentContextFence,
} from '../lib/studentBrowserContext';
import {
  dismissProfilePrompt,
  getStudentProfileProjection,
  ProfileApiError,
  profileSectionRoute,
  requestInstitutionalEmailVerification,
  updateAcademicProfile,
  updateInterestsProfile,
  updatePersonalProfile,
  type AcademicProfileInput,
  type InterestsProfileInput,
  type PersonalProfileInput,
  type ProfileMutationResult,
  type ProfileSection,
  type StudentProfileProjection,
} from '../lib/profileApi';

export const STUDENT_PROFILE_QUERY_KEY = ['student-profile-projection'] as const;

/** Shared by the hook and its actor-rotation transport lifecycle test. */
export const STUDENT_PROFILE_QUERY_OPTIONS = {
  queryKey: STUDENT_PROFILE_QUERY_KEY,
  // Cache teardown cancels this query's observer/result ownership, but an HTTP
  // request that already dispatched must finish under its shared auth lease.
  // Lower-level callers can still pass an explicit AbortSignal directly to
  // getStudentProfileProjection when cancellation is their own intent.
  queryFn: (_context: QueryFunctionContext) => getStudentProfileProjection(),
  retry: false,
} as const;

export function useStudentProfileProjection() {
  return useQuery(STUDENT_PROFILE_QUERY_OPTIONS);
}

export function createProjectionMutationOptions<TInput>(
  queryClient: QueryClient,
  mutationFn: (input: TInput) => Promise<ProfileMutationResult>,
): UseMutationOptions<ProfileMutationResult, ProfileApiError, TInput, StudentContextFence> {
  return {
    mutationFn,
    onMutate: captureStudentContextFence,
    onSuccess: (
      result: ProfileMutationResult,
      _input: TInput,
      fence: StudentContextFence,
    ) => {
      if (!isStudentContextFenceCurrent(fence)) return;
      queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, result.projection);
    },
    onError: (
      error: ProfileApiError,
      _input: TInput,
      fence: StudentContextFence | undefined,
    ) => {
      if (fence === undefined || !isStudentContextFenceCurrent(fence)) return;
      if (error instanceof ProfileApiError) {
        // A conflict projection belongs to the form's explicit review state.
        // Publishing it globally here can redirect/unmount another section and
        // destroy the retained draft before the user chooses how to proceed.
        if (error.status === 409 && error.code === 'profile_version_conflict') return;
        const projection = error.currentProjection ?? error.latestProjection;
        if (projection) queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, projection);
      }
    },
  };
}

function useProjectionMutation<TInput>(mutationFn: (input: TInput) => Promise<ProfileMutationResult>) {
  const queryClient = useQueryClient();
  return useStudentMutation(createProjectionMutationOptions(queryClient, mutationFn));
}

export function useSavePersonalProfile() {
  return useProjectionMutation<PersonalProfileInput>(updatePersonalProfile);
}

export function useSaveAcademicProfile() {
  return useProjectionMutation<AcademicProfileInput>(updateAcademicProfile);
}

export function useSaveInterestsProfile() {
  return useProjectionMutation<InterestsProfileInput>(updateInterestsProfile);
}

export function useDismissProfilePrompt() {
  return useProjectionMutation<void>(() => dismissProfilePrompt());
}

export function useRequestInstitutionalEmailVerification() {
  return useProjectionMutation<void>(() => requestInstitutionalEmailVerification());
}

export function profileSaveDestination(
  projection: StudentProfileProjection,
  intent: 'next' | 'exit',
): string {
  if (projection.accessMode === 'limited') return '/s-16';
  return intent === 'exit' ? '/s-14' : profileSectionRoute(projection.nextIncompleteSection);
}

export function profileResumeDestination(projection: StudentProfileProjection): string {
  return projection.isComplete ? '/s-14' : profileSectionRoute(projection.nextIncompleteSection);
}

export function canOpenProfileSection(
  projection: StudentProfileProjection,
  section: ProfileSection,
): boolean {
  if (section === 'personal') return true;
  if (section === 'academic') return projection.completedSections.includes('personal');
  return projection.completedSections.includes('personal')
    && projection.completedSections.includes('academic');
}

export function resolveProfileStepRoute(
  requestedSection: string | null,
  projection: StudentProfileProjection,
): { render: 'personal' | 'academic' } | { redirect: string } {
  if (requestedSection === 'personal') return { render: 'personal' };
  if (requestedSection === 'academic' && canOpenProfileSection(projection, 'academic')) {
    return { render: 'academic' };
  }
  return { redirect: profileSectionRoute(projection.nextIncompleteSection) };
}

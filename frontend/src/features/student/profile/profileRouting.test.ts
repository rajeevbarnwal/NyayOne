import { describe, expect, it } from 'vitest';
import type { StudentProfileProjection } from '../lib/profileApi';
import {
  profileResumeDestination,
  profileSaveDestination,
  resolveProfileStepRoute,
} from './profileHooks';

function projection(
  completedSections: StudentProfileProjection['completedSections'],
  nextIncompleteSection: StudentProfileProjection['nextIncompleteSection'],
): StudentProfileProjection {
  const complete = nextIncompleteSection === null;
  return {
    profileVersion: 1,
    completionVersion: 'v1',
    completionPercent: complete ? 100 : completedSections.length === 2 ? 67 : completedSections.length === 1 ? 34 : 0,
    completedSections,
    missingRequirements: complete
      ? []
      : nextIncompleteSection === 'interests'
        ? ['interests.interests', 'interests.goals']
        : nextIncompleteSection === 'academic'
          ? ['academic.college', 'academic.year_of_study', 'academic.enrolment_number', 'interests.interests', 'interests.goals']
          : ['personal.preferred_language', 'personal.city', 'academic.college', 'academic.year_of_study', 'academic.enrolment_number', 'interests.interests', 'interests.goals'],
    nextIncompleteSection,
    isComplete: complete,
    institutionalEmailStatus: 'not_provided',
    guardian: { required: false, status: 'not_required' },
    accessMode: 'full',
    disabledCapabilities: [],
    profilePrompt: { shouldShow: !complete, dismissedForSession: false },
    profile: {
      personal: { firstName: 'A', middleName: null, lastName: 'B', dateOfBirth: '2000-01-01', preferredLanguage: 'en', city: 'Pune', pronouns: null },
      academic: { college: null, yearOfStudy: null, enrolmentNumber: null, institutionalEmail: null, barEnrolmentNumber: null },
      interests: { interests: [], goals: [] },
    },
  };
}

describe('S-10 closed section routing', () => {
  it('redirects absent and invented query values to the server-selected section', () => {
    const state = projection(['personal'], 'academic');
    expect(resolveProfileStepRoute(null, state)).toEqual({ redirect: '/s-10?section=academic' });
    expect(resolveProfileStepRoute('admin', state)).toEqual({ redirect: '/s-10?section=academic' });
  });

  it('does not let direct academic entry skip incomplete personal details', () => {
    expect(resolveProfileStepRoute('academic', projection([], 'personal')))
      .toEqual({ redirect: '/s-10?section=personal' });
  });

  it('renders only allowlisted reachable sections', () => {
    expect(resolveProfileStepRoute('personal', projection([], 'personal'))).toEqual({ render: 'personal' });
    expect(resolveProfileStepRoute('academic', projection(['personal'], 'academic'))).toEqual({ render: 'academic' });
  });

  it('sends invalid S-10 state on a completed profile to S-12', () => {
    expect(resolveProfileStepRoute('anything', projection(['personal', 'academic', 'interests'], null)))
      .toEqual({ redirect: '/s-12' });
  });

  it('routes every newly limited mutation result to the restricted surface', () => {
    const limited: StudentProfileProjection = {
      ...projection(['personal'], 'academic'),
      guardian: { required: true, status: 'required_pending' },
      accessMode: 'limited',
      disabledCapabilities: ['community', 'sharing'],
    };
    expect(profileSaveDestination(limited, 'next')).toBe('/s-16');
    expect(profileSaveDestination(limited, 'exit')).toBe('/s-16');
  });

  it('opens the dashboard, not S-12, from a completed resume screen', () => {
    expect(profileResumeDestination(projection(['personal', 'academic', 'interests'], null)))
      .toBe('/s-14');
  });
});

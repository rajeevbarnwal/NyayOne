import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PROFILE_REAUTH_HANDOFF_TTL_MS,
  captureActiveProfileReauthDraft,
  clearProfileReauthHandoff,
  hasProfileReauthHandoff,
  profileReauthResumeRoute,
  releaseActiveProfileReauthDraft,
  resolveProfileReauthActor,
  restoreCapturedProfileReauthDraft,
  stageActiveProfileReauthDraft,
  takeResolvedProfileReauthDraft,
} from './profileReauthHandoff';

const ACTOR_A = '00000000-0000-4000-8000-0000000000a1';
const ACTOR_B = '00000000-0000-4000-8000-0000000000b2';

afterEach(() => {
  clearProfileReauthHandoff();
  vi.useRealTimers();
});

describe('bounded process-memory profile reauthentication handoff', () => {
  it('restores one exact draft and canonical route only after the same server actor resolves', () => {
    const owner = Symbol('academic-form');
    const value = {
      college: 'nlsiu_bengaluru',
      yearOfStudy: 'year_3',
      enrolmentNumber: 'KA/1234/2023',
      institutionalEmail: 'student@nls.ac.in',
      barEnrolmentNumber: null,
    } as const;
    stageActiveProfileReauthDraft(owner, ACTOR_A, { section: 'academic', value });

    const captured = captureActiveProfileReauthDraft();
    clearProfileReauthHandoff();
    expect(hasProfileReauthHandoff()).toBe(false);
    expect(captured).not.toBeNull();
    restoreCapturedProfileReauthDraft(captured!);

    expect(profileReauthResumeRoute(ACTOR_A)).toBeNull();
    expect(resolveProfileReauthActor(ACTOR_A)).toBe(true);
    expect(profileReauthResumeRoute(ACTOR_A)).toBe('/s-10?section=academic');
    expect(takeResolvedProfileReauthDraft(ACTOR_A, 'academic')).toEqual(value);
    expect(takeResolvedProfileReauthDraft(ACTOR_A, 'academic')).toBeNull();
    expect(hasProfileReauthHandoff()).toBe(false);
  });

  it('erases without revealing or restoring when a different authoritative actor wins', () => {
    const owner = Symbol('personal-form');
    stageActiveProfileReauthDraft(owner, ACTOR_A, {
      section: 'personal',
      value: {
        firstName: 'Aditi',
        middleName: null,
        lastName: 'Rao',
        dateOfBirth: '2000-01-01',
        preferredLanguage: 'en',
        city: 'Pune',
        pronouns: null,
      },
    });
    const captured = captureActiveProfileReauthDraft();
    clearProfileReauthHandoff();
    restoreCapturedProfileReauthDraft(captured!);

    expect(resolveProfileReauthActor(ACTOR_B)).toBe(false);
    expect(profileReauthResumeRoute(ACTOR_A)).toBeNull();
    expect(takeResolvedProfileReauthDraft(ACTOR_A, 'personal')).toBeNull();
    expect(hasProfileReauthHandoff()).toBe(false);
  });

  it('keeps only the latest mounted form and never serializes a handoff', () => {
    const first = Symbol('first');
    const second = Symbol('second');
    stageActiveProfileReauthDraft(first, ACTOR_A, {
      section: 'interests',
      value: { interests: ['Criminal'], goals: ['Litigation & judiciary'] },
    });
    stageActiveProfileReauthDraft(second, ACTOR_A, {
      section: 'interests',
      value: { interests: ['Corporate'], goals: ['Corporate / in-house'] },
    });
    releaseActiveProfileReauthDraft(second);

    expect(captureActiveProfileReauthDraft()).toEqual(expect.objectContaining({
      actorSubject: ACTOR_A,
      draft: expect.objectContaining({
        section: 'interests',
        value: { interests: ['Criminal'], goals: ['Litigation & judiciary'] },
      }),
    }));
  });

  it('actively erases the retained PII when its bounded lifetime expires', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-23T00:00:00Z'));
    const owner = Symbol('interests-form');
    stageActiveProfileReauthDraft(owner, ACTOR_A, {
      section: 'interests',
      value: { interests: ['Tech & Privacy'], goals: ['Policy & academia'] },
    });
    const captured = captureActiveProfileReauthDraft();
    clearProfileReauthHandoff();
    restoreCapturedProfileReauthDraft(captured!);
    expect(hasProfileReauthHandoff()).toBe(true);

    vi.advanceTimersByTime(PROFILE_REAUTH_HANDOFF_TTL_MS + 1);

    expect(hasProfileReauthHandoff()).toBe(false);
    expect(resolveProfileReauthActor(ACTOR_A)).toBe(false);
  });
});

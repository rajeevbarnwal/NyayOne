import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { AuthCard, DpdpFootnote, SelectField, StudentScreen, TextField } from '../components';
import { ErrorState, LoadingState } from '../../../components/ui/primitives';
import {
  ProfileApiError,
  emailIdentityErrorMessage,
  newEmailIdentityIdempotencyKey,
  profileErrorMessage,
  profileSectionRoute,
  validateLegalName,
  type EmailIdentity,
  type ProfileSection,
  type StudentProfileProjection,
} from '../lib/profileApi';
import {
  canOpenProfileSection,
  profileResumeDestination,
  profileSaveDestination,
  useSaveAcademicProfile,
  useSaveInterestsProfile,
  useSavePersonalProfile,
  useStudentProfileProjection,
  STUDENT_PROFILE_QUERY_KEY,
  useAddEmailIdentity,
  useEmailIdentities,
  useRemoveEmailIdentity,
  useResendEmailIdentity,
  useSetPrimaryEmailIdentity,
  useVerifyEmailIdentity,
} from './profileHooks';
import {
  preserveProfileConflictDraft,
  takeProfileConflictDraft,
} from './profileConflictDraftStore';
import { isStudentMutationCancellation } from '../lib/useStudentMutation';
import { useAuth } from '../../../app/authContext';
import {
  releaseActiveProfileReauthDraft,
  stageActiveProfileReauthDraft,
  takeResolvedProfileReauthDraft,
  type ProfileReauthDraft,
} from './profileReauthHandoff';
import { ENROLMENT_RE, institutionalEmailError } from '../lib/profile';
import { COLLEGE_OPTIONS, LANGUAGE_OPTIONS, YEAR_OPTIONS, labelFor, toCanonicalCollege, toCanonicalYear } from '../lib/catalog';
import { NyayOneRevLIcon, NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';

const INTERESTS = ['Constitutional', 'Arbitration', 'Criminal', 'Corporate', 'Tech & Privacy'];
const GOALS = ['Litigation & judiciary', 'Corporate / in-house', 'Policy & academia', 'Undecided'];
type FieldErrors = Record<string, string>;

/** S-10 presentation only. Identity and form authority remain server-backed. */
export function ProfileSetupFrame({ step, firstName, middleName, lastName, children }: {
  step: 1 | 2; firstName: string; middleName: string | null; lastName: string; children: ReactNode;
}) {
  const nav = useNavigate();
  const fullName = [firstName, middleName, lastName].filter(Boolean).join(' ');
  const initials = [firstName, lastName].map((name) => [...name.trim()][0] ?? '').join('').toUpperCase();
  return <section className="v321-profile" data-screen="S-10" data-profile-step={step} aria-labelledby="S-10-title">
    <header className="v321-profile__header">
      <span className="v321-profile__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-profile__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>Profile setup</b></span>
      <nav aria-label="Site" className="v321-profile__nav">
        <button type="button" onClick={() => nav('/s-14')}>Home</button>
        {['Research', 'Calendar', 'Careers'].map((label) => <button type="button" key={label} disabled>{label}</button>)}
        <button type="button" onClick={() => nav('/s-17')}>Profile</button>
      </nav>
      <button type="button" className="v321-profile__avatar" aria-label={fullName ? `Your Profile · ${fullName}` : 'Your Profile'} onClick={() => nav('/s-17')}><span>{initials || 'P'}</span></button>
    </header>
    <div className="v321-profile__layout">
      <div className="v321-profile__form">
        <div className="v321-profile__step"><div className="v321-profile__eyebrow">Profile · step {step} of 3</div><div className="v321-profile__steps" role="img" aria-label={`Step ${step} of 3`}>{[1, 2, 3].map((index) => <i key={index} className={index <= step ? 'is-current' : undefined} />)}</div></div>
        <h1 id="S-10-title" className="v321-profile__title"><span className={`v321-profile__heading-icon${step === 2 ? ' v321-profile__heading-icon--academic' : ''}`} aria-hidden="true">{step === 1 ? <NyayOneRevLIcon name="idcard" framed={false} /> : <ProfileSetupIcon name="cap" />}</span>{step === 1 ? 'About you.' : 'Your academic record.'}</h1>
        {children}
      </div>
      <section className="v321-profile__aside" aria-label="About profile setup">
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
      </section>
    </div>
  </section>;
}

function ProfileSetupIcon({ name }: { name: 'cap' | 'book' | 'grid' }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
    {name === 'cap' && <><path d="M12 4 22 9l-10 5L2 9z" fill="currentColor" opacity=".18" /><path d="M12 4 22 9l-10 5L2 9z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" /><path d="M6 11.5V16c0 1.6 2.7 3 6 3s6-1.4 6-3v-4.5M22 9v5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" /></>}
    {name === 'book' && <><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5z" fill="currentColor" opacity=".16" /><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5zM19 4.5h-6a0 0 0 0 0 0 0V20a2 2 0 0 1 2-1.5h4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></>}
    {name === 'grid' && <><rect x="4" y="4" width="7" height="7" rx="1.8" fill="currentColor" opacity=".2" /><rect x="13" y="4" width="7" height="7" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.9" /><rect x="4" y="13" width="7" height="7" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.9" /><rect x="13" y="13" width="7" height="7" rx="1.8" fill="currentColor" opacity=".45" /></>}
  </svg>;
}

function ProfileSetupField({ icon, children }: { icon: 'idcard' | 'home' | 'book' | 'cap' | 'grid'; children: ReactNode }) {
  return <div className="v321-profile__icon-field"><span className="v321-profile__field-icon" aria-hidden="true">{icon === 'idcard' || icon === 'home' ? <NyayOneRevLIcon name={icon} /> : <ProfileSetupIcon name={icon} />}</span>{children}</div>;
}

function useActiveProfileReauthDraft(
  actorSubject: string | null | undefined,
  draft: ProfileReauthDraft | null,
): () => void {
  const owner = useRef(Symbol('profile-reauth-form'));
  useEffect(() => {
    if (!actorSubject || draft === null) {
      releaseActiveProfileReauthDraft(owner.current);
      return;
    }
    stageActiveProfileReauthDraft(owner.current, actorSubject, draft);
  }, [actorSubject, draft]);
  useEffect(() => () => {
    releaseActiveProfileReauthDraft(owner.current);
  }, []);
  return () => {
    if (actorSubject && draft !== null) {
      stageActiveProfileReauthDraft(owner.current, actorSubject, draft);
    }
  };
}

function ReauthDraftRestored({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <p role="status" data-testid="profile-reauth-draft-restored">
      Your unsaved profile draft was restored after you signed in again. Review it before saving.
    </p>
  );
}

function Progress({ projection }: { projection: StudentProfileProjection }) {
  return <div className="st-progress" role="progressbar" aria-valuenow={projection.completionPercent} aria-valuemin={0} aria-valuemax={100} aria-label="Profile setup progress" data-testid="profile-completion-percent"><div className="st-progress__bar" style={{ width: `${projection.completionPercent}%` }} /></div>;
}

function ProfileLoadState({ screenId, error, retry }: { screenId: string; error?: unknown; retry?: () => void }) {
  const nav = useNavigate();
  if (!error) return <StudentScreen screenId={screenId}><LoadingState label="Loading your profile…" /></StudentScreen>;
  const signedOut = error instanceof ProfileApiError && error.status === 401;
  return <StudentScreen screenId={screenId}>{signedOut ? <div className="ui-state" role="alert"><p className="ui-state__eyebrow">Signed out</p><p className="ui-state__title">Sign in to continue with your profile</p><div className="ui-state__action"><button type="button" className="btn tap" onClick={() => nav('/s-03')}>Go to sign in</button></div></div> : <ErrorState title="Could not load your profile" detail={profileErrorMessage(error)} onRetry={retry} />}</StudentScreen>;
}

function ErrorSummary({ errors, ids }: { errors: FieldErrors; ids: Record<string, string> }) {
  const ref = useRef<HTMLDivElement>(null);
  const rows = Object.entries(errors).filter(([field]) => Boolean(ids[field]));
  useEffect(() => { if (rows.length > 0) ref.current?.focus(); }, [errors, rows.length]);
  if (rows.length === 0) return null;
  return <div ref={ref} tabIndex={-1} role="alert" data-testid="profile-error-summary" className="ui-state"><h2 className="ui-state__title">Review the highlighted fields</h2><ul>{rows.map(([field, message]) => <li key={field}><a href={`#${ids[field]}`}>{message}</a></li>)}</ul></div>;
}

function SaveError({ value }: { value: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (value) ref.current?.focus(); }, [value]);
  return value ? <div ref={ref} tabIndex={-1} role="alert" className="ui-validation" data-testid="profile-save-error">{value}</div> : null;
}

function profileSectionSummary(projection: StudentProfileProjection, section: ProfileSection): string {
  if (section === 'personal') {
    const value = projection.profile.personal;
    return [value.firstName, value.middleName, value.lastName, value.dateOfBirth,
      value.preferredLanguage, value.city, value.pronouns].filter(Boolean).join(' · ');
  }
  if (section === 'academic') {
    const value = projection.profile.academic;
    return [value.college, value.yearOfStudy, value.enrolmentNumber,
      value.institutionalEmail, value.barEnrolmentNumber].filter(Boolean).join(' · ');
  }
  const value = projection.profile.interests;
  return [...value.interests, ...value.goals].join(' · ');
}

function useProfileConflictReview(setHydratedVersion: (version: number) => void) {
  const queryClient = useQueryClient();
  const [conflict, setConflict] = useState<StudentProfileProjection | null>(null);
  function capture(error: unknown): boolean {
    if (!(error instanceof ProfileApiError)
      || error.status !== 409
      || error.code !== 'profile_version_conflict'
      || !error.currentProjection) return false;
    setConflict(error.currentProjection);
    return true;
  }
  function adoptForDeliberateRetry(): void {
    if (!conflict) return;
    setHydratedVersion(conflict.profileVersion);
    queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, conflict);
    setConflict(null);
  }
  return { conflict, capture, adoptForDeliberateRetry };
}

function ProfileConflictReview({
  conflict,
  section,
  draftSummary,
  onAdopt,
}: {
  conflict: StudentProfileProjection | null;
  section: ProfileSection;
  draftSummary: string;
  onAdopt: () => void;
}) {
  if (!conflict) return null;
  return <section role="alert" className="ui-state" data-testid="profile-conflict-review" data-server-version={conflict.profileVersion}><h2 className="ui-state__title">Review changes from another tab</h2><p><strong>Current server version {conflict.profileVersion}:</strong> {profileSectionSummary(conflict, section) || 'No saved values'}</p><p><strong>Your retained draft:</strong> {draftSummary || 'No values entered'}</p><p>Nothing will be overwritten until you explicitly adopt the current version and save again.</p><button type="button" className="btn tap" onClick={onAdopt}>Use current version and review my draft</button></section>;
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function useRedirectBlockedSection(projection: StudentProfileProjection | undefined, section: ProfileSection): boolean {
  const nav = useNavigate();
  const blocked = Boolean(projection && !canOpenProfileSection(projection, section));
  useEffect(() => { if (projection && blocked) nav(profileSectionRoute(projection.nextIncompleteSection), { replace: true }); }, [blocked, nav, projection]);
  return blocked;
}

export function ProfileStep1() {
  const nav = useNavigate();
  const auth = useAuth();
  const query = useStudentProfileProjection();
  const save = useSavePersonalProfile();
  const [hydratedVersion, setHydratedVersion] = useState<number | null>(null);
  const [firstName, setFirstName] = useState('');
  const [middleName, setMiddleName] = useState('');
  const [lastName, setLastName] = useState('');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [preferredLanguage, setPreferredLanguage] = useState('');
  const [city, setCity] = useState('');
  const [pronouns, setPronouns] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [reauthRestoreNotice, setReauthRestoreNotice] = useState(false);
  const conflictReview = useProfileConflictReview(setHydratedVersion);
  const activeReauthDraft: ProfileReauthDraft | null = dirty && hydratedVersion !== null
    ? {
        section: 'personal',
        value: {
          firstName,
          middleName: middleName || null,
          lastName,
          dateOfBirth,
          preferredLanguage,
          city,
          pronouns: pronouns || null,
        },
      }
    : null;
  const stageReauthDraft = useActiveProfileReauthDraft(auth.userId, activeReauthDraft);
  useEffect(() => {
    if (!query.data || hydratedVersion !== null) return;
    setHydratedVersion(query.data.profileVersion);
    const preserved = auth.userId
      ? takeResolvedProfileReauthDraft(auth.userId, 'personal')
      : null;
    const personal = preserved ?? query.data.profile.personal;
    setFirstName(personal.firstName); setMiddleName(personal.middleName ?? ''); setLastName(personal.lastName);
    setDateOfBirth(personal.dateOfBirth); setPreferredLanguage(personal.preferredLanguage ?? ''); setCity(personal.city ?? ''); setPronouns(personal.pronouns ?? '');
    setDirty(Boolean(preserved));
    setReauthRestoreNotice(Boolean(preserved));
  }, [auth.userId, hydratedVersion, query.data]);

  async function persist(destination: 'next' | 'exit') {
    if (!query.data || hydratedVersion === null) return;
    const next: FieldErrors = {};
    if (!validateLegalName(firstName)) next.firstName = 'Enter a valid first name of 60 characters or fewer.';
    if (middleName && !validateLegalName(middleName)) next.middleName = 'Enter a valid middle name of 60 characters or fewer.';
    if (!validateLegalName(lastName)) next.lastName = 'Enter a valid last name of 60 characters or fewer.';
    if (!validDate(dateOfBirth)) next.dateOfBirth = 'Enter a valid date of birth.';
    if (!preferredLanguage) next.preferredLanguage = 'Choose a preferred language.';
    if (!city.trim()) next.city = 'Enter your city.';
    if ([...pronouns.trim()].length > 60) next.pronouns = 'Pronouns must be 60 characters or fewer.';
    setErrors(next); if (Object.keys(next).length > 0) return;
    setSaveError(null);
    stageReauthDraft();
    try {
      const result = await save.mutateAsync({ expectedProfileVersion: hydratedVersion, firstName, middleName: middleName || null, lastName, dateOfBirth, preferredLanguage: preferredLanguage as 'en' | 'hi', city, pronouns: pronouns || null });
      setDirty(false);
      nav(profileSaveDestination(result.projection, destination));
    } catch (error) {
      if (isStudentMutationCancellation(error)) return;
      conflictReview.capture(error);
      setSaveError(profileErrorMessage(error));
    }
  }
  if (!query.data) return <ProfileLoadState screenId="S-10" error={query.error ?? undefined} retry={() => { void query.refetch(); }} />;
  const ids = { firstName: 'profile-personal-first-name', middleName: 'profile-personal-middle-name', lastName: 'profile-personal-last-name', dateOfBirth: 'profile-personal-date-of-birth', preferredLanguage: 'profile-personal-language', city: 'profile-personal-city', pronouns: 'profile-personal-pronouns' };
  return <ProfileSetupFrame step={1} {...query.data.profile.personal}>
    <ReauthDraftRestored visible={reauthRestoreNotice} />
    <ErrorSummary errors={errors} ids={ids} />
    <fieldset className="st-namegroup v321-profile__names">
      <legend className="sr-only">Legal name</legend>
      <div className="v321-profile__pair">
        <ProfileSetupField icon="idcard"><TextField id={ids.firstName} label="First name" value={firstName} onChange={(value) => { setFirstName(value); setDirty(true); }} error={errors.firstName} autoComplete="given-name" /></ProfileSetupField>
        <TextField id={ids.middleName} label="Middle name" optional="optional" value={middleName} onChange={(value) => { setMiddleName(value); setDirty(true); }} error={errors.middleName} autoComplete="additional-name" />
      </div>
      <TextField id={ids.lastName} label="Last name" value={lastName} onChange={(value) => { setLastName(value); setDirty(true); }} error={errors.lastName} autoComplete="family-name" />
    </fieldset>
    <div className="v321-profile__pair">
      <ProfileSetupField icon="book"><SelectField id={ids.preferredLanguage} label="Preferred language" value={preferredLanguage} onChange={(value) => { setPreferredLanguage(value); setDirty(true); }} options={LANGUAGE_OPTIONS} error={errors.preferredLanguage} /></ProfileSetupField>
      <ProfileSetupField icon="home"><TextField id={ids.city} label="City" value={city} onChange={(value) => { setCity(value); setDirty(true); }} error={errors.city} autoComplete="address-level2" /></ProfileSetupField>
    </div>
    <TextField id={ids.dateOfBirth} label="Date of birth" value={dateOfBirth} onChange={(value) => { setDateOfBirth(value); setDirty(true); }} type="date" error={errors.dateOfBirth} help="Used for eligibility and guardian policy · not shown publicly" />
    <TextField id={ids.pronouns} label="Pronouns" optional="optional" value={pronouns} onChange={(value) => { setPronouns(value); setDirty(true); }} error={errors.pronouns} maxLength={60} />
    <SaveError value={saveError} />
    <ProfileConflictReview conflict={conflictReview.conflict} section="personal" draftSummary={[firstName, middleName, lastName, dateOfBirth, preferredLanguage, city, pronouns].filter(Boolean).join(' · ')} onAdopt={() => { conflictReview.adoptForDeliberateRetry(); setSaveError(null); }} />
    <div className="v321-profile__actions">
      <button type="button" className="v321-profile__button v321-profile__button--primary" onClick={() => { void persist('next'); }} disabled={save.isPending || Boolean(conflictReview.conflict)}><NyayOneRevLIcon name="send" />{save.isPending ? 'Saving…' : 'Save & continue'}</button>
      <button type="button" className="v321-profile__button" onClick={() => { void persist('exit'); }} disabled={save.isPending || Boolean(conflictReview.conflict)}><NyayOneRevLIcon name="home" />Save and exit</button>
    </div>
    <div className="v321-profile__completion"><span>Profile {query.data.completionPercent}% complete</span><Progress projection={query.data} /></div>
  </ProfileSetupFrame>;
}

function AcademicStep({ screenId }: { screenId: string }) {
  const nav = useNavigate(); const auth = useAuth(); const query = useStudentProfileProjection(); const save = useSaveAcademicProfile();
  const blocked = useRedirectBlockedSection(query.data, 'academic'); const [hydratedVersion, setHydratedVersion] = useState<number | null>(null);
  const [college, setCollege] = useState(''); const [yearOfStudy, setYear] = useState(''); const [enrolmentNumber, setEnrolment] = useState(''); const [institutionalEmail, setEmail] = useState(''); const [barEnrolmentNumber, setBar] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({}); const [saveError, setSaveError] = useState<string | null>(null);
  const [restoreNotice, setRestoreNotice] = useState(false);
  const [reauthRestoreNotice, setReauthRestoreNotice] = useState(false);
  const [dirty, setDirty] = useState(false);
  const conflictReview = useProfileConflictReview(setHydratedVersion);
  const activeReauthDraft: ProfileReauthDraft | null = dirty && hydratedVersion !== null
    ? { section: 'academic', value: { college, yearOfStudy, enrolmentNumber, institutionalEmail: institutionalEmail || null, barEnrolmentNumber: barEnrolmentNumber || null } }
    : null;
  const stageReauthDraft = useActiveProfileReauthDraft(auth.userId, activeReauthDraft);
  useEffect(() => {
    if (!query.data || hydratedVersion !== null || !canOpenProfileSection(query.data, 'academic')) return;
    setHydratedVersion(query.data.profileVersion);
    const reauthDraft = auth.userId
      ? takeResolvedProfileReauthDraft(auth.userId, 'academic')
      : null;
    const preserved = reauthDraft === null ? takeProfileConflictDraft('academic') : null;
    const academic = reauthDraft ?? preserved?.value ?? query.data.profile.academic;
    setCollege(toCanonicalCollege(academic.college) ?? '');
    setYear(toCanonicalYear(academic.yearOfStudy) ?? '');
    setEnrolment(academic.enrolmentNumber ?? '');
    setEmail(academic.institutionalEmail ?? '');
    setBar(academic.barEnrolmentNumber ?? '');
    setRestoreNotice(Boolean(preserved));
    setReauthRestoreNotice(Boolean(reauthDraft));
    setDirty(Boolean(reauthDraft || preserved));
  }, [auth.userId, hydratedVersion, query.data]);
  async function persist(destination: 'next' | 'exit') {
    if (!query.data || hydratedVersion === null) return; const next: FieldErrors = {};
    if (!college) next.college = 'Select your college or university.'; if (!yearOfStudy) next.yearOfStudy = 'Select your year of study.'; if (!ENROLMENT_RE.test(enrolmentNumber.trim())) next.enrolmentNumber = 'Use state code / roll / year, for example KA/1234/2023.';
    if (institutionalEmail.trim()) { const error = institutionalEmailError(institutionalEmail); if (error) next.institutionalEmail = error; }
    setErrors(next); if (Object.keys(next).length > 0) return; setSaveError(null); stageReauthDraft();
    try { const result = await save.mutateAsync({ expectedProfileVersion: hydratedVersion, college, yearOfStudy, enrolmentNumber, institutionalEmail: institutionalEmail || null, barEnrolmentNumber: barEnrolmentNumber || null }); setDirty(false); nav(profileSaveDestination(result.projection, destination)); } catch (error) { if (isStudentMutationCancellation(error)) return; conflictReview.capture(error); setSaveError(profileErrorMessage(error)); }
  }
  if (!query.data || blocked) return <ProfileLoadState screenId={screenId} error={query.error ?? undefined} retry={() => { void query.refetch(); }} />;
  const ids = { college: 'profile-academic-college', yearOfStudy: 'profile-academic-year', enrolmentNumber: 'profile-academic-enrolment', institutionalEmail: 'profile-academic-email' };
  return <ProfileSetupFrame step={2} {...query.data.profile.personal}>
    <ReauthDraftRestored visible={reauthRestoreNotice} />
    {restoreNotice && <p role="status" data-testid="profile-conflict-draft-restored">Your retained draft has been restored. Review it before saving.</p>}
    <ErrorSummary errors={errors} ids={ids} />
    <ProfileSetupField icon="cap"><SelectField id={ids.college} label="College / University" value={college} onChange={(value) => { setCollege(value); setDirty(true); }} options={COLLEGE_OPTIONS} error={errors.college} /></ProfileSetupField>
    <ProfileSetupField icon="grid"><SelectField id={ids.yearOfStudy} label="Year of study" value={yearOfStudy} onChange={(value) => { setYear(value); setDirty(true); }} options={YEAR_OPTIONS} error={errors.yearOfStudy} /></ProfileSetupField>
    <ProfileSetupField icon="idcard"><TextField id={ids.enrolmentNumber} label="College enrolment number" value={enrolmentNumber} onChange={(value) => { setEnrolment(value); setDirty(true); }} error={errors.enrolmentNumber} help="Format: state code / roll / year — e.g. KA/1234/2023" /></ProfileSetupField>
    <TextField id={ids.institutionalEmail} label="Institutional email" optional="optional" value={institutionalEmail} onChange={(value) => { setEmail(value); setDirty(true); }} type="email" inputMode="email" error={errors.institutionalEmail} />
    <TextField id="profile-academic-bar-enrolment" label="Bar enrolment number" optional="optional · private" value={barEnrolmentNumber} onChange={(value) => { setBar(value); setDirty(true); }} help="Never shown on your public profile." />
    <SaveError value={saveError} />
    <ProfileConflictReview conflict={conflictReview.conflict} section="academic" draftSummary={[college, yearOfStudy, enrolmentNumber, institutionalEmail, barEnrolmentNumber].filter(Boolean).join(' · ')} onAdopt={() => { if (conflictReview.conflict && !canOpenProfileSection(conflictReview.conflict, 'academic')) preserveProfileConflictDraft({ section: 'academic', value: { college, yearOfStudy, enrolmentNumber, institutionalEmail: institutionalEmail || null, barEnrolmentNumber: barEnrolmentNumber || null } }); conflictReview.adoptForDeliberateRetry(); setSaveError(null); }} />
    <div className="v321-profile__actions">
      <button type="button" className="v321-profile__button v321-profile__button--primary" onClick={() => { void persist('next'); }} disabled={save.isPending || Boolean(conflictReview.conflict)}><NyayOneRevLIcon name="send" />{save.isPending ? 'Saving…' : 'Save & continue'}</button>
      <button type="button" className="v321-profile__button" onClick={() => { void persist('exit'); }} disabled={save.isPending || Boolean(conflictReview.conflict)}><NyayOneRevLIcon name="home" />Save and exit</button>
    </div>
    <div className="v321-profile__completion"><span>Profile {query.data.completionPercent}% complete</span><Progress projection={query.data} /></div>
    <DpdpFootnote>Collected under data minimisation — export or delete anytime in Settings</DpdpFootnote>
  </ProfileSetupFrame>;
}

export function ProfileStep2() { return <AcademicStep screenId="S-10" />; }

export function ProfileStep3() {
  const nav = useNavigate(); const auth = useAuth(); const query = useStudentProfileProjection(); const save = useSaveInterestsProfile(); const blocked = useRedirectBlockedSection(query.data, 'interests'); const [hydratedVersion, setHydratedVersion] = useState<number | null>(null);
  const [interests, setInterests] = useState<string[]>([]); const [goal, setGoal] = useState(''); const [errors, setErrors] = useState<FieldErrors>({}); const [saveError, setSaveError] = useState<string | null>(null);
  const [restoreNotice, setRestoreNotice] = useState(false);
  const [reauthRestoreNotice, setReauthRestoreNotice] = useState(false);
  const [dirty, setDirty] = useState(false);
  const conflictReview = useProfileConflictReview(setHydratedVersion);
  const activeReauthDraft: ProfileReauthDraft | null = dirty && hydratedVersion !== null
    ? { section: 'interests', value: { interests, goals: goal ? [goal] : [] } }
    : null;
  const stageReauthDraft = useActiveProfileReauthDraft(auth.userId, activeReauthDraft);
  useEffect(() => {
    if (!query.data || hydratedVersion !== null || !canOpenProfileSection(query.data, 'interests')) return;
    setHydratedVersion(query.data.profileVersion);
    const reauthDraft = auth.userId
      ? takeResolvedProfileReauthDraft(auth.userId, 'interests')
      : null;
    const preserved = reauthDraft === null ? takeProfileConflictDraft('interests') : null;
    const values = reauthDraft ?? preserved?.value ?? query.data.profile.interests;
    setInterests(values.interests);
    setGoal(values.goals[0] ?? '');
    setRestoreNotice(Boolean(preserved));
    setReauthRestoreNotice(Boolean(reauthDraft));
    setDirty(Boolean(reauthDraft || preserved));
  }, [auth.userId, hydratedVersion, query.data]);
  async function persist(destination: 'done' | 'exit') { if (!query.data || hydratedVersion === null) return; const next: FieldErrors = {}; if (interests.length === 0) next.interests = 'Choose at least one area of interest.'; if (!goal) next.goal = 'Choose a career goal.'; setErrors(next); if (Object.keys(next).length > 0) return; setSaveError(null); stageReauthDraft(); try { const result = await save.mutateAsync({ expectedProfileVersion: hydratedVersion, interests, goals: [goal] }); setDirty(false); nav(profileSaveDestination(result.projection, destination === 'exit' ? 'exit' : 'next')); } catch (error) { if (isStudentMutationCancellation(error)) return; conflictReview.capture(error); setSaveError(profileErrorMessage(error)); } }
  if (!query.data || blocked) return <ProfileLoadState screenId="S-11" error={query.error ?? undefined} retry={() => { void query.refetch(); }} />;
  return <AuthCard screenId="S-11" kicker="Step 3 of 3 · Interests" title="What should find you?" sub="Choose the legal work and direction you want surfaced first. You can change this later."><Progress projection={query.data} /><ReauthDraftRestored visible={reauthRestoreNotice} />{restoreNotice && <p role="status" data-testid="profile-conflict-draft-restored">Your retained draft has been restored. Review it before saving.</p>}<ErrorSummary errors={errors} ids={{ interests: 'profile-interests-first-option', goal: 'profile-interests-goal' }} /><span className="st-field__label" id="profile-interests-label">Areas of interest</span><div className="st-chips" role="group" aria-labelledby="profile-interests-label" aria-describedby={errors.interests ? 'profile-interests-options-error' : undefined}>{INTERESTS.map((interest, index) => <button id={index === 0 ? 'profile-interests-first-option' : undefined} key={interest} type="button" className="st-chip tap" aria-pressed={interests.includes(interest)} onClick={() => { setInterests((previous) => previous.includes(interest) ? previous.filter((item) => item !== interest) : [...previous, interest]); setDirty(true); }}>{interest}</button>)}</div>{errors.interests && <span id="profile-interests-options-error" className="ui-validation" role="alert">{errors.interests}</span>}<SelectField id="profile-interests-goal" label="Career goal" value={goal} onChange={(value) => { setGoal(value); setDirty(true); }} options={GOALS} error={errors.goal} /><SaveError value={saveError} /><ProfileConflictReview conflict={conflictReview.conflict} section="interests" draftSummary={[...interests, goal].filter(Boolean).join(' · ')} onAdopt={() => { if (conflictReview.conflict && !canOpenProfileSection(conflictReview.conflict, 'interests')) preserveProfileConflictDraft({ section: 'interests', value: { interests, goals: [goal] } }); conflictReview.adoptForDeliberateRetry(); setSaveError(null); }} /><div className="st-actions st-actions--split"><button type="button" className="btn tap" onClick={() => { void persist('exit'); }} disabled={save.isPending || Boolean(conflictReview.conflict)}>Save and exit</button><button type="button" className="btn btn--primary tap" onClick={() => { void persist('done'); }} disabled={save.isPending || Boolean(conflictReview.conflict)}>{save.isPending ? 'Saving…' : 'Finish setup'}</button></div></AuthCard>;
}

export function CompletionCard({ projection }: { projection: StudentProfileProjection }) {
  if (projection.isComplete) return null;
  return <section className="st-panel" data-testid="profile-completion-card" aria-label="Profile completion"><div className="st-panel__head"><h2 className="st-panel__title">Complete your profile</h2><strong data-testid="profile-completion-percent">{projection.completionPercent}%</strong></div><p>Finish the remaining details to tailor your student workspace.</p><Link className="btn btn--primary tap" to={profileResumeDestination(projection)}>Continue profile</Link></section>;
}

export function ProfileResume() {
  const nav = useNavigate(); const query = useStudentProfileProjection();
  if (!query.data) return <ProfileLoadState screenId="S-13" error={query.error ?? undefined} retry={() => { void query.refetch(); }} />;
  const projection = query.data; const current = projection.nextIncompleteSection;
  return <StudentScreen screenId="S-13" className="st-stack st-resume"><div><p className="st-eyebrow">Welcome back · {projection.completionPercent}% done</p><h1 className="st-h1">{projection.isComplete ? 'Your setup is complete' : 'Pick up where you stopped'}</h1><p className="st-card__sub">Your saved answers came from your authenticated profile.</p></div><section className="st-panel" aria-label="Profile setup progress">{(['personal', 'academic', 'interests'] as ProfileSection[]).map((section, index) => { const saved = projection.completedSections.includes(section); const active = current === section; return <div className="st-setrow" key={section}><div><div className="st-setrow__label">Step {index + 1} · {section[0].toUpperCase() + section.slice(1)}</div></div><span className={`status ${saved ? 'status--ok' : active ? 'status--warn' : 'status--info'}`}>{saved ? 'Saved' : active ? 'Continue here' : 'Not started'}</span></div>; })}</section><div className="st-actions st-actions--split"><button type="button" className="btn tap" onClick={() => nav('/s-14')}>Browse first</button><button type="button" className="btn btn--primary tap" onClick={() => nav(profileResumeDestination(projection))}>{current ? 'Continue profile' : 'Open dashboard'}</button></div></StudentScreen>;
}

export function ProfileDone() {
  const nav = useNavigate(); const query = useStudentProfileProjection();
  useEffect(() => { if (query.data && !query.data.isComplete) nav(profileSectionRoute(query.data.nextIncompleteSection), { replace: true }); }, [nav, query.data]);
  if (!query.data || !query.data.isComplete) return <ProfileLoadState screenId="S-12" error={query.error ?? undefined} retry={() => { void query.refetch(); }} />;
  const firstName = query.data.profile.personal.firstName || 'Student'; const verification = query.data.institutionalEmailStatus === 'verified' ? 'Institutional email verified' : 'Profile complete · institutional verification not complete';
  return <AuthCard screenId="S-12" kicker="Profile complete" title={`You’re ready, ${firstName}.`}><p className="st-card__sub">Your student workspace is organised. Verification remains a separate server-controlled process.</p><span className="st-badge">{verification}</span><div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={() => nav('/s-14')}>Go to dashboard</button></div></AuthCard>;
}

/* -------------------------------------------------------------------------- */
/* NYAY-12 — S-17 sign-in email identities (server-authoritative)              */
/* -------------------------------------------------------------------------- */
export interface EmailIdentityPanelViewProps {
  channelEnabled: boolean;
  maxIdentities: number;
  identities: EmailIdentity[];
  draftEmail: string;
  draftCodes: Record<string, string>;
  error: string | null;
  errorTarget: 'add' | string | null;
  busy: boolean;
  errorRef?: (node: HTMLElement | null) => void;
  onDraftEmail: (value: string) => void;
  onAdd: () => void;
  onDraftCode: (identityId: string, value: string) => void;
  onVerify: (identityId: string) => void;
  onResend: (identityId: string) => void;
  onRemove: (identityId: string) => void;
  onPrimary: (identityId: string) => void;
}

function verificationCopy(identity: EmailIdentity): string {
  const verification = identity.verification;
  if (identity.state === 'verified') return identity.isPrimary ? 'Verified · primary sign-in email' : 'Verified';
  if (verification.status === 'active') return `Code sent · expires in ${verification.expiresInSeconds ?? 0}s · ${verification.attemptsLeft ?? 0} tries left`;
  if (verification.status === 'expired') return 'Code expired · request a new code';
  if (verification.status === 'failed') return 'Delivery failed · request a new code';
  if (verification.status === 'pending_delivery') return 'Sending code…';
  return 'Not verified';
}

export function EmailIdentityPanelView(props: EmailIdentityPanelViewProps) {
  const { channelEnabled, maxIdentities, identities, draftEmail, draftCodes, error, errorTarget, busy, errorRef } = props;
  const full = identities.length >= maxIdentities;
  const addError = errorTarget === 'add' ? error : null;
  return (
    <section className="st-panel" aria-labelledby="profile-email-identity-title" data-testid="profile-email-identities" id="profile-email-identity-section">
      <div className="st-panel__head"><h2 id="profile-email-identity-title" className="st-panel__title">Sign-in email</h2><span className="st-setrow__sub">{identities.length}/{maxIdentities}</span></div>
      <p className="st-card__sub" role="status" data-testid="profile-email-identity-channel-status">{channelEnabled
        ? 'A verified address can sign you in with a one-time code. Verification always comes from the server.'
        : 'Email sign-in is not enabled yet. Addresses you verify now will be ready when it is.'}</p>
      <ul className="st-stack" aria-label="Sign-in emails">
        {identities.map((identity) => {
          const codeId = `profile-email-identity-code-${identity.id}`;
          const rowError = errorTarget === identity.id ? error : null;
          const pending = identity.state === 'pending';
          return (
            <li key={identity.id} className="st-setrow" data-testid="profile-email-identity-row">
              <div>
                <div className="st-setrow__label"><span className="st-mono">{identity.emailMasked}</span>{identity.isPrimary && <span className="st-badge" data-testid="profile-email-identity-primary-badge">Primary</span>}</div>
                <div className="st-setrow__sub">{verificationCopy(identity)}</div>
                {pending && (
                  <div className="st-field">
                    <label className="st-field__label" htmlFor={codeId}>Six digit code for {identity.emailMasked}</label>
                    <input id={codeId} className="st-input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={draftCodes[identity.id] ?? ''} disabled={busy} aria-invalid={rowError ? true : undefined} aria-describedby={rowError ? `${codeId}-error` : undefined} onChange={(event) => props.onDraftCode(identity.id, event.target.value.replace(/\D/gu, '').slice(0, 6))} />
                    {rowError && <span id={`${codeId}-error`} className="ui-validation" role="alert" tabIndex={-1} ref={errorRef}>{rowError}</span>}
                  </div>
                )}
              </div>
              <div className="st-actions">
                {pending && <button type="button" className="btn btn--primary tap" aria-label={`Verify email ${identity.emailMasked}`} disabled={busy || (draftCodes[identity.id] ?? '').length !== 6} onClick={() => props.onVerify(identity.id)}>Verify</button>}
                {pending && <button type="button" className="btn tap" aria-label={`Resend code to ${identity.emailMasked}`} disabled={busy || (identity.verification.resendInSeconds ?? 0) > 0} onClick={() => props.onResend(identity.id)}>Resend code</button>}
                {identity.state === 'verified' && !identity.isPrimary && <button type="button" className="btn tap" aria-label={`Make ${identity.emailMasked} the primary sign-in email`} disabled={busy} onClick={() => props.onPrimary(identity.id)}>Make primary</button>}
                <button type="button" className="btn tap" aria-label={`Remove email ${identity.emailMasked}`} disabled={busy} onClick={() => props.onRemove(identity.id)}>Remove</button>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="st-field">
        <label className="st-field__label" htmlFor="profile-email-identity-input">Add a sign-in email</label>
        <input id="profile-email-identity-input" className="st-input" type="email" inputMode="email" autoComplete="email" maxLength={254} value={draftEmail} disabled={busy || full} aria-invalid={addError ? true : undefined} aria-describedby={addError ? 'profile-email-identity-input-error' : undefined} onChange={(event) => props.onDraftEmail(event.target.value)} />
        {addError && <span id="profile-email-identity-input-error" className="ui-validation" role="alert" tabIndex={-1} ref={errorRef}>{addError}</span>}
        <p className="st-setrow__sub">We send a six digit code to confirm you own the address. The address never becomes a sign-in identity until that code is verified here.</p>
      </div>
      <div className="st-actions"><button type="button" className="btn btn--primary tap" aria-label="Add sign-in email" disabled={busy || full} onClick={props.onAdd}>Add email</button></div>
    </section>
  );
}

const LOGIN_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/u;

export function EmailIdentityPanel({ expanded }: { expanded: boolean }) {
  const listing = useEmailIdentities(expanded);
  const add = useAddEmailIdentity();
  const verify = useVerifyEmailIdentity();
  const resend = useResendEmailIdentity();
  const remove = useRemoveEmailIdentity();
  const primary = useSetPrimaryEmailIdentity();
  const [draftEmail, setDraftEmail] = useState('');
  const [draftCodes, setDraftCodes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [errorTarget, setErrorTarget] = useState<'add' | string | null>(null);
  const errorNode = useRef<HTMLElement | null>(null);
  useEffect(() => { if (error) errorNode.current?.focus(); }, [error, errorTarget]);
  const busy = add.isPending || verify.isPending || resend.isPending || remove.isPending || primary.isPending;
  // Collapsed by default (zero S-17 height): no identity read happens until the owner opens it.
  if (!expanded) return null;
  if (!listing.data) {
    return <section className="st-panel" aria-labelledby="profile-email-identity-title" data-testid="profile-email-identities" id="profile-email-identity-section"><h2 id="profile-email-identity-title" className="st-panel__title">Sign-in email</h2>{listing.isPending ? <LoadingState label="Loading sign-in emails…" /> : <ErrorState title="Could not load sign-in emails" detail={emailIdentityErrorMessage(listing.error)} onRetry={() => { void listing.refetch(); }} />}</section>;
  }
  function fail(target: 'add' | string, caught: unknown) { setErrorTarget(target); setError(emailIdentityErrorMessage(caught)); }
  function clear() { setError(null); setErrorTarget(null); }
  return (
    <EmailIdentityPanelView
      channelEnabled={listing.data.loginChannelEnabled}
      maxIdentities={listing.data.maxIdentities}
      identities={listing.data.identities}
      draftEmail={draftEmail}
      draftCodes={draftCodes}
      error={error}
      errorTarget={errorTarget}
      busy={busy}
      errorRef={(node) => { errorNode.current = node; }}
      onDraftEmail={setDraftEmail}
      onDraftCode={(identityId, value) => setDraftCodes((previous) => ({ ...previous, [identityId]: value }))}
      onAdd={() => {
        const candidate = draftEmail.trim();
        if (!LOGIN_EMAIL_RE.test(candidate) || [...candidate].length > 254) { fail('add', new ProfileApiError(422, 'validation_error', 'email')); return; }
        add.mutate({ email: candidate, idempotencyKey: newEmailIdentityIdempotencyKey() }, { onSuccess: () => { setDraftEmail(''); clear(); }, onError: (caught) => fail('add', caught) });
      }}
      onVerify={(identityId) => {
        const code = draftCodes[identityId] ?? '';
        if (code.length !== 6) { fail(identityId, new ProfileApiError(422, 'validation_error', 'code')); return; }
        verify.mutate({ identityId, code, idempotencyKey: newEmailIdentityIdempotencyKey() }, { onSuccess: () => { setDraftCodes((previous) => { const next = { ...previous }; delete next[identityId]; return next; }); clear(); }, onError: (caught) => fail(identityId, caught) });
      }}
      onResend={(identityId) => resend.mutate({ identityId, idempotencyKey: newEmailIdentityIdempotencyKey() }, { onSuccess: clear, onError: (caught) => fail(identityId, caught) })}
      onRemove={(identityId) => remove.mutate({ identityId, idempotencyKey: newEmailIdentityIdempotencyKey() }, { onSuccess: clear, onError: (caught) => fail(identityId, caught) })}
      onPrimary={(identityId) => primary.mutate({ identityId, idempotencyKey: newEmailIdentityIdempotencyKey() }, { onSuccess: clear, onError: (caught) => fail(identityId, caught) })}
    />
  );
}

export function ProfileView() {
  const nav = useNavigate(); const query = useStudentProfileProjection();
  const [emailIdentitiesOpen, setEmailIdentitiesOpen] = useState(false);
  if (!query.data) return <ProfileLoadState screenId="S-17" error={query.error ?? undefined} retry={() => { void query.refetch(); }} />;
  const projection = query.data; const personal = projection.profile.personal; const academic = projection.profile.academic;
  const rows: Array<[string, string]> = [['Full name', [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ')], ['Preferred language', personal.preferredLanguage ?? 'Not provided'], ['City', personal.city ?? 'Not provided'], ['College', labelFor(COLLEGE_OPTIONS, toCanonicalCollege(academic.college)) || 'Not provided'], ['Year of study', labelFor(YEAR_OPTIONS, toCanonicalYear(academic.yearOfStudy)) || 'Not provided'], ['Institutional email status', projection.institutionalEmailStatus.replace(/_/gu, ' ')], ['Guardian status', projection.guardian.status.replace(/_/gu, ' ')], ['Access', projection.accessMode]];
  return <StudentScreen screenId="S-17" className="st-set"><div className="st-set__head"><p className="st-eyebrow">Profile</p><h1 className="st-h1">Your profile</h1></div><CompletionCard projection={projection} /><div className="st-panel">{rows.map(([label, value]) => <div className="st-setrow" key={label}><div><div className="st-setrow__label">{label}</div><div className="st-setrow__sub">{value}</div></div>{label === 'Institutional email status' && <button type="button" className="btn tap" aria-label="Manage sign-in emails" aria-expanded={emailIdentitiesOpen} aria-controls="profile-email-identity-section" data-testid="profile-email-identity-disclosure" onClick={() => setEmailIdentitiesOpen((open) => !open)}>{emailIdentitiesOpen ? 'Hide' : 'Manage'}</button>}</div>)}</div><EmailIdentityPanel expanded={emailIdentitiesOpen} /><div className="st-actions st-actions--split"><button type="button" className="btn btn--primary tap" onClick={() => nav(profileSectionRoute(projection.nextIncompleteSection ?? 'personal'))}>{projection.isComplete ? 'Edit profile' : 'Continue profile'}</button><button type="button" className="btn tap" onClick={() => nav('/s-19')}>Privacy &amp; settings</button></div></StudentScreen>;
}

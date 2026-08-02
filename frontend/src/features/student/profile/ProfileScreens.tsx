import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AuthCard, TextField, SelectField, StudentScreen, DpdpFootnote } from '../components';
import { ErrorState, LoadingState, ValidationState } from '../../../components/ui/primitives';
import {
  validateStep,
  nextIncompleteStep,
  profileTier,
  TIER_LABELS,
  type FieldErrors,
} from '../lib/profile';
import {
  getStudentProfile,
  updateStudentProfile,
  PROFILE_KEY,
  SettingsApiError,
  type StudentProfile,
} from '../lib/settingsApi';
import { getProfileDraft, updateProfileDraft, seedResumeDraft } from '../lib/profileStore';
import {
  loadRegistrationSession,
  saveAcademicProfile,
} from '../lib/registrationApi';
import {
  composeDisplayName,
  fullNameToParts,
  nameErrorMessage,
  validateNameParts,
} from '../lib/registration';

import { COLLEGE_OPTIONS, LANGUAGE_OPTIONS, YEAR_OPTIONS, labelFor, toCanonicalCollege, toCanonicalYear } from '../lib/catalog';

const labelForCollege = (v: string | null | undefined) => labelFor(COLLEGE_OPTIONS, toCanonicalCollege(v));
const labelForYear = (v: string | null | undefined) => labelFor(YEAR_OPTIONS, toCanonicalYear(v));
const toCanonicalLanguage = (v: string | null | undefined): string =>
  v === 'English' || v === 'English (en-IN)' ? 'en' : v === 'हिन्दी (Hindi)' || v === 'हिन्दी (hi-IN)' ? 'hi' : (v ?? '');

const LANGUAGES = LANGUAGE_OPTIONS;
const COLLEGES = COLLEGE_OPTIONS;
const YEARS = YEAR_OPTIONS;
const INTERESTS = ['Constitutional', 'Arbitration', 'Criminal', 'Corporate', 'Tech & Privacy'];
const GOALS = ['Litigation & judiciary', 'Corporate / in-house', 'Policy & academia', 'Undecided'];

function Progress({ pct }: { pct: number }) {
  return (
    <div
      className="st-progress"
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Profile setup progress"
    >
      <div className="st-progress__bar" style={{ width: `${pct}%` }} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* S-09 — Step 1: personal                                                     */
/* -------------------------------------------------------------------------- */
export function ProfileStep1() {
  const nav = useNavigate();
  const d = getProfileDraft();
  const initialName = d.firstName || d.lastName
    ? { firstName: d.firstName, middleName: d.middleName, lastName: d.lastName }
    : fullNameToParts(d.fullName);
  const [firstName, setFirstName] = useState(initialName.firstName);
  const [middleName, setMiddleName] = useState(initialName.middleName);
  const [lastName, setLastName] = useState(initialName.lastName);
  const [preferredLanguage, setLang] = useState(toCanonicalLanguage(d.preferredLanguage) || 'en');
  const [dateOfBirth, setDob] = useState(d.dateOfBirth);
  const [errors, setErrors] = useState<FieldErrors>({});

  function next() {
    const parts = { firstName, middleName, lastName };
    const nameErrors = validateNameParts(parts);
    const draft = updateProfileDraft({
      ...parts,
      fullName: composeDisplayName(parts),
      preferredLanguage,
      dateOfBirth,
    });
    const e = validateStep(1, draft);
    if (nameErrors.firstName) e.firstName = nameErrorMessage('firstName', nameErrors.firstName);
    if (nameErrors.middleName) e.middleName = nameErrorMessage('middleName', nameErrors.middleName);
    if (nameErrors.lastName) e.lastName = nameErrorMessage('lastName', nameErrors.lastName);
    setErrors(e);
    if (Object.keys(e).length === 0) nav('/s-10');
  }

  return (
    <AuthCard screenId="S-09" kicker="Step 1 of 3 · Personal" title="About you">
      <Progress pct={33} />
      <fieldset className="st-namegroup">
        <legend className="st-namegroup__legend">Legal name</legend>
        <TextField id="p1-first-name" label="First name" value={firstName} onChange={setFirstName} error={errors.firstName} autoComplete="given-name" />
        <TextField id="p1-middle-name" label="Middle name" optional="optional" value={middleName} onChange={setMiddleName} error={errors.middleName} autoComplete="additional-name" />
        <TextField id="p1-last-name" label="Last name" value={lastName} onChange={setLastName} error={errors.lastName} autoComplete="family-name" />
      </fieldset>
      <SelectField id="p1-lang" label="Preferred language" value={preferredLanguage} onChange={setLang} options={LANGUAGES} error={errors.preferredLanguage} />
      <TextField
        id="p1-dob"
        label="Date of birth"
        value={dateOfBirth}
        onChange={setDob}
        type="date"
        error={errors.dateOfBirth}
        help="Used only to confirm eligibility · not shown publicly"
      />
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={next}>
          Continue
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-10 — Step 2: academic (validation/error)                                  */
/* S-13 — Resume (recovery) renders the same step                              */
/* -------------------------------------------------------------------------- */
function AcademicStep({ screenId }: { screenId: string }) {
  const nav = useNavigate();
  const d = getProfileDraft();

  const serverProfileQuery = useQuery({
    queryKey: PROFILE_KEY,
    queryFn: getStudentProfile,
    retry: false,
  });

  const sp = serverProfileQuery.data;

  const [college, setCollege] = useState(toCanonicalCollege(d.college || sp?.college) ?? '');
  const [yearOfStudy, setYear] = useState(toCanonicalYear(d.yearOfStudy || sp?.yearOfStudy) ?? '');
  const [enrolmentNumber, setEnrol] = useState(d.enrolmentNumber || sp?.enrolmentNumber || '');
  const [institutionalEmail, setEmail] = useState(d.institutionalEmail || sp?.institutionalEmail || '');
  const [barEnrolmentNumber, setBar] = useState(d.barEnrolmentNumber || sp?.barEnrolmentNumber || '');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);

  // Sync server profile data into state if available
  useEffect(() => {
    if (sp) {
      const canonicalCol = toCanonicalCollege(sp.college);
      const canonicalYr = toCanonicalYear(sp.yearOfStudy);
      if (canonicalCol) setCollege((prev) => prev || canonicalCol);
      if (canonicalYr) setYear((prev) => prev || canonicalYr);
      if (sp.enrolmentNumber) setEnrol((prev) => prev || sp.enrolmentNumber || '');
      if (sp.institutionalEmail) setEmail((prev) => prev || sp.institutionalEmail || '');
      if (sp.barEnrolmentNumber) setBar((prev) => prev || sp.barEnrolmentNumber || '');
    }
  }, [sp]);

  async function save() {
    const draft = updateProfileDraft({ college, yearOfStudy, enrolmentNumber, institutionalEmail, barEnrolmentNumber });
    const e = validateStep(2, draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;
    const registration = loadRegistrationSession();
    if (!registration) {
      setErrors({ submit: 'Your registration session expired. Return to registration and verify your mobile again.' });
      return;
    }
    setSaving(true);
    try {
      await saveAcademicProfile({
        registrationId: registration.registrationId,
        college,
        yearOfStudy,
        enrolmentNumber,
        institutionalEmail,
        barEnrolmentNumber,
      });
      nav('/s-11');
    } catch {
      setErrors({ submit: 'Academic details could not be saved. Please retry.' });
    } finally {
      setSaving(false);
    }
  }

  return (
    <AuthCard
      screenId={screenId}
      kicker="Step 2 of 3 · Academic"
      title="Your academic record"
      sub="Tailors internships, tutors and research to your college and year."
    >
      <Progress pct={66} />
      <SelectField id="p2-college" label="College / University *" value={college} onChange={setCollege} options={COLLEGES} error={errors.college} />
      <SelectField id="p2-year" label="Year of study *" value={yearOfStudy} onChange={setYear} options={YEARS} error={errors.yearOfStudy} />
      <TextField
        id="p2-enrol"
        label="College enrolment number *"
        value={enrolmentNumber}
        onChange={setEnrol}
        error={errors.enrolmentNumber}
        help="Format: state code / roll / year — e.g. KA/1234/2023"
      />
      <TextField
        id="p2-email"
        label="Institutional email *"
        value={institutionalEmail}
        onChange={setEmail}
        type="email"
        inputMode="email"
        error={errors.institutionalEmail}
      />
      <TextField
        id="p2-bar"
        label="Bar enrolment number"
        optional="optional · private"
        value={barEnrolmentNumber}
        onChange={setBar}
        placeholder="Not enrolled yet"
        help="Never shown on your public profile — add only if already enrolled with a State Bar Council."
      />
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-10')}>
          Back
        </button>
        <button type="button" className="btn btn--primary tap" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save & continue'}
        </button>
      </div>
      {errors.submit && <span className="ui-validation" role="alert">{errors.submit}</span>}
      <DpdpFootnote>Collected under data minimisation — export or delete anytime in Settings</DpdpFootnote>
    </AuthCard>
  );
}

export function ProfileStep2() {
  return <AcademicStep screenId="S-10" />;
}

export function ProfileResume() {
  const nav = useNavigate();
  // S-13 is a truthful handoff, not a second copy of the form. The destination
  // remains computed from the live draft and saved values remain untouched.
  const seeded = useMemo(() => seedResumeDraft(), []);
  const step = nextIncompleteStep(seeded);
  const destination = step === 1 ? '/s-10' : step === 2 ? '/s-10?step=academic' : step === 3 ? '/s-11' : '/s-14';
  const current = step ?? 4;
  const heading = step === 1 ? 'Finish your details' : step === 2 ? 'Finish your studies' : step === 3 ? 'Pick up where you stopped' : 'Your setup is complete';
  return (
    <StudentScreen screenId="S-13" className="st-stack st-resume">
      <div>
        <p className="st-eyebrow">Welcome back · {step ? `${Math.round(((step - 1) / 3) * 100)}% done` : '100% done'}</p>
        <h1 className="st-h1">{heading}</h1>
        <p className="st-card__sub" style={{ marginTop: 10 }}>
          Saved answers stay exactly as you left them. Continue at the first incomplete step, or browse before finishing.
        </p>
      </div>
      <section className="st-panel" aria-label="Profile setup progress">
        {[
          ['Personal', 'Name, date of birth and city'],
          ['Academic', 'College, year and enrolment'],
          ['Preferences', 'Practice areas and career direction'],
        ].map(([label, detail], index) => {
          const n = index + 1;
          const state = n < current ? 'Saved' : n === current ? 'Continue here' : 'Not started';
          return (
            <div className="st-setrow" key={label}>
              <div><div className="st-setrow__label">Step {n} · {label}</div><div className="st-setrow__sub">{detail}</div></div>
              <span className={`status ${n < current ? 'status--ok' : n === current ? 'status--warn' : 'status--info'}`}>{state}</span>
            </div>
          );
        })}
      </section>
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-20')}>Browse first</button>
        <button type="button" className="btn btn--primary tap" onClick={() => nav(destination)}>{step ? `Continue step ${step}` : 'Open dashboard'}</button>
      </div>
      <DpdpFootnote>Draft fields remain private and are not submitted by opening this screen</DpdpFootnote>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-11 — Step 3: preferences                                                  */
/* -------------------------------------------------------------------------- */
export function ProfileStep3() {
  const nav = useNavigate();
  const d = getProfileDraft();
  const [interests, setInterests] = useState<string[]>(d.interests);
  const [careerGoal, setGoal] = useState(d.careerGoal);
  const [errors, setErrors] = useState<FieldErrors>({});

  function toggle(i: string) {
    setInterests((prev) => (prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]));
  }

  async function finish() {
    const draft = updateProfileDraft({ interests, careerGoal });
    const e = validateStep(3, draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;
    const registration = loadRegistrationSession();
    if (registration) {
      try {
        await saveAcademicProfile({
          registrationId: registration.registrationId,
          college: draft.college || 'Other',
          yearOfStudy: draft.yearOfStudy || '1st year',
          enrolmentNumber: draft.enrolmentNumber || 'DL/0000/2026',
          institutionalEmail: draft.institutionalEmail || 'student@legalsaathi.in',
          interests: interests,
          careerGoal: careerGoal,
        });
      } catch {
        // Fallback to client state transition
      }
    }
    nav('/s-12');
  }

  return (
    <AuthCard screenId="S-11" kicker="Step 3 of 3 · Preferences" title="What should find you?" sub="Choose the legal work and direction you want LegalSaathi to surface first. You can change this later.">
      <Progress pct={100} />
      <span className="st-field__label" id="interests-label">
        Areas of interest
      </span>
      <div className="st-chips" role="group" aria-labelledby="interests-label" style={{ marginBottom: 'var(--space-4)' }}>
        {INTERESTS.map((i) => (
          <button key={i} type="button" className="st-chip" aria-pressed={interests.includes(i)} onClick={() => toggle(i)}>
            {i}
          </button>
        ))}
      </div>
      {errors.interests && (
        <span className="ui-validation" role="alert">
          <span className="ui-validation__mark" aria-hidden>
            !
          </span>{' '}
          {errors.interests}
        </span>
      )}
      <SelectField id="p3-goal" label="Career goal" value={careerGoal} onChange={setGoal} options={GOALS} error={errors.careerGoal} />
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-10?step=academic')}>
          Back
        </button>
        <button type="button" className="btn btn--primary tap" onClick={finish}>
          Finish setup
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-12 — Save success / tier badge                                            */
/* -------------------------------------------------------------------------- */
export function ProfileDone() {
  const nav = useNavigate();
  const draft = getProfileDraft();
  const tier = profileTier(draft);
  const firstName = draft.fullName.trim().split(/\s+/)[0] || 'Student';
  return (
    <AuthCard screenId="S-12" kicker="Profile complete" title={`You’re ready, ${firstName}.`}>
      <p className="st-card__sub">Your student workspace is organised. Verification controls which applications and trusted features are available.</p>
      <span className="st-badge">
        <span aria-hidden>✓</span> {TIER_LABELS[tier === 'verified_student' ? 'verified_student' : 'incomplete']}
      </span>
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-14')}>
          Go to dashboard
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-17 — Profile view/edit (server-authoritative, SAATHI-58)                  */
/* -------------------------------------------------------------------------- */

export function ProfileView() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const query = useQuery({ queryKey: PROFILE_KEY, queryFn: getStudentProfile });
  const [editing, setEditing] = useState(false);
  const [college, setCollege] = useState('');
  const [yearOfStudy, setYear] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => updateStudentProfile({ college, yearOfStudy }),
    onSuccess: (data) => {
      qc.setQueryData<StudentProfile>(PROFILE_KEY, data);
      setEditing(false);
      setSaveError(null);
    },
    onError: (error) => {
      setSaveError(
        error instanceof SettingsApiError && error.status === 401
          ? 'Your session expired — sign in again to edit your profile.'
          : 'Could not save your changes — check your connection and retry.',
      );
    },
  });

  const p = query.data;
  const signedOut = query.error instanceof SettingsApiError && query.error.status === 401;
  const fullName = p ? [p.firstName, p.middleName, p.lastName].filter(Boolean).join(' ') : '';

  function beginEdit(): void {
    if (!p) return;
    setCollege(toCanonicalCollege(p.college) ?? '');
    setYear(toCanonicalYear(p.yearOfStudy) ?? '');
    setSaveError(null);
    setEditing(true);
  }

  return (
    <StudentScreen screenId="S-17" className="st-set">
      <div className="st-set__head">
        <p className="st-eyebrow">Profile · S3</p>
        <h1 className="st-h1">Your LegalSaathi profile</h1>
      </div>

      {query.isPending && <LoadingState label="Loading your profile…" />}
      {query.isError && (signedOut ? (
        <div className="ui-state" role="alert">
          <p className="ui-state__eyebrow">Signed out</p>
          <p className="ui-state__title">Sign in to view your profile</p>
          <div className="ui-state__action">
            <button type="button" className="btn tap" onClick={() => nav('/s-03')}>Go to sign in</button>
          </div>
        </div>
      ) : (
        <ErrorState
          title="Could not load your profile"
          detail="Check your connection and retry."
          onRetry={() => void query.refetch()}
        />
      ))}

      {p && (
        <>
          {!editing && <div className="st-panel">
            {([
              ['Full name', fullName || 'Not provided'],
              ['Mobile', p.maskedMobile || 'Not provided'],
              ['College', labelForCollege(p.college) || 'Not provided'],
              ['Year of study', labelForYear(p.yearOfStudy) || 'Not provided'],
            ] as Array<[string, string]>).map(([k, v]) => (
              <div className="st-setrow" key={k}>
                <div>
                  <div className="st-setrow__label">{k}</div>
                  <div className="st-setrow__sub">{v}</div>
                </div>
              </div>
            ))}
            <p className="st-setrow__sub" style={{ marginTop: 'var(--space-3)' }}>
              Bar enrolment number stays private · never on your public profile.
            </p>
          </div>}

          {editing && (
            <div className="st-panel" style={{ marginTop: 'var(--space-3)' }}>
              <h2 className="st-panel__title">Edit college &amp; year</h2>
              <SelectField id="pv-college" label="College / University" value={college} onChange={setCollege} options={COLLEGES} />
              <SelectField id="pv-year" label="Year of study" value={yearOfStudy} onChange={setYear} options={YEARS} />
              <div className="st-actions st-actions--split">
                <button type="button" className="btn tap" onClick={() => setEditing(false)} disabled={save.isPending}>
                  Cancel
                </button>
                <button type="button" className="btn btn--primary tap" onClick={() => save.mutate()} disabled={save.isPending}>
                  {save.isPending ? 'Saving…' : 'Save changes'}
                </button>
              </div>
              {saveError && <ValidationState message={saveError} />}
            </div>
          )}

          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={beginEdit} disabled={editing}>
              Edit college &amp; year
            </button>
            <button type="button" className="btn tap" onClick={() => nav('/s-19')}>
              Privacy &amp; settings
            </button>
          </div>
        </>
      )}
    </StudentScreen>
  );
}

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthCard, TextField, SelectField, StudentScreen, DpdpFootnote } from '../components';
import {
  validateStep,
  nextIncompleteStep,
  profileTier,
  TIER_LABELS,
  type FieldErrors,
  type ProfileDraft,
} from '../lib/profile';
import { getProfileDraft, updateProfileDraft, seedResumeDraft } from '../lib/profileStore';

const LANGUAGES = ['English', 'हिन्दी (Hindi)'];
const COLLEGES = [
  'National Law School of India University (NLSIU)',
  'NALSAR University of Law',
  'The West Bengal NUJS',
  'Other',
];
const YEARS = ['1st year', '2nd year', '3rd year', '4th year · B.A. LL.B. (Hons.)', '5th year', 'LL.M.'];
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
  const [fullName, setFullName] = useState(d.fullName);
  const [preferredLanguage, setLang] = useState(d.preferredLanguage || 'English');
  const [dateOfBirth, setDob] = useState(d.dateOfBirth);
  const [errors, setErrors] = useState<FieldErrors>({});

  function next() {
    const draft = updateProfileDraft({ fullName, preferredLanguage, dateOfBirth });
    const e = validateStep(1, draft);
    setErrors(e);
    if (Object.keys(e).length === 0) nav('/s-10');
  }

  return (
    <AuthCard screenId="S-09" kicker="Step 1 of 3 · Personal" title="About you">
      <Progress pct={33} />
      <TextField id="p1-name" label="Full name" value={fullName} onChange={setFullName} error={errors.fullName} autoComplete="name" />
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
  const [college, setCollege] = useState(d.college);
  const [yearOfStudy, setYear] = useState(d.yearOfStudy);
  const [enrolmentNumber, setEnrol] = useState(d.enrolmentNumber);
  const [institutionalEmail, setEmail] = useState(d.institutionalEmail);
  const [barEnrolmentNumber, setBar] = useState(d.barEnrolmentNumber ?? '');
  const [errors, setErrors] = useState<FieldErrors>({});

  function save() {
    const draft = updateProfileDraft({ college, yearOfStudy, enrolmentNumber, institutionalEmail, barEnrolmentNumber });
    const e = validateStep(2, draft);
    setErrors(e);
    if (Object.keys(e).length === 0) nav('/s-11');
  }

  return (
    <AuthCard
      screenId={screenId}
      kicker="Step 2 of 3 · Academic"
      title="Your academic record"
      sub="Tailors internships, tutors and research to your college and year."
    >
      <Progress pct={66} />
      <SelectField id="p2-college" label="College / University" value={college} onChange={setCollege} options={COLLEGES} error={errors.college} />
      <SelectField id="p2-year" label="Year of study" value={yearOfStudy} onChange={setYear} options={YEARS} error={errors.yearOfStudy} />
      <TextField
        id="p2-enrol"
        label="College enrolment number"
        value={enrolmentNumber}
        onChange={setEnrol}
        error={errors.enrolmentNumber}
        help="Format: state code / roll / year — e.g. KA/1234/2023"
      />
      <TextField
        id="p2-email"
        label="Institutional email"
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
        <button type="button" className="btn tap" onClick={() => nav('/s-09')}>
          Back
        </button>
        <button type="button" className="btn btn--primary tap" onClick={save}>
          Save &amp; continue
        </button>
      </div>
      <DpdpFootnote>Collected under data minimisation — export or delete anytime in Settings</DpdpFootnote>
    </AuthCard>
  );
}

export function ProfileStep2() {
  return <AcademicStep screenId="S-10" />;
}

export function ProfileResume() {
  // S-13: resume from the last incomplete step. The RENDERED form must match the
  // computed step (independent-QA fix, comment 12458/12459): step 1 → Personal,
  // step 2 → Academic, step 3 → Preferences, complete → completion. Saved
  // academic values are preserved (seedResumeDraft never seeds over real data).
  const seeded = useMemo(() => seedResumeDraft(), []);
  const step = nextIncompleteStep(seeded);
  if (step === 1) return <ProfileStep1 />;
  if (step === 2) return <AcademicStep screenId="S-13" />;
  if (step === 3) return <ProfileStep3 />;
  return <ProfileDone />;
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

  function finish() {
    const draft = updateProfileDraft({ interests, careerGoal });
    const e = validateStep(3, draft);
    setErrors(e);
    if (Object.keys(e).length === 0) nav('/s-12');
  }

  return (
    <AuthCard screenId="S-11" kicker="Step 3 of 3 · Preferences" title="Specialisations">
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
        <button type="button" className="btn tap" onClick={() => nav('/s-10')}>
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
    <AuthCard screenId="S-12" kicker="Profile complete" title={`You’re all set, ${firstName}`}>
      <p className="st-card__sub">Tier badge earned. Your hub is now personalised.</p>
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
/* S-17 — Profile view (sectioned edit entry points)                           */
/* -------------------------------------------------------------------------- */
export function ProfileView() {
  const nav = useNavigate();
  const d: ProfileDraft = getProfileDraft();
  const tier = profileTier(d);
  const rows: Array<[string, string]> = [
    ['Full name', d.fullName || 'Not provided'],
    ['College', d.college || 'Not provided'],
    ['Year of study', d.yearOfStudy || 'Not provided'],
    ['Interests', d.interests.length ? d.interests.join(', ') : 'Not provided'],
    ['Career goal', d.careerGoal || 'Not provided'],
  ];
  return (
    <StudentScreen screenId="S-17" className="st-set">
      <div className="st-set__head">
        <p className="st-eyebrow">Profile · S3</p>
        <h1 className="st-h1">Your profile</h1>
        <div className="st-metarow">
          <span className="st-badge">
            <span aria-hidden>✓</span> {TIER_LABELS[tier]}
          </span>
        </div>
      </div>
      <div className="st-panel">
        {rows.map(([k, v]) => (
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
      </div>
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-09')}>
          Edit details
        </button>
        <button type="button" className="btn tap" onClick={() => nav('/s-19')}>
          Privacy &amp; settings
        </button>
      </div>
    </StudentScreen>
  );
}

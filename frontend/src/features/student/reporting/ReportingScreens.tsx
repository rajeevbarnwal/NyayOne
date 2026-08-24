import { useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  captureStudentMutationSequence,
  isStudentMutationCancellation,
  runStudentMutationStep,
  useStudentMutation as useMutation,
} from '../lib/useStudentMutation';
import { Checkbox, InfoTooltip, StudentScreen, TextField } from '../components';
import {
  REPORT_CATEGORIES,
  createInternshipReport,
  getInternshipReport,
  getInternshipReportStatus,
  listInternshipReports,
  reportingErrorCopy,
  submitInternshipReport,
  updateInternshipReport,
  uploadInternshipReportEvidence,
  type InternshipReport,
  type ReportCategory,
  type ReportDraftInput,
  type ReportPrivacyMode,
} from '../lib/reportingApi';

const CONSENT_VERSION = 'internship-report-v1';
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_FILES = 5;
const ALLOWED_FILE_TYPES = new Set(['application/pdf', 'image/png', 'image/jpeg']);
const ALLOWED_FILE_EXTENSION = /\.(pdf|png|jpe?g)$/i;

type FieldErrors = Partial<Record<
  'organisation' | 'reference' | 'start' | 'end' | 'categories' | 'narrative' | 'privacy' | 'consent' | 'evidence',
  string
>>;

interface DraftState {
  organisationName: string;
  listingApplicationRef: string;
  experienceStartDate: string;
  experienceEndDate: string;
  categories: ReportCategory[];
  narrative: string;
  privacyMode: ReportPrivacyMode;
  consentAccepted: boolean;
}

const EMPTY_DRAFT: DraftState = {
  organisationName: '',
  listingApplicationRef: '',
  experienceStartDate: '',
  experienceEndDate: '',
  categories: [],
  narrative: '',
  privacyMode: 'anonymous',
  consentAccepted: false,
};

function reportToDraft(report: InternshipReport): DraftState {
  return {
    organisationName: report.organisationName,
    listingApplicationRef: report.listingApplicationRef,
    experienceStartDate: report.experienceStartDate ?? '',
    experienceEndDate: report.experienceEndDate ?? '',
    categories: report.categories,
    narrative: report.narrative,
    privacyMode: report.privacyMode,
    consentAccepted: report.consentAccepted && report.consentVersion === CONSENT_VERSION,
  };
}

function draftPayload(draft: DraftState): ReportDraftInput {
  return {
    ...draft,
    consentVersion: CONSENT_VERSION,
  };
}

function validateDraft(draft: DraftState, today: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!draft.organisationName.trim()) errors.organisation = 'Enter the organisation name.';
  if (!draft.listingApplicationRef.trim()) errors.reference = 'Enter the listing or application reference.';
  if (!draft.experienceStartDate) errors.start = 'Enter the experience start date.';
  else if (draft.experienceStartDate > today) errors.start = 'The start date cannot be in the future.';
  if (!draft.experienceEndDate) errors.end = 'Enter the experience end date.';
  else if (draft.experienceEndDate > today) errors.end = 'The end date cannot be in the future.';
  else if (draft.experienceStartDate && draft.experienceEndDate < draft.experienceStartDate) {
    errors.end = 'The end date cannot be before the start date.';
  }
  if (draft.categories.length === 0) errors.categories = 'Choose at least one category.';
  const narrativeLength = draft.narrative.trim().length;
  if (narrativeLength < 50 || narrativeLength > 5000) {
    errors.narrative = 'Use 50–5,000 characters for the factual account.';
  }
  if (!['anonymous', 'private_to_platform'].includes(draft.privacyMode)) {
    errors.privacy = 'Choose a privacy option.';
  }
  if (!draft.consentAccepted) errors.consent = 'Review and accept the private-reporting consent notice.';
  return errors;
}

function validateFiles(files: File[], existingCount: number): string | null {
  if (existingCount + files.length > MAX_FILES) return 'You may attach up to five evidence files.';
  const tooLarge = files.find((file) => file.size > MAX_FILE_BYTES);
  if (tooLarge) return `${tooLarge.name} is larger than 5 MiB.`;
  const unsupported = files.find((file) => !ALLOWED_FILE_TYPES.has(file.type) || !ALLOWED_FILE_EXTENSION.test(file.name));
  if (unsupported) return `${unsupported.name} must be a PDF, PNG, JPG or JPEG file.`;
  return null;
}

function statusCopy(status: string): string {
  const values: Record<string, string> = {
    draft: 'Draft — only you can see it.',
    moderation_pending: 'Submitted privately for moderation.',
    under_review: 'A trained reviewer is assessing the report.',
    actioned: 'Review completed and the outcome was recorded.',
    closed: 'The private reporting workflow is closed.',
  };
  return values[status] ?? status.replace(/_/g, ' ');
}

function ReportHeader({ title, intro }: { title: string; intro: string }) {
  return (
    <header className="ir-hero">
      <div>
        <p className="ir-eyebrow">Internship safety · private reporting</p>
        <h1>{title}</h1>
        <p>{intro}</p>
      </div>
      <div className="ir-trust" aria-label="Private reporting safeguards active">
        <span aria-hidden>◈</span>
        <div><strong>Private by design</strong><small>No public organisation label is created.</small></div>
      </div>
    </header>
  );
}

export function InternshipReportCreate() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [editing, setEditing] = useState<InternshipReport | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [message, setMessage] = useState('');
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const reports = useQuery({
    queryKey: ['internship-reports'],
    queryFn: listInternshipReports,
    retry: false,
  });

  const save = useMutation({
    mutationFn: async ({ submit }: { submit: boolean }) => {
      const fence = captureStudentMutationSequence();
      let report = editing
        ? await runStudentMutationStep(
          fence,
          () => updateInternshipReport(editing.id, editing.version, draftPayload(draft)),
        )
        : await runStudentMutationStep(fence, () => createInternshipReport(draftPayload(draft)));
      for (const file of files) {
        await runStudentMutationStep(
          fence,
          () => uploadInternshipReportEvidence(report.id, report.version, file),
        );
        report = await runStudentMutationStep(fence, () => getInternshipReport(report.id));
      }
      return submit
        ? runStudentMutationStep(fence, () => submitInternshipReport(report.id, report.version))
        : report;
    },
    onSuccess: async (report, variables) => {
      const fence = captureStudentMutationSequence();
      try {
        await runStudentMutationStep(
          fence,
          () => client.invalidateQueries({ queryKey: ['internship-reports'] }),
        );
      } catch (error) {
        if (isStudentMutationCancellation(error)) return;
        throw error;
      }
      setEditing(report);
      setFiles([]);
      if (fileInput.current) fileInput.current.value = '';
      if (variables.submit) {
        navigate(`/s-87?report=${encodeURIComponent(report.id)}`);
      } else {
        setMessage('Draft saved privately. You can return and continue later.');
      }
    },
    onError: (error) => setMessage(reportingErrorCopy(error)),
  });

  const set = <K extends keyof DraftState>(key: K, value: DraftState[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key === 'listingApplicationRef' ? 'reference' : key === 'organisationName' ? 'organisation' : key === 'experienceStartDate' ? 'start' : key === 'experienceEndDate' ? 'end' : key]: undefined }));
    setMessage('');
  };

  const chooseFiles = (selected: File[]) => {
    const error = validateFiles(selected, editing?.evidence.length ?? 0);
    setErrors((current) => ({ ...current, evidence: error ?? undefined }));
    setFiles(error ? [] : selected);
  };

  const runSave = (submit: boolean) => {
    setMessage('');
    if (submit) {
      const next = validateDraft(draft, today);
      const evidenceError = validateFiles(files, editing?.evidence.length ?? 0);
      if (evidenceError) next.evidence = evidenceError;
      setErrors(next);
      if (Object.keys(next).length) return;
    }
    save.mutate({ submit });
  };

  const resume = (report: InternshipReport) => {
    setEditing(report);
    setDraft(reportToDraft(report));
    setFiles([]);
    setErrors({});
    setMessage(`Resumed private draft for ${report.organisationName || 'an unnamed organisation'}.`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const toggleCategory = (category: ReportCategory, checked: boolean) => {
    set('categories', checked
      ? [...new Set([...draft.categories, category])]
      : draft.categories.filter((value) => value !== category));
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    runSave(true);
  };

  return (
    <StudentScreen screenId="S-86" className="st-internship-reporting">
      <main className="ir-shell">
        <ReportHeader
          title="Share an internship experience safely"
          intro="Create a factual, private report. It is visible only to authorised NyayOne reviewers and is never published automatically."
        />
        <nav className="ir-tabs" aria-label="Private report steps">
          <Link to="/s-86" aria-current="page">Create report</Link>
          <Link to={editing ? `/s-87?report=${encodeURIComponent(editing.id)}` : '/s-87'}>Track status</Link>
        </nav>

        {draft.categories.some((category) => ['unsafe_environment', 'harassment', 'discrimination'].includes(category)) && (
          <aside className="ir-support" role="note">
            <strong>Immediate support is available.</strong>
            <span>If anyone is in immediate danger, contact local emergency services. You may save this report and seek a trusted person or institutional support.</span>
          </aside>
        )}

        <form className="ir-form" onSubmit={onSubmit} noValidate>
          <section className="ir-section" aria-labelledby="ir-experience-title">
            <div className="ir-section__head"><span>1</span><div><h2 id="ir-experience-title">Experience details</h2><p>Identify the placement without adding another person’s private data.</p></div></div>
            <div className="ir-two">
              <TextField id="ir-organisation" label="Organisation name" value={draft.organisationName} onChange={(value) => set('organisationName', value)} maxLength={160} error={errors.organisation} />
              <TextField id="ir-reference" label="Listing or application reference" value={draft.listingApplicationRef} onChange={(value) => set('listingApplicationRef', value)} maxLength={120} error={errors.reference} />
              <TextField id="ir-start" label="Experience start date" type="date" value={draft.experienceStartDate} onChange={(value) => set('experienceStartDate', value)} max={today} error={errors.start} />
              <TextField id="ir-end" label="Experience end date" type="date" value={draft.experienceEndDate} onChange={(value) => set('experienceEndDate', value)} max={today} error={errors.end} />
            </div>
          </section>

          <section className="ir-section" aria-labelledby="ir-category-title">
            <div className="ir-section__head"><span>2</span><div><h2 id="ir-category-title">What describes the experience?</h2><p>Choose every category that applies.</p></div></div>
            <div className="ir-category-grid" aria-describedby={errors.categories ? 'ir-categories-error' : undefined}>
              {REPORT_CATEGORIES.map(([value, label]) => (
                <Checkbox key={value} id={`ir-category-${value}`} label={label} checked={draft.categories.includes(value)} onChange={(checked) => toggleCategory(value, checked)} />
              ))}
            </div>
            {errors.categories && <p className="ir-error" role="alert" id="ir-categories-error">{errors.categories}</p>}
          </section>

          <section className="ir-section" aria-labelledby="ir-account-title">
            <div className="ir-section__head"><span>3</span><div><h2 id="ir-account-title">Factual account</h2><p>Describe what happened, when it happened and what outcome you seek.</p></div></div>
            <label className="st-field" htmlFor="ir-narrative">
              <span className="st-field__label">Your private account</span>
              <textarea
                id="ir-narrative"
                className="st-input ir-narrative"
                value={draft.narrative}
                maxLength={5000}
                aria-invalid={errors.narrative ? true : undefined}
                aria-describedby={errors.narrative ? 'ir-narrative-error ir-narrative-count' : 'ir-narrative-count'}
                onChange={(event) => set('narrative', event.target.value)}
              />
              <span className="st-field__help" id="ir-narrative-count">{draft.narrative.trim().length} / 5,000 · minimum 50 characters</span>
              {errors.narrative && <span className="ir-error" role="alert" id="ir-narrative-error">{errors.narrative}</span>}
            </label>
          </section>

          <section className="ir-section" aria-labelledby="ir-evidence-title">
            <div className="ir-section__head"><span>4</span><div><h2 id="ir-evidence-title">Evidence</h2><p>Optional files stay quarantined until malware screening passes.</p></div></div>
            <label className="ir-file" htmlFor="ir-evidence">
              <strong>Attach PDF, PNG, JPG or JPEG</strong>
              <span>Up to five files · 5 MiB each · never published with the report</span>
              <input
                ref={fileInput}
                id="ir-evidence"
                type="file"
                multiple
                accept="application/pdf,image/png,image/jpeg,.pdf,.png,.jpg,.jpeg"
                aria-describedby={errors.evidence ? 'ir-evidence-error' : undefined}
                onChange={(event) => chooseFiles(Array.from(event.target.files ?? []))}
              />
            </label>
            {files.length > 0 && <ul className="ir-files">{files.map((file) => <li key={`${file.name}-${file.size}`}>{file.name} · {(file.size / 1024).toFixed(1)} KiB</li>)}</ul>}
            {(editing?.evidence.length ?? 0) > 0 && <p className="ir-file-state">{editing?.evidence.length} previously attached file(s) passed private screening.</p>}
            {errors.evidence && <p className="ir-error" role="alert" id="ir-evidence-error">{errors.evidence}</p>}
          </section>

          <section className="ir-section" aria-labelledby="ir-privacy-title">
            <div className="ir-section__head"><span>5</span><div><h2 id="ir-privacy-title">Privacy and consent</h2><p>Choose how authorised reviewers may handle reporter identity.</p></div></div>
            <fieldset className="ir-privacy">
              <legend>
                Privacy mode
                <InfoTooltip label="About reporting privacy" text="Anonymous mode keeps identity encrypted and separated from the report. Private-to-platform mode permits authorised internal follow-up. Neither mode publishes your identity or creates a public risk label." />
              </legend>
              <label><input type="radio" name="privacy" value="anonymous" checked={draft.privacyMode === 'anonymous'} onChange={() => set('privacyMode', 'anonymous')} /><span><strong>Anonymous to reviewers</strong><small>Identity remains encrypted and separated; exceptional access requires two authorised approvals and a recorded reason.</small></span></label>
              <label><input type="radio" name="privacy" value="private_to_platform" checked={draft.privacyMode === 'private_to_platform'} onChange={() => set('privacyMode', 'private_to_platform')} /><span><strong>Private follow-up allowed</strong><small>An authorised NyayOne reviewer may contact you privately about this report.</small></span></label>
            </fieldset>
            {errors.privacy && <p className="ir-error" role="alert">{errors.privacy}</p>}
            <Checkbox
              id="ir-consent"
              checked={draft.consentAccepted}
              onChange={(checked) => set('consentAccepted', checked)}
              label="I consent to NyayOne processing this private report and evidence for moderation, support and safeguarding under the internship-report-v1 notice."
            />
            {errors.consent && <p className="ir-error" role="alert">{errors.consent}</p>}
          </section>

          {message && <p className={save.isError ? 'ir-banner ir-banner--error' : 'ir-banner'} role={save.isError ? 'alert' : 'status'}>{message}</p>}
          <div className="ir-actions">
            <button className="btn" type="button" disabled={save.isPending} onClick={() => runSave(false)}>Save private draft</button>
            <button className="btn btn--primary" type="submit" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Submit privately'}</button>
          </div>
        </form>

        <section className="ir-drafts" aria-labelledby="ir-drafts-title">
          <div><p className="ir-eyebrow">Your reports</p><h2 id="ir-drafts-title">Continue or track</h2></div>
          {reports.isLoading && <p role="status">Loading private drafts…</p>}
          {reports.isError && <p className="ir-error" role="alert">Private drafts could not load. <button className="btn" type="button" onClick={() => reports.refetch()}>Retry</button></p>}
          {reports.data?.length === 0 && <p>No saved reports yet.</p>}
          <div className="ir-draft-list">
            {reports.data?.map((report) => (
              <article key={report.id}>
                <div><strong>{report.organisationName || 'Unnamed organisation'}</strong><small>{statusCopy(report.status)}</small></div>
                {report.status === 'draft'
                  ? <button className="btn" type="button" onClick={() => resume(report)}>Resume draft</button>
                  : <Link className="btn" to={`/s-87?report=${encodeURIComponent(report.id)}`}>Track status</Link>}
              </article>
            ))}
          </div>
        </section>
        <p className="ir-foot">Public organisation risk labels are disabled. This workflow does not publish allegations or infer a public score.</p>
      </main>
    </StudentScreen>
  );
}

export function InternshipReportStatus() {
  const [params] = useSearchParams();
  const reportId = params.get('report') ?? '';
  const report = useQuery({
    queryKey: ['internship-report-status', reportId],
    queryFn: () => getInternshipReportStatus(reportId),
    enabled: Boolean(reportId),
    retry: false,
  });
  const submitted = report.data?.submittedAt
    ? new Date(report.data.submittedAt).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
    : 'Not submitted';

  return (
    <StudentScreen screenId="S-87" className="st-internship-reporting">
      <main className="ir-shell">
        <ReportHeader title="Track your private report" intro="Only the signed-in reporter can view this status. Organisation labels remain disabled." />
        <nav className="ir-tabs" aria-label="Private report steps">
          <Link to="/s-86">Create report</Link><Link to={`/s-87${reportId ? `?report=${encodeURIComponent(reportId)}` : ''}`} aria-current="page">Track status</Link>
        </nav>
        {!reportId && (
          <section className="ir-state">
            <span aria-hidden>◇</span><h2>Select a private report</h2><p>Open a submitted report from the create-report screen to track its moderation status.</p><Link className="btn btn--primary" to="/s-86">View my reports</Link>
          </section>
        )}
        {report.isLoading && <section className="ir-state" role="status" aria-busy="true"><span aria-hidden>◌</span><h2>Loading private status…</h2></section>}
        {report.isError && <section className="ir-state ir-state--error" role="alert"><span aria-hidden>!</span><h2>Status unavailable</h2><p>{reportingErrorCopy(report.error)}</p><button className="btn" type="button" onClick={() => report.refetch()}>Retry</button></section>}
        {report.data && (
          <>
            <section className="ir-status-card">
              <div className="ir-status-card__mark" aria-hidden>✓</div>
              <p className="ir-eyebrow">Private reference · {report.data.id.slice(0, 8).toUpperCase()}</p>
              <h2>{statusCopy(report.data.status)}</h2>
              <p>Your report is not searchable or visible to other students, organisations or the public.</p>
              <dl>
                <div><dt>Submitted</dt><dd>{submitted}</dd></div>
                <div><dt>Privacy</dt><dd>{report.data.privacyMode === 'anonymous' ? 'Anonymous' : 'Private follow-up'}</dd></div>
                <div><dt>Evidence screened</dt><dd>{report.data.evidenceClean} of {report.data.evidenceTotal}</dd></div>
                <div><dt>Version</dt><dd>{report.data.version}</dd></div>
              </dl>
            </section>
            {report.data.supportGuidanceRequired && <aside className="ir-support" role="note"><strong>Support remains available.</strong><span>You can seek immediate help without waiting for the moderation workflow.</span></aside>}
            <section className="ir-timeline" aria-label="Private moderation timeline">
              {['Submitted privately', 'Identity separated and evidence screened', 'Authorised moderation review', 'Private outcome'].map((label, index) => <div key={label} className={index < 2 ? 'is-complete' : ''}><span aria-hidden>{index < 2 ? '✓' : index + 1}</span><p><strong>{label}</strong><small>{index < 2 ? 'Complete' : 'No public label or score'}</small></p></div>)}
            </section>
            <div className="ir-actions"><Link className="btn" to="/s-86">Back to my reports</Link></div>
          </>
        )}
        <p className="ir-foot">A report may inform private safeguarding or moderation. It cannot activate a public organisation risk label.</p>
      </main>
    </StudentScreen>
  );
}

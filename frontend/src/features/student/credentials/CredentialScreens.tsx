import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import QRCode from 'qrcode';
import { StudentScreen, TextField, SelectField, Checkbox } from '../components';
import {
  CREDENTIAL_TYPES,
  CredentialsApiError,
  PUBLIC_CREDENTIAL_FIELDS,
  createCredential,
  createShareProjection,
  createVerificationToken,
  deleteCredential,
  getCredential,
  getCredentialHistory,
  getPublicCredentialVerification,
  isRetryableCredentialsError,
  listCredentialIssuers,
  listCredentials,
  newIdempotencyKey,
  revokeCredentialAsIssuer,
  revokeVerificationToken,
  uploadCredentialEvidence,
  verifyCredential,
  type CredentialRecord,
  type CredentialStatus,
  type PublicCredentialField,
} from '../lib/credentialsApi';

const retryCredential = (failureCount: number, error: unknown): boolean =>
  isRetryableCredentialsError(error) && failureCount < 1;

const fieldLabels: Record<PublicCredentialField, string> = {
  title: 'Title',
  credential_type: 'Credential type',
  status: 'Verification status',
  issue_date: 'Issue date',
  expiry_date: 'Expiry date',
  issuer_display_name: 'Issuer',
  verification_timestamp: 'Verified on',
  student_name: 'Student name',
};

function errorCopy(error: unknown): string {
  if (!(error instanceof CredentialsApiError)) return 'The service is unavailable. Please retry.';
  const copies: Record<string, string> = {
    validation_error: 'Review the highlighted values and try again.',
    evidence_too_large: 'Each evidence file must be 10 MB or smaller.',
    evidence_file_limit: 'A credential accepts at most five evidence files.',
    unsupported_evidence_type: 'Use PDF, PNG, JPEG or WEBP evidence.',
    mime_mismatch: 'The file contents do not match the selected file type.',
    extension_mismatch: 'The filename extension does not match its contents.',
    duplicate_evidence: 'This evidence file is already attached.',
    infected_evidence: 'The evidence was rejected because malware was detected.',
    issuer_authorisation_required: 'This account is not authorised for the selected issuer.',
    stale_credential_version: 'This credential changed in another session. Refresh and retry.',
    verification_expired: 'This verification link has expired.',
    verification_revoked: 'This verification link has been revoked.',
    verification_not_found: 'This verification link is invalid or unavailable.',
    rate_limit_exceeded: 'Too many verification attempts. Please wait a minute.',
  };
  return copies[error.code] ?? `Request failed (${error.code}).`;
}

function statusTone(status: CredentialStatus): string {
  if (status === 'verified') return 'ok';
  if (status === 'revoked') return 'risk';
  if (status === 'expired') return 'warn';
  return 'info';
}

function Status({ value }: { value: CredentialStatus }) {
  return (
    <span className={`cw-status cw-status--${statusTone(value)}`} role="status">
      <span aria-hidden>{value === 'verified' ? '✓' : value === 'revoked' ? '×' : '●'}</span>
      {value.replace(/_/g, ' ')}
    </span>
  );
}

function Header({ step, title, intro }: { step: string; title: string; intro: string }) {
  return (
    <header className="cw-hero">
      <div>
        <p className="cw-kicker">Credential trust · {step}</p>
        <h1>{title}</h1>
        <p>{intro}</p>
      </div>
      <div className="cw-trustmark" aria-label="Privacy and verification safeguards active">
        <span aria-hidden>◇</span>
        <strong>Trust layer active</strong>
        <small>Private evidence · issuer authority · revocable sharing</small>
      </div>
    </header>
  );
}

function PageNav({ current }: { current: string }) {
  return (
    <nav className="cw-tabs" aria-label="Credential wallet steps">
      {[
        ['/s-82', 'Wallet'],
        ['/s-83', 'Add'],
        ['/s-84', 'Status'],
        ['/s-85', 'Share'],
      ].map(([href, label]) => (
        <Link key={href} to={href} aria-current={current === href ? 'page' : undefined}>{label}</Link>
      ))}
    </nav>
  );
}

export function CredentialWallet() {
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ['credentials', filter, page],
    queryFn: () => listCredentials(
      (filter || undefined) as CredentialStatus | undefined,
      page,
    ),
    retry: retryCredential,
  });
  return (
    <StudentScreen screenId="S-82" className="st-credentials">
      <div className="cw-shell">
        <Header step="S-82" title="Your verified story, in one place" intro="Collect achievements, track verification and share only the facts you choose." />
        <PageNav current="/s-82" />
        <section className="cw-toolbar" aria-label="Wallet controls">
          <div>
            <p className="cw-overline">Credential wallet</p>
            <h2>{query.data?.total ?? 0} records</h2>
          </div>
          <SelectField
            id="credential-status-filter"
            label="Filter by status"
            value={filter}
            onChange={(value) => {
              setFilter(value);
              setPage(1);
            }}
            options={[
              { value: 'self_declared', label: 'Self-declared' },
              { value: 'pending_verification', label: 'Pending verification' },
              { value: 'verified', label: 'Verified' },
              { value: 'expired', label: 'Expired' },
              { value: 'revoked', label: 'Revoked' },
            ]}
          />
          <Link className="btn btn--primary" to="/s-83">+ Add credential</Link>
        </section>
        {query.isLoading && <div className="cw-state" role="status" aria-busy="true">Loading your wallet…</div>}
        {query.isError && (
          <div className="cw-state cw-state--error" role="alert">
            <strong>Wallet could not load.</strong>
            <span>{errorCopy(query.error)}</span>
            <button className="btn" type="button" onClick={() => query.refetch()}>Retry</button>
          </div>
        )}
        {query.data?.items.length === 0 && (
          <div className="cw-empty">
            <span className="cw-empty__art" aria-hidden>◇</span>
            <h2>Build a credible portfolio</h2>
            <p>Add your first certificate, badge, moot achievement or employment record.</p>
            <Link className="btn btn--primary" to="/s-83">Add first credential</Link>
          </div>
        )}
        <div className="cw-grid">
          {query.data?.items.map((item) => (
            <article className="cw-card" key={item.id}>
              <div className="cw-card__top">
                <span className="cw-monogram" aria-hidden>{item.title.slice(0, 2).toUpperCase()}</span>
                <Status value={item.status} />
              </div>
              <p className="cw-overline">{item.credentialType.replace(/_/g, ' ')}</p>
              <h2>{item.title}</h2>
              <dl className="cw-facts">
                <div><dt>Issuer</dt><dd>{item.issuerDisplayName ?? 'Self-declared'}</dd></div>
                <div><dt>Issued</dt><dd>{item.issueDate}</dd></div>
                <div><dt>Evidence</dt><dd>{item.evidence.length} file{item.evidence.length === 1 ? '' : 's'}</dd></div>
              </dl>
              <div className="cw-actions">
                <Link className="btn" to={`/s-84?credential=${encodeURIComponent(item.id)}`}>View status</Link>
                {item.status === 'verified' && <Link className="btn btn--primary" to={`/s-85?credential=${encodeURIComponent(item.id)}`}>Share</Link>}
              </div>
            </article>
          ))}
        </div>
        {(query.data?.total ?? 0) > 20 && (
          <nav className="cw-pagination" aria-label="Credential wallet pages">
            <button
              className="btn"
              type="button"
              disabled={page === 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </button>
            <span aria-live="polite">Page {page}</span>
            <button
              className="btn"
              type="button"
              disabled={page * 20 >= (query.data?.total ?? 0)}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </nav>
        )}
        <p className="cw-foot">Private by default · evidence is never public · DPDP data-minimisation controls apply</p>
      </div>
    </StudentScreen>
  );
}

export function CredentialAdd() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [credentialType, setCredentialType] = useState('');
  const [issueDate, setIssueDate] = useState('');
  const [expiryDate, setExpiryDate] = useState('');
  const [issuerId, setIssuerId] = useState('');
  const [identifier, setIdentifier] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [formError, setFormError] = useState('');
  const issuers = useQuery({
    queryKey: ['credential-issuers'],
    queryFn: listCredentialIssuers,
    retry: retryCredential,
  });
  const mutation = useMutation({
    mutationFn: async () => {
      const credential = await createCredential(
        { title, credentialType, issueDate, expiryDate, issuerId, identifier },
        newIdempotencyKey('credential'),
      );
      if (file) await uploadCredentialEvidence(credential.id, file);
      return credential.id;
    },
    onSuccess: (id) => navigate(`/s-84?credential=${encodeURIComponent(id)}`),
    onError: (error) => setFormError(errorCopy(error)),
  });
  const today = new Date().toISOString().slice(0, 10);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');
    if (title.trim().length < 2 || title.trim().length > 160) {
      return setFormError('Title must contain 2–160 characters.');
    }
    if (!credentialType) return setFormError('Select a credential type.');
    if (!issueDate || issueDate > today) return setFormError('Issue date must be today or earlier.');
    if (expiryDate && expiryDate < issueDate) return setFormError('Expiry date cannot precede the issue date.');
    mutation.mutate();
  };
  return (
    <StudentScreen screenId="S-83" className="st-credentials">
      <div className="cw-shell">
        <Header step="S-83" title="Add a credential" intro="Start with the facts. Evidence is scanned and held privately for an authorised issuer." />
        <PageNav current="/s-83" />
        <form className="cw-form" onSubmit={submit} noValidate>
          <section className="cw-form__main">
            <p className="cw-overline">1 · Credential details</p>
            <TextField id="credential-title" label="Credential title" value={title} onChange={setTitle} maxLength={160} placeholder="Advanced Moot Court Certificate" />
            <SelectField id="credential-type" label="Credential type" value={credentialType} onChange={setCredentialType} options={CREDENTIAL_TYPES} />
            <div className="cw-form__two">
              <TextField id="issue-date" label="Issue date" type="date" value={issueDate} onChange={setIssueDate} max={today} />
              <TextField id="expiry-date" label="Expiry date" optional="if applicable" type="date" value={expiryDate} onChange={setExpiryDate} />
            </div>
            <SelectField
              id="issuer-id"
              label="Issuer"
              value={issuerId}
              onChange={setIssuerId}
              options={(issuers.data ?? []).map((issuer) => ({
                value: issuer.id,
                label: `${issuer.displayName} · ${issuer.issuerType}`,
              }))}
              help="Leave unselected for a self-declared credential."
            />
            {issuers.isError && <p className="cw-error" role="alert">Issuer directory unavailable. You can still save a self-declared credential.</p>}
            <TextField id="credential-identifier" label="Credential identifier" optional="private" value={identifier} onChange={setIdentifier} maxLength={120} help="Encrypted for authorised display; never included publicly unless Product adds it later." />
          </section>
          <aside className="cw-upload">
            <p className="cw-overline">2 · Private evidence</p>
            <label className="cw-drop" htmlFor="credential-evidence">
              <input
                id="credential-evidence"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <span aria-hidden>⇧</span>
              <strong>{file ? file.name : 'Choose evidence'}</strong>
              <small>PDF, PNG, JPEG or WEBP · max 10 MB · scanned before use</small>
            </label>
            <div className="cw-privacy">
              <strong>What stays private?</strong>
              <p>The evidence file, credential identifier and internal issuer review are never exposed by a share link.</p>
            </div>
          </aside>
          {formError && <p className="cw-error" role="alert">{formError}</p>}
          <div className="cw-form__actions">
            <Link className="btn" to="/s-82">Cancel</Link>
            <button className="btn btn--primary" type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Saving and scanning…' : 'Save credential'}
            </button>
          </div>
        </form>
      </div>
    </StudentScreen>
  );
}

function useCredentialParam() {
  const [params] = useSearchParams();
  return params.get('credential') ?? '';
}

function CredentialOverview({ credential }: { credential: CredentialRecord }) {
  return (
    <section className="cw-detail">
      <div className="cw-detail__identity">
        <span className="cw-monogram cw-monogram--large" aria-hidden>{credential.title.slice(0, 2).toUpperCase()}</span>
        <div>
          <p className="cw-overline">{credential.credentialType.replace(/_/g, ' ')}</p>
          <h2>{credential.title}</h2>
          <Status value={credential.status} />
        </div>
      </div>
      <dl className="cw-facts cw-facts--detail">
        <div><dt>Issuer</dt><dd>{credential.issuerDisplayName ?? 'Self-declared'}</dd></div>
        <div><dt>Issue date</dt><dd>{credential.issueDate}</dd></div>
        <div><dt>Expiry date</dt><dd>{credential.expiryDate ?? 'Does not expire'}</dd></div>
        <div><dt>Private identifier</dt><dd>{credential.identifier ?? 'Not supplied'}</dd></div>
      </dl>
    </section>
  );
}

export function CredentialPending() {
  const id = useCredentialParam();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ['credential', id],
    queryFn: () => getCredential(id),
    enabled: Boolean(id),
    retry: retryCredential,
  });
  const history = useQuery({
    queryKey: ['credential-history', id],
    queryFn: () => getCredentialHistory(id),
    enabled: Boolean(id),
    retry: retryCredential,
  });
  const verify = useMutation({
    mutationFn: () => verifyCredential(id, query.data!.version, newIdempotencyKey('verify')),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['credential', id] });
      client.invalidateQueries({ queryKey: ['credential-history', id] });
    },
  });
  const revoke = useMutation({
    mutationFn: () => revokeCredentialAsIssuer(
      id,
      query.data!.version,
      'Issuer revoked this credential after an authorised compliance review.',
      newIdempotencyKey('revoke'),
    ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['credential', id] });
      client.invalidateQueries({ queryKey: ['credential-history', id] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteCredential(id),
    onSuccess: () => window.location.assign('/s-82'),
  });
  return (
    <StudentScreen screenId="S-84" className="st-credentials">
      <div className="cw-shell">
        <Header step="S-84" title="Verification status" intro="See exactly what was submitted, scanned and decided—without exposing private evidence." />
        <PageNav current="/s-84" />
        {!id && <div className="cw-state"><strong>Select a credential from your wallet.</strong><Link className="btn" to="/s-82">Open wallet</Link></div>}
        {query.isLoading && <div className="cw-state" role="status" aria-busy="true">Loading credential status…</div>}
        {query.isError && <div className="cw-state cw-state--error" role="alert">{errorCopy(query.error)}</div>}
        {query.data && (
          <div className="cw-detailgrid">
            <CredentialOverview credential={query.data} />
            <aside className="cw-timeline">
              <p className="cw-overline">Trust timeline</p>
              {history.data?.map((item) => (
                <div className="cw-timeline__item" key={item.id}>
                  <span aria-hidden>✓</span>
                  <div><strong>{item.toStatus.replace(/_/g, ' ')}</strong><small>{item.reasonCode.replace(/_/g, ' ')} · {new Date(item.createdAt).toLocaleString()}</small></div>
                </div>
              ))}
              {!history.data?.length && <p>No status events yet.</p>}
              <p className="cw-overline cw-space">Evidence scope</p>
              {query.data.evidence.length ? query.data.evidence.map((item) => (
                <div className="cw-evidence" key={item.id}>
                  <span aria-hidden>▣</span>
                  <div>
                    <strong>{item.mime}</strong>
                    <small>{Math.ceil(item.sizeBytes / 1024)} KB · {item.scanState.replace(/_/g, ' ')}</small>
                    {item.scanState === 'retryable_failure' && (
                      <small role="status">Scanner unavailable. A durable retry is queued; the file remains quarantined.</small>
                    )}
                  </div>
                </div>
              )) : <p>No evidence attached.</p>}
            </aside>
            <section className="cw-issuerpanel">
              <div>
                <p className="cw-overline">Issuer authority panel</p>
                <h2>Server-authoritative decision</h2>
                <p>Only a signed-in issuer with an active server-side grant can verify or revoke this record.</p>
              </div>
              <div className="cw-actions">
                {query.data.status === 'pending_verification' && <button className="btn btn--primary" type="button" onClick={() => verify.mutate()} disabled={verify.isPending}>Verify credential</button>}
                {['verified', 'expired'].includes(query.data.status) && <button className="btn" type="button" onClick={() => revoke.mutate()} disabled={revoke.isPending}>Revoke as issuer</button>}
                {query.data.status === 'verified' && <Link className="btn btn--primary" to={`/s-85?credential=${encodeURIComponent(id)}`}>Create share link</Link>}
                <button className="btn cw-danger" type="button" onClick={() => remove.mutate()} disabled={remove.isPending}>Delete credential</button>
              </div>
              {(verify.error || revoke.error || remove.error) && <p className="cw-error" role="alert">{errorCopy(verify.error ?? revoke.error ?? remove.error)}</p>}
            </section>
          </div>
        )}
      </div>
    </StudentScreen>
  );
}

export function CredentialShare() {
  const id = useCredentialParam();
  const query = useQuery({
    queryKey: ['credential', id],
    queryFn: () => getCredential(id),
    enabled: Boolean(id),
    retry: retryCredential,
  });
  const [selected, setSelected] = useState<PublicCredentialField[]>([
    'title',
    'credential_type',
    'status',
    'issue_date',
    'expiry_date',
    'issuer_display_name',
    'verification_timestamp',
  ]);
  const [includeName, setIncludeName] = useState(false);
  const [lifetime, setLifetime] = useState('90');
  const [issued, setIssued] = useState<{ id: string; verificationUrl: string; expiresAt: string } | null>(null);
  const [qrData, setQrData] = useState('');
  const mutation = useMutation({
    mutationFn: async () => {
      const fields = includeName ? [...selected, 'student_name' as const] : selected;
      const projection = await createShareProjection(id, fields, newIdempotencyKey('projection'));
      return createVerificationToken(id, projection.id, Number(lifetime), newIdempotencyKey('token'));
    },
    onSuccess: setIssued,
  });
  const revoke = useMutation({
    mutationFn: () => revokeVerificationToken(id, issued!.id),
    onSuccess: () => { setIssued(null); setQrData(''); },
  });
  useEffect(() => {
    if (!issued) return;
    QRCode.toDataURL(issued.verificationUrl, {
      errorCorrectionLevel: 'M',
      margin: 2,
      width: 320,
      color: { dark: '#123f32', light: '#ffffff' },
    }).then(setQrData).catch(() => setQrData(''));
  }, [issued]);
  const preview = useMemo(() => {
    if (!query.data) return [];
    const record: Partial<Record<PublicCredentialField, string | null>> = {
      title: query.data.title,
      credential_type: query.data.credentialType.replace(/_/g, ' '),
      status: query.data.status,
      issue_date: query.data.issueDate,
      expiry_date: query.data.expiryDate,
      issuer_display_name: query.data.issuerDisplayName,
      verification_timestamp: 'Shown after issuer verification',
      student_name: includeName ? 'Aditi Nair' : null,
    };
    return [...selected, ...(includeName ? ['student_name' as const] : [])].map((field) => [fieldLabels[field], record[field] ?? 'Not supplied']);
  }, [query.data, selected, includeName]);
  const toggleField = (field: PublicCredentialField, checked: boolean) => {
    setSelected((current) => checked ? [...current, field] : current.filter((item) => item !== field));
  };
  return (
    <StudentScreen screenId="S-85" className="st-credentials">
      <div className="cw-shell">
        <Header step="S-85" title="Share with intent" intro="Create a time-limited QR and link containing only the fields selected below." />
        <PageNav current="/s-85" />
        {!id && <div className="cw-state"><strong>Select a verified credential first.</strong><Link className="btn" to="/s-82">Open wallet</Link></div>}
        {query.data && query.data.status !== 'verified' && <div className="cw-state cw-state--error" role="alert">Only a valid verified credential can be shared.</div>}
        {query.data?.status === 'verified' && (
          <div className="cw-sharegrid">
            <section className="cw-sharefields">
              <p className="cw-overline">1 · Choose public fields</p>
              <h2>You control this projection</h2>
              {PUBLIC_CREDENTIAL_FIELDS.filter((field) => field !== 'student_name').map((field) => (
                <Checkbox
                  id={`share-${field}`}
                  key={field}
                  label={fieldLabels[field]}
                  checked={selected.includes(field)}
                  onChange={(checked) => toggleField(field, checked)}
                />
              ))}
              <Checkbox id="share-student-name" label="Include my name (explicit consent)" checked={includeName} onChange={setIncludeName} />
              <SelectField id="share-lifetime" label="Link lifetime" value={lifetime} onChange={setLifetime} options={[
                { value: '7', label: '7 days' },
                { value: '30', label: '30 days' },
                { value: '90', label: '90 days (default)' },
              ]} />
              <button className="btn btn--primary" type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending || selected.length === 0}>
                {mutation.isPending ? 'Creating secure link…' : 'Create QR & secure link'}
              </button>
              {mutation.error && <p className="cw-error" role="alert">{errorCopy(mutation.error)}</p>}
            </section>
            <section className="cw-preview" aria-label="Public verification preview">
              <p className="cw-overline">2 · Public preview</p>
              <div className="cw-publiccard">
                <span className="cw-publiccard__seal" aria-hidden>✓</span>
                <h2>{query.data.title}</h2>
                <p>Verified by {query.data.issuerDisplayName}</p>
                <dl>{preview.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
              </div>
            </section>
            {issued && (
              <section className="cw-issued" aria-live="polite">
                <div>
                  <p className="cw-overline">3 · Ready to share</p>
                  <h2>Verification QR</h2>
                  <p>Expires {new Date(issued.expiresAt).toLocaleString()} · revocable at any time</p>
                  <a className="cw-link" href={issued.verificationUrl}>{issued.verificationUrl}</a>
                  <div className="cw-actions">
                    {qrData && <a className="btn btn--primary" href={qrData} download="legalsaathi-credential-qr.png">Download QR</a>}
                    <button className="btn cw-danger" type="button" onClick={() => revoke.mutate()} disabled={revoke.isPending}>Revoke link</button>
                  </div>
                </div>
                {qrData ? <img className="cw-qr" src={qrData} alt={`QR code for ${issued.verificationUrl}`} /> : <div className="cw-qr cw-qr--loading" role="status">Generating QR…</div>}
              </section>
            )}
          </div>
        )}
      </div>
    </StudentScreen>
  );
}

export function PublicCredentialVerification() {
  const { token = '' } = useParams();
  const query = useQuery({
    queryKey: ['public-credential-verification', token],
    queryFn: () => getPublicCredentialVerification(token),
    enabled: Boolean(token),
    retry: retryCredential,
  });
  const fields = query.data?.verification ?? {};
  return (
    <section className="st-screen st-credentials cw-public-page" data-screen="VERIFY">
      <div className="cw-public-verify">
        <div className="cw-wordmark">Legal<span>Saathi</span></div>
        {query.isLoading && <div className="cw-state" role="status" aria-busy="true">Checking verification…</div>}
        {query.isError && <div className="cw-state cw-state--error" role="alert"><strong>Verification unavailable</strong><span>{errorCopy(query.error)}</span></div>}
        {query.data && (
          <>
            <span className="cw-public-verify__seal" aria-hidden>✓</span>
            <p className="cw-overline">Authentic server record</p>
            <h1>{fields.title ?? 'Verified credential'}</h1>
            <Status value={(fields.status ?? 'verified') as CredentialStatus} />
            <dl className="cw-facts cw-facts--public">
              {Object.entries(fields).filter(([field]) => field !== 'title').map(([field, value]) => (
                <div key={field}><dt>{fieldLabels[field as PublicCredentialField] ?? field.replace(/_/g, ' ')}</dt><dd>{value ?? 'Not supplied'}</dd></div>
              ))}
            </dl>
            <p className="cw-foot">This page exposes no evidence files, private identifier or internal issuer notes. Link expires {new Date(query.data.tokenExpiresAt).toLocaleDateString()}.</p>
          </>
        )}
      </div>
    </section>
  );
}

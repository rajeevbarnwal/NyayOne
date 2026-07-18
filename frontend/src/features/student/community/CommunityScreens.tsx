import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, TextField, SelectField, DpdpFootnote } from '../components';
import { StatusBadge, EmptyState, ModerationBanner, GuardrailNotice, ValidationState } from '../../../components/ui/primitives';
import {
  publicPosts,
  publicBody,
  looksLikeLegalAdvice,
  validateCompose,
  validateReply,
  REPORT_REASONS,
  REVIEW_SLA_HOURS,
  SAMPLE_CHANNELS,
  SAMPLE_POSTS,
  MODERATION_OUTCOME_COPY,
  ADVICE_REDIRECT_COPY,
  REPORT_DPDP,
  ATTRIBUTION_COPY,
  type ReportReason,
} from '../lib/community';

function Head({ title, sub }: { title: string; sub?: string }) {
  return (
    <div>
      <p className="st-eyebrow">Community · S10</p>
      <h1 className="st-h1">{title}</h1>
      {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

/* S-50 — Community feed (default) */
export function CommunityFeed() {
  const nav = useNavigate();
  const visible = publicPosts(SAMPLE_POSTS);
  return (
    <StudentScreen screenId="S-50">
      <div className="st-stack">
        <Head title="Community" sub="Moderated forums — subject, law-school and national channels" />
        <div className="st-tabsrow" role="tablist" aria-label="Channel groups">
          <button role="tab" aria-selected className="st-tab">Subjects</button>
          <button role="tab" aria-selected={false} className="st-tab">Law schools</button>
          <button role="tab" aria-selected={false} className="st-tab">National</button>
        </div>
        <section className="st-panel" aria-label="Channels">
          <h2 className="st-panel__title">Channels</h2>
          <ul className="st-list">
            {SAMPLE_CHANNELS.map((c) => (
              <li className="st-item" key={c.id}>
                <div>
                  <div>{c.name}</div>
                  <div className="st-item__meta">{c.meta}</div>
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                  <StatusBadge status={c.active ? 'ok' : 'info'} label={c.active ? 'Active' : 'Quiet'} />
                  <button type="button" className="btn tap" onClick={() => nav('/s-51')}>Open</button>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <GuardrailNotice>{ADVICE_REDIRECT_COPY}</GuardrailNotice>

        <section className="st-panel" aria-label="Moderation">
          <h2 className="st-panel__title">Moderation</h2>
          <p className="st-item__meta">Report, block &amp; takedown · UGC content policy · IT Rules.</p>
          {visible.length === 0 && <EmptyState title="No posts yet in your subjects" hint="Follow a channel to see discussions here." />}
          <div className="st-actions">
            <button type="button" className="btn tap" onClick={() => nav('/s-52')}>New post</button>
            <button type="button" className="btn tap" onClick={() => nav('/s-53')}>Report content</button>
          </div>
        </section>
        <DpdpFootnote>{ATTRIBUTION_COPY}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* S-51 — Post / thread (default) */
export function CommunityPost() {
  const nav = useNavigate();
  const post = SAMPLE_POSTS[0];
  const [reply, setReply] = useState('');
  const [replyError, setReplyError] = useState<string | null>(null);
  const [replies, setReplies] = useState<string[]>([]);

  function postReply() {
    const error = validateReply(reply);
    setReplyError(error);
    if (error) return;
    setReplies((current) => [...current, reply.trim()]);
    setReply('');
  }
  return (
    <StudentScreen screenId="S-51">
      <div className="st-stack">
        <Head title="Discussion" sub="Constitutional Law" />
        <section className="st-panel">
          <div className="st-panel__head">
            <h2 className="st-panel__title">{post.title}</h2>
            <span className="st-metatag">study discussion</span>
          </div>
          <p className="st-metatag">{post.author.toUpperCase()} · {post.replies} REPLIES</p>
          <p>{publicBody(post)}</p>
          {replies.length > 0 && (
            <ul className="st-list" aria-label="Posted replies">
              {replies.map((body, index) => (
                <li className="st-item" key={`${index}-${body}`}><div><div>You</div><div className="st-item__meta">{body}</div></div></li>
              ))}
            </ul>
          )}
          <div className="st-chips" style={{ marginTop: 'var(--space-2)' }}>
            <StatusBadge status="ok" label="Active" />
          </div>
        </section>
        <section className="st-panel">
          <h2 className="st-panel__title">Reply</h2>
          <label className="st-field" htmlFor="reply">
            <span className="st-field__label">Add to the discussion</span>
            <textarea id="reply" className="st-input" style={{ minHeight: 90, padding: 'var(--space-3)' }} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Add to the discussion…" />
            {replyError && <ValidationState message={replyError} />}
          </label>
          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={() => nav('/s-53')}>Report this post</button>
            <button type="button" className="btn btn--primary tap" onClick={postReply}>Post reply</button>
          </div>
        </section>
      </div>
    </StudentScreen>
  );
}

/* S-52 — Create post (validation) */
const CHANNEL_OPTIONS = SAMPLE_CHANNELS.map((c) => c.name);
export function CommunityCreate() {
  const nav = useNavigate();
  const [channel, setChannel] = useState(CHANNEL_OPTIONS[0]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const advice = looksLikeLegalAdvice(`${title} ${body}`);

  function publish() {
    const e = validateCompose({ channel, title, body });
    setErrors(e);
    if (Object.keys(e).length === 0 && !advice) nav('/s-50');
  }
  return (
    <StudentScreen screenId="S-52">
      <div className="st-stack">
        <Head title="Compose" sub="study discussion only" />
        <section className="st-panel">
          <SelectField id="c-channel" label="Channel" value={channel} onChange={setChannel} options={CHANNEL_OPTIONS} error={errors.channel} />
          <TextField id="c-title" label="Title" value={title} onChange={setTitle} placeholder="Your question" error={errors.title} />
          <label className="st-field" htmlFor="c-body">
            <span className="st-field__label">Body</span>
            <textarea id="c-body" className="st-input" style={{ minHeight: 110, padding: 'var(--space-3)' }} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write your post…" />
            {errors.body && <ValidationState message={errors.body} />}
          </label>
          <GuardrailNotice>Study discussion only. Requests for legal advice are redirected to disclaimers, not answered as advice.</GuardrailNotice>
          {advice && <ValidationState message="This looks like a request for legal advice — it will be redirected to disclaimers and referral paths, not published as advice." />}
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={publish} disabled={advice} aria-disabled={advice}>
              Publish
            </button>
          </div>
        </section>
      </div>
    </StudentScreen>
  );
}

/* S-53 — Report content (default) */
export function CommunityReport() {
  const nav = useNavigate();
  const [reason, setReason] = useState<ReportReason | null>(null);
  return (
    <StudentScreen screenId="S-53">
      <div className="st-stack">
        <Head title="Report content" />
        <section className="st-panel">
          <span className="st-field__label" id="reason-label">Reason</span>
          <div className="st-chips" role="radiogroup" aria-labelledby="reason-label" style={{ marginBottom: 'var(--space-3)' }}>
            {REPORT_REASONS.map((r) => (
              <button key={r.id} type="button" className="st-chip" role="radio" aria-checked={reason === r.id} aria-pressed={reason === r.id} onClick={() => setReason(r.id)}>
                {r.label}
              </button>
            ))}
          </div>
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" disabled={!reason} aria-disabled={!reason} onClick={() => nav('/s-54')}>
              Submit report
            </button>
          </div>
        </section>
        <DpdpFootnote>{REPORT_DPDP}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* S-54 — Moderation outcome (moderation) */
export function CommunityModerated() {
  const nav = useNavigate();
  return (
    <StudentScreen screenId="S-54">
      <div className="st-stack">
        <Head title="Moderation outcome" />
        <section className="st-panel">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Report received</h2>
            <StatusBadge status="ok" label={`Reviewed · within ${REVIEW_SLA_HOURS} hrs`} />
          </div>
          <ModerationBanner state="pending_review" note="queued for review" />
          <p style={{ marginTop: 'var(--space-3)' }}>{MODERATION_OUTCOME_COPY}</p>
          <div className="st-actions">
            <button type="button" className="btn tap" onClick={() => nav('/s-50')}>Back to community</button>
          </div>
        </section>
        <DpdpFootnote>{REPORT_DPDP}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

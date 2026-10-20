import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { useStudentMutation } from '../lib/useStudentMutation';
import { captureStudentContextFence, isStudentContextFenceCurrent } from '../lib/studentBrowserContext';
import { InternshipsApiError } from '../lib/internshipsApi';
import { readBrowseSaved, changeBrowseSaved } from './s20Api';
import { readInternshipDetail, validDetailId } from './s21Api';
import { settleS21Saved } from './s21SavedCache';
import { S21DetailView, type S21DetailViewProps, type S21Focus } from './S21DetailView';

export function S21DetailScreen() {
  const auth = useAuth(), session = useStudentSession(); const [params] = useSearchParams();
  const focus = useRef<S21Focus>(null);
  return <DetailController key={`${session.phase}:${auth.userId}:${auth.roles.join(',')}:${params.get('listing')}`} focus={focus}/>;
}
function DetailController({ focus }: Pick<S21DetailViewProps, 'focus'>) {
  const auth = useAuth(), session = useStudentSession(), client = useQueryClient(), nav = useNavigate();
  const [params] = useSearchParams(), [failure, setFailure] = useState(''), [notice, setNotice] = useState('');
  const [uncertain, setUncertain] = useState(false), [busy, setBusy] = useState(false);
  const lock = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const id = params.get('listing')?.trim() ?? '', valid = validDetailId(id);
  const key = ['internships-saved', auth.userId] as const;
  const canSave = session.phase === 'authenticated' && auth.isAuthenticated && auth.roles.includes('student') && !!auth.userId;
  const detail = useQuery({ queryKey: ['internship', id], queryFn: ({ signal }) => readInternshipDetail(id, signal), enabled: valid && session.phase !== 'pending', retry: false, networkMode: 'always', refetchOnWindowFocus: false });
  const saved = useQuery({ queryKey: key, queryFn: ({ signal }) => readBrowseSaved(signal), enabled: canSave, retry: false, networkMode: 'always', refetchOnMount: 'always', refetchOnWindowFocus: false });
  const mutation = useStudentMutation({ retry: false, networkMode: 'always',
    mutationFn: ({ desired }: { desired: boolean; item: NonNullable<typeof detail.data>; fence: ReturnType<typeof captureStudentContextFence> }) => changeBrowseSaved(id, desired),
    onSuccess: async (confirmed, { item, fence }) => {
      if (auth.userId) await settleS21Saved(client, auth.userId, item, confirmed, () => isStudentContextFenceCurrent(fence));
    },
    onError: () => { void client.invalidateQueries({ queryKey: key, exact: true }); },
  });
  const savedState: S21DetailViewProps['savedState'] = !canSave
    ? session.phase === 'pending' ? 'loading' : session.phase === 'unavailable' || (auth.isAuthenticated && !auth.userId) ? 'unavailable' : auth.isAuthenticated ? 'forbidden' : 'anonymous'
    : saved.isError ? 'error' : uncertain ? 'uncertain' : saved.isPending || saved.isFetching ? 'loading' : (saved.data ?? []).some(item => item.id === id) ? 'saved' : 'unsaved';
  async function toggle() {
    if (lock.current || !canSave || !detail.data || !['saved', 'unsaved'].includes(savedState)) return;
    if (!navigator.onLine) { setFailure('You are offline. No request was sent. Reconnect and try again.'); return; }
    lock.current = true; setBusy(true); setFailure(''); setNotice('');
    try {
      const confirmed = await mutation.mutateAsync({ desired: savedState !== 'saved', item: detail.data, fence: captureStudentContextFence() });
      if (mounted.current) setNotice(confirmed ? 'Saved privately to your account. The organisation is not notified.' : 'Removed from your saved internships.');
    } catch (error) {
      if (mounted.current) {
        setUncertain(true);
        setFailure(error instanceof InternshipsApiError && error.status === 401 ? 'Sign in again to confirm your saved state.' : 'Could not confirm this change. Reload your saved list before trying again.');
      }
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  async function retrySaved() {
    if (lock.current || !canSave) return;
    lock.current = true;
    try { const result = await saved.refetch(); if (mounted.current && result.isSuccess) { setUncertain(false); setFailure(''); setNotice('Saved list reloaded.'); } }
    finally { lock.current = false; }
  }
  const phase = !valid ? 'incomplete' : detail.isError ? detail.error instanceof InternshipsApiError && detail.error.status === 404 ? 'missing' : 'error' : detail.isPending ? 'loading' : 'detail';
  // Presentation only: retain the actual response status, never invent 500 for
  // a transport failure, invalid link, or malformed successful response.
  const statusCode = valid && detail.isError && detail.error instanceof InternshipsApiError
    && Number.isInteger(detail.error.status) && detail.error.status >= 400 && detail.error.status <= 599 ? detail.error.status : null;
  return <S21DetailView focus={focus} phase={phase} item={detail.data ?? null} savedState={savedState} busy={busy} failure={failure} notice={notice}
    statusCode={statusCode} fromSaved={params.get('from') === 's25'} onNavigate={nav} onToggle={toggle} onRetry={() => detail.refetch()} onRetrySaved={retrySaved}/>;
}

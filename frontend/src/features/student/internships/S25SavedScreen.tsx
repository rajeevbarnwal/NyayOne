import { useEffect, useRef, useState } from 'react';
import { useIsMutating, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { useStudentMutation } from '../lib/useStudentMutation';
import { captureStudentContextFence, isStudentContextFenceCurrent } from '../lib/studentBrowserContext';
import { InternshipsApiError } from '../lib/internshipsApi';
import type { InternshipListing } from '../lib/internships';
import { readBrowseSaved, changeBrowseSaved } from './s20Api';
import { settleS21Saved } from './s21SavedCache';
import { S25SavedView, type S25SavedViewProps, type S25Focus } from './S25SavedView';

export function S25SavedScreen() {
  const auth = useAuth(), session = useStudentSession(), focus = useRef<S25Focus>(null);
  return <SavedController key={`${session.phase}:${auth.userId}:${auth.roles.join(',')}`} focus={focus}/>;
}
function SavedController({ focus }: Pick<S25SavedViewProps, 'focus'>) {
  const auth = useAuth(), session = useStudentSession(), client = useQueryClient(), nav = useNavigate();
  const [pendingId, setPendingId] = useState<string | null>(null), [failure, setFailure] = useState(''), [notice, setNotice] = useState('');
  const [uncertain, setUncertain] = useState(false), lock = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const enabled = session.phase === 'authenticated' && auth.isAuthenticated && auth.roles.includes('student') && !!auth.userId;
  const key = ['internships-saved', auth.userId] as const, mutationKey = ['s25-remove', auth.userId] as const;
  const activeMutation = useIsMutating({ mutationKey, exact: true }) > 0;
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => readBrowseSaved(signal), enabled,
    retry: false, networkMode: 'always', refetchOnMount: 'always', refetchOnWindowFocus: false });
  const mutation = useStudentMutation({ mutationKey, retry: false, networkMode: 'always',
    mutationFn: ({ item }: { item: InternshipListing; fence: ReturnType<typeof captureStudentContextFence> }) => changeBrowseSaved(item.id, false),
    onSuccess: async (confirmed, { item, fence }) => {
      if (auth.userId) await settleS21Saved(client, auth.userId, item, confirmed, () => isStudentContextFenceCurrent(fence));
    },
    onError: async (_error, { fence }) => {
      // A lost response is not proof that DELETE failed. Cancel snapshots taken
      // before the mutation, including an S-21 read started after leaving here,
      // then re-read server truth. Never publish an optimistic "still saved".
      if (!isStudentContextFenceCurrent(fence)) return;
      await client.cancelQueries({ queryKey: key, exact: true });
      await client.cancelQueries({ queryKey: ['s20-saved', auth.userId], exact: true });
      if (!isStudentContextFenceCurrent(fence)) return;
      void client.invalidateQueries({ queryKey: key, exact: true });
      void client.invalidateQueries({ queryKey: ['s20-saved', auth.userId], exact: true });
    },
  });
  async function remove(item: InternshipListing) {
    if (lock.current || activeMutation || !enabled || uncertain || query.isFetching || query.isError) return;
    if (!navigator.onLine) { setFailure('You are offline. No request was sent. Reconnect and try again.'); return; }
    const fence = captureStudentContextFence();
    lock.current = true; setPendingId(item.id); setFailure(''); setNotice('');
    try {
      await mutation.mutateAsync({ item, fence });
      if (mounted.current && isStudentContextFenceCurrent(fence)) setNotice(`${item.role} removed from your saved internships.`);
    } catch {
      if (mounted.current && isStudentContextFenceCurrent(fence)) {
        setUncertain(true); setFailure('Could not confirm removal. Reload your saved list.');
      }
    } finally { lock.current = false; if (mounted.current) setPendingId(null); }
  }
  async function retry() {
    if (lock.current || activeMutation || !enabled) return;
    if (!navigator.onLine) { setFailure('You are offline. No request was sent. Reconnect and try again.'); return; }
    lock.current = true;
    try {
      const result = await query.refetch();
      if (mounted.current && result.isSuccess) { setFailure(''); setUncertain(false); setNotice('Saved list reloaded.'); }
    } finally { lock.current = false; }
  }
  const phase: S25SavedViewProps['phase'] = session.phase === 'pending' ? 'loading'
    : !enabled ? session.phase === 'unavailable' || (auth.isAuthenticated && !auth.userId) ? 'unavailable' : auth.isAuthenticated ? 'forbidden' : 'anonymous'
      : query.isError ? 'error' : query.isPending ? 'loading' : (query.data?.length ?? 0) ? 'list' : 'empty';
  const statusCode = query.isError && query.error instanceof InternshipsApiError && query.error.status >= 400 && query.error.status <= 599 ? query.error.status : null;
  return <S25SavedView focus={focus} phase={phase} items={enabled ? query.data ?? [] : []} pendingId={pendingId ?? (activeMutation ? '__pending__' : null)}
    refreshing={enabled && query.isFetching} failure={failure} notice={notice} uncertain={uncertain} statusCode={statusCode}
    onNavigate={nav} onRemove={remove} onRetry={retry}/>;
}

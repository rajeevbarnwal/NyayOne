import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { captureStudentContextFence, isStudentContextFenceCurrent } from '../lib/studentBrowserContext';
import { InternshipsApiError } from '../lib/internshipsApi';
import { readBrowseSaved } from './s20Api';
import { S26RecoveryView, type S26Focus, type S26RecoveryViewProps } from './S26RecoveryView';

export function S26RecoveryScreen() {
  const auth = useAuth(), session = useStudentSession(), focus = useRef<S26Focus>(null);
  return <RecoveryController key={`${session.phase}:${auth.userId}:${auth.roles.join(',')}`} focus={focus}/>;
}
function RecoveryController({ focus }: Pick<S26RecoveryViewProps, 'focus'>) {
  const auth = useAuth(), session = useStudentSession(), nav = useNavigate();
  const [retrying, setRetrying] = useState(false), [offline, setOffline] = useState(false), [attempt, setAttempt] = useState(0);
  const lock = useRef(false), mounted = useRef(true), previousError = useRef<unknown>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const enabled = session.phase === 'authenticated' && auth.isAuthenticated && auth.roles.includes('student') && !!auth.userId;
  const query = useQuery({ queryKey: ['internships-saved', auth.userId], queryFn: ({ signal }) => readBrowseSaved(signal), enabled,
    retry: false, networkMode: 'always', refetchOnMount: 'always', refetchOnWindowFocus: false });
  if (query.isError) previousError.current = query.error;
  async function retry() {
    if (lock.current || query.isFetching || !enabled) return;
    setAttempt(n => n + 1);
    if (!navigator.onLine) { setOffline(true); return; }
    const fence = captureStudentContextFence(); lock.current = true; setRetrying(true); setOffline(false);
    try { await query.refetch(); }
    finally { lock.current = false; if (mounted.current && isStudentContextFenceCurrent(fence)) setRetrying(false); }
  }
  // Preserve the retry button while its explicit read is pending. React Query
  // clears its error on retry; that must not detach the keyboard's active node.
  const failed = query.isError || (retrying && previousError.current !== null) || offline;
  const phase: S26RecoveryViewProps['phase'] = session.phase === 'pending' ? 'loading'
    : !enabled ? session.phase === 'unavailable' || (auth.isAuthenticated && !auth.userId) ? 'unavailable' : auth.isAuthenticated ? 'forbidden' : 'anonymous'
      : failed ? 'error' : query.isPending ? 'loading' : query.data?.length ? 'nonempty' : 'empty';
  const error = query.error ?? (retrying ? previousError.current : null);
  const statusCode = error instanceof InternshipsApiError && error.status >= 400 && error.status <= 599 ? error.status : null;
  return <S26RecoveryView focus={focus} phase={phase} count={enabled ? query.data?.length ?? 0 : 0}
    refreshing={retrying || (enabled && query.isFetching)} statusCode={statusCode} offline={offline} attempt={attempt} onNavigate={nav} onRetry={retry}/>;
}

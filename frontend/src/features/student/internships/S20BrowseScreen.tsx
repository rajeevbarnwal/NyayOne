import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { useStudentMutation } from '../lib/useStudentMutation';
import { InternshipsApiError } from '../lib/internshipsApi';
import type { InternshipListing, StipendFilter } from '../lib/internships';
import { S20BrowseView, type S20BrowseViewProps, type S20FocusContinuity } from './S20BrowseView';
import { browseInternships, readBrowseSaved, changeBrowseSaved, filterBrowsePage } from './s20Api';
import { captureStudentContextFence, isStudentContextFenceCurrent } from '../lib/studentBrowserContext';
import { settleS21Saved } from './s21SavedCache';

export function S20BrowseScreen() {
  const auth = useAuth(); const session = useStudentSession();
  const focusContinuity = useRef<S20FocusContinuity>(null);
  // Never carry private marks, action errors or in-flight UI across actors.
  return <BrowseController key={`${session.phase}:${auth.userId ?? 'public'}:${auth.roles.join(',')}`} focusContinuity={focusContinuity}/>;
}
function BrowseController({ focusContinuity }: Pick<S20BrowseViewProps, 'focusContinuity'>) {
  const auth = useAuth(); const session = useStudentSession(); const nav = useNavigate(); const client = useQueryClient();
  const [page, setPage] = useState(1), [verifiedOnly, setVerified] = useState(false);
  const [query, setQuery] = useState(''), [stipend, setStipend] = useState<StipendFilter>('any');
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<S20BrowseViewProps['saveError']>(null);
  const [notice, setNotice] = useState(''), [uncertain, setUncertain] = useState(false);
  const lock = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const canSave = session.phase === 'authenticated' && auth.isAuthenticated && auth.roles.includes('student') && !!auth.userId;
  // Detail and saved-list mutations write this same account-scoped cache.
  // Revalidate on entry using S-20's strict reader before exposing save marks.
  const savedKey = ['internships-saved', auth.userId] as const;
  const catalogue = useQuery({ queryKey: ['s20-catalogue', page, verifiedOnly], queryFn: ({ signal }) => browseInternships({ page, verifiedOnly }, signal), enabled: session.phase !== 'pending', retry: false, networkMode: 'always', refetchOnWindowFocus: false });
  const saved = useQuery({ queryKey: savedKey, queryFn: ({ signal }) => readBrowseSaved(signal), enabled: canSave, retry: false, networkMode: 'always', refetchOnWindowFocus: false, refetchOnMount: 'always' });
  const mutation = useStudentMutation({
    retry: false, networkMode: 'always',
    mutationFn: ({ item, desired }: { item: InternshipListing; desired: boolean; fence: ReturnType<typeof captureStudentContextFence> }) => changeBrowseSaved(item.id, desired),
    onSuccess: async (confirmed, { item, fence }) => {
      if (auth.userId) await settleS21Saved(client, auth.userId, item, confirmed, () => isStudentContextFenceCurrent(fence));
    },
  });
  let savedPhase: S20BrowseViewProps['savedPhase'] = !canSave
    ? session.phase === 'pending' ? 'loading' : session.phase === 'unavailable' || (auth.isAuthenticated && !auth.userId) ? 'unavailable' : auth.isAuthenticated ? 'forbidden' : 'anonymous'
    : saved.isError ? 'error' : uncertain ? 'uncertain' : saved.isPending ? 'loading' : 'ready';
  if (canSave && saved.isFetching) savedPhase = 'loading';
  async function save(item: InternshipListing) {
    if (lock.current || savedPhase !== 'ready' || !canSave) return;
    if (!navigator.onLine) {
      setSaveError({ id: item.id, message: 'You are offline. No request was sent. Reconnect and try again.' });
      setNotice(''); return;
    }
    lock.current = true; setPendingId(item.id); setSaveError(null); setNotice('');
    try {
      const confirmed = await mutation.mutateAsync({ item, desired: !(saved.data ?? []).some(i => i.id === item.id), fence: captureStudentContextFence() });
      if (mounted.current) setNotice(confirmed ? 'Saved privately to your account. The organisation is not notified.' : 'Removed from your saved internships.');
    } catch (error) {
      if (mounted.current) {
        setUncertain(true);
        setSaveError({ id: item.id, message: error instanceof InternshipsApiError && error.status === 404 ? 'This listing is no longer available. Reload your saved list.' : 'Could not confirm the change. Reload your saved list before trying again.' });
      }
    } finally {
      lock.current = false; if (mounted.current) setPendingId(null);
    }
  }
  async function retrySaved() {
    if (lock.current || !canSave) return;
    const result = await saved.refetch();
    if (mounted.current && result.isSuccess) { setUncertain(false); setSaveError(null); setNotice('Saved list reloaded.'); }
  }
  const phase: S20BrowseViewProps['phase'] = catalogue.isError ? (typeof navigator !== 'undefined' && !navigator.onLine ? 'offline' : 'error') : catalogue.isPending ? 'loading' : 'results';
  return <S20BrowseView focusContinuity={focusContinuity} catalogueBusy={catalogue.isFetching} phase={phase} items={filterBrowsePage(catalogue.data?.items ?? [], query, stipend)} total={catalogue.data?.total ?? 0} page={page}
    query={query} stipend={stipend} verifiedOnly={verifiedOnly} saved={(saved.data ?? []).map(i => i.id)} savedPhase={savedPhase} pendingId={pendingId} saveError={saveError} notice={notice}
    statusCode={catalogue.error instanceof InternshipsApiError ? catalogue.error.status : null}
    onNavigate={nav} onQuery={setQuery} onStipend={setStipend} onVerified={() => { setVerified(v => !v); setPage(1); }} onPage={setPage}
    onClear={() => { setQuery(''); setStipend('any'); setVerified(false); setPage(1); }} onRetry={() => catalogue.refetch()} onRetrySaved={retrySaved} onSave={save}/>;
}

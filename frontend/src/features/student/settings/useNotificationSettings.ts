import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useStudentSession } from '../../../app/authContext';
import { getStudentSettings, updateStudentSettings } from '../lib/settingsApi';
import { captureStudentMutationSequence, runStudentMutationStep, isStudentMutationCancellation } from '../lib/useStudentMutation';
import { useRequestSettlement, useRouteContinuation } from '../lib/routeContinuation';
import { beginSettingsChange, confirmedSettings, failSettingsChange, initialSettingsState, validateSettings, type NotificationPatch, type NotificationSettingsState } from './notificationSettingsState';

/** S-18 only. S-19's existing settings controller is intentionally untouched. */
export function useNotificationSettings() {
  const session = useStudentSession();
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ['student-settings'], queryFn: async () => validateSettings(await getStudentSettings()), enabled: session.phase === 'authenticated', retry: false, refetchOnWindowFocus: false });
  const [actionState, setState] = useState(initialSettingsState);
  const state = actionState.phase !== 'loading' ? actionState
    : query.isFetching || !query.isFetched ? initialSettingsState
    : query.isError ? failSettingsChange(initialSettingsState, query.error)
    : confirmedSettings(query.data);
  const inFlight = useRef(false);
  const currentRoute = useRouteContinuation();
  const currentSettlement = useRequestSettlement();
  const commit = (next: NotificationSettingsState) => setState(next);

  async function reload() {
    if (inFlight.current || session.phase !== 'authenticated') return;
    inFlight.current = true;
    const routeOwned = currentRoute(), settledHere = currentSettlement();
    commit(initialSettingsState);
    try {
      const result = await query.refetch();
      if (routeOwned()) commit(result.isError ? failSettingsChange(initialSettingsState, result.error) : confirmedSettings(result.data));
    } finally {
      // Release UI ownership only once transport settles, never on a URL change.
      if (settledHere()) inFlight.current = false;
    }
  }

  async function change(patch: NotificationPatch) {
    if (inFlight.current || session.phase !== 'authenticated') return;
    const next = beginSettingsChange(state, patch);
    if (next === state || next.expectedVersion === undefined) return;
    inFlight.current = true;
    const routeOwned = currentRoute(), settledHere = currentSettlement();
    const fence = captureStudentMutationSequence();
    commit(next);
    try {
      const data = await runStudentMutationStep(fence, () => updateStudentSettings(patch, next.expectedVersion!));
      const confirmed = confirmedSettings(data, true);
      // Auth-fenced server truth can refresh the shared cache; stale route UI
      // must not announce success or navigate after the owner has left.
      qc.setQueryData(['student-settings'], data);
      if (routeOwned()) commit(confirmed);
      else if (settledHere()) commit(confirmedSettings(data));
    } catch (error) {
      if (!isStudentMutationCancellation(error) && settledHere()) {
        commit(failSettingsChange(next, error));
      }
    } finally {
      if (settledHere()) inFlight.current = false;
    }
  }

  return { state, change, reload };
}

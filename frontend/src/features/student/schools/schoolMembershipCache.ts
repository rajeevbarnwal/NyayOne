import type { QueryClient } from '@tanstack/react-query';
import type { S28Detail } from './s28Api';

/** Apply only a validated server-confirmed removal, after cancelling older reads.
 * Keep the other membership intact; never create a missing list or detail cache. */
export function synchronizeSchoolRemoval(client: QueryClient, actor: string, kind: 'saved' | 'followed', id: string): void {
  client.setQueryData<{ id: string }[]>([`law-schools-${kind}`, actor], items => items?.filter(item => item.id !== id));
  client.setQueryData<S28Detail>(['s28-detail', actor, id], detail => detail ? {
    ...detail,
    ...(kind === 'saved' ? { saved: false } : { followed: false, notifyOptIn: false }),
  } : detail);
}

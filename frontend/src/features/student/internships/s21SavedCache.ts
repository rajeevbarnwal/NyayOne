import type { QueryClient } from '@tanstack/react-query';
import type { InternshipListing } from '../lib/internships';

// S-20 and S-25 observe the same actor-scoped cache. Cancel even a GET that
// started AFTER dispatch, but BEFORE the mutation committed (QA R2-1).
export async function settleS21Saved(client: QueryClient, userId: string, item: InternshipListing, saved: boolean, current: () => boolean) {
  if (!current()) return;
  const key = ['internships-saved', userId];
  await client.cancelQueries({ queryKey: key, exact: true });
  await client.cancelQueries({ queryKey: ['s20-saved', userId], exact: true });
  if (!current()) return;
  client.setQueryData<InternshipListing[]>(key, (old = []) =>
    saved ? [item, ...old.filter(i => i.id !== item.id)] : old.filter(i => i.id !== item.id));
  // Mark inactive consumers stale too. Active consumers now read a post-commit
  // snapshot, never a pre-commit response selected for its arrival order.
  void client.invalidateQueries({ queryKey: key, exact: true });
  void client.invalidateQueries({ queryKey: ['s20-saved', userId], exact: true });
}

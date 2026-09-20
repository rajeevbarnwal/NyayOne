import { useLayoutEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';

/** UI ownership only. Never abort transport, release a lease, or undo a server write. */
export function createRouteContinuationOwner() {
  let active = false;
  let generation = 0;
  return {
    activate() { generation += 1; active = true; },
    retire() { generation += 1; active = false; },
    capture() {
      const token = ++generation;
      const capturedActive = active;
      return () => capturedActive && active && token === generation;
    },
  };
}

/** Retire on committed navigation (including query/hash/history key) and unmount. */
export function useRouteContinuation() {
  const location = useLocation();
  const owner = useMemo(createRouteContinuationOwner, []);
  useLayoutEffect(() => {
    owner.activate();
    return () => owner.retire();
  }, [owner, location.key, location.pathname, location.search, location.hash]);
  return owner.capture;
}

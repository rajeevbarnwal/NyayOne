import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getOtpFlowState,
  type OtpFlowState,
} from './registrationApi';

interface OtpFlowSnapshot {
  state: OtpFlowState;
  receivedAtMs: number;
}

export interface LiveOtpFlowState extends OtpFlowState {
  expiresInSeconds: number | null;
  resendInSeconds: number | null;
  lockedForSeconds: number | null;
}

export interface OtpFlowStateOptions {
  /**
   * The owning session boundary must settle before OTP discovery begins.
   * Disabled reads expose no cached capability and dispatch no server request.
   */
  enabled?: boolean;
}

function subtractElapsed(value: number | null, elapsedSeconds: number): number | null {
  return value === null ? null : Math.max(0, value - elapsedSeconds);
}

/**
 * Read-only view of the server-owned OTP flow.
 *
 * The snapshot contains relative durations only.  A local monotonic-looking
 * display ticker may count those values down, but it never grants a resend or
 * verification decision: controls remain gated by the latest server boolean
 * and every mutation returns/refetches authoritative state.
 */
export function useOtpFlowState(
  initialState?: OtpFlowState,
  options: OtpFlowStateOptions = {},
) {
  const enabled = options.enabled ?? true;
  const [snapshot, setSnapshot] = useState<OtpFlowSnapshot | null>(() => (
    initialState ? { state: initialState, receivedAtMs: Date.now() } : null
  ));
  const [nowMs, setNowMs] = useState(Date.now());
  const [loading, setLoading] = useState(initialState === undefined);
  const [loadError, setLoadError] = useState(false);
  const mutationRevision = useRef(0);
  const enabledRef = useRef(enabled);
  // Render-time assignment also protects callbacks retained by an async action
  // from publishing a capability after the session phase turns pending.
  enabledRef.current = enabled;

  const adopt = useCallback((state: OtpFlowState) => {
    mutationRevision.current += 1;
    if (!enabledRef.current) {
      setSnapshot(null);
      setLoadError(false);
      setLoading(true);
      return;
    }
    const receivedAtMs = Date.now();
    setSnapshot({ state, receivedAtMs });
    setNowMs(receivedAtMs);
    setLoadError(false);
    setLoading(false);
  }, []);

  const refresh = useCallback(async () => {
    if (!enabledRef.current) throw new Error('otp_flow_state_read_disabled');
    const revisionAtStart = mutationRevision.current;
    try {
      const state = await getOtpFlowState();
      // A start/verify/resend response received while this GET was in flight is
      // newer authority. Never let the stale read overwrite that mutation.
      if (enabledRef.current && revisionAtStart === mutationRevision.current) {
        const receivedAtMs = Date.now();
        setSnapshot({ state, receivedAtMs });
        setNowMs(receivedAtMs);
        setLoadError(false);
        setLoading(false);
      }
      return state;
    } catch (error) {
      if (enabledRef.current && revisionAtStart === mutationRevision.current) {
        // A failed later read revokes the browser's ability to act on the
        // previously displayed snapshot. Keep no stale pending/verified
        // capability alive while authority is unreachable; a later successful
        // poll may restore a fresh server projection.
        setSnapshot(null);
        setLoadError(true);
        setLoading(false);
      }
      throw error;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      mutationRevision.current += 1;
      setSnapshot(null);
      setLoadError(false);
      setLoading(true);
      return;
    }
    void refresh().catch(() => undefined);
  }, [enabled, refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  // A short read-only poll corrects clock suspension/background-tab drift and
  // picks up a server transition at expiry/cooldown/lock boundaries.  It does
  // not reset or invent any client-side security budget.
  useEffect(() => {
    if (!enabled) return undefined;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [enabled, refresh]);

  const state = useMemo<LiveOtpFlowState | null>(() => {
    if (!snapshot) return null;
    const elapsedSeconds = Math.max(
      0,
      Math.floor((nowMs - snapshot.receivedAtMs) / 1_000),
    );
    return {
      ...snapshot.state,
      expiresInSeconds: subtractElapsed(snapshot.state.expiresInSeconds, elapsedSeconds),
      resendInSeconds: subtractElapsed(snapshot.state.resendInSeconds, elapsedSeconds),
      lockedForSeconds: subtractElapsed(snapshot.state.lockedForSeconds, elapsedSeconds),
    };
  }, [nowMs, snapshot]);

  return {
    state: enabled ? state : null,
    loading: enabled ? loading : true,
    loadError: enabled ? loadError : false,
    adopt,
    refresh,
  } as const;
}

import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OtpFlowState } from '../lib/registrationApi';
import type { S06R2Props } from './S06R2';

// This controller harness invokes the actual event callbacks with deterministic
// async authority. The separate browser regression covers browser event/focus behavior.
const harness = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0,
  phase: 'anonymous',
  flow: { state: null as OtpFlowState | null, loading: false, loadError: false, adopt: vi.fn(), refresh: vi.fn() },
  useFlow: vi.fn(), start: vi.fn(), verify: vi.fn(), resend: vi.fn(), cancel: vi.fn(), complete: vi.fn(), navigate: vi.fn(),
}));
vi.mock('react', async importOriginal => ({
  ...(await importOriginal<typeof import('react')>()),
  useState: (initial: unknown) => {
    const index = harness.cursor++;
    if (!(index in harness.slots)) harness.slots[index] = initial;
    return [harness.slots[index], (next: unknown) => {
      harness.slots[index] = typeof next === 'function' ? next(harness.slots[index]) : next;
    }];
  },
  useRef: (initial: unknown) => {
    const index = harness.cursor++;
    if (!(index in harness.slots)) harness.slots[index] = { current: initial };
    return harness.slots[index];
  },
  useEffect: () => undefined,
}));
vi.mock('react-router-dom', () => ({ useNavigate: () => harness.navigate }));
vi.mock('../../../app/authContext', () => ({ useStudentSession: () => ({ phase: harness.phase }) }));
vi.mock('../lib/useOtpFlowState', () => ({ useOtpFlowState: (...args: unknown[]) => { harness.useFlow(...args); return harness.flow; } }));
vi.mock('../lib/registrationApi', async importOriginal => ({
  ...(await importOriginal<typeof import('../lib/registrationApi')>()),
  startRecovery: (...args: unknown[]) => harness.start(...args),
  verifyRecovery: (...args: unknown[]) => harness.verify(...args),
  resendStudentOtp: (...args: unknown[]) => harness.resend(...args),
  cancelStudentOtp: (...args: unknown[]) => harness.cancel(...args),
  completeRecovery: (...args: unknown[]) => harness.complete(...args),
}));

import { RegistrationApiError } from '../lib/registrationApi';
import { S06Recovery } from './S06Recovery';
import { S06R2, focusRecoveryTarget } from './S06R2';

const pending: OtpFlowState = { status: 'pending', purpose: 'recovery', destinationMasked: '••••••0340', attemptsLeft: 3, expiresInSeconds: 272, resendInSeconds: 0, lockedForSeconds: 0, resendAllowed: true };
const empty: OtpFlowState = { status: 'unavailable', purpose: null, destinationMasked: null, attemptsLeft: null, expiresInSeconds: null, resendInSeconds: null, lockedForSeconds: null, resendAllowed: false };
function render(): S06R2Props { harness.cursor = 0; return S06Recovery().props; }
async function settle() { await new Promise<void>(resolve => setTimeout(resolve, 0)); return render(); }
function findInput(node: ReactNode): ReactElement<Record<string, unknown>> | undefined {
  if (!isValidElement(node)) return undefined;
  const element = node as ReactElement<Record<string, unknown>>;
  if (element.type === 'input' && element.props.id === 'v34-recovery-code') return element;
  for (const child of [element.props.children].flat(Infinity) as ReactNode[]) {
    const found = findInput(child); if (found) return found;
  }
  return undefined;
}

beforeEach(() => {
  vi.clearAllMocks(); vi.unstubAllGlobals(); harness.slots = []; harness.cursor = 0; harness.phase = 'anonymous';
  harness.flow.state = pending; harness.flow.loading = false; harness.flow.loadError = false;
  harness.flow.adopt.mockImplementation(state => { harness.flow.state = state; });
});

describe('NYAY-85 independent-QA regression contracts', () => {
  it.each(['pending', 'authenticated', 'unavailable'])('F1 refuses discovery while session is %s', phase => {
    harness.phase = phase; render();
    expect(harness.useFlow).toHaveBeenLastCalledWith(undefined, { enabled: false });
  });
  it('F1 enables discovery only when the session is anonymous', () => {
    render(); expect(harness.useFlow).toHaveBeenLastCalledWith(undefined, { enabled: true });
  });
  it('F2 maps a real resend_cooldown projection to cooldown, never incorrect-code', async () => {
    const cooldown = { ...pending, resendAllowed: false, resendInSeconds: 8 };
    harness.resend.mockRejectedValue(new RegistrationApiError(429, 'resend_cooldown', undefined, cooldown, 8));
    render().onResend(); const result = await settle();
    expect(harness.flow.adopt).toHaveBeenCalledWith(cooldown);
    expect(result.state).toBe('cooldown'); expect(result.resendAllowed).toBe(false);
    expect(result.resendInSeconds).toBe(8); expect(result.attemptsLeft).toBe(3);
  });
  it('F2 preserves wrong-code handling for an actual incorrect_otp response', async () => {
    harness.verify.mockRejectedValue(new RegistrationApiError(401, 'incorrect_otp', undefined, { ...pending, attemptsLeft: 2 }));
    render().onCodeChange('123456'); render().onVerify(); const result = await settle();
    expect(result.state).toBe('wrong'); expect(result.attemptsLeft).toBe(2); expect(harness.complete).not.toHaveBeenCalled();
  });
  it.each(['123 456', '123-456', ' 123-456\n', '123456'])('F4 normalizes a full paste before the native maxlength truncates %j', text => {
    const props = render(); harness.cursor = 0;
    const input = findInput(S06R2(props));
    const preventDefault = vi.fn(); const onPaste = input?.props.onPaste as ((event: unknown) => void) | undefined;
    expect(onPaste).toBeTypeOf('function');
    onPaste?.({ preventDefault, clipboardData: { getData: () => text } });
    expect(preventDefault).toHaveBeenCalledOnce(); expect(render().code).toBe('123456');
  });
  it.each(['Verify', 'Send', 'Change number', 'Try again'])('F5 requests focus recovery after keyboard %s fails', async action => {
    vi.stubGlobal('document', { activeElement: { matches: (selector: string) => selector === ':focus-visible' } });
    const failure = new Error('network_unavailable');
    harness.verify.mockRejectedValue(failure); harness.start.mockRejectedValue(failure);
    harness.cancel.mockRejectedValue(failure); harness.flow.refresh.mockRejectedValue(failure);
    if (action === 'Send') { harness.flow.state = empty; render().onMobileChange('9876543210'); render().onSend(); }
    else if (action === 'Verify') { render().onCodeChange('123456'); render().onVerify(); }
    else if (action === 'Change number') render().onChangeNumber();
    else render().onRetry();
    const result = await settle(); expect(result.state).toBe('neterr'); expect(result.focusRequest).toBe(1);
  });
  it('F5 does not move focus after a pointer operation', async () => {
    vi.stubGlobal('document', { activeElement: { matches: () => false } });
    harness.cancel.mockRejectedValue(new Error('network_unavailable'));
    render().onChangeNumber(); const result = await settle(); expect(result.focusRequest).toBe(0);
  });
  it.each([
    ['entry', '#v34-reset-mobile'], ['invalidnum', '#v34-reset-mobile'],
    ['wrong', '#v34-recovery-code'], ['cooldown', '#v34-recovery-code'],
    ['neterr', '[data-recovery-retry]'], ['locked', '[data-recovery-return]'],
  ] as const)('F5 selects a meaningful focus target for %s', (state, selector) => {
    const focus = vi.fn(), querySelector = vi.fn(() => ({ focus }));
    focusRecoveryTarget({ querySelector } as unknown as HTMLElement, state);
    expect(querySelector).toHaveBeenCalledWith(selector); expect(focus).toHaveBeenCalledOnce();
  });
});

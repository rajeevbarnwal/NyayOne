import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Controller callbacks and real ownership hooks; synthetic transport/React lifecycle.
// nyay84-pr1-browser.mjs separately exercises the actual React Router and browser.
const h = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0,
  effects: new Map<number, { deps: unknown[]; cleanup?: () => void }>(),
  location: { key: 'entry', pathname: '/s-08', search: '', hash: '' },
  register: vi.fn(), verify: vi.fn(), navigate: vi.fn(), adopt: vi.fn(),
  purpose: 'login',
}));
vi.mock('react', async original => ({
  ...(await original<typeof import('react')>()),
  useState: (initial: unknown) => {
    const index = h.cursor++;
    if (!(index in h.slots)) h.slots[index] = initial;
    return [h.slots[index], (value: unknown) => { h.slots[index] = value; }];
  },
  useRef: (initial: unknown) => {
    const index = h.cursor++;
    if (!(index in h.slots)) h.slots[index] = { current: initial };
    return h.slots[index];
  },
  useMemo: (factory: () => unknown) => {
    const index = h.cursor++;
    if (!(index in h.slots)) h.slots[index] = factory();
    return h.slots[index];
  },
  useLayoutEffect: (effect: () => (() => void), deps: unknown[]) => {
    const index = h.cursor++;
    const previous = h.effects.get(index);
    if (!previous || deps.some((value, i) => value !== previous.deps[i])) {
      previous?.cleanup?.();
      h.effects.set(index, { deps, cleanup: effect() });
    }
  },
  useEffect: () => undefined,
  useContext: () => ({}),
}));
vi.mock('react-router-dom', async original => ({
  ...(await original<typeof import('react-router-dom')>()),
  useNavigate: () => h.navigate, useLocation: () => h.location,
}));
vi.mock('../../../app/authContext', () => ({ useStudentSession: () => ({ phase: 'anonymous' }) }));
vi.mock('../lib/useOtpFlowState', () => ({ useOtpFlowState: () => ({
  state: { status: 'pending', purpose: h.purpose, expiresInSeconds: 300, resendInSeconds: 0, resendAllowed: true, attemptsLeft: 3 },
  adopt: h.adopt, loading: false, loadError: false,
}) }));
vi.mock('../lib/registrationApi', async original => ({
  ...(await original<typeof import('../lib/registrationApi')>()),
  registerStudent: (...args: unknown[]) => h.register(...args),
  verifyLoginOtp: (...args: unknown[]) => h.verify(...args),
  verifyStudentOtp: (...args: unknown[]) => h.verify(...args),
}));
import { V34Register, V34LoginOtp, V34OtpVerify } from './V34Screens';

type Kind = 'register' | 'login' | 'signup';
type Element = ReactElement<Record<string, unknown>>;
function find(node: ReactNode, matches: (element: Element) => boolean): Element | undefined {
  if (!isValidElement(node)) return undefined;
  const element = node as Element;
  if (matches(element)) return element;
  for (const child of [element.props.children].flat(Infinity) as ReactNode[]) {
    const found = find(child, matches); if (found) return found;
  }
}
function render(kind: Kind): ReactNode {
  h.cursor = 0;
  if (kind === 'register') return V34Register({});
  h.purpose = kind === 'signup' ? 'signup' : 'login';
  const wrapper = kind === 'login' ? V34LoginOtp({}) : V34OtpVerify({});
  const child = wrapper.props.children;
  return child.type(child.props);
}
function button(kind: Kind) {
  const element = find(render(kind), e => e.type === 'button' && e.props['aria-label'] === (kind === 'register' ? 'Create Account' : 'Verify and continue'));
  if (!element) throw Error('missing submit button');
  return element.props as { disabled: boolean; onClick: () => Promise<void> };
}
function fill(kind: Kind) {
  if (kind === 'register') {
    for (const [id, value] of [['first', 'Synthetic'], ['last', 'Student'], ['mobile', '9000000084'], ['dob', '2000-01-01']]) {
      const field = find(render(kind), e => e.props.id === `v34-${id}`)!;
      (field.props.onChange as (value: string) => void)(value);
    }
    for (const id of ['terms', 'privacy']) {
      const field = find(render(kind), e => e.props.id === `v34-${id}`)!;
      (field.props.onChange as (event: unknown) => void)({ target: { checked: true } });
    }
  } else {
    const field = find(render(kind), e => e.props['aria-label'] === 'Six digit code')!;
    (field.props.onChange as (event: unknown) => void)({ target: { value: '123456' } });
  }
}
function held() {
  let resolve!: (value: unknown) => void, reject!: (reason: Error) => void;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function unmount() { for (const effect of h.effects.values()) effect.cleanup?.(); h.effects.clear(); h.slots = []; }
beforeEach(() => {
  unmount(); vi.clearAllMocks(); h.cursor = 0;
  h.location = { key: 'entry', pathname: '/s-08', search: '', hash: '' };
});

describe.each<Kind>(['register', 'login', 'signup'])('CQA-F1 %s settlement ownership', kind => {
  it.each(['search', 'hash'] as const)('settles success/failure after a same-mounted %s change without stale publication', async field => {
    for (const outcome of ['success', 'failure']) {
      fill(kind);
      const request = held(); (kind === 'register' ? h.register : h.verify).mockReturnValueOnce(request.promise);
      const result = button(kind).onClick();
      expect(button(kind).disabled).toBe(true);
      h.location = { ...h.location, key: outcome, [field]: field === 'hash' ? '#changed' : '?changed' };
      expect(button(kind).disabled).toBe(true); // Do not clear busy on location change.
      if (outcome === 'failure') request.reject(Error('synthetic_failure'));
      else request.resolve({ status: 'authenticated' });
      await result;
      expect(button(kind).disabled).toBe(false);
      expect(h.navigate).not.toHaveBeenCalled(); expect(h.adopt).not.toHaveBeenCalled();
      expect(find(render(kind), e => e.props.role === 'alert' && e.props.hidden !== true)).toBeUndefined();
    }
  });
  it('does not let an older settlement clear a newer submission', async () => {
    fill(kind); const first = held(), second = held();
    (kind === 'register' ? h.register : h.verify).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const submit = button(kind).onClick;
    const old = submit(), current = submit(); // Synthetic overlapping callbacks, not duplicate-dispatch acceptance.
    first.reject(Error('old')); await old;
    expect(button(kind).disabled).toBe(true);
    second.reject(Error('current')); await current;
    expect(button(kind).disabled).toBe(false);
  });
  it('cannot clear a new mount\'s busy state after leaving and returning', async () => {
    fill(kind); const first = held(), second = held();
    (kind === 'register' ? h.register : h.verify).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const old = button(kind).onClick(); unmount(); fill(kind);
    const current = button(kind).onClick();
    first.reject(Error('unmounted')); await old;
    expect(button(kind).disabled).toBe(true); expect(h.navigate).not.toHaveBeenCalled();
    second.reject(Error('current')); await current;
    expect(button(kind).disabled).toBe(false);
  });
});

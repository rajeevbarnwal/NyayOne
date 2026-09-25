import { describe, expect, it } from 'vitest';
import { createRouteContinuationOwner } from './routeContinuation';

describe('PR1 route/request continuation ownership', () => {
  it('permits only the current request on the committed route', () => {
    const owner = createRouteContinuationOwner();
    owner.activate();
    const first = owner.capture();
    expect(first()).toBe(true);
    const second = owner.capture();
    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });

  it('retirement suppresses both late success and late failure, without cancelling transport', async () => {
    const owner = createRouteContinuationOwner();
    owner.activate();
    const current = owner.capture();
    let settle!: () => void;
    let committed = false;
    const transport = new Promise<void>(resolve => { settle = resolve; });
    const response = transport.then(() => { committed = true; return current(); });
    owner.retire();
    settle();
    expect(await response).toBe(false);
    expect(committed).toBe(true); // UI retirement is not server rollback or lease release.
    expect(current()).toBe(false);
  });

  it('returning to the same route or StrictMode remount never revives old tokens', () => {
    const owner = createRouteContinuationOwner();
    owner.activate();
    const old = owner.capture();
    owner.retire();
    owner.activate();
    expect(old()).toBe(false);
    expect(owner.capture()()).toBe(true);
  });

  it('captures before commit or after unmount never acquire ownership', () => {
    const owner = createRouteContinuationOwner();
    const before = owner.capture();
    expect(before()).toBe(false);
    owner.activate();
    expect(before()).toBe(false);
    owner.retire();
    expect(owner.capture()()).toBe(false);
  });
});

import { vi } from 'vitest';

type FakeLockMode = 'exclusive' | 'shared';

interface FakeLockRequestOptions {
  mode?: FakeLockMode;
  signal?: AbortSignal;
}

interface QueuedLockRequest<T = unknown> {
  name: string;
  mode: FakeLockMode;
  callback: (lock: Lock) => PromiseLike<T> | T;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
  signal?: AbortSignal;
  abort: () => void;
}

/** Deterministic FIFO readers/writer LockManager used by auth-boundary tests. */
export class FakeLockManager {
  private readonly queues = new Map<string, QueuedLockRequest[]>();
  private readonly held = new Map<string, Set<QueuedLockRequest>>();

  request<T>(
    name: string,
    options: FakeLockRequestOptions,
    callback: (lock: Lock) => PromiseLike<T> | T,
  ): Promise<T>;
  request<T>(name: string, callback: (lock: Lock) => PromiseLike<T> | T): Promise<T>;
  request<T>(
    name: string,
    optionsOrCallback: FakeLockRequestOptions | ((lock: Lock) => PromiseLike<T> | T),
    maybeCallback?: (lock: Lock) => PromiseLike<T> | T,
  ): Promise<T> {
    const options = typeof optionsOrCallback === 'function' ? {} : optionsOrCallback;
    const callback = typeof optionsOrCallback === 'function' ? optionsOrCallback : maybeCallback!;
    return new Promise<T>((resolve, reject) => {
      if (options.signal?.aborted) {
        reject(new DOMException('The lock request was aborted', 'AbortError'));
        return;
      }
      const request: QueuedLockRequest<T> = {
        name,
        mode: options.mode ?? 'exclusive',
        callback,
        resolve,
        reject,
        signal: options.signal,
        abort: () => {
          const queue = this.queues.get(name);
          const index = queue?.indexOf(request as QueuedLockRequest) ?? -1;
          if (index < 0) return;
          queue!.splice(index, 1);
          reject(new DOMException('The lock request was aborted', 'AbortError'));
          this.drain(name);
        },
      };
      options.signal?.addEventListener('abort', request.abort, { once: true });
      const queue = this.queues.get(name) ?? [];
      queue.push(request as QueuedLockRequest);
      this.queues.set(name, queue);
      this.drain(name);
    });
  }

  async acquireShared(name: string): Promise<() => void> {
    let release!: () => void;
    let acquired!: () => void;
    const acquiredPromise = new Promise<void>((resolve) => { acquired = resolve; });
    const held = new Promise<void>((resolve) => { release = resolve; });
    void this.request(name, { mode: 'shared' }, async () => {
      acquired();
      await held;
    });
    await acquiredPromise;
    return release;
  }

  heldModes(name: string): FakeLockMode[] {
    return [...(this.held.get(name) ?? [])].map((request) => request.mode);
  }

  queuedModes(name: string): FakeLockMode[] {
    return (this.queues.get(name) ?? []).map((request) => request.mode);
  }

  private drain(name: string): void {
    const queue = this.queues.get(name) ?? [];
    const held = this.held.get(name) ?? new Set<QueuedLockRequest>();
    if (held.size > 0 && [...held].some((request) => request.mode === 'exclusive')) return;
    if (queue.length === 0) return;
    if (held.size > 0 && queue[0]?.mode === 'exclusive') return;

    if (queue[0]?.mode === 'exclusive') {
      this.grant(name, queue.shift()!);
      return;
    }
    while (queue[0]?.mode === 'shared') this.grant(name, queue.shift()!);
  }

  private grant(name: string, request: QueuedLockRequest): void {
    request.signal?.removeEventListener('abort', request.abort);
    const held = this.held.get(name) ?? new Set<QueuedLockRequest>();
    held.add(request);
    this.held.set(name, held);
    const lock = { name, mode: request.mode } as Lock;
    void Promise.resolve()
      .then(() => request.callback(lock))
      .then(request.resolve, request.reject)
      .finally(() => {
        held.delete(request);
        this.drain(name);
      });
  }
}

export function stubNavigatorLocks(locks: FakeLockManager): void {
  vi.stubGlobal('navigator', { locks });
}

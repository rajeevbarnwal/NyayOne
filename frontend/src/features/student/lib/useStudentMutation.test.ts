import { QueryClient } from '@tanstack/react-query';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  clearStudentBrowserContext,
  observeStudentSessionActor,
} from './studentBrowserContext';
import {
  captureStudentMutationVariables,
  createStudentMutationOptions,
  runStudentMutationStep,
  settleStudentMutationForCaller,
} from './useStudentMutation';

afterEach(() => {
  clearStudentBrowserContext();
});

describe('student mutation actor-generation fence', () => {
  it('keeps the wrapped mutate entry points stable across consumer rerenders', () => {
    const source = readFileSync(
      join(process.cwd(), 'src/features/student/lib/useStudentMutation.ts'),
      'utf8',
    );

    expect(source).toMatch(/const mutate = useCallback\(/u);
    expect(source).toMatch(/const mutateAsync = useCallback\(/u);
    expect(source).toMatch(/return \{[\s\S]*\bmutate,[\s\S]*\bmutateAsync,[\s\S]*\} as UseMutationResult/u);
  });

  it('routes every student screen mutation callback through the generation fence', () => {
    const root = join(process.cwd(), 'src/features/student');
    const files: string[] = [];
    const visit = (directory: string) => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) visit(path);
        else if (entry.isFile() && entry.name.endsWith('.tsx')) files.push(path);
      }
    };
    visit(root);
    const mutationScreens = files.filter((path) => readFileSync(path, 'utf8').includes('useMutation('));
    expect(mutationScreens.length).toBeGreaterThan(0);
    for (const path of mutationScreens) {
      const value = readFileSync(path, 'utf8');
      expect(value, path).toMatch(/useStudentMutation\s+as\s+useMutation[\s\S]*from ['"]\.\.\/lib\/useStudentMutation['"]/u);
      expect(value, path).not.toMatch(/import \{[^\n]*useMutation[^\n]*\} from '@tanstack\/react-query'/u);
    }
  });

  it('forwards callback context while the owning actor remains current', async () => {
    const client = new QueryClient();
    const onSuccess = vi.fn();
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const mutation = client.getMutationCache().build(client, createStudentMutationOptions({
      mutationFn: async (value: string) => value.toUpperCase(),
      onMutate: (value) => ({ previous: value }),
      onSuccess,
    }));

    await mutation.execute(captureStudentMutationVariables('draft'));

    expect(onSuccess).toHaveBeenCalledWith(
      'DRAFT',
      'draft',
      { previous: 'draft' },
      expect.any(Object),
    );
  });

  it('suppresses a late success after logout and actor rotation', async () => {
    const client = new QueryClient();
    const onSuccess = vi.fn();
    let resolveMutation!: (value: string) => void;
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const mutation = client.getMutationCache().build(client, createStudentMutationOptions({
      mutationFn: () => new Promise<string>((resolve) => { resolveMutation = resolve; }),
      onSuccess,
    }));
    const result = mutation.execute(captureStudentMutationVariables(undefined));
    await vi.waitFor(() => expect(resolveMutation).toBeTypeOf('function'));

    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    resolveMutation('actor-A-result');
    await result;

    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('never dispatches actor A payload after rotation during async onMutate', async () => {
    const client = new QueryClient();
    const mutationFn = vi.fn(async (_value: string) => 'sent');
    let releaseOnMutate!: () => void;
    let onMutateStarted!: () => void;
    const started = new Promise<void>((resolve) => { onMutateStarted = resolve; });
    const paused = new Promise<void>((resolve) => { releaseOnMutate = resolve; });
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const mutation = client.getMutationCache().build(client, createStudentMutationOptions({
      mutationFn,
      onMutate: async () => {
        onMutateStarted();
        await paused;
      },
    }));
    const result = mutation.execute(
      captureStudentMutationVariables('actor-A-payload'),
    ).catch((error: unknown) => error);
    await started;

    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    releaseOnMutate();
    const error = await result;

    expect(mutationFn).not.toHaveBeenCalled();
    expect(error).toEqual(expect.objectContaining({
      message: 'student_context_changed_before_mutation',
    }));
  });

  it('never resolves a stale mutateAsync continuation into actor B UI', async () => {
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const variables = captureStudentMutationVariables('actor-A-payload');
    let resolveMutation!: (value: string) => void;
    const request = new Promise<string>((resolve) => { resolveMutation = resolve; });
    const continuation = settleStudentMutationForCaller(variables.fence, request);

    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    resolveMutation('actor-A-result');

    await expect(continuation).rejects.toEqual(expect.objectContaining({
      message: 'student_context_changed_before_mutation',
    }));
  });

  it('never dispatches a later network step after the actor changes mid-sequence', async () => {
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const variables = captureStudentMutationVariables(undefined);
    const first = vi.fn(async () => 'created-for-A');
    const second = vi.fn(async () => 'uploaded-for-A');

    await expect(runStudentMutationStep(variables.fence, first)).resolves.toBe('created-for-A');
    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });

    await expect(runStudentMutationStep(variables.fence, second)).rejects.toEqual(
      expect.objectContaining({ message: 'student_context_changed_before_mutation' }),
    );
    expect(second).not.toHaveBeenCalled();
  });

  it('lets an already-dispatched step settle before rejecting its stale actor generation', async () => {
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const variables = captureStudentMutationVariables(undefined);
    let releaseResponse!: (value: string) => void;
    let transportSignal: AbortSignal | undefined;
    const heldResponse = new Promise<string>((resolve) => { releaseResponse = resolve; });
    const attempt = runStudentMutationStep(variables.fence, (signal) => {
      transportSignal = signal;
      return heldResponse;
    });

    await vi.waitFor(() => expect(releaseResponse).toBeTypeOf('function'));
    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });

    // Context invalidation suppresses the continuation, but must not abort an
    // already-dispatched HTTP request and prematurely release its shared lease.
    expect(transportSignal?.aborted ?? false).toBe(false);
    releaseResponse('actor-A-response');
    await expect(attempt).rejects.toEqual(expect.objectContaining({
      message: 'student_context_changed_before_mutation',
    }));
  });

  it('still forwards an explicit caller cancellation signal to the operation', async () => {
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const variables = captureStudentMutationVariables(undefined);
    const cancellation = new AbortController();
    let receivedSignal: AbortSignal | undefined;

    const attempt = runStudentMutationStep(
      variables.fence,
      (signal) => new Promise<string>((_resolve, reject) => {
        receivedSignal = signal;
        signal?.addEventListener('abort', () => {
          reject(new DOMException('caller cancelled', 'AbortError'));
        }, { once: true });
      }),
      cancellation.signal,
    );

    expect(receivedSignal).toBe(cancellation.signal);
    cancellation.abort();
    await expect(attempt).rejects.toEqual(expect.objectContaining({ name: 'AbortError' }));
  });

  it('suppresses late error and settled callbacks after actor rotation', async () => {
    const client = new QueryClient();
    const onError = vi.fn();
    const onSettled = vi.fn();
    let rejectMutation!: (error: Error) => void;
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const mutation = client.getMutationCache().build(client, createStudentMutationOptions({
      mutationFn: () => new Promise<string>((_resolve, reject) => { rejectMutation = reject; }),
      onError,
      onSettled,
    }));
    const result = mutation.execute(
      captureStudentMutationVariables(undefined),
    ).catch((error: unknown) => error);
    await vi.waitFor(() => expect(rejectMutation).toBeTypeOf('function'));

    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    rejectMutation(new Error('actor A failed late'));
    await result;

    expect(onError).not.toHaveBeenCalled();
    expect(onSettled).not.toHaveBeenCalled();
  });
});

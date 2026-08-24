import {
  useMutation,
  type DefaultError,
  type MutateOptions,
  type UseMutationOptions,
  type UseMutationResult,
} from '@tanstack/react-query';
import { useCallback } from 'react';
import {
  captureStudentContextFence,
  isStudentContextFenceCurrent,
  type StudentContextFence,
} from './studentBrowserContext';

export interface StudentMutationVariables<TVariables> {
  fence: StudentContextFence;
  value: TVariables;
}

interface StudentMutationCallbackContext<TOnMutateResult> {
  fence: StudentContextFence;
  value: TOnMutateResult | undefined;
}

export class StudentMutationCancelledError extends Error {
  readonly code = 'student_context_changed_before_mutation';

  constructor() {
    super('student_context_changed_before_mutation');
    this.name = 'StudentMutationCancelledError';
  }
}

function staleStudentMutation(): StudentMutationCancelledError {
  return new StudentMutationCancelledError();
}

export async function runStudentMutationStep<T>(
  fence: StudentContextFence,
  operation: (signal?: AbortSignal) => Promise<T>,
  operationSignal?: AbortSignal,
): Promise<T> {
  if (!isStudentContextFenceCurrent(fence)) throw staleStudentMutation();
  // The generation fence controls dispatch and continuation ownership only.
  // Aborting a request that has already reached the server would release its
  // Web Locks shared lease before the full response is observed, allowing an
  // exclusive cookie transition to overtake that request. Callers that own a
  // real cancellation capability may still pass it explicitly.
  const result = await operation(operationSignal);
  if (!isStudentContextFenceCurrent(fence)) throw staleStudentMutation();
  return result;
}

export function isStudentMutationCancellation(
  error: unknown,
): error is StudentMutationCancelledError {
  return error instanceof StudentMutationCancelledError;
}

export function captureStudentMutationVariables<TVariables>(
  value: TVariables,
): StudentMutationVariables<TVariables> {
  return { fence: captureStudentContextFence(), value };
}

export function captureStudentMutationSequence(): StudentContextFence {
  return captureStudentContextFence();
}

export async function settleStudentMutationForCaller<TData>(
  fence: StudentContextFence,
  request: Promise<TData>,
): Promise<TData> {
  try {
    const data = await request;
    if (!isStudentContextFenceCurrent(fence)) throw staleStudentMutation();
    return data;
  } catch (error) {
    if (!isStudentContextFenceCurrent(fence)) throw staleStudentMutation();
    throw error;
  }
}

/**
 * Bind dispatch and every UI/cache callback to the actor generation that
 * invoked the mutation. Clearing MutationCache alone neither cancels a queued
 * mutation nor stops callbacks from an already-running promise.
 */
export function createStudentMutationOptions<
  TData = unknown,
  TError = DefaultError,
  TVariables = void,
  TOnMutateResult = unknown,
>(
  options: UseMutationOptions<TData, TError, TVariables, TOnMutateResult>,
): UseMutationOptions<
  TData,
  TError,
  StudentMutationVariables<TVariables>,
  StudentMutationCallbackContext<TOnMutateResult>
> {
  const {
    mutationFn,
    onMutate,
    onSuccess,
    onError,
    onSettled,
    ...rest
  } = options;
  return {
    ...rest,
    mutationFn: mutationFn
      ? async (variables, context) => {
        if (!isStudentContextFenceCurrent(variables.fence)) throw staleStudentMutation();
        return mutationFn(variables.value, context);
      }
      : undefined,
    onMutate: async (variables, context) => {
      if (!isStudentContextFenceCurrent(variables.fence)) throw staleStudentMutation();
      const value = await onMutate?.(variables.value, context);
      if (!isStudentContextFenceCurrent(variables.fence)) throw staleStudentMutation();
      return { fence: variables.fence, value };
    },
    onSuccess: async (data, variables, callbackContext, context) => {
      if (!isStudentContextFenceCurrent(variables.fence)
        || !isStudentContextFenceCurrent(callbackContext.fence)) return;
      await onSuccess?.(
        data,
        variables.value,
        callbackContext.value as TOnMutateResult,
        context,
      );
    },
    onError: async (error, variables, callbackContext, context) => {
      if (!isStudentContextFenceCurrent(variables.fence)
        || !callbackContext
        || !isStudentContextFenceCurrent(callbackContext.fence)) return;
      await onError?.(error, variables.value, callbackContext.value, context);
    },
    onSettled: async (data, error, variables, callbackContext, context) => {
      if (!isStudentContextFenceCurrent(variables.fence)
        || !callbackContext
        || !isStudentContextFenceCurrent(callbackContext.fence)) return;
      await onSettled?.(data, error, variables.value, callbackContext.value, context);
    },
  };
}

function wrapObserverOptions<TData, TError, TVariables, TOnMutateResult>(
  options?: MutateOptions<TData, TError, TVariables, TOnMutateResult>,
): MutateOptions<
  TData,
  TError,
  StudentMutationVariables<TVariables>,
  StudentMutationCallbackContext<TOnMutateResult>
> | undefined {
  if (!options) return undefined;
  return {
    onSuccess: (data, variables, callbackContext, context) => {
      if (!callbackContext || !isStudentContextFenceCurrent(variables.fence)
        || !isStudentContextFenceCurrent(callbackContext.fence)) return;
      options.onSuccess?.(data, variables.value, callbackContext.value, context);
    },
    onError: (error, variables, callbackContext, context) => {
      if (!callbackContext || !isStudentContextFenceCurrent(variables.fence)
        || !isStudentContextFenceCurrent(callbackContext.fence)) return;
      options.onError?.(error, variables.value, callbackContext.value, context);
    },
    onSettled: (data, error, variables, callbackContext, context) => {
      if (!callbackContext || !isStudentContextFenceCurrent(variables.fence)
        || !isStudentContextFenceCurrent(callbackContext.fence)) return;
      options.onSettled?.(data, error, variables.value, callbackContext.value, context);
    },
  };
}

export function useStudentMutation<
  TData = unknown,
  TError = DefaultError,
  TVariables = void,
  TOnMutateResult = unknown,
>(
  options: UseMutationOptions<TData, TError, TVariables, TOnMutateResult>,
): UseMutationResult<TData, TError, TVariables, TOnMutateResult> {
  const mutation = useMutation(createStudentMutationOptions(options));
  const mutate = useCallback((
    variables: TVariables,
    observerOptions?: MutateOptions<TData, TError, TVariables, TOnMutateResult>,
  ) => mutation.mutate(
    captureStudentMutationVariables(variables),
    wrapObserverOptions(observerOptions),
  ), [mutation.mutate]);
  const mutateAsync = useCallback((
    variables: TVariables,
    observerOptions?: MutateOptions<TData, TError, TVariables, TOnMutateResult>,
  ) => {
    const captured = captureStudentMutationVariables(variables);
    return settleStudentMutationForCaller(
      captured.fence,
      mutation.mutateAsync(captured, wrapObserverOptions(observerOptions)),
    );
  }, [mutation.mutateAsync]);
  return {
    ...mutation,
    variables: mutation.variables?.value,
    mutate,
    mutateAsync,
  } as UseMutationResult<TData, TError, TVariables, TOnMutateResult>;
}

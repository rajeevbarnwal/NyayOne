/** Page-memory ownership for an uncertain registration request. */
export interface RegistrationAttempt {
  body: string;
  key: string;
}

let attempt: RegistrationAttempt | null = null;

export function getRegistrationAttempt(): RegistrationAttempt | null {
  return attempt;
}

export function setRegistrationAttempt(next: RegistrationAttempt | null): void {
  attempt = next;
}

export function clearRegistrationAttempt(): void {
  attempt = null;
}

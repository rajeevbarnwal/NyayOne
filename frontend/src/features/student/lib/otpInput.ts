/** Input-shape validation only. Security policy and verification live server-side. */
export function normalizeOtpDigits(value: string): string {
  return value.replace(/\D/g, '').slice(0, 6);
}

export function isValidOtpInput(value: string): boolean {
  return /^\d{6}$/.test(value);
}

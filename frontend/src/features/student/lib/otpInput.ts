/** Input-shape validation only. Security policy and verification live server-side. */
export function isValidOtpInput(value: string): boolean {
  return /^\d{6}$/.test(value);
}

export const LEGAL_NAME_MAX_CODE_POINTS = 60;

/** Canonical NFC + ASCII-space normalization shared with the backend corpus. */
export function normalizeLegalName(input: string): string {
  return input.normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '');
}

/**
 * Unicode legal-name rule shared by registration and canonical profile writes.
 * Marks may follow only Letters/Marks; approved punctuation may lead or trail;
 * at least one Letter is mandatory. Only ASCII space is accepted.
 */
export function validateLegalName(input: string): boolean {
  if (/[^\S ]/u.test(input)) return false;
  const normalized = normalizeLegalName(input);
  const codePointLength = [...normalized].length;
  if (codePointLength < 1 || codePointLength > LEGAL_NAME_MAX_CODE_POINTS) return false;
  let hasLetter = false;
  let previousAllowsMark = false;
  for (const codePoint of normalized) {
    if (/^\p{L}$/u.test(codePoint)) {
      hasLetter = true;
      previousAllowsMark = true;
    } else if (/^\p{M}$/u.test(codePoint)) {
      if (!previousAllowsMark) return false;
      previousAllowsMark = true;
    } else if (codePoint === ' ' || codePoint === '.' || codePoint === '-'
      || codePoint === "'" || codePoint === '‘' || codePoint === '’') {
      previousAllowsMark = false;
    } else {
      return false;
    }
  }
  return hasLetter;
}

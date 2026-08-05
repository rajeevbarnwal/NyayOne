/**
 * Centralized Date & Time Utility for LegalSaathi.
 * Standardizes UI date formatting across all student and lawyer modules to DD-MM-YYYY
 * and time formatting to 12-Hour AM/PM.
 */

/**
 * Formats any ISO date string, timestamp, or Date object into DD-MM-YYYY format.
 * Examples:
 *   formatDateDDMMYYYY('2004-03-14') -> '14-03-2004'
 *   formatDateDDMMYYYY('2026-07-29T06:35:10Z') -> '29-07-2026'
 *   formatDateDDMMYYYY(null) -> ''
 */
export function formatDateDDMMYYYY(dateInput: string | Date | number | null | undefined): string {
  if (!dateInput) return '';

  if (typeof dateInput === 'string') {
    const trimmed = dateInput.trim();
    if (!trimmed) return '';
    // If already in DD-MM-YYYY format, return as is
    if (/^\d{2}-\d{2}-\d{4}$/.test(trimmed)) {
      return trimmed;
    }
    // Handle simple YYYY-MM-DD string without timezone offset drift
    if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      const [year, month, day] = trimmed.split('-');
      return `${day}-${month}-${year}`;
    }
  }

  const d = typeof dateInput === 'object' ? dateInput : new Date(dateInput);
  if (isNaN(d.getTime())) {
    return String(dateInput);
  }

  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const year = d.getFullYear();

  return `${day}-${month}-${year}`;
}

/**
 * Parses a DD-MM-YYYY string into a standard ISO YYYY-MM-DD string.
 * Example: '14-03-2004' -> '2004-03-14'
 */
export function parseDDMMYYYYToISO(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const trimmed = dateStr.trim();
  if (/^\d{2}-\d{2}-\d{4}$/.test(trimmed)) {
    const [day, month, year] = trimmed.split('-');
    return `${year}-${month}-${day}`;
  }
  return trimmed;
}

/**
 * Formats any ISO date string or Date object into 12-Hour AM/PM time format.
 * Examples:
 *   formatTime12Hour('2026-07-20T18:30:00Z', 'UTC') -> '06:30 PM'
 *   formatTime12Hour('2026-07-20T05:30:00Z', 'UTC') -> '05:30 AM'
 */
export function formatTime12Hour(
  dateInput: string | Date | number | null | undefined,
  timeZone = 'UTC',
): string {
  if (!dateInput) return '';
  const d = typeof dateInput === 'object' ? dateInput : new Date(dateInput);
  if (isNaN(d.getTime())) return '';

  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(d);
}

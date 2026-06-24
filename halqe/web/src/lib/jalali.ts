/**
 * Minimal Jalali date utilities — stub for now.
 *
 * Full Jalali conversion (Gregorian ↔ Jalali) will be added in the next slice
 * when we vendor a Jalali library. For now:
 * - formatJalali: returns the ISO date string as-is (pass-through stub).
 * - toFarsiDigits: converts ASCII digits to Persian-Indic ۰–۹.
 *
 * These stubs are designed so that swapping in a real converter requires only
 * changing the body of formatJalali without touching callers.
 */

/**
 * Convert ASCII digits 0-9 to Persian-Indic ۰-۹.
 */
export function toFarsiDigits(input: string | number): string {
  return String(input).replace(/[0-9]/g, (d) =>
    String.fromCharCode(d.charCodeAt(0) + 0x06f0 - 0x30),
  );
}

/**
 * Format a datetime ISO string for display.
 * Stub: returns YYYY/MM/DD portion until a Jalali library is vendored.
 */
export function formatJalali(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  // Take only the date part (YYYY-MM-DD) and replace - with /
  const datePart = isoString.slice(0, 10).replace(/-/g, "/");
  return datePart;
}

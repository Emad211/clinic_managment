/**
 * Encounter label maps + error mapping — shared by RegisterVisitForm and
 * EncountersList. Extracted verbatim from patients/[uuid]/page.tsx (cleanup
 * step 9) so both encounter sub-components share one source of truth.
 *
 * Behaviour-preserving: identical maps and identical message logic.
 */

import { errorMessageFromCode, ApiError, type EncounterType } from "@/lib/api";

export const ENCOUNTER_TYPE_LABEL: Record<EncounterType, string> = {
  visit: "ویزیت",
  follow_up: "پیگیری",
  phone: "تلفنی",
  remote: "از راه دور",
};

export const ENCOUNTER_STATUS_LABEL: Record<string, string> = {
  open: "باز",
  completed: "تکمیل‌شده",
  cancelled: "لغوشده",
};

/** Map backend error codes to human-readable Farsi messages. */
export function encounterErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // Primary path: use stable code from ApiError.code (set from backend body.code).
    if (err.code) {
      return errorMessageFromCode(err.code, `خطا: ${err.message}`);
    }
    // Fallback for older responses without a code field: status-based.
    if (err.status === 401) return "لطفاً دوباره وارد شوید.";
    if (err.status === 404) return "بیمار یا ویزیت یافت نشد.";
    if (err.status === 409) return "تعارض داده — ممکن است این ویزیت قبلاً ثبت شده باشد.";
    if (err.status === 422) return "داده‌های وارد‌شده معتبر نیستند.";
    return `خطا: ${err.message}`;
  }
  return "عملیات ناموفق بود. دوباره امتحان کنید.";
}

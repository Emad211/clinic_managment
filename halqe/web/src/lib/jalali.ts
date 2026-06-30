/**
 * Jalali (Solar Hijri) date utilities — pure TypeScript, no runtime CDN.
 *
 * Algorithm: Gregorian→Jalali via the Julian Day Number (JDN) bridge,
 * using the 2820-year Borkowski cycle. Equivalent to the Python jdatetime
 * library and specialist_clinic's src/common/jalali.py.
 *
 * JALALI_EPOCH = 1948322 is the JDN of the algorithmic base point, derived
 * from the constraint that jalaliYearStart(1400) = JDN(2021-03-21) = 2459295.
 *
 * Known-good pairs verified against time.ir and jdatetime:
 *   2026-06-24  → 1405/04/03
 *   2024-03-20  → 1403/01/01  (Nowruz 1403)
 *   2024-03-19  → 1402/12/29
 *   1988-10-01  → 1367/07/09
 *   2000-01-01  → 1378/10/11
 */

// ─────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────

/** Algorithmic base JDN for the 2820-year Jalali cycle. */
const JALALI_EPOCH = 1948322;

// ─────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────

/**
 * Gregorian date → Julian Day Number (proleptic Gregorian formula).
 * Valid for all CE dates.
 */
function gregorianToJDN(gy: number, gm: number, gd: number): number {
  const a = Math.floor((14 - gm) / 12);
  const y = gy + 4800 - a;
  const m = gm + 12 * a - 3;
  return (
    gd +
    Math.floor((153 * m + 2) / 5) +
    365 * y +
    Math.floor(y / 4) -
    Math.floor(y / 100) +
    Math.floor(y / 400) -
    32045
  );
}

/**
 * Return the JDN of 1 Farvardin of a given Jalali year.
 * Uses the 2820-year cycle (Borkowski, 1996).
 */
function jalaliYearStart(jy: number): number {
  const epbase = jy - 474;
  const epyear = 474 + (((epbase % 2820) + 2820) % 2820);
  const cycle = Math.floor(epbase / 2820);
  return (
    Math.floor((epyear * 682 - 110) / 2816) +
    (epyear - 1) * 365 +
    cycle * 1029983 +
    JALALI_EPOCH - 1
  );
}

/**
 * JDN → Jalali [year, month, day].
 *
 * Approach: use the 2820-year cycle arithmetic to find the approximate year,
 * then verify against jalaliYearStart() and advance one year if needed
 * (handles the Nowruz boundary where the cycle formula is off by one).
 */
function jdnToJalali(jdn: number): [number, number, number] {
  const depoch = jdn - JALALI_EPOCH;
  const cycleNo = Math.floor(depoch / 1029983);
  const cyear = ((depoch % 1029983) + 1029983) % 1029983;

  let ycycle: number;
  if (cyear === 1029982) {
    ycycle = 2819;
  } else {
    const aux1 = Math.floor(cyear / 366);
    const aux2 = cyear % 366;
    ycycle =
      Math.floor((2134 * aux1 + 2816 * aux2 + 2815) / 1028522) + aux1 + 1;
  }

  // ycycle encodes the Jalali year directly (for cycle 0, epoch ~year 0 CE)
  let year = ycycle + 2820 * cycleNo;

  // Verify boundary: if jdn >= start of (year+1), we crossed into the next year
  const nextYearStart = jalaliYearStart(year + 1);
  if (jdn >= nextYearStart) {
    year += 1;
  }

  const yearStartJdn = jalaliYearStart(year);
  const yday = jdn - yearStartJdn + 1; // 1-based day of year

  // Months 1–6: 31 days each; months 7–12: 30 days each (month 12: 29 or 30)
  let jm: number;
  if (yday <= 186) {
    jm = Math.ceil(yday / 31);
  } else {
    jm = Math.ceil((yday - 6) / 30);
  }
  const jd = yday - (jm <= 6 ? (jm - 1) * 31 : (jm - 1) * 30 + 6);

  return [year, jm, jd];
}

// ─────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────

/**
 * Convert ASCII digits 0-9 to Persian-Indic ۰-۹.
 */
export function toFarsiDigits(input: string | number): string {
  return String(input).replace(/[0-9]/g, (d) =>
    String.fromCharCode(d.charCodeAt(0) + 0x06f0 - 0x30),
  );
}

/**
 * Format an ISO datetime/date string as Jalali "YYYY/MM/DD" in Persian digits.
 *
 * Accepts:
 *   "2026-06-24"              → ۱۴۰۵/۰۴/۰۳
 *   "2026-06-24T10:30:00Z"    → ۱۴۰۵/۰۴/۰۳  (date-part only, no tz shift)
 *   null / undefined / ""     → "—"
 *
 * Timezone note: only the YYYY-MM-DD date portion is used, with no timezone
 * conversion. For stored Tehran-local dates returned by the API this is exact.
 * For UTC ISO timestamps, the date label is accurate in all but the ~3h30m
 * window around Tehran midnight — acceptable for a display label.
 */
export function formatJalali(isoString: string | null | undefined): string {
  if (!isoString) return "—";

  const datePart = isoString.slice(0, 10);
  const parts = datePart.split("-");
  if (parts.length !== 3) return "—";

  const gy = parseInt(parts[0], 10);
  const gm = parseInt(parts[1], 10);
  const gd = parseInt(parts[2], 10);

  if (isNaN(gy) || isNaN(gm) || isNaN(gd)) return "—";
  if (gm < 1 || gm > 12 || gd < 1 || gd > 31) return "—";

  const jdn = gregorianToJDN(gy, gm, gd);
  const [jy, jm, jd] = jdnToJalali(jdn);

  const formatted = `${jy}/${String(jm).padStart(2, "0")}/${String(jd).padStart(2, "0")}`;
  return toFarsiDigits(formatted);
}

/**
 * Format an integer Toman amount with thousands separators and Persian digits,
 * followed by the تومان suffix.
 *
 * Examples:
 *   1500000  → "۱٬۵۰۰٬۰۰۰ تومان"
 *   0        → "۰ تومان"
 *   null/undefined → "—"
 */
export function formatToman(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  const formatted = amount.toLocaleString("fa-IR");
  return `${formatted} تومان`;
}

/**
 * Today's date in Tehran, as a Gregorian "YYYY-MM-DD" string.
 *
 * Why Intl + Asia/Tehran (not `new Date().toISOString()`): toISOString emits the
 * date in UTC, which is off by Tehran's +3:30 offset around midnight — so within
 * the ~3.5h window after Tehran midnight it would report "yesterday". Intl with
 * an explicit timeZone gives the correct Tehran calendar date regardless of the
 * browser's own timezone. The "en-CA" locale formats as ISO (YYYY-MM-DD), which
 * sorts lexicographically — so string comparison with stored YYYY-MM-DD dates is
 * a correct date comparison.
 */
export function todayTehranISO(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tehran" }).format(
    new Date(),
  );
}

/**
 * Return only the Jalali year from an ISO date/datetime string, as Persian digits.
 * Example: "2026-06-24" → "۱۴۰۵"
 */
export function toJalaliYear(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const datePart = isoString.slice(0, 10);
  const parts = datePart.split("-");
  if (parts.length !== 3) return "—";
  const gy = parseInt(parts[0], 10);
  const gm = parseInt(parts[1], 10);
  const gd = parseInt(parts[2], 10);
  if (isNaN(gy) || isNaN(gm) || isNaN(gd)) return "—";
  const jdn = gregorianToJDN(gy, gm, gd);
  const [jy] = jdnToJalali(jdn);
  return toFarsiDigits(String(jy));
}

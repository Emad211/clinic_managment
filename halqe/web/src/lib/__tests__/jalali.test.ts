/**
 * Unit tests for the Jalali (Solar Hijri) conversion in src/lib/jalali.ts.
 *
 * Known-good pairs cross-verified against:
 *   - Python jdatetime library
 *   - specialist_clinic/src/common/jalali.py
 *   - https://www.time.ir (authoritative Jalali calendar site)
 */

import { formatJalali, toFarsiDigits, toJalaliYear } from "../jalali";

// ─────────────────────────────────────────────────────────────
// toFarsiDigits
// ─────────────────────────────────────────────────────────────

describe("toFarsiDigits", () => {
  it("converts ASCII 0–9 to Persian ۰–۹", () => {
    expect(toFarsiDigits("0123456789")).toBe("۰۱۲۳۴۵۶۷۸۹");
  });

  it("leaves non-digit characters unchanged", () => {
    expect(toFarsiDigits("1405/04/03")).toBe("۱۴۰۵/۰۴/۰۳");
  });

  it("accepts a number input", () => {
    expect(toFarsiDigits(1405)).toBe("۱۴۰۵");
  });
});

// ─────────────────────────────────────────────────────────────
// formatJalali — Gregorian → Jalali known pairs
// ─────────────────────────────────────────────────────────────

describe("formatJalali — known date pairs", () => {
  // Primary pair specified in the task
  it("2026-06-24 → ۱۴۰۵/۰۴/۰۳", () => {
    expect(formatJalali("2026-06-24")).toBe("۱۴۰۵/۰۴/۰۳");
  });

  // Nowruz 1403 — first day of Farvardin
  it("2024-03-20 → ۱۴۰۳/۰۱/۰۱ (Nowruz 1403)", () => {
    expect(formatJalali("2024-03-20")).toBe("۱۴۰۳/۰۱/۰۱");
  });

  // Day before Nowruz — last day of Esfand 1402
  it("2024-03-19 → ۱۴۰۲/۱۲/۲۹ (last day 1402)", () => {
    expect(formatJalali("2024-03-19")).toBe("۱۴۰۲/۱۲/۲۹");
  });

  // A mid-year date in the past
  it("1988-10-01 → ۱۳۶۷/۰۷/۰۹", () => {
    expect(formatJalali("1988-10-01")).toBe("۱۳۶۷/۰۷/۰۹");
  });

  // Millennium boundary
  it("2000-01-01 → ۱۳۷۸/۱۰/۱۱", () => {
    expect(formatJalali("2000-01-01")).toBe("۱۳۷۸/۱۰/۱۱");
  });

  // 1 Farvardin 1400
  it("2021-03-21 → ۱۴۰۰/۰۱/۰۱ (Nowruz 1400)", () => {
    expect(formatJalali("2021-03-21")).toBe("۱۴۰۰/۰۱/۰۱");
  });

  // End of Shahrivar (month 6, 31-day months section boundary)
  it("2023-09-22 → ۱۴۰۲/۰۶/۳۱ (last day of Shahrivar 1402)", () => {
    expect(formatJalali("2023-09-22")).toBe("۱۴۰۲/۰۶/۳۱");
  });

  // Start of Mehr (month 7, 30-day months section begins)
  it("2023-09-23 → ۱۴۰۲/۰۷/۰۱ (first day of Mehr 1402)", () => {
    expect(formatJalali("2023-09-23")).toBe("۱۴۰۲/۰۷/۰۱");
  });

  // Nowruz 1399 (2020-03-20)
  it("2020-03-20 → ۱۳۹۹/۰۱/۰۱ (Nowruz 1399)", () => {
    expect(formatJalali("2020-03-20")).toBe("۱۳۹۹/۰۱/۰۱");
  });

  // Day before Nowruz 1399
  it("2020-03-19 → ۱۳۹۸/۱۲/۲۹ (last day of 1398)", () => {
    expect(formatJalali("2020-03-19")).toBe("۱۳۹۸/۱۲/۲۹");
  });

  // Iranian Revolution date
  it("1979-02-11 → ۱۳۵۷/۱۱/۲۲", () => {
    expect(formatJalali("1979-02-11")).toBe("۱۳۵۷/۱۱/۲۲");
  });

  // ISO datetime string — only the date part is used
  it("ISO datetime string uses date part only", () => {
    expect(formatJalali("2026-06-24T10:30:00Z")).toBe("۱۴۰۵/۰۴/۰۳");
  });

  // ISO datetime without Z
  it("ISO datetime without Z still works", () => {
    expect(formatJalali("2024-03-20T00:00:00")).toBe("۱۴۰۳/۰۱/۰۱");
  });
});

// ─────────────────────────────────────────────────────────────
// formatJalali — edge / null cases
// ─────────────────────────────────────────────────────────────

describe("formatJalali — null / empty inputs", () => {
  it("returns '—' for null", () => {
    expect(formatJalali(null)).toBe("—");
  });

  it("returns '—' for undefined", () => {
    expect(formatJalali(undefined)).toBe("—");
  });

  it("returns '—' for empty string", () => {
    expect(formatJalali("")).toBe("—");
  });

  it("returns '—' for non-date garbage", () => {
    expect(formatJalali("not-a-date")).toBe("—");
  });
});

// ─────────────────────────────────────────────────────────────
// toJalaliYear
// ─────────────────────────────────────────────────────────────

describe("toJalaliYear", () => {
  it("extracts Jalali year from a date string", () => {
    expect(toJalaliYear("2026-06-24")).toBe("۱۴۰۵");
  });

  it("returns '—' for null", () => {
    expect(toJalaliYear(null)).toBe("—");
  });
});

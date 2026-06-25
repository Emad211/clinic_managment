/**
 * Tests for /patients page — client-side search filter (Step 25).
 *
 * Strategy: inline components that mirror the exact normalizeForSearch +
 * filter logic from patients/page.tsx — avoids importing the full Next.js
 * page (which requires router/auth mocking).
 *
 * Covers:
 *   1. normalizeForSearch helper: Latin/Persian/Arabic-Indic digit mapping
 *   2. PatientTableStub: typing in search → only matching rows shown
 *   3. No-results state: distinct message from "no patients at all" state
 *   4. Empty-DB state: "هیچ بیماری ثبت‌نام نشده" (no patients whatsoever)
 *   5. Search cleared → all rows visible again
 *   6. Null field handling: null full_name / national_id / phone_number
 */

import React, { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { EnrolledPatient } from "../src/lib/api";

// ─────────────────────────────────────────────────────────────
// Mock localStorage (required by api.ts module init)
// ─────────────────────────────────────────────────────────────

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  writable: true,
});

// ─────────────────────────────────────────────────────────────
// 1. normalizeForSearch — pure helper (duplicated from page.tsx for isolation)
// ─────────────────────────────────────────────────────────────

/**
 * Mirror of the normalizeForSearch function in patients/page.tsx.
 * Converts lowercase + Persian/Arabic-Indic digits → ASCII digits.
 */
function normalizeForSearch(s: string): string {
  return s
    .toLowerCase()
    .replace(/[۰-۹]/g, (c) => String(c.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (c) => String(c.charCodeAt(0) - 0x0660));
}

describe("normalizeForSearch", () => {
  it("lowercases ASCII text", () => {
    expect(normalizeForSearch("Ali")).toBe("ali");
  });

  it("converts Persian digits ۰–۹ to ASCII 0–9", () => {
    expect(normalizeForSearch("۰۱۲۳۴۵۶۷۸۹")).toBe("0123456789");
  });

  it("converts Arabic-Indic digits ٠–٩ to ASCII 0–9", () => {
    expect(normalizeForSearch("٠١٢٣٤٥٦٧٨٩")).toBe("0123456789");
  });

  it("leaves ASCII digits unchanged", () => {
    expect(normalizeForSearch("09123456789")).toBe("09123456789");
  });

  it("mixes Persian digits and Persian text unchanged (text stays as-is, digits convert)", () => {
    const result = normalizeForSearch("احمدی ۱۲۳");
    expect(result).toBe("احمدی 123");
  });

  it("empty string → empty string", () => {
    expect(normalizeForSearch("")).toBe("");
  });
});

// ─────────────────────────────────────────────────────────────
// 2. PatientTableStub — mirrors the filter + render logic from page.tsx
// ─────────────────────────────────────────────────────────────

/** Inline stub mirroring the patients page filter + table rendering. */
function PatientTableStub({ patients }: { patients: EnrolledPatient[] }) {
  const [search, setSearch] = useState("");

  const normalizedSearch = normalizeForSearch(search.trim());

  const filtered: EnrolledPatient[] =
    normalizedSearch === ""
      ? patients
      : patients.filter((p) => {
          const name = normalizeForSearch(p.full_name ?? "");
          const nid = normalizeForSearch(p.national_id ?? "");
          const phone = normalizeForSearch(p.phone_number ?? "");
          return (
            name.includes(normalizedSearch) ||
            nid.includes(normalizedSearch) ||
            phone.includes(normalizedSearch)
          );
        });

  const hasPatients = patients.length > 0;
  const searchActive = normalizedSearch !== "";
  const noSearchResults = searchActive && filtered.length === 0;

  return (
    <div>
      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="جستجو در بیماران — نام، کد ملی یا شماره تماس"
        placeholder="جستجو در نام، کد ملی، شماره تماس… (در این صفحه)"
      />

      {/* Empty-DB state */}
      {!hasPatients && (
        <div role="status">هیچ بیماری ثبت‌نام نشده است.</div>
      )}

      {/* No-search-results state */}
      {hasPatients && noSearchResults && (
        <div role="status" aria-live="polite">
          {`نتیجه‌ای برای «${search}» یافت نشد.`}
        </div>
      )}

      {/* Patient table */}
      {filtered.length > 0 && (
        <table aria-label="لیست بیماران">
          <thead>
            <tr>
              <th scope="col">نام و نام خانوادگی</th>
              <th scope="col">کد ملی</th>
              <th scope="col">شماره تماس</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr key={p.link_id} data-testid={`row-${p.link_id}`}>
                <td>{p.full_name ?? "بدون نام"}</td>
                <td>{p.national_id ?? "—"}</td>
                <td>{p.phone_number ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────

const SAMPLE_PATIENTS: EnrolledPatient[] = [
  {
    link_id: 1,
    patient_id: 101,
    is_active: true,
    enrolled_at: "2025-01-15T09:00:00+03:30",
    full_name: "علی رضایی",
    national_id: "0012345678",
    phone_number: "09121234567",
    patient_uuid: "uuid-1",
  },
  {
    link_id: 2,
    patient_id: 102,
    is_active: true,
    enrolled_at: "2025-02-20T10:00:00+03:30",
    full_name: "مریم احمدی",
    national_id: "0087654321",
    phone_number: "09361234567",
    patient_uuid: "uuid-2",
  },
  {
    link_id: 3,
    patient_id: 103,
    is_active: false,
    enrolled_at: "2025-03-10T11:00:00+03:30",
    full_name: "حسن موسوی",
    national_id: "0011112222",
    phone_number: "09151112233",
    patient_uuid: "uuid-3",
  },
];

// ─────────────────────────────────────────────────────────────
// 3. Search filter tests
// ─────────────────────────────────────────────────────────────

describe("PatientTableStub — client-side search filter", () => {
  it("renders all rows when search is empty", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    expect(screen.getByTestId("row-1")).toBeInTheDocument();
    expect(screen.getByTestId("row-2")).toBeInTheDocument();
    expect(screen.getByTestId("row-3")).toBeInTheDocument();
  });

  it("filters by full_name (partial match)", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "مریم" } });
    expect(screen.queryByTestId("row-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("row-2")).toBeInTheDocument();
    expect(screen.queryByTestId("row-3")).not.toBeInTheDocument();
  });

  it("filters by national_id (partial match)", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "0011112222" } });
    expect(screen.queryByTestId("row-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("row-2")).not.toBeInTheDocument();
    expect(screen.getByTestId("row-3")).toBeInTheDocument();
  });

  it("filters by phone_number (partial match)", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "0936" } });
    expect(screen.queryByTestId("row-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("row-2")).toBeInTheDocument();
    expect(screen.queryByTestId("row-3")).not.toBeInTheDocument();
  });

  it("match is case-insensitive for ASCII (no Persian uppercase, but future-proof)", () => {
    const latinPatients: EnrolledPatient[] = [
      {
        link_id: 10,
        patient_id: 201,
        is_active: true,
        enrolled_at: "2025-01-01T00:00:00",
        full_name: "Ahmad Karimi",
        national_id: "0099887766",
        phone_number: "09190000001",
        patient_uuid: "uuid-10",
      },
    ];
    render(<PatientTableStub patients={latinPatients} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "AHMAD" } });
    expect(screen.getByTestId("row-10")).toBeInTheDocument();
  });

  it("accepts Persian digits in search and matches national_id stored as ASCII", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    // Patient 1 has national_id "0012345678" — user types in Persian digits
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "۰۰۱۲۳۴۵۶۷۸" } });
    expect(screen.getByTestId("row-1")).toBeInTheDocument();
    expect(screen.queryByTestId("row-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("row-3")).not.toBeInTheDocument();
  });

  it("accepts Arabic-Indic digits (٠–٩) in search", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    // Patient 3 has phone "09151112233"; user types Arabic-Indic: ٠٩١٥١
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "٠٩١٥١" } });
    expect(screen.getByTestId("row-3")).toBeInTheDocument();
    expect(screen.queryByTestId("row-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("row-2")).not.toBeInTheDocument();
  });

  it("clears filter and shows all rows when search is cleared", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    const input = screen.getByRole("searchbox");
    fireEvent.change(input, { target: { value: "مریم" } });
    expect(screen.queryByTestId("row-1")).not.toBeInTheDocument();
    // Now clear
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("row-1")).toBeInTheDocument();
    expect(screen.getByTestId("row-2")).toBeInTheDocument();
    expect(screen.getByTestId("row-3")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// 4. No-search-results state (distinct from empty-DB state)
// ─────────────────────────────────────────────────────────────

describe("PatientTableStub — no search results vs empty-DB state", () => {
  it("shows no-results message when search yields nothing (patients exist)", () => {
    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "ناموجود۱۲۳" } });

    // The no-results message should be visible
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("نتیجه‌ای");
    expect(status.textContent).toContain("یافت نشد");
    // "هیچ بیماری" should NOT appear
    expect(status.textContent).not.toContain("هیچ بیماری");
    // Table should not render
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows 'هیچ بیماری ثبت‌نام نشده' when patients array is empty (no search)", () => {
    render(<PatientTableStub patients={[]} />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("هیچ بیماری ثبت‌نام نشده است.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("the two empty states have distinct messages", () => {
    const { unmount } = render(<PatientTableStub patients={[]} />);
    const emptyDbMsg = screen.getByRole("status").textContent;
    unmount();

    render(<PatientTableStub patients={SAMPLE_PATIENTS} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "xyz_impossible_xyz" } });
    const noResultsMsg = screen.getByRole("status").textContent;

    expect(emptyDbMsg).not.toBe(noResultsMsg);
  });
});

// ─────────────────────────────────────────────────────────────
// 5. Null field handling
// ─────────────────────────────────────────────────────────────

describe("PatientTableStub — null field handling", () => {
  const NULL_PATIENT: EnrolledPatient = {
    link_id: 99,
    patient_id: 999,
    is_active: true,
    enrolled_at: "2025-06-01T00:00:00",
    full_name: null,
    national_id: null,
    phone_number: null,
    patient_uuid: null,
  };

  it("renders row with null fields without crashing", () => {
    render(<PatientTableStub patients={[NULL_PATIENT]} />);
    expect(screen.getByTestId("row-99")).toBeInTheDocument();
  });

  it("null-field patient matches empty search (shows in unfiltered list)", () => {
    render(<PatientTableStub patients={[NULL_PATIENT]} />);
    expect(screen.getByTestId("row-99")).toBeInTheDocument();
  });

  it("null-field patient is filtered out when search has text", () => {
    render(<PatientTableStub patients={[NULL_PATIENT]} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "علی" } });
    expect(screen.queryByTestId("row-99")).not.toBeInTheDocument();
  });
});

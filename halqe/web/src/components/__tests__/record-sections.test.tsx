/**
 * Light render tests for the patient-detail presentational sections extracted
 * in cleanup step 9: PatientHeader, ActiveConditions, ActiveMedications.
 *
 * These assert the same behaviour the inline JSX had in page.tsx:
 *   - optional-field guards (header)
 *   - empty states
 *   - "—" fallbacks (medications)
 *   - Jalali rendering (birthdate / onset / start_date)
 *   - server order preserved
 *
 * Pure presentational components → no router/fetch mocking needed.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PatientHeader } from "../PatientHeader";
import { ActiveConditions } from "../ActiveConditions";
import { ActiveMedications } from "../ActiveMedications";
import type { PatientDemographics, ConditionDTO, MedicationDTO } from "@/lib/api";

// ── Helpers ─────────────────────────────────────────────────

function makeDemo(overrides: Partial<PatientDemographics> = {}): PatientDemographics {
  return {
    id: 1,
    uuid: "u-1",
    name: "علی",
    family_name: "رضایی",
    full_name: "علی رضایی",
    national_id: "0012345678",
    phone_number: "09120000000",
    birthdate: "2026-01-15",
    gender: "male",
    ...overrides,
  };
}

function makeCondition(overrides: Partial<ConditionDTO> = {}): ConditionDTO {
  return {
    id: 1,
    condition_id: 10,
    condition_name: "دیابت نوع ۲",
    condition_code: "DM",
    stage: null,
    onset_date: null,
    notes: null,
    is_active: true,
    diagnosed_at: "2024-01-01T00:00:00+03:30",
    ...overrides,
  };
}

function makeMed(overrides: Partial<MedicationDTO> = {}): MedicationDTO {
  return {
    id: 1,
    drug_name: "متفورمین",
    dose: "500mg",
    schedule: "روزی دو بار",
    start_date: "2026-01-15",
    refill_due_date: null,
    drug_class: "biguanide",
    is_active: true,
    notes: null,
    created_at: "2026-01-15T00:00:00+03:30",
    ...overrides,
  };
}

// ── PatientHeader ───────────────────────────────────────────

describe("PatientHeader", () => {
  it("نام کامل را نمایش می‌دهد", () => {
    render(<PatientHeader demo={makeDemo()} />);
    expect(screen.getByRole("heading", { name: "علی رضایی" })).toBeInTheDocument();
  });

  it("وقتِ demo نال است «بیمار ناشناس» نشان می‌دهد", () => {
    render(<PatientHeader demo={null} />);
    expect(screen.getByRole("heading", { name: "بیمار ناشناس" })).toBeInTheDocument();
  });

  it("کد ملی و تلفن را نمایش می‌دهد", () => {
    render(<PatientHeader demo={makeDemo()} />);
    expect(screen.getByText("0012345678")).toBeInTheDocument();
    expect(screen.getByText("09120000000")).toBeInTheDocument();
  });

  it("birthdate را به‌صورتِ Jalali نمایش می‌دهد (۲۰۲۶-۰۱-۱۵ → ۱۴۰۴/۱۰/۲۶)", () => {
    render(<PatientHeader demo={makeDemo({ birthdate: "2026-01-15" })} />);
    expect(screen.getByText("۱۴۰۴/۱۰/۲۶")).toBeInTheDocument();
  });

  it("فیلدهای اختیاریِ نال را رندر نمی‌کند (بدونِ کد ملی)", () => {
    render(<PatientHeader demo={makeDemo({ national_id: null })} />);
    expect(screen.queryByText("کد ملی")).not.toBeInTheDocument();
  });
});

// ── ActiveConditions ────────────────────────────────────────

describe("ActiveConditions", () => {
  it("وقتِ آرایه خالی است state خالی نشان می‌دهد", () => {
    render(<ActiveConditions conditions={[]} />);
    expect(
      screen.getByText("هیچ بیماری مزمن فعالی ثبت نشده است."),
    ).toBeInTheDocument();
  });

  it("نامِ بیماری را نمایش می‌دهد", () => {
    render(<ActiveConditions conditions={[makeCondition()]} />);
    expect(screen.getByText("دیابت نوع ۲")).toBeInTheDocument();
  });

  it("وقتِ نام نال است به code برمی‌گردد", () => {
    render(
      <ActiveConditions
        conditions={[makeCondition({ condition_name: null, condition_code: "HTN" })]}
      />,
    );
    expect(screen.getByText("HTN")).toBeInTheDocument();
  });

  it("onset_date را به‌صورتِ Jalali در متن نمایش می‌دهد", () => {
    render(
      <ActiveConditions
        conditions={[makeCondition({ onset_date: "2026-01-15" })]}
      />,
    );
    // formatJalali("2026-01-15") → ۱۴۰۴/۱۰/۲۶
    expect(screen.getByText(/۱۴۰۴\/۱۰\/۲۶/)).toBeInTheDocument();
  });

  it("ترتیبِ سرور را حفظ می‌کند", () => {
    render(
      <ActiveConditions
        conditions={[
          makeCondition({ id: 1, condition_name: "دیابت نوع ۲" }),
          makeCondition({ id: 2, condition_name: "فشار خون بالا" }),
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("دیابت نوع ۲");
    expect(items[1]).toHaveTextContent("فشار خون بالا");
  });
});

// ── ActiveMedications ───────────────────────────────────────

describe("ActiveMedications", () => {
  it("وقتِ آرایه خالی است state خالی نشان می‌دهد", () => {
    render(<ActiveMedications medications={[]} />);
    expect(screen.getByText("هیچ دارویی ثبت نشده است.")).toBeInTheDocument();
  });

  it("نام و دوزِ دارو را نمایش می‌دهد", () => {
    render(<ActiveMedications medications={[makeMed()]} />);
    expect(screen.getByText("متفورمین")).toBeInTheDocument();
    expect(screen.getByText("500mg")).toBeInTheDocument();
  });

  it("فیلدهای نال را با «—» نشان می‌دهد", () => {
    render(
      <ActiveMedications
        medications={[
          makeMed({ dose: null, schedule: null, drug_class: null, start_date: null }),
        ]}
      />,
    );
    // four "—" cells for dose/schedule/drug_class/start_date
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  });

  it("start_date را به‌صورتِ Jalali نمایش می‌دهد (۲۰۲۶-۰۱-۱۵ → ۱۴۰۴/۱۰/۲۶)", () => {
    render(<ActiveMedications medications={[makeMed({ start_date: "2026-01-15" })]} />);
    expect(screen.getByText("۱۴۰۴/۱۰/۲۶")).toBeInTheDocument();
  });
});

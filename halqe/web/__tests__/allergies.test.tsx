/**
 * Allergies — banner + section render tests (فاز ۱ cockpit, safety-critical).
 *
 * Covers:
 *   Banner:
 *     - renders ONLY when allergies exist (empty → null)
 *     - red (data-severity=danger) when any severe/anaphylaxis; amber otherwise
 *     - role="alert" (life-safety announcement) + lists each substance
 *   Section:
 *     - lists allergies with a severity label (text, not colour alone)
 *     - empty state
 *     - add calls addAllergy then onChanged
 *     - delete calls deleteAllergy then onChanged
 *     - empty substance → inline validation, no API call
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { AllergyDTO } from "@/lib/api";

// Mock only the two mutating client calls; keep the rest real.
jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    addAllergy: jest.fn(),
    deleteAllergy: jest.fn(),
  };
});

import { addAllergy, deleteAllergy } from "@/lib/api";
import { AllergiesBanner, Allergies } from "@/components/Allergies";

const mockAdd = addAllergy as jest.MockedFunction<typeof addAllergy>;
const mockDelete = deleteAllergy as jest.MockedFunction<typeof deleteAllergy>;

function allergy(overrides: Partial<AllergyDTO> = {}): AllergyDTO {
  return {
    id: 1,
    substance: "پنی‌سیلین",
    severity: "moderate",
    note: null,
    reaction: null,
    created_at: "2026-07-01T10:00:00",
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ─── Banner ─────────────────────────────────────────────────

describe("AllergiesBanner", () => {
  it("renders nothing when there are no allergies", () => {
    const { container } = render(<AllergiesBanner allergies={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders an alert banner listing each substance when allergies exist", () => {
    render(<AllergiesBanner allergies={[allergy({ id: 1, substance: "پنی‌سیلین" })]} />);
    const banner = screen.getByTestId("allergies-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveAttribute("role", "alert");
    expect(banner).toHaveTextContent("پنی‌سیلین");
  });

  it("is amber (warn) when only mild/moderate severities are present", () => {
    render(<AllergiesBanner allergies={[allergy({ severity: "moderate" })]} />);
    expect(screen.getByTestId("allergies-banner")).toHaveAttribute("data-severity", "warn");
  });

  it("is red (danger) when any allergy is severe or anaphylaxis", () => {
    render(
      <AllergiesBanner
        allergies={[allergy({ id: 1, severity: "mild" }), allergy({ id: 2, severity: "anaphylaxis" })]}
      />,
    );
    expect(screen.getByTestId("allergies-banner")).toHaveAttribute("data-severity", "danger");
  });
});

// ─── Section: list + empty ──────────────────────────────────

describe("Allergies section — list", () => {
  it("shows an empty state when there are no allergies", () => {
    render(<Allergies uuid="u1" allergies={[]} onChanged={() => {}} />);
    expect(screen.getByTestId("allergies-empty")).toHaveTextContent("هیچ حساسیتی ثبت نشده است.");
  });

  it("lists an allergy with its substance + a text severity label", () => {
    render(
      <Allergies
        uuid="u1"
        allergies={[allergy({ id: 7, substance: "آسپرین", severity: "severe" })]}
        onChanged={() => {}}
      />,
    );
    const item = screen.getByTestId("allergy-item-7");
    expect(item).toHaveTextContent("آسپرین");
    // severity is a text label (not colour alone)
    expect(item).toHaveTextContent("شدید");
  });
});

// ─── Section: add ───────────────────────────────────────────

describe("Allergies section — add", () => {
  it("adds an allergy and calls onChanged", async () => {
    mockAdd.mockResolvedValueOnce(allergy({ id: 99, substance: "گوگرد" }));
    const onChanged = jest.fn();
    render(<Allergies uuid="u1" allergies={[]} onChanged={onChanged} />);

    fireEvent.change(screen.getByLabelText("مادهٔ حساسیت‌زا"), {
      target: { value: "گوگرد" },
    });
    fireEvent.change(screen.getByLabelText("شدت"), { target: { value: "severe" } });
    fireEvent.click(screen.getByRole("button", { name: "افزودن حساسیت" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(mockAdd).toHaveBeenCalledWith("u1", {
      substance: "گوگرد",
      severity: "severe",
      note: null,
    });
  });

  it("empty substance → inline validation, no API call", async () => {
    const onChanged = jest.fn();
    render(<Allergies uuid="u1" allergies={[]} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "افزودن حساسیت" }));

    await screen.findByText("نام مادهٔ حساسیت‌زا الزامی است.");
    expect(mockAdd).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("sends severity=null when left unspecified", async () => {
    mockAdd.mockResolvedValueOnce(allergy({ id: 5 }));
    render(<Allergies uuid="u1" allergies={[]} onChanged={() => {}} />);

    fireEvent.change(screen.getByLabelText("مادهٔ حساسیت‌زا"), {
      target: { value: "لاتکس" },
    });
    fireEvent.click(screen.getByRole("button", { name: "افزودن حساسیت" }));

    await waitFor(() =>
      expect(mockAdd).toHaveBeenCalledWith("u1", {
        substance: "لاتکس",
        severity: null,
        note: null,
      }),
    );
  });
});

// ─── Section: delete ────────────────────────────────────────

describe("Allergies section — delete", () => {
  it("deletes an allergy and calls onChanged", async () => {
    mockDelete.mockResolvedValueOnce({ deleted: true, id: 3 });
    const onChanged = jest.fn();
    render(
      <Allergies
        uuid="u1"
        allergies={[allergy({ id: 3, substance: "یُد" })]}
        onChanged={onChanged}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "حذف حساسیت به یُد" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(mockDelete).toHaveBeenCalledWith("u1", 3);
  });
});

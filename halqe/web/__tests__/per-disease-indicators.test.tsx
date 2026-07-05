/**
 * PerDiseaseIndicators — render tests (فاز ۱ cockpit overview).
 *
 * Covers:
 *   - one block per active condition, with its control + risk badges
 *   - indicator tile: value + unit + target + level badge
 *   - delta chip: arrow + Persian magnitude + improving/worsening cue (not colour alone)
 *   - graceful fallback: undefined / [] → renders nothing
 *   - a disease with zero indicators still shows its header + a note
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PerDiseaseIndicators } from "@/components/PerDiseaseIndicators";
import type { PerDiseaseDTO } from "@/lib/api";

const DIABETES: PerDiseaseDTO = {
  condition_code: "diabetes",
  condition_name: "دیابت",
  control: { status: "uncontrolled", label: "کنترل‌نشده" },
  risk_level: "high",
  indicators: [
    {
      key: "hba1c",
      label: "HbA1c",
      value: 8.2,
      unit: "%",
      target: "<7" as unknown as number, // backend may send a string target
      direction: "high",
      delta: { value: -0.6, dir: "down", improving: true },
      level: "danger",
    },
    {
      key: "fbs",
      label: "قند ناشتا",
      value: 150,
      unit: "mg/dL",
      target: 100,
      direction: "high",
      delta: { value: 12, dir: "up", improving: false },
      level: "warn",
    },
  ],
};

const HTN_NO_DATA: PerDiseaseDTO = {
  condition_code: "hypertension",
  condition_name: "فشار خون",
  control: { status: "no_data", label: "بدون داده" },
  risk_level: "stable",
  indicators: [],
};

describe("PerDiseaseIndicators — blocks", () => {
  it("renders one block per active condition", () => {
    render(<PerDiseaseIndicators perDisease={[DIABETES, HTN_NO_DATA]} />);
    expect(screen.getByTestId("disease-block-diabetes")).toBeInTheDocument();
    expect(screen.getByTestId("disease-block-hypertension")).toBeInTheDocument();
  });

  it("shows the disease name + control + risk badges", () => {
    render(<PerDiseaseIndicators perDisease={[DIABETES]} />);
    const block = screen.getByTestId("disease-block-diabetes");
    expect(block).toHaveTextContent("دیابت");
    expect(block).toHaveTextContent("کنترل‌نشده");
    expect(block).toHaveTextContent("پرخطر");
  });
});

describe("PerDiseaseIndicators — indicator tiles", () => {
  it("shows value + unit + target", () => {
    render(<PerDiseaseIndicators perDisease={[DIABETES]} />);
    const tile = screen.getByTestId("indicator-tile-hba1c");
    // value 8.2 → Persian digits
    expect(tile).toHaveTextContent("۸.۲");
    expect(tile).toHaveTextContent("%");
    // target "<7" preserved (< kept, 7 → ۷)
    expect(tile).toHaveTextContent("هدف: <۷");
  });

  it("renders the level badge with label + shape (danger)", () => {
    render(<PerDiseaseIndicators perDisease={[DIABETES]} />);
    expect(screen.getByTestId("indicator-level-hba1c")).toHaveTextContent("خطر");
    expect(screen.getByTestId("indicator-tile-hba1c")).toHaveAttribute("data-level", "danger");
  });

  it("delta chip: improving (down arrow) carries an improving cue, not colour alone", () => {
    render(<PerDiseaseIndicators perDisease={[DIABETES]} />);
    const tile = screen.getByTestId("indicator-tile-hba1c");
    // magnitude 0.6 → ۰.۶ with a down arrow ▼
    expect(tile).toHaveTextContent("▼");
    expect(tile).toHaveTextContent("۰.۶");
    // aria-label announces the improving trend
    expect(screen.getByLabelText(/روند بهبود/)).toBeInTheDocument();
  });

  it("delta chip: worsening (up arrow) announces worsening trend", () => {
    render(<PerDiseaseIndicators perDisease={[DIABETES]} />);
    const tile = screen.getByTestId("indicator-tile-fbs");
    expect(tile).toHaveTextContent("▲");
    expect(screen.getByLabelText(/روند بدتر شدن/)).toBeInTheDocument();
  });
});

describe("PerDiseaseIndicators — graceful fallback", () => {
  it("renders nothing when perDisease is undefined", () => {
    const { container } = render(<PerDiseaseIndicators />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when perDisease is an empty array", () => {
    const { container } = render(<PerDiseaseIndicators perDisease={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("a disease with zero indicators still shows its header + a note", () => {
    render(<PerDiseaseIndicators perDisease={[HTN_NO_DATA]} />);
    const block = screen.getByTestId("disease-block-hypertension");
    expect(block).toHaveTextContent("فشار خون");
    expect(block).toHaveTextContent("بدون داده");
    expect(block).toHaveTextContent("شاخصِ داده‌داری برای این بیماری ثبت نشده است.");
  });
});

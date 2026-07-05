/**
 * ClinicalSummaryStrip — render tests (فاز ۱ cockpit).
 *
 * Covers the four mini-KPIs + the sacred graceful-fallback rule:
 *   - control + risk render their label + dominant driver
 *   - counts render with Persian digits
 *   - each status tile has a non-colour cue (icon + aria-label)
 *   - when NOTHING is supplied (older backend) the strip renders nothing
 *   - a count tile renders even when the value is 0
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ClinicalSummaryStrip } from "@/components/ClinicalSummaryStrip";
import type { ControlDTO, RiskDTO } from "@/lib/api";

const CONTROL: ControlDTO = { status: "uncontrolled", label: "کنترل‌نشده" };
const RISK: RiskDTO = { level: "high", dominant: "قند خون", score: 4.5 };

describe("ClinicalSummaryStrip — full data", () => {
  it("renders the strip container", () => {
    render(
      <ClinicalSummaryStrip
        control={CONTROL}
        risk={RISK}
        openFollowupsCount={3}
        refillDueCount={1}
      />,
    );
    expect(screen.getByTestId("clinical-summary-strip")).toBeInTheDocument();
  });

  it("shows the control label", () => {
    render(<ClinicalSummaryStrip control={CONTROL} risk={RISK} openFollowupsCount={0} refillDueCount={0} />);
    expect(screen.getByTestId("kpi-control")).toHaveTextContent("کنترل‌نشده");
  });

  it("shows the risk label + dominant driver", () => {
    render(<ClinicalSummaryStrip control={CONTROL} risk={RISK} openFollowupsCount={0} refillDueCount={0} />);
    const risk = screen.getByTestId("kpi-risk");
    expect(risk).toHaveTextContent("پرخطر");
    expect(screen.getByTestId("kpi-risk-dominant")).toHaveTextContent("قند خون");
  });

  it("renders follow-up + refill counts in Persian digits", () => {
    render(<ClinicalSummaryStrip control={CONTROL} risk={RISK} openFollowupsCount={3} refillDueCount={1} />);
    expect(screen.getByTestId("kpi-followups")).toHaveTextContent("۳");
    expect(screen.getByTestId("kpi-refills")).toHaveTextContent("۱");
  });

  it("status tiles carry a non-colour cue (aria-label describing the status)", () => {
    render(<ClinicalSummaryStrip control={CONTROL} risk={RISK} openFollowupsCount={0} refillDueCount={0} />);
    // control label span is aria-labelled with the status
    expect(screen.getByLabelText("وضعیت کنترل: کنترل‌نشده")).toBeInTheDocument();
    expect(screen.getByLabelText("سطح خطر: پرخطر")).toBeInTheDocument();
  });

  it("carries data-status / data-risk tokens for stable non-colour styling hooks", () => {
    render(<ClinicalSummaryStrip control={CONTROL} risk={RISK} openFollowupsCount={0} refillDueCount={0} />);
    expect(screen.getByTestId("kpi-control")).toHaveAttribute("data-status", "uncontrolled");
    expect(screen.getByTestId("kpi-risk")).toHaveAttribute("data-risk", "high");
  });
});

describe("ClinicalSummaryStrip — graceful fallback", () => {
  it("renders NOTHING when no fields are supplied (older backend)", () => {
    const { container } = render(<ClinicalSummaryStrip />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("clinical-summary-strip")).not.toBeInTheDocument();
  });

  it("renders a count tile even when the value is 0", () => {
    render(<ClinicalSummaryStrip openFollowupsCount={0} refillDueCount={0} />);
    expect(screen.getByTestId("kpi-followups")).toHaveTextContent("۰");
    expect(screen.getByTestId("kpi-refills")).toHaveTextContent("۰");
    // no status tiles when control/risk absent
    expect(screen.queryByTestId("kpi-control")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kpi-risk")).not.toBeInTheDocument();
  });

  it("omits the dominant sub-line when dominant is null", () => {
    render(<ClinicalSummaryStrip risk={{ level: "stable", dominant: null, score: 0 }} />);
    expect(screen.getByTestId("kpi-risk")).toHaveTextContent("پایدار");
    expect(screen.queryByTestId("kpi-risk-dominant")).not.toBeInTheDocument();
  });
});

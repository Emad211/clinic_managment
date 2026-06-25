/**
 * Tests for vital level badge rendering.
 *
 * Strategy: render a minimal inline component that mirrors the exact
 * rendering logic of the vitals table in /patients/[uuid]/page.tsx.
 * This avoids importing the full page (which requires Next.js router mocks)
 * while testing the logic that matters.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { vitalLevelDisplay, type VitalLevel } from "../src/lib/vital-level";

// ─────────────────────────────────────────────────────────────
// Minimal VitalRow component — mirrors the table row rendering
// in /patients/[uuid]/page.tsx (the TD for the "مقدار" column).
// ─────────────────────────────────────────────────────────────

interface MinimalVitalRowProps {
  value: number;
  level?: VitalLevel;
}

function MinimalVitalValueCell({ value, level }: MinimalVitalRowProps) {
  const lvl = vitalLevelDisplay(level);
  const hasBadge = lvl.key !== "none";

  return (
    <span
      data-testid="vital-value-cell"
      aria-label={lvl.ariaLabel || undefined}
    >
      <span data-testid="vital-number">{value}</span>
      {hasBadge && (
        <span
          data-testid={`vital-badge-${lvl.key}`}
          aria-hidden="true"
        >
          {lvl.label}
        </span>
      )}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────

describe("VitalValueCell level rendering", () => {
  it("renders danger badge with text label when level='danger'", () => {
    render(<MinimalVitalValueCell value={188} level="danger" />);

    const badge = screen.getByTestId("vital-badge-danger");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("خطر");

    // The cell carries the ARIA label for screen readers
    const cell = screen.getByTestId("vital-value-cell");
    expect(cell).toHaveAttribute("aria-label");
    expect(cell.getAttribute("aria-label")).toContain("خطر");
  });

  it("renders warn badge with text label when level='warn'", () => {
    render(<MinimalVitalValueCell value={135} level="warn" />);

    const badge = screen.getByTestId("vital-badge-warn");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("احتیاط");
  });

  it("renders ok badge with text label when level='ok'", () => {
    render(<MinimalVitalValueCell value={90} level="ok" />);

    const badge = screen.getByTestId("vital-badge-ok");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("عادی");
  });

  it("renders no badge and no aria-label when level=null", () => {
    render(<MinimalVitalValueCell value={72} level={null} />);

    // No badge at all
    expect(screen.queryByTestId("vital-badge-ok")).toBeNull();
    expect(screen.queryByTestId("vital-badge-warn")).toBeNull();
    expect(screen.queryByTestId("vital-badge-danger")).toBeNull();

    // Cell has no aria-label when there is no status
    const cell = screen.getByTestId("vital-value-cell");
    expect(cell).not.toHaveAttribute("aria-label");
  });

  it("renders no badge when level=undefined (type not in catalog)", () => {
    render(<MinimalVitalValueCell value={72} />);

    expect(screen.queryByTestId(/vital-badge/)).toBeNull();
  });

  it("always renders the numeric value regardless of level", () => {
    const { rerender } = render(<MinimalVitalValueCell value={188} level="danger" />);
    expect(screen.getByTestId("vital-number")).toHaveTextContent("188");

    rerender(<MinimalVitalValueCell value={72} level={null} />);
    expect(screen.getByTestId("vital-number")).toHaveTextContent("72");
  });

  it("badge is aria-hidden (screen readers use aria-label on cell instead)", () => {
    render(<MinimalVitalValueCell value={188} level="danger" />);
    const badge = screen.getByTestId("vital-badge-danger");
    expect(badge).toHaveAttribute("aria-hidden", "true");
  });
});

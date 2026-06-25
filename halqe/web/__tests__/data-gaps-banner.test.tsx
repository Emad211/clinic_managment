/**
 * Tests for the data_gaps transparency banner in SuggestionsPanel.
 *
 * Verifies the "قاعدهٔ خاموش" (silent-rule) transparency contract:
 *   (a) when data_gaps is non-empty → banner rendered with label + Farsi count
 *   (b) when data_gaps is empty []  → banner NOT in DOM (not hidden, removed)
 *   (c) when data_gaps is absent (undefined) → banner NOT in DOM
 *   (d) suggestion-only: no action buttons inside the banner
 *   (e) existing redflag + framing banner still render correctly alongside data_gaps
 *   (f) multiple gaps → all labels shown
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─────────────────────────────────────────────────────────────
// Mock @/lib/api — same pattern as suggestions-guard.test.tsx
// ─────────────────────────────────────────────────────────────

jest.mock("../src/lib/api", () => ({
  apiSuggestionAction: jest.fn(),
  apiGetRecord: jest.fn(),
  apiGetSuggestions: jest.fn(),
  apiCreateEncounter: jest.fn(),
  apiAddVitals: jest.fn(),
  apiCompleteEncounter: jest.fn(),
  apiListEncounters: jest.fn(),
  getToken: jest.fn(() => null),
  saveToken: jest.fn(),
  clearToken: jest.fn(),
  errorMessageFromCode: jest.fn((_code: string, fallback: string) => fallback),
  ApiError: class ApiError extends Error {
    status: number;
    code: string | null;
    constructor(status: number, message: string, code: string | null = null) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
    }
  },
}));

// ─────────────────────────────────────────────────────────────
// Import REAL SuggestionsPanel (not a mirror)
// ─────────────────────────────────────────────────────────────

import { SuggestionsPanel } from "../src/components/SuggestionsPanel";
import type {
  SuggestionsResponseDTO,
  SuggestionRuleDTO,
  DataGapDTO,
} from "../src/lib/api";

// ─────────────────────────────────────────────────────────────
// Test data factories
// ─────────────────────────────────────────────────────────────

function makeRule(overrides: Partial<SuggestionRuleDTO> = {}): SuggestionRuleDTO {
  return {
    rule_code: "T2-TEST-01",
    title: "پیشنهاد آزمایشی",
    category: "test",
    condition_code: "DM",
    recommendation: "توصیهٔ آزمایشی.",
    dosage_titration: null,
    monitoring: null,
    contraindications: null,
    evidence_level: null,
    action_type: "review",
    severity: "info",
    priority: 1,
    source_ref: null,
    section: "glycemic",
    suggestion_only: true,
    prior_action: null,
    ...overrides,
  };
}

function makeSuggestions(
  overrides: Partial<SuggestionsResponseDTO> = {},
): SuggestionsResponseDTO {
  return {
    patient_link_id: 1,
    count: 1,
    has_redflag: false,
    framing: "پیشنهاد — تأیید با پزشک",
    sections: [
      {
        key: "glycemic",
        label: "کنترل قند",
        rules: [makeRule()],
      },
    ],
    ...overrides,
  };
}

const TEST_UUID = "test-uuid-gaps";

// ─────────────────────────────────────────────────────────────
// (a) Non-empty data_gaps → banner renders with label + Farsi count
// ─────────────────────────────────────────────────────────────

describe("a — non-empty data_gaps renders banner", () => {
  it("shows the banner container when data_gaps has one item", () => {
    const gaps: DataGapDTO[] = [
      { datum: "age", label: "سن", affected_rules: 4 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const banner = screen.getByTestId("data-gaps-banner");
    expect(banner).toBeInTheDocument();
  });

  it("banner contains the Persian label text", () => {
    const gaps: DataGapDTO[] = [
      { datum: "egfr", label: "eGFR (تخمین فیلتراسیون کلیه)", affected_rules: 2 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const banner = screen.getByTestId("data-gaps-banner");
    expect(banner.textContent).toContain("eGFR");
    expect(banner.textContent).toContain("تخمین فیلتراسیون کلیه");
  });

  it("banner shows rule count as Persian digits (۴ not 4)", () => {
    const gaps: DataGapDTO[] = [
      { datum: "age", label: "سن", affected_rules: 4 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const banner = screen.getByTestId("data-gaps-banner");
    // Should contain Persian ۴ (U+06F4), not ASCII 4
    expect(banner.textContent).toContain("۴");
    // ASCII "4" should NOT appear in the count position
    // (we check the overall banner doesn't have standalone ASCII digit)
    expect(banner.textContent).not.toMatch(/\b4\b/);
  });

  it("banner has role=note (informational, not urgent)", () => {
    const gaps: DataGapDTO[] = [
      { datum: "age", label: "سن", affected_rules: 1 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // The data-gaps banner carries role="note"; the framing banner also has role="note".
    // There should be at least one note role (possibly two: framing + gaps).
    const notes = screen.getAllByRole("note");
    expect(notes.length).toBeGreaterThanOrEqual(1);

    // The gaps banner specifically is found by testid and has no role="alert"
    const banner = screen.getByTestId("data-gaps-banner");
    expect(banner).not.toHaveAttribute("role", "alert");
    expect(banner).toHaveAttribute("role", "note");
  });
});

// ─────────────────────────────────────────────────────────────
// (b) Empty data_gaps [] → banner NOT in DOM
// ─────────────────────────────────────────────────────────────

describe("b — empty data_gaps → banner absent from DOM", () => {
  it("does NOT render the banner when data_gaps is []", () => {
    const suggestions = makeSuggestions({ data_gaps: [] });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.queryByTestId("data-gaps-banner")).toBeNull();
  });

  it("empty data_gaps still shows suggestion cards normally", () => {
    const suggestions = makeSuggestions({ data_gaps: [] });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // Framing banner still present
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("پیشنهاد");

    // Rule card still rendered
    expect(screen.getByText("پیشنهاد آزمایشی")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (c) data_gaps absent (undefined) → banner NOT in DOM
// ─────────────────────────────────────────────────────────────

describe("c — absent data_gaps → banner absent from DOM", () => {
  it("does NOT render the banner when data_gaps is undefined", () => {
    // makeSuggestions without data_gaps key → field is absent
    const suggestions = makeSuggestions();
    expect(suggestions.data_gaps).toBeUndefined();

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.queryByTestId("data-gaps-banner")).toBeNull();
  });

  it("existing framing banner still renders when data_gaps is undefined", () => {
    const suggestions = makeSuggestions();

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const note = screen.getByRole("note");
    expect(note.textContent).toContain("تأیید با پزشک");
  });
});

// ─────────────────────────────────────────────────────────────
// (d) suggestion-only: banner has no action buttons
// ─────────────────────────────────────────────────────────────

describe("d — suggestion-only: no action buttons in banner", () => {
  it("data-gaps banner contains no <button> elements", () => {
    const gaps: DataGapDTO[] = [
      { datum: "hba1c", label: "HbA1c", affected_rules: 3 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    const { container } = render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const banner = container.querySelector("[data-testid='data-gaps-banner']");
    expect(banner).not.toBeNull();
    const buttons = banner!.querySelectorAll("button");
    expect(buttons.length).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────
// (e) redflag + data_gaps both render correctly together
// ─────────────────────────────────────────────────────────────

describe("e — redflag and data_gaps coexist without breaking", () => {
  it("renders role=alert (redflag) AND data-gaps banner when both are present", () => {
    const gaps: DataGapDTO[] = [
      { datum: "ldl", label: "LDL کلسترول", affected_rules: 2 },
    ];
    const suggestions = makeSuggestions({
      has_redflag: true,
      data_gaps: gaps,
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // redflag alert
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();

    // data-gaps banner
    const banner = screen.getByTestId("data-gaps-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("LDL");
  });

  it("when has_redflag=false and data_gaps is empty, no alert and no banner", () => {
    const suggestions = makeSuggestions({
      has_redflag: false,
      data_gaps: [],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("data-gaps-banner")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// (f) Multiple gaps → all labels shown
// ─────────────────────────────────────────────────────────────

describe("f — multiple data_gaps all appear in banner", () => {
  it("shows all gap labels when there are two gaps", () => {
    const gaps: DataGapDTO[] = [
      { datum: "age", label: "سن", affected_rules: 4 },
      { datum: "egfr", label: "eGFR (تخمین فیلتراسیون کلیه)", affected_rules: 2 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const banner = screen.getByTestId("data-gaps-banner");
    expect(banner.textContent).toContain("سن");
    expect(banner.textContent).toContain("eGFR");
    // Both counts as Farsi digits
    expect(banner.textContent).toContain("۴");
    expect(banner.textContent).toContain("۲");
  });

  it("shows all three gap labels when there are three gaps", () => {
    const gaps: DataGapDTO[] = [
      { datum: "age", label: "سن", affected_rules: 4 },
      { datum: "egfr", label: "eGFR", affected_rules: 2 },
      { datum: "hba1c", label: "HbA1c", affected_rules: 5 },
    ];
    const suggestions = makeSuggestions({ data_gaps: gaps });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const banner = screen.getByTestId("data-gaps-banner");
    expect(banner.textContent).toContain("سن");
    expect(banner.textContent).toContain("eGFR");
    expect(banner.textContent).toContain("HbA1c");
    expect(banner.textContent).toContain("۵");
  });
});

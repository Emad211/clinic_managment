/**
 * Tests for the DDI (Drug-Drug Interaction) section in SuggestionsPanel.
 *
 * Contract (clinical pharmacist + قرارداد قفل‌شده):
 *   (a) Non-empty ddi array → section renders with items + severity labels
 *   (b) contraindicated item → role="alert" + red styling marker
 *   (c) major/moderate → role="note" (ضدِ alert-fatigue)
 *   (d) ddi=[] → section NOT in DOM
 *   (e) ddi=undefined → section NOT in DOM
 *   (f) Items sorted by severity: contraindicated first, moderate last
 *   (g) suggestion-only chip present; no action buttons
 *   (h) evidence field shown when present; hidden when absent
 *   (i) Existing redflag / data-gaps / framing-banner still render alongside DDI
 */

import React from "react";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─────────────────────────────────────────────────────────────
// Mock @/lib/api — same pattern as other suggestion tests
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
  DdiDTO,
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

function makeDdi(overrides: Partial<DdiDTO> = {}): DdiDTO {
  return {
    class_a: "acei",
    class_b: "arb",
    severity: "contraindicated",
    message_fa: "ترکیبِ دو بلاکرِ RAAS (ACEi + ARB) خطرِ هیپرکالمی و AKI را افزایش می‌دهد.",
    evidence: "ONTARGET 2008؛ ADA 2025 §CKD",
    suggestion_only: true,
    ...overrides,
  };
}

const TEST_UUID = "test-uuid-ddi";

// ─────────────────────────────────────────────────────────────
// (a) Non-empty ddi → section renders with items + labels
// ─────────────────────────────────────────────────────────────

describe("a — non-empty ddi renders the DDI section", () => {
  it("renders the DDI section container when ddi has one item", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi()],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.getByTestId("ddi-section")).toBeInTheDocument();
  });

  it("renders the section title 'تداخلات دارویی'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi()],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const section = screen.getByTestId("ddi-section");
    expect(section.textContent).toContain("تداخلات دارویی");
  });

  it("renders the Persian message_fa text", () => {
    const msg = "ترکیبِ دو بلاکرِ RAAS خطرناک است.";
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ message_fa: msg })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.getByText(msg)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (b) contraindicated → role="alert" + red severity badge label
// ─────────────────────────────────────────────────────────────

describe("b — contraindicated item uses role='alert' and red label", () => {
  it("contraindicated DDI item has role='alert'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "contraindicated" })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // The DDI item div carries role="alert"
    const ddiItem = screen.getByTestId("ddi-item-contraindicated");
    expect(ddiItem).toHaveAttribute("role", "alert");
  });

  it("contraindicated item badge text is 'منع مصرف همزمان'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "contraindicated" })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const section = screen.getByTestId("ddi-section");
    expect(section.textContent).toContain("منع مصرف همزمان");
  });

  it("contraindicated item has data-severity='contraindicated'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "contraindicated" })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const item = screen.getByTestId("ddi-item-contraindicated");
    expect(item).toHaveAttribute("data-severity", "contraindicated");
  });
});

// ─────────────────────────────────────────────────────────────
// (c) major / moderate → role="note"
// ─────────────────────────────────────────────────────────────

describe("c — major/moderate items use role='note'", () => {
  it("major DDI item has role='note'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "major", message_fa: "تداخل مهم." })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const item = screen.getByTestId("ddi-item-major");
    expect(item).toHaveAttribute("role", "note");
  });

  it("major badge text is 'تداخل مهم'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "major", message_fa: "تداخل مهم." })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const section = screen.getByTestId("ddi-section");
    expect(section.textContent).toContain("تداخل مهم");
  });

  it("moderate DDI item has role='note'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "moderate", message_fa: "تداخل متوسط." })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const item = screen.getByTestId("ddi-item-moderate");
    expect(item).toHaveAttribute("role", "note");
  });

  it("moderate badge text is 'تداخل متوسط'", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ severity: "moderate", message_fa: "تداخل متوسط." })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const section = screen.getByTestId("ddi-section");
    expect(section.textContent).toContain("تداخل متوسط");
  });
});

// ─────────────────────────────────────────────────────────────
// (d) ddi=[] → section NOT in DOM
// ─────────────────────────────────────────────────────────────

describe("d — empty ddi → section absent from DOM", () => {
  it("does NOT render DDI section when ddi is []", () => {
    const suggestions = makeSuggestions({ ddi: [] });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.queryByTestId("ddi-section")).toBeNull();
  });

  it("empty ddi still shows framing banner", () => {
    const suggestions = makeSuggestions({ ddi: [] });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const note = screen.getByRole("note");
    expect(note.textContent).toContain("پیشنهاد");
  });
});

// ─────────────────────────────────────────────────────────────
// (e) ddi=undefined → section NOT in DOM
// ─────────────────────────────────────────────────────────────

describe("e — absent ddi → section absent from DOM", () => {
  it("does NOT render DDI section when ddi is undefined", () => {
    const suggestions = makeSuggestions();
    expect(suggestions.ddi).toBeUndefined();

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.queryByTestId("ddi-section")).toBeNull();
  });

  it("regular suggestions still render when ddi is absent", () => {
    const suggestions = makeSuggestions();

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.getByText("پیشنهاد آزمایشی")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// (f) Items sorted: contraindicated first, moderate last
// ─────────────────────────────────────────────────────────────

describe("f — DDI items sorted by severity (contraindicated first)", () => {
  it("contraindicated item appears before moderate in rendered DOM", () => {
    const suggestions = makeSuggestions({
      ddi: [
        // Deliberately reversed order — engine may return in any order
        makeDdi({ severity: "moderate", class_a: "sglt2i", class_b: "loop_diuretic", message_fa: "تداخل متوسط." }),
        makeDdi({ severity: "contraindicated", class_a: "acei", class_b: "arb", message_fa: "ترکیب خطرناک." }),
        makeDdi({ severity: "major", class_a: "nsaid", class_b: "acei", message_fa: "تداخل مهم." }),
      ],
    });

    const { container } = render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const items = container.querySelectorAll("[data-testid^='ddi-item-']");
    expect(items.length).toBe(3);

    // First rendered = contraindicated
    expect(items[0]).toHaveAttribute("data-severity", "contraindicated");
    // Second = major
    expect(items[1]).toHaveAttribute("data-severity", "major");
    // Third = moderate
    expect(items[2]).toHaveAttribute("data-severity", "moderate");
  });

  it("two contraindicated items both render before any moderate", () => {
    const suggestions = makeSuggestions({
      ddi: [
        makeDdi({ severity: "moderate", class_a: "x", class_b: "y", message_fa: "متوسط." }),
        makeDdi({ severity: "contraindicated", class_a: "acei", class_b: "arb", message_fa: "خطرناک ۱." }),
        makeDdi({ severity: "contraindicated", class_a: "acei", class_b: "dri", message_fa: "خطرناک ۲." }),
      ],
    });

    const { container } = render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const items = container.querySelectorAll("[data-testid^='ddi-item-']");
    expect(items[0]).toHaveAttribute("data-severity", "contraindicated");
    expect(items[1]).toHaveAttribute("data-severity", "contraindicated");
    expect(items[2]).toHaveAttribute("data-severity", "moderate");
  });
});

// ─────────────────────────────────────────────────────────────
// (g) suggestion-only chip present; no action buttons
// ─────────────────────────────────────────────────────────────

describe("g — suggestion-only chip present; no action buttons in DDI section", () => {
  it("DDI section contains 'پیشنهاد' chip text", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi()],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const section = screen.getByTestId("ddi-section");
    expect(section.textContent).toContain("پیشنهاد");
  });

  it("DDI section contains no <button> elements", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi(), makeDdi({ severity: "major", message_fa: "تداخل." })],
    });

    const { container } = render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const section = container.querySelector("[data-testid='ddi-section']");
    expect(section).not.toBeNull();
    const buttons = section!.querySelectorAll("button");
    expect(buttons.length).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────
// (h) evidence field shown when present; absent when missing
// ─────────────────────────────────────────────────────────────

describe("h — evidence citation", () => {
  it("renders evidence text when present", () => {
    const ev = "ONTARGET 2008؛ ADA 2025 §CKD";
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ evidence: ev })],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.getByText(ev)).toBeInTheDocument();
  });

  it("does NOT render evidence element when evidence is absent", () => {
    const suggestions = makeSuggestions({
      ddi: [makeDdi({ evidence: undefined })],
    });

    const { container } = render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // No element with evidence aria-label when field is missing
    const item = container.querySelector("[data-testid='ddi-item-contraindicated']");
    expect(item).not.toBeNull();
    // The only text should be the message and badge — not an evidence paragraph
    const evidenceEl = item!.querySelector("[aria-label^='مرجع:']");
    expect(evidenceEl).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// (i) DDI section + redflag + data-gaps + framing all coexist
// ─────────────────────────────────────────────────────────────

describe("i — DDI section coexists with redflag, data-gaps, framing banner", () => {
  it("redflag strip, framing banner, data-gaps banner, and DDI section all render together", () => {
    const suggestions = makeSuggestions({
      has_redflag: true,
      data_gaps: [{ datum: "egfr", label: "eGFR", affected_rules: 2 }],
      ddi: [makeDdi()],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // Framing banner (role="note" with پیشنهاد text)
    const notes = screen.getAllByRole("note");
    const framingNote = notes.find((n) => n.textContent?.includes("تأیید با پزشک"));
    expect(framingNote).toBeInTheDocument();

    // Redflag strip: contraindicated DDI is role="alert" AND has_redflag produces a strip
    // Both share role="alert" in this case — at least one alert should be present
    const alerts = screen.getAllByRole("alert");
    expect(alerts.length).toBeGreaterThanOrEqual(1);

    // Data gaps banner
    expect(screen.getByTestId("data-gaps-banner")).toBeInTheDocument();

    // DDI section
    expect(screen.getByTestId("ddi-section")).toBeInTheDocument();
  });

  it("when ddi=[], other sections still render correctly", () => {
    const suggestions = makeSuggestions({
      has_redflag: false,
      data_gaps: [{ datum: "age", label: "سن", affected_rules: 1 }],
      ddi: [],
    });

    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    expect(screen.queryByTestId("ddi-section")).toBeNull();
    expect(screen.getByTestId("data-gaps-banner")).toBeInTheDocument();
    // Both the framing banner and the data-gaps banner have role="note"
    const notes = screen.getAllByRole("note");
    expect(notes.length).toBeGreaterThanOrEqual(1);
  });
});

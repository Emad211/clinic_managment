/**
 * Architecture Guard — suggestions-guard.test.tsx
 *
 * Tests the REAL exported RuleCard and SuggestionsPanel components
 * (not a mirror). This is the safety net that enforces the
 * suggestion-only principle at the UI level.
 *
 * Asserting:
 *   A. framing banner (role="note") always in DOM when suggestions loaded
 *   B. every RuleCard carries data-suggestion-only="true" AND visible chip «پیشنهاد»
 *   C. clicking «پذیرفتم» calls ONLY apiSuggestionAction — nothing else
 *   D. acted state is display-only: role="status" remains, no action buttons
 *   E. has_redflag=true renders role="alert"
 */

import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─────────────────────────────────────────────────────────────
// Mock @/lib/api
// All functions must be mocked; only apiSuggestionAction should be called
// during normal suggestion accept/dismiss flow.
// ─────────────────────────────────────────────────────────────

const mockApiSuggestionAction = jest.fn();

jest.mock("../src/lib/api", () => ({
  apiSuggestionAction: (...args: unknown[]) => mockApiSuggestionAction(...args),
  // Other exports used only as type imports in the components — provide stubs
  // so the module resolves cleanly.
  apiGetRecord: jest.fn(),
  apiGetSuggestions: jest.fn(),
  apiCreateEncounter: jest.fn(),
  apiAddVitals: jest.fn(),
  apiCompleteEncounter: jest.fn(),
  apiListEncounters: jest.fn(),
  getToken: jest.fn(() => null),
  saveToken: jest.fn(),
  clearToken: jest.fn(),
  errorMessageFromCode: jest.fn((code: string, fallback: string) => fallback),
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
// Import REAL components (not mirrors)
// ─────────────────────────────────────────────────────────────

import { RuleCard } from "../src/components/RuleCard";
import { SuggestionsPanel } from "../src/components/SuggestionsPanel";
import type { SuggestionsResponseDTO, SuggestionRuleDTO } from "../src/lib/api";

// ─────────────────────────────────────────────────────────────
// Test data factories
// ─────────────────────────────────────────────────────────────

function makeRule(overrides: Partial<SuggestionRuleDTO> = {}): SuggestionRuleDTO {
  return {
    rule_code: "T2-TEST-01",
    title: "پیشنهاد آزمایشی",
    category: "test",
    condition_code: "DM",
    recommendation: "این یک توصیهٔ آزمایشی است.",
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
  rules: SuggestionRuleDTO[],
  overrides: Partial<SuggestionsResponseDTO> = {},
): SuggestionsResponseDTO {
  return {
    patient_link_id: 1,
    count: rules.length,
    has_redflag: false,
    framing: "پیشنهاد — تأیید با پزشک",
    sections: rules.length > 0
      ? [{ key: "glycemic", label: "کنترل قند", rules }]
      : [],
    ...overrides,
  };
}

// UUID used across tests
const TEST_UUID = "test-uuid-1234";

// ─────────────────────────────────────────────────────────────
// Setup / teardown
// ─────────────────────────────────────────────────────────────

beforeEach(() => {
  mockApiSuggestionAction.mockReset();
  mockApiSuggestionAction.mockResolvedValue({ ok: true });
});

// ─────────────────────────────────────────────────────────────
// A. Framing banner always in DOM when suggestions loaded
// ─────────────────────────────────────────────────────────────

describe("A — framing banner", () => {
  it("renders role=note with 'پیشنهاد' and 'تأیید با پزشک' when suggestions are loaded", () => {
    const suggestions = makeSuggestions([makeRule()]);
    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const note = screen.getByRole("note");
    expect(note).toBeInTheDocument();
    expect(note.textContent).toContain("پیشنهاد");
    expect(note.textContent).toContain("تأیید با پزشک");
  });

  it("renders framing banner even when sections are empty (no rules)", () => {
    const suggestions = makeSuggestions([]);
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
    expect(note.textContent).toContain("تأیید با پزشک");
  });

  it("does NOT render framing banner while loading", () => {
    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={null}
        suggestionsLoading={true}
        suggestionsError={null}
      />,
    );
    expect(screen.queryByRole("note")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// B. Every RuleCard has data-suggestion-only="true" AND chip text
// ─────────────────────────────────────────────────────────────

describe("B — per-card suggestion-only marker", () => {
  it("standalone RuleCard has data-suggestion-only='true' attribute", () => {
    const rule = makeRule();
    const { container } = render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );
    const article = container.querySelector("article");
    expect(article).toHaveAttribute("data-suggestion-only", "true");
  });

  it("standalone RuleCard shows visible chip text 'پیشنهاد'", () => {
    const rule = makeRule({ title: "قند ناشتا بالا" });
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );
    // The chip has text "پیشنهاد" — find it by text (not aria-label to stay robust)
    const chip = screen.getByText("پیشنهاد");
    expect(chip).toBeInTheDocument();
  });

  it("SuggestionsPanel: number of data-suggestion-only cards equals number of rules", () => {
    const rules = [
      makeRule({ rule_code: "R-1", title: "پیشنهاد ۱" }),
      makeRule({ rule_code: "R-2", title: "پیشنهاد ۲" }),
      makeRule({ rule_code: "R-3", title: "پیشنهاد ۳" }),
    ];
    const suggestions = makeSuggestions(rules);
    const { container } = render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const cards = container.querySelectorAll("[data-suggestion-only='true']");
    expect(cards.length).toBe(rules.length);
  });
});

// ─────────────────────────────────────────────────────────────
// C. Button click calls ONLY apiSuggestionAction — no other endpoint
// ─────────────────────────────────────────────────────────────

describe("C — accept/dismiss calls only apiSuggestionAction", () => {
  it("clicking 'پذیرفتم' calls apiSuggestionAction with 'accept'", async () => {
    const rule = makeRule({ rule_code: "T2-GLUC-01", title: "قند ناشتا" });
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );

    const btn = screen.getByRole("button", { name: /ثبت پذیرش پیشنهاد/ });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockApiSuggestionAction).toHaveBeenCalledTimes(1);
      expect(mockApiSuggestionAction).toHaveBeenCalledWith(
        TEST_UUID,
        "T2-GLUC-01",
        "accept",
      );
    });
  });

  it("clicking 'رد کردم' calls apiSuggestionAction with 'dismiss'", async () => {
    const rule = makeRule({ rule_code: "T2-GLUC-02", title: "داروی جدید" });
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );

    const btn = screen.getByRole("button", { name: /ثبت رد پیشنهاد/ });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockApiSuggestionAction).toHaveBeenCalledTimes(1);
      expect(mockApiSuggestionAction).toHaveBeenCalledWith(
        TEST_UUID,
        "T2-GLUC-02",
        "dismiss",
      );
    });
  });

  it("apiSuggestionAction is the ONLY mock called (no prescription/SMS endpoints)", async () => {
    const rule = makeRule();
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /ثبت پذیرش/ }));
    await waitFor(() => expect(mockApiSuggestionAction).toHaveBeenCalledTimes(1));

    // Verify no OTHER api functions were called
    const { apiGetRecord, apiGetSuggestions, apiCreateEncounter, apiAddVitals } =
      jest.requireMock("../src/lib/api") as {
        apiGetRecord: jest.Mock;
        apiGetSuggestions: jest.Mock;
        apiCreateEncounter: jest.Mock;
        apiAddVitals: jest.Mock;
      };
    expect(apiGetRecord).not.toHaveBeenCalled();
    expect(apiGetSuggestions).not.toHaveBeenCalled();
    expect(apiCreateEncounter).not.toHaveBeenCalled();
    expect(apiAddVitals).not.toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────
// D. Acted state is display-only: role="status" only, no action buttons
// ─────────────────────────────────────────────────────────────

describe("D — acted state is display-only", () => {
  it("acted='accepted' shows role=status 'پذیرفته شد', hides action buttons", () => {
    const rule = makeRule();
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted="accepted"
        onAct={jest.fn()}
      />,
    );

    const status = screen.getByRole("status");
    expect(status.textContent).toContain("پذیرفته شد");

    // No action buttons
    expect(screen.queryByRole("button", { name: /ثبت پذیرش/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /ثبت رد/ })).toBeNull();
  });

  it("acted='dismissed' shows role=status 'رد شد', hides action buttons", () => {
    const rule = makeRule();
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted="dismissed"
        onAct={jest.fn()}
      />,
    );

    const status = screen.getByRole("status");
    expect(status.textContent).toContain("رد شد");

    expect(screen.queryByRole("button", { name: /ثبت پذیرش/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /ثبت رد/ })).toBeNull();
  });

  it("after clicking 'پذیرفتم', onAct is called and optimistic acted state can replace buttons with status", async () => {
    const onAct = jest.fn();
    const rule = makeRule();

    // Render with external acted state controlled by test (simulates parent state)
    function TestWrapper() {
      const [acted, setActed] = React.useState<"accepted" | "dismissed" | undefined>(undefined);
      function handleAct(_code: string, action: "accept" | "dismiss") {
        onAct(_code, action);
        setActed(action === "accept" ? "accepted" : "dismissed");
      }
      return (
        <RuleCard
          rule={rule}
          uuid={TEST_UUID}
          acted={acted}
          onAct={handleAct}
        />
      );
    }

    render(<TestWrapper />);

    // Buttons visible initially
    expect(screen.getByRole("button", { name: /ثبت پذیرش/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /ثبت پذیرش/ }));

    await waitFor(() => {
      expect(onAct).toHaveBeenCalledWith(rule.rule_code, "accept");
      // After act, buttons gone and status shown
      expect(screen.queryByRole("button", { name: /ثبت پذیرش/ })).toBeNull();
      expect(screen.getByRole("status")).toBeInTheDocument();
    });
  });
});

// ─────────────────────────────────────────────────────────────
// E. has_redflag=true renders role="alert"
// ─────────────────────────────────────────────────────────────

describe("E — redflag alert", () => {
  it("renders role=alert when has_redflag is true", () => {
    const suggestions = makeSuggestions([makeRule()], { has_redflag: true });
    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    // Should contain some form of urgency cue
    expect(alert.textContent).toBeTruthy();
  });

  it("does NOT render role=alert when has_redflag is false", () => {
    const suggestions = makeSuggestions([makeRule()], { has_redflag: false });
    render(
      <SuggestionsPanel
        uuid={TEST_UUID}
        suggestions={suggestions}
        suggestionsLoading={false}
        suggestionsError={null}
      />,
    );

    // No alert element (the error message p is not alert-role when no error)
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// F. Button framing text (physician-decision framing)
// ─────────────────────────────────────────────────────────────

describe("F — button framing text", () => {
  it("accept button text is 'پذیرفتم' (not 'تأیید')", () => {
    const rule = makeRule();
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );
    // Accept button must show 'پذیرفتم', not 'تأیید'
    const acceptBtn = screen.getByRole("button", { name: /ثبت پذیرش/ });
    expect(acceptBtn.textContent).toContain("پذیرفتم");
    expect(acceptBtn.textContent).not.toContain("تأیید");
  });

  it("dismiss button text is 'رد کردم' (not 'رد')", () => {
    const rule = makeRule();
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted={undefined}
        onAct={jest.fn()}
      />,
    );
    const dismissBtn = screen.getByRole("button", { name: /ثبت رد/ });
    expect(dismissBtn.textContent).toContain("رد کردم");
  });

  it("accepted state text is 'پذیرفته شد' (not 'تأیید شد')", () => {
    const rule = makeRule();
    render(
      <RuleCard
        rule={rule}
        uuid={TEST_UUID}
        acted="accepted"
        onAct={jest.fn()}
      />,
    );
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("پذیرفته شد");
    expect(status.textContent).not.toContain("تأیید شد");
  });
});

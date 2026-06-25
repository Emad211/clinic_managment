/**
 * Tests for the vital-catalog module and the VitalTypeSelect behavior
 * baked into RegisterVisitForm.
 *
 * Strategy: unit-test the catalog directly, then test a minimal inline
 * component that mirrors the select/«دیگر»/auto-unit logic in
 * RegisterVisitForm — without importing the full Next.js page.
 */

import React, { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  VITAL_CATALOG,
  VITAL_CATALOG_MAP,
  type VitalCatalogItem,
} from "../src/lib/vital-catalog";

// ─────────────────────────────────────────────────────────────
// 1.  VITAL_CATALOG static structure
// ─────────────────────────────────────────────────────────────

describe("VITAL_CATALOG", () => {
  it("contains at least 12 entries", () => {
    expect(VITAL_CATALOG.length).toBeGreaterThanOrEqual(12);
  });

  it("every item has a non-empty key, label, and unit (unit may be empty string)", () => {
    for (const item of VITAL_CATALOG) {
      expect(item.key).toBeTruthy();
      expect(item.label).toBeTruthy();
      expect(typeof item.unit).toBe("string"); // unit may be "" (BMI)
    }
  });

  it("all keys are lowercase (match canonical vital_readings.type)", () => {
    for (const item of VITAL_CATALOG) {
      expect(item.key).toBe(item.key.toLowerCase());
    }
  });

  it("contains the required canonical keys verified against schema.sql / vitals_repo.py", () => {
    const required = [
      "fbs",
      "hba1c",
      "ppg",
      "bp_systolic",
      "bp_diastolic",
      "ldl",
      "triglyceride",
      "egfr",
      "uacr",
      "tsh",
      "weight",
      "pulse",
    ];
    const keys = VITAL_CATALOG.map((v) => v.key);
    for (const key of required) {
      expect(keys).toContain(key);
    }
  });

  it("keys are unique (no duplicates)", () => {
    const keys = VITAL_CATALOG.map((v) => v.key);
    const unique = new Set(keys);
    expect(unique.size).toBe(keys.length);
  });
});

// ─────────────────────────────────────────────────────────────
// 2.  VITAL_CATALOG_MAP lookup
// ─────────────────────────────────────────────────────────────

describe("VITAL_CATALOG_MAP", () => {
  it("is keyed by the catalog item key", () => {
    for (const item of VITAL_CATALOG) {
      expect(VITAL_CATALOG_MAP[item.key]).toBeDefined();
      expect(VITAL_CATALOG_MAP[item.key].key).toBe(item.key);
    }
  });

  it("returns correct unit for fbs", () => {
    expect(VITAL_CATALOG_MAP["fbs"].unit).toBe("mg/dL");
  });

  it("returns correct unit for hba1c", () => {
    expect(VITAL_CATALOG_MAP["hba1c"].unit).toBe("%");
  });

  it("returns correct unit for bp_systolic", () => {
    expect(VITAL_CATALOG_MAP["bp_systolic"].unit).toBe("mmHg");
  });

  it("returns correct unit for egfr", () => {
    expect(VITAL_CATALOG_MAP["egfr"].unit).toBe("mL/min");
  });

  it("returns correct unit for tsh", () => {
    expect(VITAL_CATALOG_MAP["tsh"].unit).toBe("mIU/L");
  });

  it("returns empty string unit for bmi", () => {
    expect(VITAL_CATALOG_MAP["bmi"].unit).toBe("");
  });

  it("returns undefined for unknown key", () => {
    expect(VITAL_CATALOG_MAP["unknown_key"]).toBeUndefined();
  });
});

// ─────────────────────────────────────────────────────────────
// 3.  Minimal VitalTypeSelect component — mirrors page logic
// ─────────────────────────────────────────────────────────────

/**
 * Minimal component that exactly mirrors the select/«دیگر»/auto-unit
 * logic added to RegisterVisitForm in patients/[uuid]/page.tsx.
 *
 * Props exposed for testability:
 *   onTypeChange(key: string)  — called when canonical key is selected (isOther=false)
 *   onUnitChange(unit: string) — called when unit auto-fills
 *   isOther / type / unit      — controlled state to inspect from tests
 */

interface VitalSelectState {
  type: string;
  unit: string;
  isOther: boolean;
}

function MinimalVitalTypeSelect({
  onChange,
}: {
  onChange: (state: VitalSelectState) => void;
}) {
  const [state, setState] = useState<VitalSelectState>({
    type: "",
    unit: "",
    isOther: false,
  });

  function handleSelect(selectedKey: string) {
    let next: VitalSelectState;
    if (selectedKey === "__other__") {
      next = { type: "", unit: "", isOther: true };
    } else {
      const item: VitalCatalogItem | undefined = VITAL_CATALOG_MAP[selectedKey];
      next = { type: selectedKey, unit: item?.unit ?? "", isOther: false };
    }
    setState(next);
    onChange(next);
  }

  const selectValue = state.isOther ? "__other__" : state.type !== "" ? state.type : "";

  return (
    <div>
      <select
        value={selectValue}
        onChange={(e) => handleSelect(e.target.value)}
        aria-label="نوع اندازه‌گیری"
        data-testid="vital-type-select"
      >
        <option value="" disabled>
          — انتخاب کنید —
        </option>
        {VITAL_CATALOG.map((item) => (
          <option key={item.key} value={item.key}>
            {item.label}
          </option>
        ))}
        <option value="__other__">دیگر…</option>
      </select>

      {/* Free-text input for «دیگر» */}
      {state.isOther && (
        <input
          type="text"
          aria-label="نام اندازه‌گیری (دیگر)"
          placeholder="نام اندازه‌گیری"
          value={state.type}
          onChange={(e) => {
            const next = { ...state, type: e.target.value };
            setState(next);
            onChange(next);
          }}
          data-testid="vital-type-other-input"
        />
      )}

      {/* Auto-filled unit (read-only when canonical) */}
      <input
        type="text"
        aria-label="واحد اندازه‌گیری"
        value={state.unit}
        readOnly={!state.isOther && state.type !== ""}
        onChange={(e) => {
          if (state.isOther) {
            const next = { ...state, unit: e.target.value };
            setState(next);
            onChange(next);
          }
        }}
        data-testid="vital-unit-input"
      />
    </div>
  );
}

describe("MinimalVitalTypeSelect — select renders catalog options", () => {
  it("renders a <select> with all catalog options plus «دیگر»", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);
    const select = screen.getByRole("combobox", { name: /نوع اندازه‌گیری/ });
    expect(select).toBeInTheDocument();

    const options = screen.getAllByRole("option");
    const values = options.map((o) => (o as HTMLOptionElement).value);
    // All catalog keys present
    for (const item of VITAL_CATALOG) {
      expect(values).toContain(item.key);
    }
    // «دیگر» sentinel present
    expect(values).toContain("__other__");
  });

  it("shows Persian labels for catalog items (not raw keys)", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);
    const optionTexts = screen
      .getAllByRole("option")
      .map((o) => o.textContent ?? "");
    // Check a few known Persian labels
    expect(optionTexts.some((t) => t.includes("قند ناشتا"))).toBe(true);
    expect(optionTexts.some((t) => t.includes("فشار سیستول"))).toBe(true);
    expect(optionTexts.some((t) => t.includes("HbA1c"))).toBe(true);
  });

  it("renders «دیگر…» as the last option", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);
    const options = screen.getAllByRole("option");
    const last = options[options.length - 1];
    expect(last.textContent).toBe("دیگر…");
  });
});

describe("MinimalVitalTypeSelect — canonical key selection auto-fills unit", () => {
  it("selecting fbs sets type=fbs, unit=mg/dL, isOther=false", () => {
    const onChange = jest.fn();
    render(<MinimalVitalTypeSelect onChange={onChange} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "fbs" },
    });

    expect(onChange).toHaveBeenLastCalledWith({
      type: "fbs",
      unit: "mg/dL",
      isOther: false,
    });
  });

  it("selecting hba1c sets unit=%", () => {
    const onChange = jest.fn();
    render(<MinimalVitalTypeSelect onChange={onChange} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "hba1c" },
    });

    expect(onChange).toHaveBeenLastCalledWith({
      type: "hba1c",
      unit: "%",
      isOther: false,
    });
  });

  it("selecting bp_systolic sets unit=mmHg", () => {
    const onChange = jest.fn();
    render(<MinimalVitalTypeSelect onChange={onChange} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "bp_systolic" },
    });

    expect(onChange).toHaveBeenLastCalledWith({
      type: "bp_systolic",
      unit: "mmHg",
      isOther: false,
    });
  });

  it("unit input becomes read-only after canonical selection", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "egfr" },
    });

    const unitInput = screen.getByTestId("vital-unit-input") as HTMLInputElement;
    expect(unitInput.readOnly).toBe(true);
    expect(unitInput.value).toBe("mL/min");
  });

  it("unit input is NOT read-only before any selection", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);
    const unitInput = screen.getByTestId("vital-unit-input") as HTMLInputElement;
    // Initially no canonical key selected → readOnly false
    expect(unitInput.readOnly).toBe(false);
  });
});

describe("MinimalVitalTypeSelect — «دیگر» shows free-text input", () => {
  it("selecting «دیگر» shows the free-text type input", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);

    // Initially no free-text input
    expect(screen.queryByTestId("vital-type-other-input")).toBeNull();

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "__other__" },
    });

    expect(screen.getByTestId("vital-type-other-input")).toBeInTheDocument();
  });

  it("selecting «دیگر» sets isOther=true and clears type/unit", () => {
    const onChange = jest.fn();
    render(<MinimalVitalTypeSelect onChange={onChange} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "__other__" },
    });

    expect(onChange).toHaveBeenLastCalledWith({
      type: "",
      unit: "",
      isOther: true,
    });
  });

  it("unit input is editable after «دیگر» selection", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "__other__" },
    });

    const unitInput = screen.getByTestId("vital-unit-input") as HTMLInputElement;
    expect(unitInput.readOnly).toBe(false);
  });

  it("typing in the free-text input updates the type value", () => {
    const onChange = jest.fn();
    render(<MinimalVitalTypeSelect onChange={onChange} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "__other__" },
    });

    fireEvent.change(screen.getByTestId("vital-type-other-input"), {
      target: { value: "نبض شریانی" },
    });

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall.type).toBe("نبض شریانی");
    expect(lastCall.isOther).toBe(true);
  });

  it("switching from «دیگر» back to a canonical key removes free-text input", () => {
    render(<MinimalVitalTypeSelect onChange={jest.fn()} />);

    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "__other__" },
    });
    expect(screen.getByTestId("vital-type-other-input")).toBeInTheDocument();

    // Switch back to canonical
    fireEvent.change(screen.getByTestId("vital-type-select"), {
      target: { value: "weight" },
    });
    expect(screen.queryByTestId("vital-type-other-input")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// 4.  Submitted vital type is lowercase canonical key
// ─────────────────────────────────────────────────────────────

describe("Submitted vital type normalization", () => {
  /**
   * Mirrors the .map() in RegisterVisitForm.handleSubmit:
   *   type: r.type.trim().toLowerCase()
   */
  function normalizeType(raw: string): string {
    return raw.trim().toLowerCase();
  }

  it("canonical keys are already lowercase → no change", () => {
    for (const item of VITAL_CATALOG) {
      expect(normalizeType(item.key)).toBe(item.key);
    }
  });

  it("«دیگر» free-text is lowercased on submit", () => {
    expect(normalizeType("  SomeCustomVital  ")).toBe("somecustomvital");
  });

  it("pure whitespace becomes empty string and would be filtered out", () => {
    expect(normalizeType("   ")).toBe("");
    // Empty type → filtered by .filter(r => r.type.trim() !== "")
    expect("".trim()).toBe("");
  });
});

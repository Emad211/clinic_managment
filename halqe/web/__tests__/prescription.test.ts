/**
 * Tests for the free-prescription write path (Step 31).
 *
 * Covers:
 *   1. apiAddPrescription — correct POST body, URL, and response parsing.
 *   2. ALLOWED_FREQUENCIES / ALLOWED_ROUTES — exact canonical sets from models.py.
 *   3. FREQUENCY_LABEL / ROUTE_LABEL — Persian labels present for every canonical value.
 *   4. errorMessageFromCode — 'insurance_prescription_not_supported' maps to Persian.
 *   5. Hard-block validation helpers — drug_name empty / quantity ≤ 0.
 *   6. mode is always "free" in the outgoing body.
 *   7. 422 (insurance_prescription_not_supported) → Persian error message.
 */

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

import {
  ALLOWED_FREQUENCIES,
  ALLOWED_ROUTES,
  FREQUENCY_LABEL,
  ROUTE_LABEL,
  errorMessageFromCode,
  ApiError,
  type PrescriptionFrequency,
  type PrescriptionRoute,
} from "../src/lib/api";

// ────────────────────────────────────────────────────────────
// 1. ALLOWED_FREQUENCIES — must match PrescriptionItem.ALLOWED_FREQUENCIES
//    in clinical/models.py (frozenset from FREQUENCY_CHOICES, lines 769-781).
// ────────────────────────────────────────────────────────────

describe("ALLOWED_FREQUENCIES — canonical set (models.py)", () => {
  const EXPECTED_FROM_MODELS_PY = [
    "od", "bid", "tid", "qid", "qod",
    "weekly", "monthly", "prn", "with_meal", "bedtime", "other",
  ];

  test("contains all 11 values from models.py FREQUENCY_CHOICES", () => {
    const set = new Set(ALLOWED_FREQUENCIES);
    for (const v of EXPECTED_FROM_MODELS_PY) {
      expect(set.has(v as PrescriptionFrequency)).toBe(true);
    }
    expect(ALLOWED_FREQUENCIES.length).toBe(EXPECTED_FROM_MODELS_PY.length);
  });

  test("does not contain values not in models.py", () => {
    const set = new Set(ALLOWED_FREQUENCIES);
    expect(set.has("daily" as PrescriptionFrequency)).toBe(false);
    expect(set.has("twice_daily" as PrescriptionFrequency)).toBe(false);
    expect(set.has("qhs" as PrescriptionFrequency)).toBe(false);
  });
});

// ────────────────────────────────────────────────────────────
// 2. ALLOWED_ROUTES — must match PrescriptionItem.ALLOWED_ROUTES
//    in clinical/models.py (frozenset from ROUTE_CHOICES, lines 783-792).
// ────────────────────────────────────────────────────────────

describe("ALLOWED_ROUTES — canonical set (models.py)", () => {
  const EXPECTED_FROM_MODELS_PY = [
    "oral", "sublingual", "sc", "im", "iv",
    "topical", "inhaled", "other",
  ];

  test("contains all 8 values from models.py ROUTE_CHOICES", () => {
    const set = new Set(ALLOWED_ROUTES);
    for (const v of EXPECTED_FROM_MODELS_PY) {
      expect(set.has(v as PrescriptionRoute)).toBe(true);
    }
    expect(ALLOWED_ROUTES.length).toBe(EXPECTED_FROM_MODELS_PY.length);
  });

  test("does not contain values not in models.py", () => {
    const set = new Set(ALLOWED_ROUTES);
    expect(set.has("nasal" as PrescriptionRoute)).toBe(false);
    expect(set.has("rectal" as PrescriptionRoute)).toBe(false);
    expect(set.has("transdermal" as PrescriptionRoute)).toBe(false);
  });
});

// ────────────────────────────────────────────────────────────
// 3. FREQUENCY_LABEL — Persian label for every canonical key
// ────────────────────────────────────────────────────────────

describe("FREQUENCY_LABEL — Persian label coverage", () => {
  test("every ALLOWED_FREQUENCIES value has a non-empty Persian label", () => {
    for (const f of ALLOWED_FREQUENCIES) {
      expect(FREQUENCY_LABEL[f]).toBeTruthy();
      // Must be non-empty string
      expect(typeof FREQUENCY_LABEL[f]).toBe("string");
      expect(FREQUENCY_LABEL[f].length).toBeGreaterThan(0);
    }
  });

  test("od → یک‌بار روزانه", () => {
    expect(FREQUENCY_LABEL["od"]).toBe("یک‌بار روزانه");
  });

  test("bid → دوبار روزانه", () => {
    expect(FREQUENCY_LABEL["bid"]).toBe("دوبار روزانه");
  });

  test("prn → در صورت نیاز", () => {
    expect(FREQUENCY_LABEL["prn"]).toBe("در صورت نیاز");
  });

  test("with_meal → با غذا", () => {
    expect(FREQUENCY_LABEL["with_meal"]).toBe("با غذا");
  });

  test("bedtime → قبل از خواب", () => {
    expect(FREQUENCY_LABEL["bedtime"]).toBe("قبل از خواب");
  });
});

// ────────────────────────────────────────────────────────────
// 4. ROUTE_LABEL — Persian label for every canonical route
// ────────────────────────────────────────────────────────────

describe("ROUTE_LABEL — Persian label coverage", () => {
  test("every ALLOWED_ROUTES value has a non-empty Persian label", () => {
    for (const r of ALLOWED_ROUTES) {
      expect(ROUTE_LABEL[r]).toBeTruthy();
      expect(typeof ROUTE_LABEL[r]).toBe("string");
      expect(ROUTE_LABEL[r].length).toBeGreaterThan(0);
    }
  });

  test("oral → خوراکی", () => { expect(ROUTE_LABEL["oral"]).toBe("خوراکی"); });
  test("sublingual → زیرزبانی", () => { expect(ROUTE_LABEL["sublingual"]).toBe("زیرزبانی"); });
  test("sc → زیرپوستی", () => { expect(ROUTE_LABEL["sc"]).toBe("زیرپوستی"); });
  test("im → عضلانی", () => { expect(ROUTE_LABEL["im"]).toBe("عضلانی"); });
  test("iv → وریدی", () => { expect(ROUTE_LABEL["iv"]).toBe("وریدی"); });
  test("topical → موضعی", () => { expect(ROUTE_LABEL["topical"]).toBe("موضعی"); });
  test("inhaled → تنفسی", () => { expect(ROUTE_LABEL["inhaled"]).toBe("تنفسی"); });
  test("other → سایر", () => { expect(ROUTE_LABEL["other"]).toBe("سایر"); });
});

// ────────────────────────────────────────────────────────────
// 5. errorMessageFromCode — insurance_prescription_not_supported
// ────────────────────────────────────────────────────────────

describe("errorMessageFromCode — prescription codes", () => {
  test("insurance_prescription_not_supported → Persian message containing 'بیمه'", () => {
    const msg = errorMessageFromCode("insurance_prescription_not_supported", "fallback");
    expect(msg).toContain("بیمه");
    expect(msg).not.toBe("fallback");
  });

  test("validation_error → message about invalid data", () => {
    const msg = errorMessageFromCode("validation_error", "fallback");
    expect(msg).toContain("معتبر");
  });
});

// ────────────────────────────────────────────────────────────
// 6. apiAddPrescription — POST body, URL, mode always "free"
// ────────────────────────────────────────────────────────────

describe("apiAddPrescription", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    localStorageMock.setItem("halqe_token", "mock-bearer-token");
  });

  const MOCK_RX_OUT = {
    id: 5,
    tenant_id: 1,
    patient_link_id: 42,
    encounter_id: 7,
    kind: "outpatient",
    mode: "free",
    prescriber_user_id: null,
    followup_task_id: null,
    issued_at: "2026-06-25T10:00:00+03:30",
    items_structured: [
      {
        id: 10,
        tenant_id: 1,
        prescription_id: 5,
        drug_name: "متفورمین",
        drug_class: "biguanide",
        dose_value: 1000.0,
        dose_unit: "mg",
        frequency: "bid",
        route: "oral",
        quantity: 60,
        duration_days: 30,
        instructions: "با غذا مصرف شود",
      },
    ],
  };

  test("POSTs to /encounters/{id}/prescriptions with correct body", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_RX_OUT,
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    const result = await apiAddPrescription(7, {
      kind: "outpatient",
      items: [
        {
          drug_name: "متفورمین",
          drug_class: "biguanide",
          dose_value: 1000,
          dose_unit: "mg",
          frequency: "bid",
          route: "oral",
          quantity: 60,
          duration_days: 30,
          instructions: "با غذا مصرف شود",
        },
      ],
      mode: "free",
    });

    expect(result.id).toBe(5);
    expect(result.mode).toBe("free");
    expect(result.kind).toBe("outpatient");
    expect(result.items_structured).toHaveLength(1);
    expect(result.items_structured[0].drug_name).toBe("متفورمین");
    expect(result.items_structured[0].frequency).toBe("bid");
    expect(result.items_structured[0].route).toBe("oral");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain("/encounters/7/prescriptions");
    expect(options.method).toBe("POST");
    expect(body.mode).toBe("free");
    expect(body.kind).toBe("outpatient");
    expect(body.items).toHaveLength(1);
    expect(body.items[0].drug_name).toBe("متفورمین");
    expect(body.items[0].frequency).toBe("bid");
    expect(body.items[0].route).toBe("oral");
    expect(body.items[0].quantity).toBe(60);

    const headers = options.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });

  test("mode is always 'free' — cannot send 'insurance'", async () => {
    // This test is a compile-time guard: the type system only allows mode: "free".
    // At runtime we also verify the outgoing body has mode=free.
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_RX_OUT,
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    await apiAddPrescription(7, {
      kind: "outpatient",
      items: [{ drug_name: "Test Drug" }],
      mode: "free",
    });

    const body = JSON.parse(
      ((globalThis.fetch as jest.Mock).mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.mode).toBe("free");
    expect(body.mode).not.toBe("insurance");
  });

  test("throws ApiError(422) when server returns insurance_prescription_not_supported", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({
        detail: "Insurance prescription not supported.",
        code: "insurance_prescription_not_supported",
      }),
    }) as jest.Mock;

    const { apiAddPrescription, ApiError: AE } = await import("../src/lib/api");
    let caught: InstanceType<typeof AE> | null = null;
    try {
      await apiAddPrescription(7, {
        kind: "outpatient",
        items: [{ drug_name: "Test" }],
        mode: "free",
      });
    } catch (err) {
      if (err instanceof AE) caught = err;
    }
    expect(caught).not.toBeNull();
    expect(caught!.status).toBe(422);
    expect(caught!.code).toBe("insurance_prescription_not_supported");
    // Verify the error code maps to Persian message
    expect(errorMessageFromCode(caught!.code, "fallback")).toContain("بیمه");
  });

  test("throws ApiError(409) on encounter_sealed", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "Encounter is sealed.", code: "encounter_sealed" }),
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    await expect(
      apiAddPrescription(7, { kind: "outpatient", items: [{ drug_name: "Drug" }], mode: "free" }),
    ).rejects.toMatchObject({ status: 409, code: "encounter_sealed" });
  });

  test("throws ApiError(422) on validation_error (bad frequency)", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({
        detail: "frequency 'invalid_freq' not in allowed set",
        code: "validation_error",
      }),
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    await expect(
      apiAddPrescription(7, { kind: "outpatient", items: [{ drug_name: "Drug" }], mode: "free" }),
    ).rejects.toMatchObject({ status: 422, code: "validation_error" });
  });

  test("throws ApiError(404) when encounter not found", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "Encounter not found.", code: "not_found" }),
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    await expect(
      apiAddPrescription(999, { kind: "outpatient", items: [{ drug_name: "Drug" }], mode: "free" }),
    ).rejects.toMatchObject({ status: 404 });
  });

  test("sends only drug_name when all other fields are null/omitted", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...MOCK_RX_OUT,
        items_structured: [
          {
            id: 11,
            tenant_id: 1,
            prescription_id: 5,
            drug_name: "آسپرین",
            drug_class: null,
            dose_value: null,
            dose_unit: null,
            frequency: null,
            route: null,
            quantity: null,
            duration_days: null,
            instructions: null,
          },
        ],
      }),
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    const result = await apiAddPrescription(7, {
      kind: "outpatient",
      items: [{ drug_name: "آسپرین" }],
      mode: "free",
    });

    expect(result.items_structured[0].drug_name).toBe("آسپرین");
    expect(result.items_structured[0].frequency).toBeNull();
    expect(result.items_structured[0].route).toBeNull();

    const body = JSON.parse(
      ((globalThis.fetch as jest.Mock).mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.items[0].drug_name).toBe("آسپرین");
    // Other fields should be undefined (omitted) or null — not required
  });

  test("attaches Bearer token in Authorization header", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_RX_OUT,
    }) as jest.Mock;

    const { apiAddPrescription } = await import("../src/lib/api");
    await apiAddPrescription(7, {
      kind: "outpatient",
      items: [{ drug_name: "Drug" }],
      mode: "free",
    });

    const headers = (globalThis.fetch as jest.Mock).mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });
});

// ────────────────────────────────────────────────────────────
// 7. Front-end validation helpers (mirrors RegisterVisitForm logic)
// ────────────────────────────────────────────────────────────

describe("prescription front-end validation helpers", () => {
  /**
   * Mirrors the hard-block validation logic in RegisterVisitForm.handleSubmit:
   * - Empty drug_name → block
   * - quantity ≤ 0 → block
   * - duration_days ≤ 0 → block
   */

  type RxRowForValidation = {
    drug_name: string;
    quantity: string;
    duration_days: string;
  };

  function validateRxRows(rows: RxRowForValidation[]): string | null {
    // Hard block 1: empty drug_name
    if (rows.some((r) => r.drug_name.trim() === "")) {
      return "نام دارو خالی است";
    }
    // Hard block 2: quantity or duration_days invalid if provided
    const invalidNum = rows.find(
      (r) =>
        (r.quantity.trim() !== "" && (parseInt(r.quantity) <= 0 || isNaN(parseInt(r.quantity)))) ||
        (r.duration_days.trim() !== "" && (parseInt(r.duration_days) <= 0 || isNaN(parseInt(r.duration_days)))),
    );
    if (invalidNum) {
      return "تعداد یا مدت مصرف باید عدد مثبت باشد";
    }
    return null; // valid
  }

  test("empty drug_name → hard block", () => {
    expect(validateRxRows([{ drug_name: "", quantity: "30", duration_days: "30" }])).toBe("نام دارو خالی است");
  });

  test("whitespace-only drug_name → hard block", () => {
    expect(validateRxRows([{ drug_name: "   ", quantity: "30", duration_days: "30" }])).toBe("نام دارو خالی است");
  });

  test("quantity = 0 → hard block", () => {
    expect(validateRxRows([{ drug_name: "Drug", quantity: "0", duration_days: "30" }])).toBe(
      "تعداد یا مدت مصرف باید عدد مثبت باشد",
    );
  });

  test("quantity = -5 → hard block", () => {
    expect(validateRxRows([{ drug_name: "Drug", quantity: "-5", duration_days: "30" }])).toBe(
      "تعداد یا مدت مصرف باید عدد مثبت باشد",
    );
  });

  test("duration_days = 0 → hard block", () => {
    expect(validateRxRows([{ drug_name: "Drug", quantity: "30", duration_days: "0" }])).toBe(
      "تعداد یا مدت مصرف باید عدد مثبت باشد",
    );
  });

  test("valid row with all fields → no error", () => {
    expect(
      validateRxRows([{ drug_name: "متفورمین", quantity: "60", duration_days: "30" }]),
    ).toBeNull();
  });

  test("valid row with empty quantity and duration (optional) → no error", () => {
    expect(validateRxRows([{ drug_name: "متفورمین", quantity: "", duration_days: "" }])).toBeNull();
  });

  test("multiple rows — error if ANY row has empty drug_name", () => {
    expect(
      validateRxRows([
        { drug_name: "متفورمین", quantity: "60", duration_days: "30" },
        { drug_name: "", quantity: "", duration_days: "" },
      ]),
    ).toBe("نام دارو خالی است");
  });

  test("empty rows array → no error (nothing to validate)", () => {
    expect(validateRxRows([])).toBeNull();
  });
});

/**
 * Unit tests for the API client lib (src/lib/api.ts).
 * Uses a mocked fetch — no real network calls.
 */

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
});

import { saveToken, getToken, clearToken, ApiError } from "../src/lib/api";

// ────────────────────────────────────────────────────────────
// Token helpers
// ────────────────────────────────────────────────────────────

describe("token storage", () => {
  beforeEach(() => localStorageMock.clear());

  test("getToken returns null when nothing is stored", () => {
    expect(getToken()).toBeNull();
  });

  test("saveToken + getToken round-trips correctly", () => {
    saveToken("test-jwt-token-abc123");
    expect(getToken()).toBe("test-jwt-token-abc123");
  });

  test("clearToken removes the token", () => {
    saveToken("some-token");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

// ────────────────────────────────────────────────────────────
// apiLogin — fetch mock
// ────────────────────────────────────────────────────────────

describe("apiLogin", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
  });

  test("returns token on 200", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ token: "eyJhbGciOiJIUzI1NiJ9.test" }),
    }) as jest.Mock;

    // Import dynamically so fetch mock is in place
    const { apiLogin } = await import("../src/lib/api");
    const result = await apiLogin("admin", "admin");
    expect(result.token).toBe("eyJhbGciOiJIUzI1NiJ9.test");
  });

  test("throws ApiError with status 401 on wrong credentials", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Invalid credentials" }),
    }) as jest.Mock;

    const { apiLogin } = await import("../src/lib/api");
    await expect(apiLogin("bad", "creds")).rejects.toBeInstanceOf(ApiError);
    await expect(apiLogin("bad", "creds")).rejects.toMatchObject({
      status: 401,
    });
  });
});

// ────────────────────────────────────────────────────────────
// apiGetPatients — fetch mock
// ────────────────────────────────────────────────────────────

describe("apiGetPatients", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("returns patient list on 200", async () => {
    const mockPayload = {
      items: [
        {
          link_id: 1,
          patient_id: 1,
          is_active: true,
          enrolled_at: "2024-06-01T10:00:00+03:30",
          full_name: "نمونه ۱ - کنترل خوب",
          national_id: "TEST0001",
          phone_number: "09120000001",
          patient_uuid: "abc-123",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockPayload,
    }) as jest.Mock;

    const { apiGetPatients } = await import("../src/lib/api");
    const result = await apiGetPatients(20, 0);
    expect(result.total).toBe(1);
    expect(result.items[0].national_id).toBe("TEST0001");
    expect(result.items[0].full_name).toBe("نمونه ۱ - کنترل خوب");
  });

  test("attaches Authorization header with Bearer token", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetPatients } = await import("../src/lib/api");
    await apiGetPatients();

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const headers = callArgs[1]?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });
});

// ────────────────────────────────────────────────────────────
// apiGetRecord
// ────────────────────────────────────────────────────────────

describe("apiGetRecord", () => {
  const TEST_UUID = "11111111-2222-3333-4444-555555555555";

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("parses ClinicalRecordDTO correctly on 200", async () => {
    const mockRecord = {
      patient_link_id: 42,
      demographics: {
        id: 7,
        uuid: TEST_UUID,
        name: "علی",
        family_name: "رضایی",
        full_name: "علی رضایی",
        national_id: "TEST0001",
        phone_number: "09120000001",
        birthdate: "1970-03-15",
        gender: "M",
      },
      active_conditions: [
        {
          id: 1,
          condition_id: 10,
          condition_name: "دیابت نوع ۲",
          condition_code: "DM",
          stage: null,
          onset_date: "2015-06-01",
          notes: null,
          is_active: true,
          diagnosed_at: "2024-01-01T10:00:00+03:30",
        },
      ],
      active_medications: [
        {
          id: 5,
          drug_name: "متفورمین",
          dose: "1000mg",
          schedule: "دو بار در روز",
          start_date: "2024-01-10",
          refill_due_date: null,
          drug_class: "biguanide",
          is_active: true,
          notes: null,
          created_at: "2024-01-10T09:00:00+03:30",
        },
      ],
      recent_vitals: [
        {
          id: 99,
          patient_link_id: 42,
          type: "FBS",
          value: 188.0,
          unit: "mg/dL",
          measured_at: "2024-06-01T08:30:00+03:30",
          source: "lab",
          notes: null,
        },
      ],
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRecord,
    }) as jest.Mock;

    const { apiGetRecord } = await import("../src/lib/api");
    const result = await apiGetRecord(TEST_UUID);

    expect(result.patient_link_id).toBe(42);
    expect(result.demographics?.full_name).toBe("علی رضایی");
    expect(result.demographics?.national_id).toBe("TEST0001");
    expect(result.active_conditions).toHaveLength(1);
    expect(result.active_conditions[0].condition_code).toBe("DM");
    expect(result.active_medications).toHaveLength(1);
    expect(result.active_medications[0].drug_name).toBe("متفورمین");
    expect(result.recent_vitals).toHaveLength(1);
    expect(result.recent_vitals[0].value).toBe(188.0);
  });

  test("attaches Bearer token in Authorization header", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        patient_link_id: 1,
        demographics: null,
        active_conditions: [],
        active_medications: [],
        recent_vitals: [],
      }),
    }) as jest.Mock;

    const { apiGetRecord } = await import("../src/lib/api");
    await apiGetRecord(TEST_UUID);

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const headers = callArgs[1]?.headers as Record<string, string>;

    expect(url).toContain(`/patients/${TEST_UUID}/record`);
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });

  test("throws ApiError(401) on unauthorized", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Authentication required" }),
    }) as jest.Mock;

    const { apiGetRecord } = await import("../src/lib/api");
    await expect(apiGetRecord(TEST_UUID)).rejects.toMatchObject({ status: 401 });
  });
});

// ────────────────────────────────────────────────────────────
// apiGetSuggestions
// ────────────────────────────────────────────────────────────

describe("apiGetSuggestions", () => {
  const TEST_UUID = "11111111-2222-3333-4444-555555555555";

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("parses SuggestionsResponseDTO correctly on 200", async () => {
    const mockSuggestions = {
      patient_link_id: 42,
      count: 2,
      has_redflag: true,
      framing: "پیشنهاد — تأیید با پزشک",
      sections: [
        {
          key: "redflags",
          label: "پرچم‌های قرمز",
          rules: [
            {
              rule_code: "T2-RF-001",
              title: "HbA1c بالاتر از ۱۰٪",
              category: "glycemic",
              condition_code: "DM",
              recommendation: "بررسی دوز انسولین",
              dosage_titration: null,
              monitoring: null,
              contraindications: null,
              evidence_level: "A",
              action_type: "urgent_review",
              severity: "urgent",
              priority: 1,
              source_ref: null,
              section: "redflags",
              suggestion_only: true,
            },
          ],
        },
        {
          key: "treatment",
          label: "درمان",
          rules: [
            {
              rule_code: "T2-TX-010",
              title: "اضافه کردن GLP-1",
              category: "treatment",
              condition_code: "DM",
              recommendation: "در صورت BMI بالا بررسی شود",
              dosage_titration: null,
              monitoring: null,
              contraindications: null,
              evidence_level: "B",
              action_type: "add_drug",
              severity: "warn",
              priority: 5,
              source_ref: null,
              section: "treatment",
              suggestion_only: true,
            },
          ],
        },
      ],
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockSuggestions,
    }) as jest.Mock;

    const { apiGetSuggestions } = await import("../src/lib/api");
    const result = await apiGetSuggestions(TEST_UUID);

    expect(result.count).toBe(2);
    expect(result.has_redflag).toBe(true);
    expect(result.framing).toBe("پیشنهاد — تأیید با پزشک");
    expect(result.sections).toHaveLength(2);
    expect(result.sections[0].key).toBe("redflags");
    expect(result.sections[0].rules[0].rule_code).toBe("T2-RF-001");
    expect(result.sections[0].rules[0].suggestion_only).toBe(true);
    expect(result.sections[0].rules[0].severity).toBe("urgent");
    expect(result.sections[1].rules[0].rule_code).toBe("T2-TX-010");
  });

  test("attaches Bearer token and hits the correct URL", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        patient_link_id: 1,
        count: 0,
        has_redflag: false,
        framing: "پیشنهاد — تأیید با پزشک",
        sections: [],
      }),
    }) as jest.Mock;

    const { apiGetSuggestions } = await import("../src/lib/api");
    await apiGetSuggestions(TEST_UUID);

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const headers = callArgs[1]?.headers as Record<string, string>;

    expect(url).toContain(`/patients/${TEST_UUID}/suggestions`);
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });
});

// ────────────────────────────────────────────────────────────
// apiSuggestionAction
// ────────────────────────────────────────────────────────────

describe("apiSuggestionAction", () => {
  const TEST_UUID = "11111111-2222-3333-4444-555555555555";
  const RULE_CODE = "T2-RF-001";

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("POSTs the correct body for accept action", async () => {
    const mockLog = {
      id: 10,
      patient_link_id: 42,
      tenant_id: 1,
      rule_code: RULE_CODE,
      status: "accepted",
      acted_by: "admin",
      acted_at: "2024-06-01T10:00:00+03:30",
      note: null,
      created_at: "2024-06-01T10:00:00+03:30",
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockLog,
    }) as jest.Mock;

    const { apiSuggestionAction } = await import("../src/lib/api");
    const result = await apiSuggestionAction(TEST_UUID, RULE_CODE, "accept");

    expect(result.status).toBe("accepted");
    expect(result.rule_code).toBe(RULE_CODE);

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain(`/patients/${TEST_UUID}/suggestions/${RULE_CODE}/action`);
    expect(options.method).toBe("POST");
    expect(body.action).toBe("accept");
    expect(body.note).toBeNull();

    const headers = options.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });

  test("POSTs the correct body for dismiss action with note", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 11,
        patient_link_id: 42,
        tenant_id: 1,
        rule_code: RULE_CODE,
        status: "dismissed",
        acted_by: "admin",
        acted_at: "2024-06-01T10:01:00+03:30",
        note: "بیمار نمی‌تواند دارو را تحمل کند",
        created_at: "2024-06-01T10:01:00+03:30",
      }),
    }) as jest.Mock;

    const { apiSuggestionAction } = await import("../src/lib/api");
    const result = await apiSuggestionAction(
      TEST_UUID,
      RULE_CODE,
      "dismiss",
      "بیمار نمی‌تواند دارو را تحمل کند",
    );

    expect(result.status).toBe("dismissed");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const body = JSON.parse((callArgs[1] as RequestInit).body as string);
    expect(body.action).toBe("dismiss");
    expect(body.note).toBe("بیمار نمی‌تواند دارو را تحمل کند");
  });

  test("URL-encodes rule_code in the path", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 12,
        patient_link_id: 42,
        tenant_id: 1,
        rule_code: "T2-RF/001",
        status: "accepted",
        acted_by: "admin",
        acted_at: "2024-06-01T10:00:00+03:30",
        note: null,
        created_at: "2024-06-01T10:00:00+03:30",
      }),
    }) as jest.Mock;

    const { apiSuggestionAction } = await import("../src/lib/api");
    await apiSuggestionAction(TEST_UUID, "T2-RF/001", "accept");

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    // slash must be encoded
    expect(url).toContain("T2-RF%2F001");
  });

  test("throws ApiError(400) on invalid action response", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: async () => ({ detail: "Invalid action" }),
    }) as jest.Mock;

    const { apiSuggestionAction } = await import("../src/lib/api");
    await expect(
      apiSuggestionAction(TEST_UUID, RULE_CODE, "accept"),
    ).rejects.toMatchObject({ status: 400 });
  });
});

// ────────────────────────────────────────────────────────────
// apiGetWorklist
// ────────────────────────────────────────────────────────────

describe("apiGetWorklist", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  const MOCK_ITEM = {
    id: 7,
    patient_uuid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    patient_full_name: "علی رضایی",
    kind: "lab_review",
    reason: "lab_review",
    due_date: "2026-06-20",
    status: "open",
    fulfillment: null,
    created_at: "2026-06-10T09:00:00+03:30",
    resolved_at: null,
  };

  test("parses WorklistResponseDTO correctly on 200", async () => {
    const mockPayload = {
      items: [MOCK_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockPayload,
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    const result = await apiGetWorklist({ limit: 20, offset: 0 });

    expect(result.total).toBe(1);
    expect(result.items).toHaveLength(1);
    expect(result.items[0].id).toBe(7);
    expect(result.items[0].patient_full_name).toBe("علی رضایی");
    expect(result.items[0].status).toBe("open");
    expect(result.items[0].due_date).toBe("2026-06-20");
  });

  test("attaches Authorization header with Bearer token", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await apiGetWorklist();

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const headers = callArgs[1]?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });

  test("passes status filter as query param when provided", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await apiGetWorklist({ status: "done", limit: 20, offset: 0 });

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).toContain("status=done");
    expect(url).toContain("/worklist");
  });

  test("omits status param when not provided (uses backend default)", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await apiGetWorklist({ limit: 20, offset: 0 });

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).not.toContain("status=");
  });

  test("returns empty items array when worklist is empty", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    const result = await apiGetWorklist();
    expect(result.items).toHaveLength(0);
    expect(result.total).toBe(0);
  });

  test("throws ApiError(401) when token missing or expired", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Authentication required" }),
    }) as jest.Mock;

    const { apiGetWorklist } = await import("../src/lib/api");
    await expect(apiGetWorklist()).rejects.toMatchObject({ status: 401 });
  });
});

// ────────────────────────────────────────────────────────────
// apiMarkDone
// ────────────────────────────────────────────────────────────

describe("apiMarkDone", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  const MOCK_TASK = {
    id: 7,
    patient_link_id: 42,
    tenant_id: 1,
    reason: "lab_review",
    detail: null,
    due_date: "2026-06-20",
    status: "done",
    fulfillment: null,
    source_rule: null,
    source_event: null,
    created_at: "2026-06-10T09:00:00+03:30",
    resolved_at: "2026-06-24T10:00:00+03:30",
  };

  test("POSTs to /worklist/{id}/done and returns FollowupTaskDTO", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_TASK,
    }) as jest.Mock;

    const { apiMarkDone } = await import("../src/lib/api");
    const result = await apiMarkDone(7);

    expect(result.id).toBe(7);
    expect(result.status).toBe("done");
    expect(result.resolved_at).toBe("2026-06-24T10:00:00+03:30");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;

    expect(url).toContain("/worklist/7/done");
    expect(options.method).toBe("POST");
    const headers = options.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });

  test("throws ApiError(404) when task does not exist for tenant", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "FollowupTask id=99 not found for this tenant." }),
    }) as jest.Mock;

    const { apiMarkDone } = await import("../src/lib/api");
    await expect(apiMarkDone(99)).rejects.toMatchObject({ status: 404 });
  });

  test("throws ApiError(409) when task is already done", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({
        detail: "Task id=7 is already 'done'; only open tasks can be marked done.",
      }),
    }) as jest.Mock;

    const { apiMarkDone } = await import("../src/lib/api");
    await expect(apiMarkDone(7)).rejects.toMatchObject({ status: 409 });
  });

  test("throws ApiError(401) when unauthenticated", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Authentication required" }),
    }) as jest.Mock;

    const { apiMarkDone } = await import("../src/lib/api");
    await expect(apiMarkDone(7)).rejects.toMatchObject({ status: 401 });
  });
});

// ────────────────────────────────────────────────────────────
// apiCreateEncounter
// ────────────────────────────────────────────────────────────

describe("apiCreateEncounter", () => {
  const TEST_UUID = "11111111-2222-3333-4444-555555555555";

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  const MOCK_ENCOUNTER = {
    id: 1,
    tenant_id: 1,
    patient_link_id: 42,
    encounter_type: "visit",
    encounter_at: "2026-06-24T10:00:00+03:30",
    status: "open",
    chief_complaint: "سردرد",
    doctor_id: null,
    appointment_id: null,
    accounting_invoice_id: null,
    completed_at: null,
    summary_note: null,
    created_by: "admin",
    created_at: "2026-06-24T10:00:00+03:30",
    updated_at: "2026-06-24T10:00:00+03:30",
  };

  test("POSTs to /patients/{uuid}/encounters with correct body and returns EncounterOut", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_ENCOUNTER,
    }) as jest.Mock;

    const { apiCreateEncounter } = await import("../src/lib/api");
    const result = await apiCreateEncounter(TEST_UUID, {
      encounter_type: "visit",
      chief_complaint: "سردرد",
    });

    expect(result.id).toBe(1);
    expect(result.status).toBe("open");
    expect(result.chief_complaint).toBe("سردرد");
    expect(result.encounter_type).toBe("visit");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain(`/patients/${TEST_UUID}/encounters`);
    expect(options.method).toBe("POST");
    expect(body.encounter_type).toBe("visit");
    expect(body.chief_complaint).toBe("سردرد");

    const headers = options.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });

  test("throws ApiError with detail message on error response", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "Patient not found for this tenant." }),
    }) as jest.Mock;

    const { apiCreateEncounter, ApiError: AE } = await import("../src/lib/api");
    await expect(
      apiCreateEncounter(TEST_UUID, { encounter_type: "visit" }),
    ).rejects.toBeInstanceOf(AE);
    await expect(
      apiCreateEncounter(TEST_UUID, { encounter_type: "visit" }),
    ).rejects.toMatchObject({ status: 404, message: "Patient not found for this tenant." });
  });
});

// ────────────────────────────────────────────────────────────
// apiAddVitals
// ────────────────────────────────────────────────────────────

describe("apiAddVitals", () => {
  const ENCOUNTER_ID = 7;

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("POSTs list of vitals to /encounters/{id}/vitals and returns count", async () => {
    const mockResponse = {
      count: 2,
      vitals: [
        {
          id: 1,
          patient_link_id: 42,
          encounter_id: ENCOUNTER_ID,
          type: "FBS",
          value: 188.0,
          unit: "mg/dL",
          source: "clinic",
          measured_at: "2026-06-24T10:00:00+03:30",
        },
        {
          id: 2,
          patient_link_id: 42,
          encounter_id: ENCOUNTER_ID,
          type: "BP_SYS",
          value: 135,
          unit: "mmHg",
          source: "clinic",
          measured_at: "2026-06-24T10:00:00+03:30",
        },
      ],
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    }) as jest.Mock;

    const { apiAddVitals } = await import("../src/lib/api");
    const result = await apiAddVitals(ENCOUNTER_ID, [
      { type: "FBS", value: 188.0, unit: "mg/dL" },
      { type: "BP_SYS", value: 135, unit: "mmHg" },
    ]);

    expect(result.count).toBe(2);
    expect(result.vitals).toHaveLength(2);
    expect(result.vitals[0].type).toBe("FBS");
    expect(result.vitals[1].type).toBe("BP_SYS");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain(`/encounters/${ENCOUNTER_ID}/vitals`);
    expect(options.method).toBe("POST");
    expect(Array.isArray(body)).toBe(true);
    expect(body[0].type).toBe("FBS");
    expect(body[0].value).toBe(188.0);
    expect(body[1].unit).toBe("mmHg");
  });

  test("throws ApiError(409) on duplicate_vital", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "duplicate_vital", code: "duplicate_vital" }),
    }) as jest.Mock;

    const { apiAddVitals } = await import("../src/lib/api");
    await expect(
      apiAddVitals(ENCOUNTER_ID, [{ type: "FBS", value: 188 }]),
    ).rejects.toMatchObject({ status: 409 });
  });

  test("throws ApiError(409) on encounter_sealed", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "encounter_sealed", code: "encounter_sealed" }),
    }) as jest.Mock;

    const { apiAddVitals } = await import("../src/lib/api");
    await expect(
      apiAddVitals(ENCOUNTER_ID, [{ type: "FBS", value: 188 }]),
    ).rejects.toMatchObject({ status: 409 });
  });
});

// ────────────────────────────────────────────────────────────
// apiCompleteEncounter
// ────────────────────────────────────────────────────────────

describe("apiCompleteEncounter", () => {
  const ENCOUNTER_ID = 7;

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("POSTs to /encounters/{id}/complete with summary_note and returns completed EncounterOut", async () => {
    const mockCompleted = {
      id: ENCOUNTER_ID,
      tenant_id: 1,
      patient_link_id: 42,
      encounter_type: "visit",
      encounter_at: "2026-06-24T10:00:00+03:30",
      status: "completed",
      chief_complaint: "سردرد",
      doctor_id: null,
      appointment_id: null,
      accounting_invoice_id: null,
      completed_at: "2026-06-24T10:15:00+03:30",
      summary_note: "بیمار در وضعیت مناسب",
      created_by: "admin",
      created_at: "2026-06-24T10:00:00+03:30",
      updated_at: "2026-06-24T10:15:00+03:30",
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockCompleted,
    }) as jest.Mock;

    const { apiCompleteEncounter } = await import("../src/lib/api");
    const result = await apiCompleteEncounter(ENCOUNTER_ID, "بیمار در وضعیت مناسب");

    expect(result.status).toBe("completed");
    expect(result.summary_note).toBe("بیمار در وضعیت مناسب");
    expect(result.completed_at).toBe("2026-06-24T10:15:00+03:30");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain(`/encounters/${ENCOUNTER_ID}/complete`);
    expect(options.method).toBe("POST");
    expect(body.summary_note).toBe("بیمار در وضعیت مناسب");
  });

  test("sends null summary_note when not provided", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: ENCOUNTER_ID,
        status: "completed",
        summary_note: null,
        encounter_type: "visit",
        encounter_at: "2026-06-24T10:00:00+03:30",
        tenant_id: 1,
        patient_link_id: 42,
        chief_complaint: null,
        doctor_id: null,
        appointment_id: null,
        accounting_invoice_id: null,
        completed_at: "2026-06-24T10:15:00+03:30",
        created_by: "admin",
        created_at: "2026-06-24T10:00:00+03:30",
        updated_at: "2026-06-24T10:15:00+03:30",
      }),
    }) as jest.Mock;

    const { apiCompleteEncounter } = await import("../src/lib/api");
    await apiCompleteEncounter(ENCOUNTER_ID);

    const body = JSON.parse(
      ((globalThis.fetch as jest.Mock).mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.summary_note).toBeNull();
  });
});

// ────────────────────────────────────────────────────────────
// apiCancelEncounter
// ────────────────────────────────────────────────────────────

describe("apiCancelEncounter", () => {
  const ENCOUNTER_ID = 7;

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("POSTs to /encounters/{id}/cancel with reason and returns cancelled EncounterOut", async () => {
    const mockCancelled = {
      id: ENCOUNTER_ID,
      tenant_id: 1,
      patient_link_id: 42,
      encounter_type: "visit",
      encounter_at: "2026-06-24T10:00:00+03:30",
      status: "cancelled",
      chief_complaint: null,
      doctor_id: null,
      appointment_id: null,
      accounting_invoice_id: null,
      completed_at: null,
      summary_note: null,
      created_by: "admin",
      created_at: "2026-06-24T10:00:00+03:30",
      updated_at: "2026-06-24T10:20:00+03:30",
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockCancelled,
    }) as jest.Mock;

    const { apiCancelEncounter } = await import("../src/lib/api");
    const result = await apiCancelEncounter(ENCOUNTER_ID, "بیمار نیامد");

    expect(result.status).toBe("cancelled");

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const url: string = callArgs[0];
    const options = callArgs[1] as RequestInit;
    const body = JSON.parse(options.body as string);

    expect(url).toContain(`/encounters/${ENCOUNTER_ID}/cancel`);
    expect(options.method).toBe("POST");
    expect(body.reason).toBe("بیمار نیامد");
  });
});

// ────────────────────────────────────────────────────────────
// apiListEncounters
// ────────────────────────────────────────────────────────────

describe("apiListEncounters", () => {
  const TEST_UUID = "11111111-2222-3333-4444-555555555555";

  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  const MOCK_ENC_1 = {
    id: 3,
    tenant_id: 1,
    patient_link_id: 42,
    encounter_type: "visit",
    encounter_at: "2026-06-24T10:00:00+03:30",
    status: "completed",
    chief_complaint: "کنترل دوره‌ای",
    doctor_id: null,
    appointment_id: null,
    accounting_invoice_id: null,
    completed_at: "2026-06-24T10:30:00+03:30",
    summary_note: null,
    created_by: "admin",
    created_at: "2026-06-24T10:00:00+03:30",
    updated_at: "2026-06-24T10:30:00+03:30",
  };

  test("GETs /patients/{uuid}/encounters and returns EncounterListResponse", async () => {
    const mockPayload = {
      items: [MOCK_ENC_1],
      total: 1,
      limit: 10,
      offset: 0,
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockPayload,
    }) as jest.Mock;

    const { apiListEncounters } = await import("../src/lib/api");
    const result = await apiListEncounters(TEST_UUID);

    expect(result.total).toBe(1);
    expect(result.items).toHaveLength(1);
    expect(result.items[0].id).toBe(3);
    expect(result.items[0].status).toBe("completed");
    expect(result.items[0].chief_complaint).toBe("کنترل دوره‌ای");

    const url: string = (globalThis.fetch as jest.Mock).mock.calls[0][0];
    expect(url).toContain(`/patients/${TEST_UUID}/encounters`);
    expect(url).toContain("limit=10");
    expect(url).toContain("offset=0");
  });

  test("attaches Bearer token and uses GET method (no body)", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 10, offset: 0 }),
    }) as jest.Mock;

    const { apiListEncounters } = await import("../src/lib/api");
    await apiListEncounters(TEST_UUID);

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const headers = callArgs[1]?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
    // GET — apiFetch default method; no explicit method needed
    expect(callArgs[1]?.method).toBeUndefined();
  });

  test("returns empty items array when no encounters", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 10, offset: 0 }),
    }) as jest.Mock;

    const { apiListEncounters } = await import("../src/lib/api");
    const result = await apiListEncounters(TEST_UUID);
    expect(result.items).toHaveLength(0);
    expect(result.total).toBe(0);
  });

  test("throws ApiError(401) when unauthenticated", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Authentication required" }),
    }) as jest.Mock;

    const { apiListEncounters } = await import("../src/lib/api");
    await expect(apiListEncounters(TEST_UUID)).rejects.toMatchObject({ status: 401 });
  });
});

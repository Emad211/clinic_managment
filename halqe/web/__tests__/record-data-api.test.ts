/** API contract tests for the complete specialist patient record. */

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  writable: true,
});

const UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

beforeEach(() => {
  localStorageMock.clear();
  localStorageMock.setItem("halqe_token", "record-test-token");
  jest.resetAllMocks();
});

function okJson(payload: unknown) {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  }) as jest.Mock;
}

test("GETs the complete record and attaches bearer auth", async () => {
  okJson({ condition_catalog: [], conditions: [], surgeries: [], medical_history: [], notes: [], flag_catalog: [], patient_flags: {}, lab_catalog: [], suggested_labs: [], labs: [], indicator_catalog: [], drug_classes: [], drug_catalog: [], medications: [], medication_events: [], appointments: [], prescriptions: [], accounting_visit_history: [] });
  const { apiGetRecordData } = await import("../src/lib/api");
  await apiGetRecordData(UUID);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record-data`);
  expect(options.headers.Authorization).toBe("Bearer record-test-token");
});

test("flags update is PUT and preserves the explicit managed-key contract", async () => {
  okJson({ values: { smoking: "current", eye_exam_date: "2026-01-01" } });
  const { apiUpdateRecordFlags } = await import("../src/lib/api");
  await apiUpdateRecordFlags(UUID, {
    managed_keys: ["smoking", "eye_exam_date"],
    values: { smoking: "current", eye_exam_date: "" },
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/flags`);
  expect(options.method).toBe("PUT");
  expect(JSON.parse(options.body)).toEqual({
    managed_keys: ["smoking", "eye_exam_date"],
    values: { smoking: "current", eye_exam_date: "" },
  });
});

test("bulk labs send only catalog keys, values and notes", async () => {
  okJson({ count: 2, ids: [1, 2] });
  const { apiAddRecordLabs } = await import("../src/lib/api");
  await apiAddRecordLabs(UUID, {
    items: [
      { test_key: "hba1c", value: 7.2, notes: null },
      { test_key: "creatinine", value: 1.1, notes: "ناشتا" },
    ],
    taken_at: "2026-03-01T12:00:00",
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/labs`);
  expect(options.method).toBe("POST");
  const body = JSON.parse(options.body);
  expect(body.items[0]).toEqual({ test_key: "hba1c", value: 7.2, notes: null });
  expect(body.items[0]).not.toHaveProperty("unit");
  expect(body.items[0]).not.toHaveProperty("ref_low");
  expect(body.items[0]).not.toHaveProperty("test_name");
});

test("bulk vitals send indicator keys without a client-supplied unit", async () => {
  okJson({ count: 1, ids: [9] });
  const { apiAddRecordVitals } = await import("../src/lib/api");
  await apiAddRecordVitals(UUID, {
    items: [{ type: "bp_systolic", value: 128, notes: null }],
  });
  const [, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(JSON.parse(options.body).items[0]).toEqual({
    type: "bp_systolic",
    value: 128,
    notes: null,
  });
  expect(JSON.parse(options.body).items[0]).not.toHaveProperty("unit");
});

test("medication lifecycle uses distinct start, dose and stop endpoints", async () => {
  const medication = { id: 12, drug_name: "متفورمین", dose: "500mg", is_active: true };
  okJson(medication);
  const {
    apiAddRecordMedication,
    apiChangeMedicationDose,
    apiStopRecordMedication,
  } = await import("../src/lib/api");

  await apiAddRecordMedication(UUID, {
    drug_id: 3,
    dose: "500mg",
    refill_interval_days: 30,
  });
  await apiChangeMedicationDose(UUID, 12, {
    new_dose: "1000mg",
    change_date: "2026-02-01",
  });
  await apiStopRecordMedication(UUID, 12, { end_date: "2026-03-01" });

  const calls = (globalThis.fetch as jest.Mock).mock.calls;
  expect(calls[0][0]).toContain(`/patients/${UUID}/record/medications`);
  expect(calls[1][0]).toContain(`/patients/${UUID}/record/medications/12/dose`);
  expect(calls[2][0]).toContain(`/patients/${UUID}/record/medications/12/stop`);
  expect(calls.every(([, options]) => options.method === "POST")).toBe(true);
});

test("condition removal and clinical history deletes are scoped under the patient UUID", async () => {
  okJson({ deleted: true, id: 8 });
  const {
    apiRemoveRecordCondition,
    apiDeleteSurgery,
    apiDeleteMedicalHistory,
    apiDeleteClinicalNote,
  } = await import("../src/lib/api");
  await apiRemoveRecordCondition(UUID, 8);
  await apiDeleteSurgery(UUID, 9);
  await apiDeleteMedicalHistory(UUID, 10);
  await apiDeleteClinicalNote(UUID, 11);
  const urls = (globalThis.fetch as jest.Mock).mock.calls.map(([url]) => String(url));
  expect(urls).toEqual(expect.arrayContaining([
    expect.stringContaining(`/patients/${UUID}/record/conditions/8`),
    expect.stringContaining(`/patients/${UUID}/record/surgeries/9`),
    expect.stringContaining(`/patients/${UUID}/record/medical-history/10`),
    expect.stringContaining(`/patients/${UUID}/record/notes/11`),
  ]));
});

test("complete vital history uses GET on the same resource whose POST adds clinic readings", async () => {
  okJson([]);
  const { apiGetRecordVitals } = await import("../src/lib/api");
  await apiGetRecordVitals(UUID);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/vitals`);
  expect(options.method ?? "GET").toBe("GET");
});

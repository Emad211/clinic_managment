import {
  apiAddPatientCondition,
  apiAddPatientLabResult,
  apiAddPatientMedication,
  apiChangePatientMedicationDose,
  apiDeactivatePatientCondition,
  apiGetStructuredPatientRecord,
  apiPatchPatientRecordFlags,
  apiStopPatientMedication,
  saveToken,
} from "../src/lib/api";

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
  writable: true,
});

const UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

function mockJson(payload: unknown) {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  }) as jest.Mock;
}

beforeEach(() => {
  localStorageMock.clear();
  saveToken("record-test-token");
  jest.resetAllMocks();
});

test("loads the structured record with bearer authentication", async () => {
  mockJson({
    patient_link_id: 7,
    condition_catalog: [],
    conditions: [],
    medications: [],
    orphan_medication_events: [],
    flag_catalog: [],
    surgeries: [],
    medical_history: [],
    clinical_notes: [],
    labs: [],
    lab_catalog: [],
    appointments: [],
    followups: [],
    prescriptions: [],
    drug_classes: [],
    drug_catalog: [],
  });

  const result = await apiGetStructuredPatientRecord(UUID);
  expect(result.patient_link_id).toBe(7);
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/structured`);
  expect(options.headers.Authorization).toBe("Bearer record-test-token");
});

test("creates and deactivates a condition through patient-scoped paths", async () => {
  mockJson({
    id: 11,
    condition_id: 3,
    condition_name: "آسم",
    condition_code: "asthma",
    stage: null,
    onset_date: null,
    notes: null,
    is_active: true,
    diagnosed_at: "2026-07-13T10:00:00+03:30",
  });
  await apiAddPatientCondition(UUID, {
    condition_id: 3,
    stage: "mild",
    onset_date: "2024-01-01",
  });
  let [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/conditions`);
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toMatchObject({
    condition_id: 3,
    stage: "mild",
  });

  mockJson({ deleted: true, id: 11 });
  await apiDeactivatePatientCondition(UUID, 11);
  [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/conditions/11`);
  expect(options.method).toBe("DELETE");
});

test("ports the complete medication state machine contract", async () => {
  const medication = {
    id: 31,
    drug_name: "متفورمین",
    dose: "500 mg",
    schedule: "روزی دو بار",
    start_date: "2026-01-01",
    refill_due_date: "2026-01-31",
    end_date: null,
    drug_class: "metformin",
    is_active: true,
    notes: null,
    created_at: "2026-01-01T08:00:00+03:30",
    events: [],
  };
  mockJson(medication);
  await apiAddPatientMedication(UUID, {
    drug_name: "متفورمین",
    dose: "500 mg",
    schedule: "روزی دو بار",
    start_date: "2026-01-01",
    refill_interval_days: 30,
    drug_class: "metformin",
  });
  let [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/medications`);
  expect(JSON.parse(options.body).refill_interval_days).toBe(30);

  mockJson({ ...medication, dose: "1000 mg" });
  await apiChangePatientMedicationDose(UUID, 31, "1000 mg", "2026-01-10", "افزایش");
  [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/record/medications/31/dose`);
  expect(JSON.parse(options.body)).toEqual({
    dose: "1000 mg",
    change_date: "2026-01-10",
    note: "افزایش",
  });

  mockJson({ ...medication, is_active: false, end_date: "2026-01-20" });
  await apiStopPatientMedication(UUID, 31, "2026-01-20", "پایان");
  [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/record/medications/31/stop`);
  expect(JSON.parse(options.body).end_date).toBe("2026-01-20");
});

test("sends partial-safe flags and explicit clear keys", async () => {
  mockJson([]);
  await apiPatchPatientRecordFlags(UUID, {
    values: { risk_flag: true, screening_date: "" },
    clear_keys: ["old_date"],
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/flags`);
  expect(options.method).toBe("PATCH");
  expect(JSON.parse(options.body)).toEqual({
    values: { risk_flag: true, screening_date: "" },
    clear_keys: ["old_date"],
  });
});

test("adds a catalogue lab without fabricating display metadata client-side", async () => {
  mockJson({
    id: 88,
    encounter_id: null,
    test_name: "HbA1c",
    test_key: "hba1c",
    value: 7.2,
    unit: "%",
    ref_low: 4,
    ref_high: 6.5,
    taken_at: "2026-07-13T10:00:00+03:30",
    notes: null,
    recorded_by: "testuser",
  });
  await apiAddPatientLabResult(UUID, {
    test_key: "hba1c",
    value: 7.2,
    notes: null,
  });
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/labs`);
  expect(JSON.parse(options.body)).toEqual({
    test_key: "hba1c",
    value: 7.2,
    notes: null,
  });
});

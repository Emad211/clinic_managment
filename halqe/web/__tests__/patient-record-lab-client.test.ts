import { apiAddPatientLabResult, saveToken } from "../src/lib/api";

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

function mockSuccess() {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      id: 1,
      encounter_id: null,
      test_name: "آزمایش کانونیک",
      test_key: "canonical_test",
      value: 12,
      unit: "mg/dL",
      ref_low: 10,
      ref_high: 20,
      taken_at: "2026-07-13T10:00:00+03:30",
      notes: null,
      recorded_by: "testuser",
    }),
  }) as jest.Mock;
}

beforeEach(() => {
  localStorageMock.clear();
  saveToken("record-lab-test-token");
  jest.resetAllMocks();
  mockSuccess();
});

test("catalog request strips client-supplied name, unit and reference interval", async () => {
  await apiAddPatientLabResult(UUID, {
    test_key: "  canonical_test  ",
    test_name: "نام جعل‌شده",
    value: 12,
    unit: "evil-unit",
    ref_low: -999,
    ref_high: 999,
    taken_at: "2026-07-13T10:00:00+03:30",
    notes: "نمونه",
  });

  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toContain(`/patients/${UUID}/record/labs`);
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual({
    test_key: "canonical_test",
    value: 12,
    taken_at: "2026-07-13T10:00:00+03:30",
    notes: "نمونه",
  });
});

test("free-text request preserves its explicit snapshot metadata", async () => {
  await apiAddPatientLabResult(UUID, {
    test_key: null,
    test_name: "آزمایش آزاد",
    value: 3.25,
    unit: "custom-unit",
    ref_low: 1.5,
    ref_high: 4.5,
    notes: null,
  });

  const [, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(JSON.parse(options.body)).toEqual({
    test_key: null,
    test_name: "آزمایش آزاد",
    value: 3.25,
    unit: "custom-unit",
    ref_low: 1.5,
    ref_high: 4.5,
    notes: null,
  });
});

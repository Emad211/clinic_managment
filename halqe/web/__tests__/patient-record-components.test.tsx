import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { MedicationRecordPanel } from "../src/components/MedicationRecordPanel";
import { StructuredPatientRecordPanel } from "../src/components/StructuredPatientRecordPanel";
import { saveToken, type StructuredPatientRecordDTO } from "../src/lib/api";

const UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

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

const RECORD: StructuredPatientRecordDTO = {
  patient_link_id: 7,
  condition_catalog: [
    {
      id: 11,
      name: "دیابت",
      code: "diabetes",
      description: null,
      icon: null,
      color: null,
      display_order: 10,
    },
  ],
  conditions: [
    {
      id: 21,
      condition_id: 11,
      condition_name: "دیابت",
      condition_code: "diabetes",
      stage: "T2DM",
      onset_date: "2020-01-01",
      notes: null,
      is_active: true,
      diagnosed_at: "2020-01-01T08:00:00+03:30",
    },
  ],
  medications: [
    {
      id: 31,
      drug_name: "متفورمین",
      dose: "500 mg",
      schedule: "روزی دو بار",
      start_date: "2025-01-01",
      refill_due_date: "2025-01-31",
      end_date: null,
      drug_class: "metformin",
      is_active: true,
      notes: null,
      created_at: "2025-01-01T08:00:00+03:30",
      events: [
        {
          id: 32,
          medication_id: 31,
          drug_name: "متفورمین",
          event_type: "start",
          dose: "500 mg",
          event_date: "2025-01-01",
          note: null,
          created_by: "doctor",
          created_at: "2025-01-01T08:00:00+03:30",
        },
      ],
    },
    {
      id: 33,
      drug_name: "داروی قدیمی",
      dose: "1 mg",
      schedule: null,
      start_date: "2023-01-01",
      refill_due_date: null,
      end_date: "2024-01-01",
      drug_class: null,
      is_active: false,
      notes: null,
      created_at: "2023-01-01T08:00:00+03:30",
      events: [],
    },
  ],
  orphan_medication_events: [],
  flag_catalog: [
    {
      id: 41,
      flag_key: "cv_risk",
      label: "ریسک قلبی",
      flag_type: "bool",
      options: [],
      category: "risk",
      record_section: "disease",
      display_order: 10,
      notes: null,
      value: "1",
      recorded_by: "doctor",
      updated_at: "2025-01-01T08:00:00+03:30",
    },
    {
      id: 42,
      flag_key: "risk_level",
      label: "سطح خطر",
      flag_type: "enum",
      options: [
        { value: "low", label: "کم" },
        { value: "high", label: "زیاد" },
      ],
      category: "risk",
      record_section: "disease",
      display_order: 20,
      notes: null,
      value: "low",
      recorded_by: "doctor",
      updated_at: "2025-01-01T08:00:00+03:30",
    },
    {
      id: 43,
      flag_key: "exam_date",
      label: "آخرین معاینه",
      flag_type: "date",
      options: [],
      category: "exam",
      record_section: "exam",
      display_order: 30,
      notes: null,
      value: "2025-02-01",
      recorded_by: "doctor",
      updated_at: "2025-02-01T08:00:00+03:30",
    },
    {
      id: 44,
      flag_key: "general_text",
      label: "شرح عمومی",
      flag_type: "text",
      options: [],
      category: "other",
      record_section: "general",
      display_order: 40,
      notes: null,
      value: "بدون تغییر",
      recorded_by: "doctor",
      updated_at: "2025-01-01T08:00:00+03:30",
    },
  ],
  surgeries: [],
  medical_history: [],
  clinical_notes: [],
  labs: [],
  lab_catalog: [
    {
      id: 51,
      test_key: "hba1c",
      name_fa: "هموگلوبین A1c",
      unit: "%",
      ref_low: 4,
      ref_high: 5.6,
      category: "glycemic",
      display_order: 10,
      suggested: true,
    },
  ],
  appointments: [],
  followups: [],
  prescriptions: [],
  drug_classes: [
    {
      id: 61,
      class_key: "metformin",
      label: "متفورمین",
      glucose_lowering: true,
      display_order: 10,
    },
  ],
  drug_catalog: [
    {
      id: 62,
      generic_fa: "متفورمین",
      drug_class_key: "metformin",
      standard_doses: ["500 mg", "1000 mg"],
    },
  ],
};

function mockSuccess(payload: unknown = {}) {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  }) as jest.Mock;
}

function requestAt(index = 0) {
  const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[index];
  return {
    url: String(url),
    method: options.method ?? "GET",
    body: options.body ? JSON.parse(options.body) : undefined,
  };
}

beforeEach(() => {
  localStorageMock.clear();
  saveToken("component-test-token");
  jest.resetAllMocks();
  mockSuccess({});
  Object.defineProperty(window, "confirm", {
    configurable: true,
    value: jest.fn(() => true),
  });
});

test("flags submit only touched values and an explicit date clear", async () => {
  const onChanged = jest.fn();
  render(
    <StructuredPatientRecordPanel
      uuid={UUID}
      record={RECORD}
      loading={false}
      error={null}
      onChanged={onChanged}
    />,
  );

  const flagsSection = screen.getByText("فلگ‌های تصمیم‌یار").closest("section");
  expect(flagsSection).not.toBeNull();
  const flags = within(flagsSection as HTMLElement);

  const risk = flags.getByLabelText("ریسک قلبی");
  expect(risk).toBeChecked();
  fireEvent.click(risk);
  fireEvent.click(flags.getByRole("button", { name: "پاک‌کردن" }));
  fireEvent.click(flags.getByRole("button", { name: "ذخیرهٔ تغییرات فلگ‌ها" }));

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(requestAt()).toEqual({
    url: expect.stringContaining(`/patients/${UUID}/record/flags`),
    method: "PATCH",
    body: {
      values: { cv_risk: false },
      clear_keys: ["exam_date"],
    },
  });
  expect(screen.getByRole("status")).toHaveTextContent(
    "فلگ‌های بالینی با حفظ مقادیر ارسال‌نشده ذخیره شدند.",
  );
});

test("condition deactivation requires confirmation and stays patient scoped", async () => {
  const onChanged = jest.fn();
  const confirm = window.confirm as jest.Mock;
  confirm.mockReturnValueOnce(false).mockReturnValueOnce(true);

  render(
    <StructuredPatientRecordPanel
      uuid={UUID}
      record={RECORD}
      loading={false}
      error={null}
      onChanged={onChanged}
    />,
  );

  const button = screen.getByRole("button", { name: "غیرفعال‌کردن" });
  fireEvent.click(button);
  expect(globalThis.fetch).not.toHaveBeenCalled();

  fireEvent.click(button);
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(requestAt()).toEqual({
    url: expect.stringContaining(`/patients/${UUID}/record/conditions/21`),
    method: "DELETE",
    body: undefined,
  });
});

test("catalog lab form sends only key, value and clinical notes over the wire", async () => {
  const onChanged = jest.fn();
  render(
    <StructuredPatientRecordPanel
      uuid={UUID}
      record={RECORD}
      loading={false}
      error={null}
      onChanged={onChanged}
    />,
  );

  const labSection = screen.getByText("نتایج آزمایش").closest("section");
  expect(labSection).not.toBeNull();
  const lab = within(labSection as HTMLElement);

  fireEvent.change(lab.getByLabelText("آزمایش کاتالوگ"), {
    target: { value: "hba1c" },
  });
  expect(lab.getByLabelText("نام آزاد")).toBeDisabled();
  expect(lab.getByLabelText("نام آزاد")).toHaveValue("هموگلوبین A1c");
  expect(lab.getByLabelText("واحد")).toHaveValue("%");
  expect(lab.getByLabelText("حد پایین")).toHaveValue("4");
  expect(lab.getByLabelText("حد بالا")).toHaveValue("5.6");

  fireEvent.change(lab.getByLabelText("مقدار"), { target: { value: "7.2" } });
  fireEvent.change(lab.getByLabelText("یادداشت"), { target: { value: "ناشتا" } });
  fireEvent.click(lab.getByRole("button", { name: "ثبت آزمایش" }));

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(requestAt()).toEqual({
    url: expect.stringContaining(`/patients/${UUID}/record/labs`),
    method: "POST",
    body: {
      test_key: "hba1c",
      value: 7.2,
      taken_at: null,
      notes: "ناشتا",
    },
  });
});

test("medication form and lifecycle actions use separate atomic endpoints", async () => {
  const onChanged = jest.fn();
  render(
    <MedicationRecordPanel
      uuid={UUID}
      record={RECORD}
      loading={false}
      error={null}
      onChanged={onChanged}
    />,
  );

  fireEvent.change(screen.getByLabelText("داروی کاتالوگ"), {
    target: { value: "62" },
  });
  expect(screen.getByLabelText("نام دارو")).toHaveValue("متفورمین");
  expect(screen.getByLabelText("کلاس دارویی")).toHaveValue("metformin");
  expect(screen.getByLabelText("دوز")).toHaveValue("500 mg");
  fireEvent.change(screen.getByLabelText("برنامه مصرف"), {
    target: { value: "شب‌ها" },
  });
  fireEvent.change(screen.getByLabelText("تاریخ شروع"), {
    target: { value: "2026-07-01" },
  });
  fireEvent.change(screen.getByLabelText("یادآوری تجدید"), {
    target: { value: "30" },
  });
  fireEvent.change(screen.getByLabelText("یادداشت"), {
    target: { value: "شروع جدید" },
  });
  fireEvent.click(screen.getByRole("button", { name: "ثبت دارو" }));

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(requestAt(0)).toEqual({
    url: expect.stringContaining(`/patients/${UUID}/record/medications`),
    method: "POST",
    body: {
      drug_name: "متفورمین",
      drug_class: "metformin",
      dose: "500 mg",
      schedule: "شب‌ها",
      start_date: "2026-07-01",
      refill_interval_days: 30,
      notes: "شروع جدید",
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "تغییر دوز" }));
  const doseForm = screen.getByRole("heading", { name: "ثبت تغییر دوز" }).closest("form");
  expect(doseForm).not.toBeNull();
  const dose = within(doseForm as HTMLFormElement);
  fireEvent.change(dose.getByLabelText("دوز جدید"), {
    target: { value: "1000 mg" },
  });
  fireEvent.change(dose.getByLabelText("تاریخ"), {
    target: { value: "2026-07-10" },
  });
  fireEvent.change(dose.getByLabelText("یادداشت"), {
    target: { value: "افزایش" },
  });
  fireEvent.click(dose.getByRole("button", { name: "تأیید" }));

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
  expect(requestAt(1)).toEqual({
    url: expect.stringContaining(`/patients/${UUID}/record/medications/31/dose`),
    method: "POST",
    body: {
      dose: "1000 mg",
      change_date: "2026-07-10",
      note: "افزایش",
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "قطع دارو" }));
  const stopForm = screen.getByRole("heading", { name: "ثبت قطع دارو" }).closest("form");
  expect(stopForm).not.toBeNull();
  const stop = within(stopForm as HTMLFormElement);
  fireEvent.change(stop.getByLabelText("تاریخ"), {
    target: { value: "2026-07-20" },
  });
  fireEvent.change(stop.getByLabelText("یادداشت"), {
    target: { value: "پایان درمان" },
  });
  fireEvent.click(stop.getByRole("button", { name: "تأیید" }));

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(3));
  expect(requestAt(2)).toEqual({
    url: expect.stringContaining(`/patients/${UUID}/record/medications/31/stop`),
    method: "POST",
    body: {
      end_date: "2026-07-20",
      note: "پایان درمان",
    },
  });
});

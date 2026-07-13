import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { PatientRecordDataDTO, RecordVitalDTO } from "@/lib/api";

jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    apiAddRecordCondition: jest.fn(),
    apiRemoveRecordCondition: jest.fn(),
    apiAddSurgery: jest.fn(),
    apiDeleteSurgery: jest.fn(),
    apiAddMedicalHistory: jest.fn(),
    apiDeleteMedicalHistory: jest.fn(),
    apiAddClinicalNote: jest.fn(),
    apiDeleteClinicalNote: jest.fn(),
    apiUpdateRecordFlags: jest.fn(),
    apiAddRecordMedication: jest.fn(),
    apiChangeMedicationDose: jest.fn(),
    apiStopRecordMedication: jest.fn(),
    apiAddRecordLabs: jest.fn(),
    apiDeleteRecordLab: jest.fn(),
    apiAddRecordVitals: jest.fn(),
    apiDeleteRecordVital: jest.fn(),
  };
});

import {
  apiAddRecordCondition,
  apiAddRecordLabs,
  apiAddRecordMedication,
  apiUpdateRecordFlags,
} from "@/lib/api";
import { RecordCoreEditor } from "@/components/record/RecordCoreEditor";
import { RecordMedicationManager } from "@/components/record/RecordMedicationManager";
import { RecordMeasurementsEditor } from "@/components/record/RecordMeasurementsEditor";

const UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

const DATA: PatientRecordDataDTO = {
  condition_catalog: [
    { id: 1, name: "دیابت", code: "diabetes", description: null, icon: null, color: null, display_order: 10 },
    { id: 2, name: "فشار خون", code: "hypertension", description: null, icon: null, color: null, display_order: 20 },
  ],
  conditions: [
    { id: 11, condition_id: 1, condition_name: "دیابت", condition_code: "diabetes", stage: "T2DM", onset_date: "2020-01-01", notes: null, is_active: true, diagnosed_at: "2026-01-01T10:00:00+03:30" },
  ],
  surgeries: [{ id: 21, title: "آپاندکتومی", performed_on: "2010-05-01", note: null, created_at: "2026-01-01T10:00:00+03:30" }],
  medical_history: [{ id: 22, title: "آسم", since: "2001-01-01", note: "خاموش", created_at: "2026-01-01T10:00:00+03:30" }],
  notes: [{ id: 23, kind: "symptom", body: "تشنگی", recorded_at: "2026-01-01T10:00:00+03:30", recorded_by: "doctor" }],
  flag_catalog: [
    { flag_key: "smoking", label: "مصرف دخانیات/ویپ", flag_type: "enum", options: [{ value: "never", label: "هرگز" }, { value: "former", label: "ترک‌کرده" }, { value: "current", label: "فعلی" }], category: "lifestyle", category_label: "سبک زندگی", record_section: "lifestyle", display_order: 10 },
    { flag_key: "ascvd", label: "سابقه ASCVD", flag_type: "bool", options: [], category: "cardiac", category_label: "قلبی", record_section: "disease", display_order: 20 },
    { flag_key: "eye_exam_date", label: "آخرین معاینه چشم", flag_type: "date", options: [], category: "exam", category_label: "معاینات", record_section: "exam", display_order: 30 },
  ],
  patient_flags: { smoking: "current", ascvd: "1", eye_exam_date: "2026-01-01" },
  lab_catalog: [{ id: 31, test_key: "hba1c", name_fa: "هموگلوبین A1c", unit: "%", ref_low: 4, ref_high: 5.6, category: "glycemic", display_order: 10 }],
  suggested_labs: [{ id: 31, test_key: "hba1c", name_fa: "هموگلوبین A1c", unit: "%", ref_low: 4, ref_high: 5.6, category: "glycemic", display_order: 10 }],
  labs: [{ id: 32, test_name: "هموگلوبین A1c", test_key: "hba1c", value: 7.2, unit: "%", ref_low: 4, ref_high: 5.6, taken_at: "2026-02-01T10:00:00+03:30", notes: null, recorded_by: "doctor", encounter_id: null }],
  indicator_catalog: [{ key: "bp_systolic", label: "فشار سیستولیک", unit: "mmHg", category: "vital", display_order: 10 }],
  drug_classes: [{ class_key: "metformin", label: "متفورمین", glucose_lowering: true, display_order: 10 }],
  drug_catalog: [{ id: 41, generic_fa: "متفورمین", drug_class_key: "metformin", doses: ["500mg", "1000mg"] }],
  medications: [{ id: 42, drug_name: "متفورمین", dose: "500mg", schedule: "روزی دو بار", start_date: "2026-01-01", refill_due_date: "2026-01-31", end_date: null, drug_class: "metformin", is_active: true, notes: null, created_at: "2026-01-01T10:00:00+03:30" }],
  medication_events: [{ id: 43, medication_id: 42, drug_name: "متفورمین", event_type: "start", dose: "500mg", event_date: "2026-01-01", note: null, created_by: "doctor", created_at: "2026-01-01T10:00:00+03:30" }],
  appointments: [{ id: 51, scheduled_at: "2026-04-01T09:00:00+03:30", appt_type: "checkup", status: "scheduled", notes: null, chief_complaint: "پیگیری", doctor_id: null }],
  prescriptions: [{ id: 52, kind: "دارویی", mode: "free", insurer: null, portal_rx_id: null, issued_at: "2026-02-01T10:00:00+03:30", item_count: 1, items: [] }],
  accounting_visit_history: [{ visit_id: 53, invoice_id: 54, visit_date: "2026-02-01T10:00:00+03:30", work_date: "2026-02-01", doctor_name: "دکتر تست", price: 90000, status: "done" }],
};

const VITALS: RecordVitalDTO[] = [
  { id: 61, type: "bp_systolic", value: 128, unit: "mmHg", measured_at: "2026-02-01T10:00:00+03:30", source: "patient_self", notes: null, recorded_by: null, verified: false, verified_by: null, verified_at: null, rejected_by: null, rejected_at: null, encounter_id: null },
];

beforeEach(() => {
  jest.clearAllMocks();
  (apiAddRecordCondition as jest.Mock).mockResolvedValue({ id: 99, changed: true });
  (apiUpdateRecordFlags as jest.Mock).mockResolvedValue({ values: {} });
  (apiAddRecordMedication as jest.Mock).mockResolvedValue(DATA.medications[0]);
  (apiAddRecordLabs as jest.Mock).mockResolvedValue({ count: 1, ids: [100] });
});

test("core editor renders every specialist core section and stored values", () => {
  render(<RecordCoreEditor uuid={UUID} data={DATA} onChanged={() => {}} />);
  expect(screen.getByRole("heading", { name: "بیماری‌های مزمن" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "سوابق پزشکی و جراحی" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "ورودی‌های ساختاریافتهٔ بالینی" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "علائم، معاینه و یادداشت‌های بالینی" })).toBeInTheDocument();
  expect(screen.getByLabelText("مصرف دخانیات/ویپ")).toHaveValue("current");
  expect(screen.getByLabelText("سابقه ASCVD")).toBeChecked();
  expect(screen.getByText("آپاندکتومی")).toBeInTheDocument();
  expect(screen.getByText("تشنگی")).toBeInTheDocument();
});

test("saving a flag group sends only that group's managed keys", async () => {
  render(<RecordCoreEditor uuid={UUID} data={DATA} onChanged={() => {}} />);
  fireEvent.change(screen.getByLabelText("مصرف دخانیات/ویپ"), { target: { value: "former" } });
  const heading = screen.getByRole("heading", { name: "سبک زندگی" });
  fireEvent.click(within(heading.parentElement!).getByRole("button", { name: "ذخیره این بخش" }));
  await waitFor(() => expect(apiUpdateRecordFlags).toHaveBeenCalled());
  expect(apiUpdateRecordFlags).toHaveBeenCalledWith(UUID, {
    managed_keys: ["smoking"],
    values: { smoking: "former" },
  });
});

test("condition form sends catalog id and structured fields then refreshes", async () => {
  const onChanged = jest.fn();
  render(<RecordCoreEditor uuid={UUID} data={DATA} onChanged={onChanged} />);
  fireEvent.change(screen.getByLabelText("بیماری"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("مرحله / نوع"), { target: { value: "stage-2" } });
  fireEvent.change(screen.getByLabelText("تاریخ شروع"), { target: { value: "2025-01-01" } });
  fireEvent.click(screen.getByRole("button", { name: "ثبت بیماری" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(apiAddRecordCondition).toHaveBeenCalledWith(UUID, {
    condition_id: 2,
    stage: "stage-2",
    onset_date: "2025-01-01",
    notes: null,
  });
});

test("medication editor submits catalog identity, dose and refill interval", async () => {
  const onChanged = jest.fn();
  render(<RecordMedicationManager uuid={UUID} data={DATA} onChanged={onChanged} />);
  fireEvent.change(screen.getByLabelText("انتخاب دارو"), { target: { value: "41" } });
  fireEvent.change(screen.getByLabelText("تجدید نسخه"), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "افزودن دارو" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(apiAddRecordMedication).toHaveBeenCalledWith(UUID, expect.objectContaining({
    drug_id: 41,
    drug_name: null,
    dose: "500mg",
    refill_interval_days: 30,
  }));
  expect(screen.getByText("شروع")).toBeInTheDocument();
});

test("measurement editor sends a suggested lab by key and never exposes self-report delete", async () => {
  const onChanged = jest.fn();
  render(<RecordMeasurementsEditor uuid={UUID} data={DATA} vitals={VITALS} onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "هموگلوبین A1c" }));
  const labHeading = screen.getByRole("heading", { name: "آزمایش‌ها" });
  const labSection = labHeading.closest("section")!;
  fireEvent.change(within(labSection).getByLabelText("مقدار (%)"), { target: { value: "7.5" } });
  fireEvent.click(within(labSection).getByRole("button", { name: "ثبت آزمایش‌ها" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(apiAddRecordLabs).toHaveBeenCalledWith(UUID, {
    items: [{ test_key: "hba1c", value: 7.5, notes: null }],
    taken_at: null,
  });
  const selfReportText = screen.getByText("حذف از این مسیر مجاز نیست");
  const row = selfReportText.closest("tr")!;
  expect(within(row).queryByRole("button", { name: "حذف" })).not.toBeInTheDocument();
  expect(within(row).getByText("در انتظار بازبینی")).toBeInTheDocument();
});

test("mutation errors are visible and do not claim refresh success", async () => {
  (apiAddRecordCondition as jest.Mock).mockRejectedValueOnce(new Error("boom"));
  const onChanged = jest.fn();
  render(<RecordCoreEditor uuid={UUID} data={DATA} onChanged={onChanged} />);
  fireEvent.change(screen.getByLabelText("بیماری"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "ثبت بیماری" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("ثبت تغییرات پرونده ناموفق بود");
  expect(onChanged).not.toHaveBeenCalled();
});

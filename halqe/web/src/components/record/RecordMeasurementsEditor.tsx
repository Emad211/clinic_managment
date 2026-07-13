"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  apiAddRecordLabs,
  apiAddRecordVitals,
  apiDeleteRecordLab,
  apiDeleteRecordVital,
  type PatientRecordDataDTO,
  type RecordLabCatalogDTO,
  type RecordVitalDTO,
} from "@/lib/api";
import { formatJalali, formatToman, toFarsiDigits } from "@/lib/jalali";
import styles from "./record-editor.module.css";

interface Props {
  uuid: string;
  data: PatientRecordDataDTO;
  vitals: RecordVitalDTO[];
  onChanged: () => Promise<void> | void;
}

interface EntryRow {
  key: string;
  value: string;
  notes: string;
}

function newRow(key = ""): EntryRow {
  return { key, value: "", notes: "" };
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function labStatus(value: number | null, low: number | null, high: number | null): string {
  if (value === null) return "بدون مقدار";
  if (low !== null && value < low) return "پایین‌تر از محدوده";
  if (high !== null && value > high) return "بالاتر از محدوده";
  return "در محدودهٔ مرجع";
}

export function RecordMeasurementsEditor({ uuid, data, vitals, onChanged }: Props) {
  const [labRows, setLabRows] = useState<EntryRow[]>([newRow()]);
  const [labDate, setLabDate] = useState("");
  const [vitalRows, setVitalRows] = useState<EntryRow[]>([newRow()]);
  const [vitalDate, setVitalDate] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const labByKey = useMemo(
    () => Object.fromEntries(data.lab_catalog.map((item) => [item.test_key, item])),
    [data.lab_catalog],
  );
  const indicatorByKey = useMemo(
    () => Object.fromEntries(data.indicator_catalog.map((item) => [item.key, item])),
    [data.indicator_catalog],
  );

  async function mutate(key: string, action: () => Promise<unknown>, successText: string) {
    setBusy(key);
    setError(null);
    setSuccess(null);
    try {
      await action();
      await onChanged();
      setSuccess(successText);
      return true;
    } catch (err) {
      setError(errorText(err, "ثبت اندازه‌گیری‌ها ناموفق بود."));
      return false;
    } finally {
      setBusy(null);
    }
  }

  function updateRow(
    setter: React.Dispatch<React.SetStateAction<EntryRow[]>>,
    index: number,
    patch: Partial<EntryRow>,
  ) {
    setter((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)),
    );
  }

  function addSuggestedLab(test: RecordLabCatalogDTO) {
    setLabRows((current) => {
      if (current.some((row) => row.key === test.test_key)) return current;
      const firstEmpty = current.findIndex((row) => !row.key && !row.value);
      if (firstEmpty >= 0) {
        return current.map((row, index) =>
          index === firstEmpty ? { ...row, key: test.test_key } : row,
        );
      }
      return [...current, newRow(test.test_key)];
    });
  }

  async function submitLabs(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const complete = labRows.filter((row) => row.key && row.value.trim() !== "");
    if (complete.length === 0) {
      setError("حداقل یک آزمایش و مقدار وارد کنید.");
      return;
    }
    const duplicate = complete.find(
      (row, index) => complete.findIndex((other) => other.key === row.key) !== index,
    );
    if (duplicate) {
      setError("هر آزمایش در یک ثبت فقط یک‌بار مجاز است.");
      return;
    }
    const ok = await mutate(
      "labs-add",
      () =>
        apiAddRecordLabs(uuid, {
          items: complete.map((row) => ({
            test_key: row.key,
            value: Number(row.value),
            notes: row.notes.trim() || null,
          })),
          taken_at: labDate ? `${labDate}T12:00:00` : null,
        }),
      `${toFarsiDigits(complete.length)} نتیجهٔ آزمایش ثبت شد.`,
    );
    if (ok) {
      setLabRows([newRow()]);
      setLabDate("");
    }
  }

  async function submitVitals(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const complete = vitalRows.filter((row) => row.key && row.value.trim() !== "");
    if (complete.length === 0) {
      setError("حداقل یک شاخص و مقدار وارد کنید.");
      return;
    }
    const duplicate = complete.find(
      (row, index) => complete.findIndex((other) => other.key === row.key) !== index,
    );
    if (duplicate) {
      setError("هر شاخص در یک ثبت فقط یک‌بار مجاز است.");
      return;
    }
    const ok = await mutate(
      "vitals-add",
      () =>
        apiAddRecordVitals(uuid, {
          items: complete.map((row) => ({
            type: row.key,
            value: Number(row.value),
            notes: row.notes.trim() || null,
          })),
          measured_at: vitalDate ? `${vitalDate}T12:00:00` : null,
        }),
      `${toFarsiDigits(complete.length)} شاخص ثبت شد.`,
    );
    if (ok) {
      setVitalRows([newRow()]);
      setVitalDate("");
    }
  }

  return (
    <div className={styles.stack}>
      {(error || success) && (
        <div className={styles.statusRow} role={error ? "alert" : "status"} aria-live="polite">
          <span className={error ? styles.error : styles.success}>{error ?? success}</span>
        </div>
      )}

      <section className={styles.section} aria-labelledby="record-labs-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-labs-title">آزمایش‌ها</h2>
            <p>نام، واحد و محدودهٔ مرجع از کاتالوگ سرور snapshot می‌شود؛ client فقط کلید و مقدار را می‌فرستد.</p>
          </div>
          <span className={styles.count}>{toFarsiDigits(data.labs.length)} نتیجه</span>
        </header>
        <div className={`${styles.sectionBody} ${styles.stack}`}>
          {data.suggested_labs.length > 0 && (
            <div>
              <div className={styles.listTitle}>پیشنهاد بر اساس بیماری‌های فعال</div>
              <div className={styles.chips} aria-label="آزمایش‌های پیشنهادی">
                {data.suggested_labs.map((test) => (
                  <button
                    type="button"
                    className={`${styles.chip} ${labRows.some((row) => row.key === test.test_key) ? styles.chipActive : ""}`}
                    key={test.test_key}
                    onClick={() => addSuggestedLab(test)}
                  >
                    {test.name_fa}
                  </button>
                ))}
              </div>
            </div>
          )}

          <form className={styles.form} onSubmit={submitLabs}>
            <label className={styles.field}>
              تاریخ نمونه‌گیری
              <input type="date" value={labDate} onChange={(event) => setLabDate(event.target.value)} />
            </label>
            <div className={styles.entryRows}>
              {labRows.map((row, index) => {
                const definition = labByKey[row.key];
                return (
                  <div className={styles.entryRow} key={`lab-${index}`}>
                    <label className={styles.field}>
                      آزمایش
                      <select
                        aria-label={`آزمایش ردیف ${index + 1}`}
                        value={row.key}
                        onChange={(event) => updateRow(setLabRows, index, { key: event.target.value })}
                      >
                        <option value="">انتخاب کنید</option>
                        {data.lab_catalog.map((test) => (
                          <option key={test.test_key} value={test.test_key}>{test.name_fa}</option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      مقدار {definition?.unit ? `(${definition.unit})` : ""}
                      <input
                        inputMode="decimal"
                        value={row.value}
                        onChange={(event) => updateRow(setLabRows, index, { value: event.target.value })}
                      />
                    </label>
                    <label className={styles.field}>
                      یادداشت
                      <input value={row.notes} onChange={(event) => updateRow(setLabRows, index, { notes: event.target.value })} />
                    </label>
                    <button
                      type="button"
                      className={styles.dangerButton}
                      aria-label={`حذف ردیف آزمایش ${index + 1}`}
                      onClick={() => setLabRows((current) => current.length === 1 ? [newRow()] : current.filter((_, rowIndex) => rowIndex !== index))}
                    >
                      حذف ردیف
                    </button>
                  </div>
                );
              })}
            </div>
            <div className={styles.actions}>
              <button type="button" className={styles.secondaryButton} onClick={() => setLabRows((current) => [...current, newRow()])}>+ ردیف آزمایش</button>
              <button type="submit" className={styles.button} disabled={busy !== null}>{busy === "labs-add" ? "در حال ثبت…" : "ثبت آزمایش‌ها"}</button>
            </div>
          </form>

          {data.labs.length === 0 ? <div className={styles.empty}>نتیجهٔ آزمایشی ثبت نشده است.</div> : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>آزمایش</th><th>مقدار</th><th>محدوده</th><th>وضعیت</th><th>تاریخ</th><th>عملیات</th></tr></thead>
                <tbody>
                  {data.labs.map((lab) => (
                    <tr key={lab.id}>
                      <td><strong>{lab.test_name}</strong>{lab.notes && <div className={styles.listMeta}>{lab.notes}</div>}</td>
                      <td>{lab.value ?? "—"} {lab.unit || ""}</td>
                      <td>{lab.ref_low ?? "—"} تا {lab.ref_high ?? "—"}</td>
                      <td>{labStatus(lab.value, lab.ref_low, lab.ref_high)}</td>
                      <td>{formatJalali(lab.taken_at)}</td>
                      <td><button type="button" className={styles.dangerButton} disabled={busy !== null} onClick={() => mutate(`lab-delete-${lab.id}`, () => apiDeleteRecordLab(uuid, lab.id), "نتیجهٔ آزمایش حذف شد.")}>حذف</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="record-vitals-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-vitals-title">علائم حیاتی و شاخص‌ها</h2>
            <p>ثبت کلینیکی تأییدشده است؛ دادهٔ خوداظهاری برای حفظ زنجیرهٔ بازبینی hard-delete نمی‌شود.</p>
          </div>
          <span className={styles.count}>{toFarsiDigits(vitals.length)} اندازه‌گیری</span>
        </header>
        <div className={`${styles.sectionBody} ${styles.stack}`}>
          <form className={styles.form} onSubmit={submitVitals}>
            <label className={styles.field}>
              تاریخ اندازه‌گیری
              <input type="date" value={vitalDate} onChange={(event) => setVitalDate(event.target.value)} />
            </label>
            <div className={styles.entryRows}>
              {vitalRows.map((row, index) => {
                const definition = indicatorByKey[row.key];
                return (
                  <div className={styles.entryRow} key={`vital-${index}`}>
                    <label className={styles.field}>
                      شاخص
                      <select value={row.key} aria-label={`شاخص ردیف ${index + 1}`} onChange={(event) => updateRow(setVitalRows, index, { key: event.target.value })}>
                        <option value="">انتخاب کنید</option>
                        {data.indicator_catalog.map((indicator) => <option key={indicator.key} value={indicator.key}>{indicator.label}</option>)}
                      </select>
                    </label>
                    <label className={styles.field}>
                      مقدار {definition?.unit ? `(${definition.unit})` : ""}
                      <input inputMode="decimal" value={row.value} onChange={(event) => updateRow(setVitalRows, index, { value: event.target.value })} />
                    </label>
                    <label className={styles.field}>یادداشت<input value={row.notes} onChange={(event) => updateRow(setVitalRows, index, { notes: event.target.value })} /></label>
                    <button type="button" className={styles.dangerButton} onClick={() => setVitalRows((current) => current.length === 1 ? [newRow()] : current.filter((_, rowIndex) => rowIndex !== index))}>حذف ردیف</button>
                  </div>
                );
              })}
            </div>
            <div className={styles.actions}>
              <button type="button" className={styles.secondaryButton} onClick={() => setVitalRows((current) => [...current, newRow()])}>+ ردیف شاخص</button>
              <button type="submit" className={styles.button} disabled={busy !== null}>{busy === "vitals-add" ? "در حال ثبت…" : "ثبت شاخص‌ها"}</button>
            </div>
          </form>

          {vitals.length === 0 ? <div className={styles.empty}>شاخصی ثبت نشده است.</div> : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>شاخص</th><th>مقدار</th><th>منبع</th><th>بازبینی</th><th>تاریخ</th><th>عملیات</th></tr></thead>
                <tbody>
                  {vitals.map((vital) => {
                    const definition = indicatorByKey[vital.type];
                    const selfReported = vital.source === "patient_self" || vital.source === "self";
                    const review = vital.verified ? "تأییدشده" : vital.rejected_at ? "ردشده" : "در انتظار بازبینی";
                    return (
                      <tr key={vital.id}>
                        <td>{definition?.label ?? vital.type}{vital.notes && <div className={styles.listMeta}>{vital.notes}</div>}</td>
                        <td>{vital.value} {vital.unit || definition?.unit || ""}</td>
                        <td>{selfReported ? "خوداظهاری بیمار" : "ثبت کلینیک"}</td>
                        <td>{review}</td>
                        <td>{formatJalali(vital.measured_at)}</td>
                        <td>
                          {selfReported ? <span className={styles.listMeta}>حذف از این مسیر مجاز نیست</span> : (
                            <button type="button" className={styles.dangerButton} disabled={busy !== null} onClick={() => mutate(`vital-delete-${vital.id}`, () => apiDeleteRecordVital(uuid, vital.id), "شاخص حذف شد.")}>حذف</button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="record-history-timeline-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-history-timeline-title">تاریخچهٔ خدمات، نوبت و نسخه</h2>
            <p>ویزیت‌های مالی فقط از AccountingReadPort خوانده می‌شوند؛ پروندهٔ بالینی حسابداری را نمی‌نویسد.</p>
          </div>
        </header>
        <div className={`${styles.sectionBody} ${styles.gridThree}`}>
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>ویزیت‌های حسابداری</h3>
            <div className={styles.subsectionBody}>
              {data.accounting_visit_history.length === 0 ? <div className={styles.empty}>ویزیتی ثبت نشده است.</div> : (
                <ul className={styles.list}>{data.accounting_visit_history.map((visit) => <li className={styles.listItem} key={visit.visit_id}><div><div className={styles.listTitle}>{visit.doctor_name || "پزشک نامشخص"}</div><div className={styles.listMeta}>{formatJalali(visit.work_date || visit.visit_date)} · {formatToman(visit.price)}</div></div></li>)}</ul>
              )}
            </div>
          </div>
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>نوبت‌ها</h3>
            <div className={styles.subsectionBody}>
              {data.appointments.length === 0 ? <div className={styles.empty}>نوبتی ثبت نشده است.</div> : (
                <ul className={styles.list}>{data.appointments.map((appointment) => <li className={styles.listItem} key={appointment.id}><div><div className={styles.listTitle}>{appointment.appt_type || "نوبت"}<span className={styles.badge}>{appointment.status}</span></div><div className={styles.listMeta}>{formatJalali(appointment.scheduled_at)}</div>{appointment.chief_complaint && <div className={styles.listNote}>{appointment.chief_complaint}</div>}</div></li>)}</ul>
              )}
            </div>
          </div>
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>نسخه‌ها</h3>
            <div className={styles.subsectionBody}>
              {data.prescriptions.length === 0 ? <div className={styles.empty}>نسخه‌ای ثبت نشده است.</div> : (
                <ul className={styles.list}>{data.prescriptions.map((prescription) => <li className={styles.listItem} key={prescription.id}><div><div className={styles.listTitle}>{prescription.kind}<span className={styles.badge}>{toFarsiDigits(prescription.item_count)} قلم</span></div><div className={styles.listMeta}>{formatJalali(prescription.issued_at)} · {prescription.mode || "free"}</div></div></li>)}</ul>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

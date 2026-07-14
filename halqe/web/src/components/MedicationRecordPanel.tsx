"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  apiAddPatientMedication,
  apiChangePatientMedicationDose,
  apiStopPatientMedication,
  type StructuredPatientRecordDTO,
  type StructuredMedicationDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import styles from "./patient-record.module.css";

interface MedicationRecordPanelProps {
  uuid: string;
  record: StructuredPatientRecordDTO | null;
  loading: boolean;
  error: string | null;
  onChanged: () => void | Promise<void>;
}

interface AddForm {
  catalogId: string;
  drugName: string;
  drugClass: string;
  dose: string;
  schedule: string;
  startDate: string;
  refillInterval: string;
  notes: string;
}

const EMPTY_ADD_FORM: AddForm = {
  catalogId: "",
  drugName: "",
  drugClass: "",
  dose: "",
  schedule: "",
  startDate: "",
  refillInterval: "",
  notes: "",
};

interface MedicationAction {
  medicationId: number;
  kind: "dose" | "stop";
  dose: string;
  date: string;
  note: string;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function eventLabel(eventType: string): string {
  if (eventType === "start") return "شروع";
  if (eventType === "stop") return "قطع";
  if (eventType === "dose_change") return "تغییر دوز";
  return eventType;
}

export function MedicationRecordPanel({
  uuid,
  record,
  loading,
  error,
  onChanged,
}: MedicationRecordPanelProps) {
  const [form, setForm] = useState<AddForm>(EMPTY_ADD_FORM);
  const [action, setAction] = useState<MedicationAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const active = useMemo(
    () => (record?.medications ?? []).filter((item) => item.is_active),
    [record?.medications],
  );
  const inactive = useMemo(
    () => (record?.medications ?? []).filter((item) => !item.is_active),
    [record?.medications],
  );
  const selectedCatalog = useMemo(
    () =>
      record?.drug_catalog.find((item) => String(item.id) === form.catalogId) ?? null,
    [record?.drug_catalog, form.catalogId],
  );

  function updateForm<K extends keyof AddForm>(key: K, value: AddForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function chooseDrug(value: string) {
    const row = record?.drug_catalog.find((item) => String(item.id) === value);
    setForm((current) => ({
      ...current,
      catalogId: value,
      drugName: row?.generic_fa ?? current.drugName,
      drugClass: row?.drug_class_key ?? "",
      dose: row?.standard_doses[0] ?? current.dose,
    }));
  }

  async function addMedication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.drugName.trim()) {
      setLocalError("نام دارو الزامی است.");
      return;
    }
    setBusy(true);
    setLocalError(null);
    setNotice(null);
    try {
      await apiAddPatientMedication(uuid, {
        drug_name: form.drugName.trim(),
        drug_class: form.drugClass || null,
        dose: form.dose.trim() || null,
        schedule: form.schedule.trim() || null,
        start_date: form.startDate || null,
        refill_interval_days: form.refillInterval
          ? Number(form.refillInterval)
          : null,
        notes: form.notes.trim() || null,
      });
      setForm(EMPTY_ADD_FORM);
      setNotice("دارو و رویداد شروع آن به‌صورت اتمیک ثبت شد.");
      await onChanged();
    } catch (err) {
      setLocalError(errorText(err, "ثبت دارو ناموفق بود."));
    } finally {
      setBusy(false);
    }
  }

  function beginDose(medication: StructuredMedicationDTO) {
    setAction({
      medicationId: medication.id,
      kind: "dose",
      dose: medication.dose ?? "",
      date: "",
      note: "",
    });
    setLocalError(null);
    setNotice(null);
  }

  function beginStop(medication: StructuredMedicationDTO) {
    setAction({
      medicationId: medication.id,
      kind: "stop",
      dose: "",
      date: "",
      note: "",
    });
    setLocalError(null);
    setNotice(null);
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!action) return;
    if (action.kind === "dose" && !action.dose.trim()) {
      setLocalError("دوز جدید الزامی است.");
      return;
    }
    setBusy(true);
    setLocalError(null);
    setNotice(null);
    try {
      if (action.kind === "dose") {
        await apiChangePatientMedicationDose(
          uuid,
          action.medicationId,
          action.dose.trim(),
          action.date || null,
          action.note.trim() || null,
        );
        setNotice("دوز دارو و رویداد تغییر دوز ثبت شد.");
      } else {
        await apiStopPatientMedication(
          uuid,
          action.medicationId,
          action.date || null,
          action.note.trim() || null,
        );
        setNotice("دارو قطع و رویداد قطع ثبت شد.");
      }
      setAction(null);
      await onChanged();
    } catch (err) {
      setLocalError(errorText(err, "به‌روزرسانی دارو ناموفق بود."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.workspace} aria-labelledby="medication-record-title">
      <div className={styles.workspaceHeader}>
        <div>
          <h2 id="medication-record-title">پروندهٔ کامل دارویی</h2>
          <p>داروهای فعال و متوقف‌شده همراه با خط زمانی تغییرات</p>
        </div>
        <span className={styles.countBadge}>
          {toFarsiDigits(active.length)} فعال
        </span>
      </div>

      {(error || localError) && (
        <div className={styles.errorBox} role="alert">
          {localError || error}
        </div>
      )}
      {notice && (
        <div className={styles.noticeBox} role="status" aria-live="polite">
          {notice}
        </div>
      )}

      <form className={styles.formCard} onSubmit={addMedication}>
        <div className={styles.formTitle}>افزودن دارو</div>
        <div className={styles.gridThree}>
          <label>
            داروی کاتالوگ
            <select value={form.catalogId} onChange={(event) => chooseDrug(event.target.value)}>
              <option value="">ورود دستی</option>
              {(record?.drug_catalog ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.generic_fa}
                </option>
              ))}
            </select>
          </label>
          <label>
            نام دارو
            <input
              value={form.drugName}
              onChange={(event) => updateForm("drugName", event.target.value)}
              required
            />
          </label>
          <label>
            کلاس دارویی
            <select
              value={form.drugClass}
              onChange={(event) => updateForm("drugClass", event.target.value)}
            >
              <option value="">تعریف نشده</option>
              {(record?.drug_classes ?? []).map((item) => (
                <option key={item.id} value={item.class_key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className={styles.gridThree}>
          <label>
            دوز
            {selectedCatalog && selectedCatalog.standard_doses.length > 0 ? (
              <select value={form.dose} onChange={(event) => updateForm("dose", event.target.value)}>
                <option value="">بدون دوز</option>
                {selectedCatalog.standard_doses.map((dose) => (
                  <option key={dose} value={dose}>{dose}</option>
                ))}
              </select>
            ) : (
              <input value={form.dose} onChange={(event) => updateForm("dose", event.target.value)} />
            )}
          </label>
          <label>
            برنامه مصرف
            <input
              value={form.schedule}
              onChange={(event) => updateForm("schedule", event.target.value)}
              placeholder="مثلاً روزی دو بار"
            />
          </label>
          <label>
            تاریخ شروع
            <input
              type="date"
              value={form.startDate}
              onChange={(event) => updateForm("startDate", event.target.value)}
            />
          </label>
        </div>
        <div className={styles.gridTwo}>
          <label>
            یادآوری تجدید
            <select
              value={form.refillInterval}
              onChange={(event) => updateForm("refillInterval", event.target.value)}
            >
              <option value="">ندارد</option>
              <option value="15">۱۵ روز</option>
              <option value="30">۳۰ روز</option>
              <option value="60">۶۰ روز</option>
              <option value="90">۹۰ روز</option>
            </select>
          </label>
          <label>
            یادداشت
            <input value={form.notes} onChange={(event) => updateForm("notes", event.target.value)} />
          </label>
        </div>
        <div className={styles.formActions}>
          <button type="submit" className={styles.primaryButton} disabled={busy || loading}>
            {busy ? "در حال ثبت…" : "ثبت دارو"}
          </button>
        </div>
      </form>

      {loading && <div className={styles.stateBox}>در حال بارگذاری پروندهٔ دارویی…</div>}

      {!loading && active.length === 0 && (
        <div className={styles.stateBox}>داروی فعالی ثبت نشده است.</div>
      )}

      <div className={styles.recordList}>
        {active.map((medication) => (
          <article key={medication.id} className={styles.recordItem}>
            <div className={styles.recordItemHeader}>
              <div>
                <h3>{medication.drug_name}</h3>
                <p>
                  {[medication.dose, medication.schedule].filter(Boolean).join(" — ") || "دوز ثبت نشده"}
                </p>
              </div>
              <span className={styles.activeBadge}>فعال</span>
            </div>
            <dl className={styles.definitionGrid}>
              <div><dt>شروع</dt><dd>{medication.start_date ? formatJalali(medication.start_date) : "—"}</dd></div>
              <div><dt>تجدید</dt><dd>{medication.refill_due_date ? formatJalali(medication.refill_due_date) : "—"}</dd></div>
              <div><dt>کلاس</dt><dd>{medication.drug_class || "—"}</dd></div>
            </dl>
            {medication.notes && <p className={styles.noteText}>{medication.notes}</p>}
            <div className={styles.inlineActions}>
              <button type="button" onClick={() => beginDose(medication)} disabled={busy}>تغییر دوز</button>
              <button type="button" className={styles.dangerButton} onClick={() => beginStop(medication)} disabled={busy}>قطع دارو</button>
            </div>
            {medication.events.length > 0 && (
              <ol className={styles.timeline} aria-label={`تاریخچه ${medication.drug_name}`}>
                {medication.events.map((item) => (
                  <li key={item.id}>
                    <strong>{eventLabel(item.event_type)}</strong>
                    <span>{item.event_date ? formatJalali(item.event_date) : "بدون تاریخ"}</span>
                    {item.dose && <span>دوز: {item.dose}</span>}
                    {item.note && <small>{item.note}</small>}
                  </li>
                ))}
              </ol>
            )}
          </article>
        ))}
      </div>

      {action && (
        <form className={styles.actionCard} onSubmit={submitAction}>
          <h3>{action.kind === "dose" ? "ثبت تغییر دوز" : "ثبت قطع دارو"}</h3>
          <div className={styles.gridThree}>
            {action.kind === "dose" && (
              <label>
                دوز جدید
                <input
                  value={action.dose}
                  onChange={(event) => setAction((current) => current ? { ...current, dose: event.target.value } : current)}
                  required
                />
              </label>
            )}
            <label>
              تاریخ
              <input
                type="date"
                value={action.date}
                onChange={(event) => setAction((current) => current ? { ...current, date: event.target.value } : current)}
              />
            </label>
            <label>
              یادداشت
              <input
                value={action.note}
                onChange={(event) => setAction((current) => current ? { ...current, note: event.target.value } : current)}
              />
            </label>
          </div>
          <div className={styles.formActions}>
            <button type="button" onClick={() => setAction(null)} disabled={busy}>انصراف</button>
            <button type="submit" className={styles.primaryButton} disabled={busy}>
              {busy ? "در حال ثبت…" : "تأیید"}
            </button>
          </div>
        </form>
      )}

      {inactive.length > 0 && (
        <details className={styles.archiveBlock}>
          <summary>داروهای متوقف‌شده ({toFarsiDigits(inactive.length)})</summary>
          <div className={styles.recordList}>
            {inactive.map((medication) => (
              <article key={medication.id} className={styles.recordItemMuted}>
                <div className={styles.recordItemHeader}>
                  <div>
                    <h3>{medication.drug_name}</h3>
                    <p>{medication.dose || "دوز ثبت نشده"}</p>
                  </div>
                  <span className={styles.inactiveBadge}>متوقف</span>
                </div>
                <p>
                  پایان: {medication.end_date ? formatJalali(medication.end_date) : "ثبت نشده"}
                </p>
              </article>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

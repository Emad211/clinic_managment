"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  apiAddRecordMedication,
  apiChangeMedicationDose,
  apiStopRecordMedication,
  type PatientRecordDataDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import styles from "./record-editor.module.css";

interface Props {
  uuid: string;
  data: PatientRecordDataDTO;
  onChanged: () => Promise<void> | void;
}

const REFILL_OPTIONS = [15, 30, 60, 90] as const;

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function RecordMedicationManager({ uuid, data, onChanged }: Props) {
  const [drugChoice, setDrugChoice] = useState("");
  const [customName, setCustomName] = useState("");
  const [customClass, setCustomClass] = useState("");
  const [dose, setDose] = useState("");
  const [schedule, setSchedule] = useState("");
  const [startDate, setStartDate] = useState("");
  const [refillDays, setRefillDays] = useState<"" | `${(typeof REFILL_OPTIONS)[number]}`>("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [doseEdits, setDoseEdits] = useState<Record<number, string>>({});
  const [doseDates, setDoseDates] = useState<Record<number, string>>({});
  const [stopDates, setStopDates] = useState<Record<number, string>>({});

  const selectedDrug = useMemo(
    () => data.drug_catalog.find((item) => String(item.id) === drugChoice) ?? null,
    [data.drug_catalog, drugChoice],
  );

  const classLabelByKey = useMemo(
    () => Object.fromEntries(data.drug_classes.map((item) => [item.class_key, item.label])),
    [data.drug_classes],
  );

  const active = data.medications.filter((item) => item.is_active);
  const inactive = data.medications.filter((item) => !item.is_active);

  useEffect(() => {
    if (!selectedDrug) return;
    setCustomClass(selectedDrug.drug_class_key ?? "");
    if (selectedDrug.doses.length > 0 && !selectedDrug.doses.includes(dose)) {
      setDose(selectedDrug.doses[0]);
    }
  }, [selectedDrug, dose]);

  async function runMutation(
    key: string,
    action: () => Promise<unknown>,
    successText: string,
  ) {
    setBusy(key);
    setError(null);
    setSuccess(null);
    try {
      await action();
      await onChanged();
      setSuccess(successText);
    } catch (err) {
      setError(messageFrom(err, "عملیات دارویی ناموفق بود."));
    } finally {
      setBusy(null);
    }
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const isCustom = drugChoice === "custom";
    if (!drugChoice || (isCustom && !customName.trim())) {
      setError("یک دارو از کاتالوگ انتخاب کنید یا نام داروی آزاد را بنویسید.");
      return;
    }

    await runMutation(
      "add",
      () =>
        apiAddRecordMedication(uuid, {
          drug_id: isCustom ? null : Number(drugChoice),
          drug_name: isCustom ? customName.trim() : null,
          drug_class: isCustom ? customClass || null : null,
          dose: dose.trim() || null,
          schedule: schedule.trim() || null,
          start_date: startDate || null,
          refill_interval_days: refillDays ? Number(refillDays) as 15 | 30 | 60 | 90 : null,
          notes: notes.trim() || null,
        }),
      "دارو با موفقیت به پرونده افزوده شد.",
    );

    setDrugChoice("");
    setCustomName("");
    setCustomClass("");
    setDose("");
    setSchedule("");
    setStartDate("");
    setRefillDays("");
    setNotes("");
  }

  async function handleDoseChange(medicationId: number) {
    const nextDose = (doseEdits[medicationId] ?? "").trim();
    if (!nextDose) {
      setError("دوز جدید را وارد کنید.");
      return;
    }
    await runMutation(
      `dose-${medicationId}`,
      () =>
        apiChangeMedicationDose(uuid, medicationId, {
          new_dose: nextDose,
          change_date: doseDates[medicationId] || null,
        }),
      "تغییر دوز ثبت شد.",
    );
    setDoseEdits((current) => ({ ...current, [medicationId]: "" }));
    setDoseDates((current) => ({ ...current, [medicationId]: "" }));
  }

  async function handleStop(medicationId: number) {
    await runMutation(
      `stop-${medicationId}`,
      () =>
        apiStopRecordMedication(uuid, medicationId, {
          end_date: stopDates[medicationId] || null,
        }),
      "قطع دارو در پرونده ثبت شد.",
    );
    setStopDates((current) => ({ ...current, [medicationId]: "" }));
  }

  return (
    <section className={styles.section} aria-labelledby="record-medications-title">
      <header className={styles.sectionHeader}>
        <div>
          <h2 id="record-medications-title">داروها و چرخهٔ درمان</h2>
          <p>شروع، تغییر دوز و قطع دارو به‌صورت رویداد تاریخی و قابل‌ممیزی ثبت می‌شود.</p>
        </div>
        <span className={styles.count}>{toFarsiDigits(active.length)} داروی فعال</span>
      </header>

      <div className={`${styles.sectionBody} ${styles.stack}`}>
        {(error || success) && (
          <div className={styles.statusRow} role={error ? "alert" : "status"} aria-live="polite">
            <span className={error ? styles.error : styles.success}>{error ?? success}</span>
          </div>
        )}

        <div className={styles.gridTwo}>
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>افزودن دارو</h3>
            <div className={styles.subsectionBody}>
              <form className={styles.form} onSubmit={handleAdd}>
                <label className={styles.field}>
                  دارو
                  <select
                    aria-label="انتخاب دارو"
                    value={drugChoice}
                    onChange={(event) => setDrugChoice(event.target.value)}
                    required
                  >
                    <option value="">انتخاب کنید</option>
                    {data.drug_classes.map((drugClass) => (
                      <optgroup key={drugClass.class_key} label={drugClass.label}>
                        {data.drug_catalog
                          .filter((drug) => drug.drug_class_key === drugClass.class_key)
                          .map((drug) => (
                            <option key={drug.id} value={drug.id}>
                              {drug.generic_fa}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                    <option value="custom">داروی آزاد / خارج از کاتالوگ</option>
                  </select>
                </label>

                {drugChoice === "custom" && (
                  <div className={styles.formGrid}>
                    <label className={styles.field}>
                      نام داروی آزاد
                      <input
                        value={customName}
                        onChange={(event) => setCustomName(event.target.value)}
                        required
                      />
                    </label>
                    <label className={styles.field}>
                      کلاس دارویی
                      <select value={customClass} onChange={(event) => setCustomClass(event.target.value)}>
                        <option value="">نامشخص</option>
                        {data.drug_classes.map((item) => (
                          <option key={item.class_key} value={item.class_key}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                )}

                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    دوز
                    {selectedDrug?.doses.length ? (
                      <select value={dose} onChange={(event) => setDose(event.target.value)}>
                        <option value="">انتخاب دوز</option>
                        {selectedDrug.doses.map((item) => (
                          <option key={item} value={item}>{item}</option>
                        ))}
                      </select>
                    ) : (
                      <input value={dose} onChange={(event) => setDose(event.target.value)} />
                    )}
                  </label>
                  <label className={styles.field}>
                    نحوه مصرف
                    <input
                      value={schedule}
                      onChange={(event) => setSchedule(event.target.value)}
                      placeholder="مثلاً روزی دو بار"
                    />
                  </label>
                </div>

                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    تاریخ شروع
                    <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                  </label>
                  <label className={styles.field}>
                    تجدید نسخه
                    <select value={refillDays} onChange={(event) => setRefillDays(event.target.value as typeof refillDays)}>
                      <option value="">بدون تاریخ خودکار</option>
                      {REFILL_OPTIONS.map((days) => (
                        <option key={days} value={days}>{toFarsiDigits(days)} روز</option>
                      ))}
                    </select>
                  </label>
                </div>

                <label className={styles.field}>
                  توضیحات
                  <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />
                </label>

                <div className={styles.actions}>
                  <button className={styles.button} type="submit" disabled={busy !== null}>
                    {busy === "add" ? "در حال ثبت…" : "افزودن دارو"}
                  </button>
                </div>
              </form>
            </div>
          </div>

          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>داروهای فعال</h3>
            <div className={`${styles.subsectionBody} ${styles.stack}`}>
              {active.length === 0 ? (
                <div className={styles.empty}>داروی فعالی ثبت نشده است.</div>
              ) : (
                active.map((medication) => {
                  const events = data.medication_events.filter(
                    (event) => event.medication_id === medication.id,
                  );
                  return (
                    <article key={medication.id} className={styles.medicationCard} data-testid={`record-med-${medication.id}`}>
                      <div className={styles.medicationHeader}>
                        <div>
                          <div className={styles.listTitle}>{medication.drug_name}</div>
                          <div className={styles.listMeta}>
                            {medication.dose || "دوز ثبت نشده"}
                            {medication.schedule ? ` · ${medication.schedule}` : ""}
                            {medication.drug_class ? ` · ${classLabelByKey[medication.drug_class] ?? medication.drug_class}` : ""}
                          </div>
                          <div className={styles.listMeta}>
                            شروع: {formatJalali(medication.start_date)}
                            {medication.refill_due_date ? ` · تجدید: ${formatJalali(medication.refill_due_date)}` : ""}
                          </div>
                        </div>
                        <span className={styles.badge}>فعال</span>
                      </div>

                      <details className={styles.medicationActions}>
                        <summary>تغییر دوز یا قطع دارو</summary>
                        <div className={`${styles.form} ${styles.medicationActions}`}>
                          <div className={styles.formGrid}>
                            <label className={styles.field}>
                              دوز جدید
                              <input
                                value={doseEdits[medication.id] ?? ""}
                                onChange={(event) =>
                                  setDoseEdits((current) => ({ ...current, [medication.id]: event.target.value }))
                                }
                              />
                            </label>
                            <label className={styles.field}>
                              تاریخ تغییر
                              <input
                                type="date"
                                value={doseDates[medication.id] ?? ""}
                                onChange={(event) =>
                                  setDoseDates((current) => ({ ...current, [medication.id]: event.target.value }))
                                }
                              />
                            </label>
                          </div>
                          <div className={styles.actions}>
                            <button
                              type="button"
                              className={styles.secondaryButton}
                              disabled={busy !== null}
                              onClick={() => handleDoseChange(medication.id)}
                            >
                              {busy === `dose-${medication.id}` ? "…" : "ثبت تغییر دوز"}
                            </button>
                          </div>

                          <div className={styles.formGrid}>
                            <label className={styles.field}>
                              تاریخ قطع
                              <input
                                type="date"
                                value={stopDates[medication.id] ?? ""}
                                onChange={(event) =>
                                  setStopDates((current) => ({ ...current, [medication.id]: event.target.value }))
                                }
                              />
                            </label>
                          </div>
                          <div className={styles.actions}>
                            <button
                              type="button"
                              className={styles.dangerButton}
                              disabled={busy !== null}
                              onClick={() => handleStop(medication.id)}
                            >
                              {busy === `stop-${medication.id}` ? "…" : "قطع دارو"}
                            </button>
                          </div>
                        </div>
                      </details>

                      {events.length > 0 && (
                        <div className={styles.timeline} aria-label={`تاریخچه ${medication.drug_name}`}>
                          {events.map((event) => (
                            <div className={styles.timelineItem} key={event.id}>
                              <strong>
                                {event.event_type === "start"
                                  ? "شروع"
                                  : event.event_type === "stop"
                                    ? "قطع"
                                    : "تغییر دوز"}
                              </strong>
                              {event.dose ? ` · ${event.dose}` : ""}
                              <div className={styles.listMeta}>{formatJalali(event.event_date)}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </article>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {inactive.length > 0 && (
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>داروهای قطع‌شده</h3>
            <div className={styles.subsectionBody}>
              <ul className={styles.list}>
                {inactive.map((medication) => (
                  <li key={medication.id} className={styles.listItem}>
                    <div className={styles.listMain}>
                      <div className={styles.listTitle}>{medication.drug_name}</div>
                      <div className={styles.listMeta}>
                        {medication.dose || "—"} · قطع در {formatJalali(medication.end_date)}
                      </div>
                    </div>
                    <span className={`${styles.badge} ${styles.badgeMuted}`}>قطع‌شده</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

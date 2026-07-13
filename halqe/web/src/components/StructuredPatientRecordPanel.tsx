"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  apiAddPatientClinicalNote,
  apiAddPatientCondition,
  apiAddPatientLabResult,
  apiAddPatientMedicalHistory,
  apiAddPatientSurgery,
  apiDeactivatePatientCondition,
  apiDeletePatientClinicalNote,
  apiDeletePatientLabResult,
  apiDeletePatientMedicalHistory,
  apiDeletePatientSurgery,
  apiPatchPatientRecordFlags,
  type RecordFlagDTO,
  type StructuredPatientRecordDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import styles from "./patient-record.module.css";

interface StructuredPatientRecordPanelProps {
  uuid: string;
  record: StructuredPatientRecordDTO | null;
  loading: boolean;
  error: string | null;
  onChanged: () => void | Promise<void>;
}

interface ConditionForm {
  conditionId: string;
  stage: string;
  onsetDate: string;
  notes: string;
}

interface DatedTextForm {
  title: string;
  date: string;
  note: string;
}

interface LabForm {
  catalogKey: string;
  testName: string;
  value: string;
  unit: string;
  refLow: string;
  refHigh: string;
  takenAt: string;
  notes: string;
}

const EMPTY_CONDITION: ConditionForm = {
  conditionId: "",
  stage: "",
  onsetDate: "",
  notes: "",
};

const EMPTY_DATED_TEXT: DatedTextForm = { title: "", date: "", note: "" };

const EMPTY_LAB: LabForm = {
  catalogKey: "",
  testName: "",
  value: "",
  unit: "",
  refLow: "",
  refHigh: "",
  takenAt: "",
  notes: "",
};

const NOTE_LABELS: Record<string, string> = {
  symptom: "علائم",
  exam: "معاینه",
  lifestyle: "سبک زندگی",
  general: "عمومی",
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    scheduled: "برنامه‌ریزی‌شده",
    done: "انجام‌شده",
    no_show: "عدم مراجعه",
    cancelled: "لغوشده",
    open: "باز",
    dismissed: "مختومه",
  };
  return labels[status] ?? status;
}

function truthyFlag(value: string | null): boolean {
  return ![null, "", "0", "false", "False", "no", "off"].includes(value);
}

export function StructuredPatientRecordPanel({
  uuid,
  record,
  loading,
  error,
  onChanged,
}: StructuredPatientRecordPanelProps) {
  const [condition, setCondition] = useState<ConditionForm>(EMPTY_CONDITION);
  const [surgery, setSurgery] = useState<DatedTextForm>(EMPTY_DATED_TEXT);
  const [history, setHistory] = useState<DatedTextForm>(EMPTY_DATED_TEXT);
  const [noteKind, setNoteKind] = useState<"symptom" | "exam" | "lifestyle" | "general">("general");
  const [noteBody, setNoteBody] = useState("");
  const [lab, setLab] = useState<LabForm>(EMPTY_LAB);
  const [flagDraft, setFlagDraft] = useState<Record<string, string | boolean>>({});
  const [flagTouched, setFlagTouched] = useState<Set<string>>(new Set());
  const [flagCleared, setFlagCleared] = useState<Set<string>>(new Set());
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const activeConditions = useMemo(
    () => (record?.conditions ?? []).filter((item) => item.is_active),
    [record?.conditions],
  );
  const inactiveConditions = useMemo(
    () => (record?.conditions ?? []).filter((item) => !item.is_active),
    [record?.conditions],
  );
  const flagsBySection = useMemo(() => {
    const groups: Record<string, RecordFlagDTO[]> = {};
    for (const item of record?.flag_catalog ?? []) {
      const key = item.record_section || "general";
      (groups[key] ??= []).push(item);
    }
    return groups;
  }, [record?.flag_catalog]);

  useEffect(() => {
    const next: Record<string, string | boolean> = {};
    for (const item of record?.flag_catalog ?? []) {
      next[item.flag_key] =
        item.flag_type === "bool" ? truthyFlag(item.value) : item.value ?? "";
    }
    setFlagDraft(next);
    setFlagTouched(new Set());
    setFlagCleared(new Set());
  }, [record?.flag_catalog]);

  async function runAction(key: string, operation: () => Promise<unknown>, success: string) {
    setBusyKey(key);
    setLocalError(null);
    setNotice(null);
    try {
      await operation();
      setNotice(success);
      await onChanged();
      return true;
    } catch (err) {
      setLocalError(errorText(err, "عملیات پرونده ناموفق بود."));
      return false;
    } finally {
      setBusyKey(null);
    }
  }

  async function submitCondition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!condition.conditionId) {
      setLocalError("یک بیماری را انتخاب کنید.");
      return;
    }
    const ok = await runAction(
      "condition:add",
      () =>
        apiAddPatientCondition(uuid, {
          condition_id: Number(condition.conditionId),
          stage: condition.stage.trim() || null,
          onset_date: condition.onsetDate || null,
          notes: condition.notes.trim() || null,
        }),
      "بیماری مزمن به پرونده افزوده شد.",
    );
    if (ok) setCondition(EMPTY_CONDITION);
  }

  async function removeCondition(id: number, title: string) {
    if (!window.confirm(`بیماری «${title}» از حالت فعال خارج شود؟`)) return;
    await runAction(
      `condition:${id}`,
      () => apiDeactivatePatientCondition(uuid, id),
      "بیماری از حالت فعال خارج شد؛ سابقهٔ آن حفظ شده است.",
    );
  }

  function updateFlag(item: RecordFlagDTO, value: string | boolean) {
    setFlagDraft((current) => ({ ...current, [item.flag_key]: value }));
    setFlagTouched((current) => new Set(current).add(item.flag_key));
    setFlagCleared((current) => {
      const next = new Set(current);
      next.delete(item.flag_key);
      return next;
    });
  }

  function clearDateFlag(item: RecordFlagDTO) {
    setFlagDraft((current) => ({ ...current, [item.flag_key]: "" }));
    setFlagTouched((current) => new Set(current).add(item.flag_key));
    setFlagCleared((current) => new Set(current).add(item.flag_key));
  }

  async function saveFlags() {
    if (flagTouched.size === 0) {
      setLocalError("هیچ فلگی تغییر نکرده است.");
      return;
    }
    const values: Record<string, unknown> = {};
    for (const key of flagTouched) {
      if (!flagCleared.has(key)) values[key] = flagDraft[key];
    }
    const ok = await runAction(
      "flags",
      () =>
        apiPatchPatientRecordFlags(uuid, {
          values,
          clear_keys: [...flagCleared],
        }),
      "فلگ‌های بالینی با حفظ مقادیر ارسال‌نشده ذخیره شدند.",
    );
    if (ok) {
      setFlagTouched(new Set());
      setFlagCleared(new Set());
    }
  }

  async function submitSurgery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!surgery.title.trim()) {
      setLocalError("عنوان جراحی الزامی است.");
      return;
    }
    const ok = await runAction(
      "surgery:add",
      () => apiAddPatientSurgery(uuid, surgery.title.trim(), surgery.date || null, surgery.note.trim() || null),
      "سابقهٔ جراحی ثبت شد.",
    );
    if (ok) setSurgery(EMPTY_DATED_TEXT);
  }

  async function submitHistory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!history.title.trim()) {
      setLocalError("عنوان سابقهٔ پزشکی الزامی است.");
      return;
    }
    const ok = await runAction(
      "history:add",
      () => apiAddPatientMedicalHistory(uuid, history.title.trim(), history.date || null, history.note.trim() || null),
      "سابقهٔ پزشکی ثبت شد.",
    );
    if (ok) setHistory(EMPTY_DATED_TEXT);
  }

  async function submitNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!noteBody.trim()) {
      setLocalError("متن یادداشت الزامی است.");
      return;
    }
    const ok = await runAction(
      "note:add",
      () => apiAddPatientClinicalNote(uuid, noteKind, noteBody.trim()),
      "یادداشت بالینی ثبت شد.",
    );
    if (ok) setNoteBody("");
  }

  function chooseLab(key: string) {
    const catalog = record?.lab_catalog.find((item) => item.test_key === key);
    setLab((current) => ({
      ...current,
      catalogKey: key,
      testName: catalog?.name_fa ?? "",
      unit: catalog?.unit ?? "",
      refLow: catalog?.ref_low == null ? "" : String(catalog.ref_low),
      refHigh: catalog?.ref_high == null ? "" : String(catalog.ref_high),
    }));
  }

  async function submitLab(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!lab.catalogKey && !lab.testName.trim()) {
      setLocalError("آزمایش کاتالوگ یا نام آزمایش آزاد را وارد کنید.");
      return;
    }
    const numericValue = lab.value === "" ? null : Number(lab.value);
    if (numericValue !== null && !Number.isFinite(numericValue)) {
      setLocalError("مقدار آزمایش عدد معتبر نیست.");
      return;
    }
    const ok = await runAction(
      "lab:add",
      () =>
        apiAddPatientLabResult(uuid, {
          test_key: lab.catalogKey || null,
          test_name: lab.catalogKey ? null : lab.testName.trim(),
          value: numericValue,
          unit: lab.unit.trim() || null,
          ref_low: lab.refLow === "" ? null : Number(lab.refLow),
          ref_high: lab.refHigh === "" ? null : Number(lab.refHigh),
          taken_at: lab.takenAt ? new Date(lab.takenAt).toISOString() : null,
          notes: lab.notes.trim() || null,
        }),
      "نتیجهٔ آزمایش ثبت و وارد جریان Observation شد.",
    );
    if (ok) setLab(EMPTY_LAB);
  }

  return (
    <section className={styles.workspace} aria-labelledby="structured-record-title">
      <div className={styles.workspaceHeader}>
        <div>
          <h2 id="structured-record-title">پروندهٔ ساختاریافته</h2>
          <p>انتقال دقیق سابقه‌ها، فلگ‌ها، آزمایش‌ها و پیگیری‌ها از کلینیک تخصصی</p>
        </div>
        <span className={styles.countBadge}>{toFarsiDigits(activeConditions.length)} بیماری فعال</span>
      </div>

      {(error || localError) && <div className={styles.errorBox} role="alert">{localError || error}</div>}
      {notice && <div className={styles.noticeBox} role="status" aria-live="polite">{notice}</div>}
      {loading && <div className={styles.stateBox}>در حال بارگذاری پروندهٔ ساختاریافته…</div>}

      {!loading && record && (
        <div className={styles.workspaceStack}>
          <section className={styles.formCard}>
            <div className={styles.formTitle}>بیماری‌های مزمن</div>
            <form onSubmit={submitCondition}>
              <div className={styles.gridFour}>
                <label>
                  بیماری
                  <select value={condition.conditionId} onChange={(event) => setCondition((current) => ({ ...current, conditionId: event.target.value }))}>
                    <option value="">انتخاب کنید</option>
                    {record.condition_catalog.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  مرحله
                  <input value={condition.stage} onChange={(event) => setCondition((current) => ({ ...current, stage: event.target.value }))} />
                </label>
                <label>
                  شروع
                  <input type="date" value={condition.onsetDate} onChange={(event) => setCondition((current) => ({ ...current, onsetDate: event.target.value }))} />
                </label>
                <label>
                  یادداشت
                  <input value={condition.notes} onChange={(event) => setCondition((current) => ({ ...current, notes: event.target.value }))} />
                </label>
              </div>
              <div className={styles.formActions}>
                <button type="submit" className={styles.primaryButton} disabled={busyKey !== null}>افزودن بیماری</button>
              </div>
            </form>
            <div className={styles.chipList}>
              {activeConditions.map((item) => (
                <div key={item.id} className={styles.conditionChip}>
                  <span><strong>{item.condition_name || item.condition_code}</strong>{item.stage && <small>{item.stage}</small>}</span>
                  <button type="button" onClick={() => removeCondition(item.id, item.condition_name || item.condition_code || "بیماری")} disabled={busyKey !== null}>غیرفعال‌کردن</button>
                </div>
              ))}
            </div>
            {inactiveConditions.length > 0 && (
              <details className={styles.archiveBlock}>
                <summary>سوابق غیرفعال ({toFarsiDigits(inactiveConditions.length)})</summary>
                <ul className={styles.simpleList}>
                  {inactiveConditions.map((item) => <li key={item.id}>{item.condition_name || item.condition_code}</li>)}
                </ul>
              </details>
            )}
          </section>

          <section className={styles.formCard}>
            <div className={styles.formTitle}>فلگ‌های تصمیم‌یار</div>
            <p className={styles.helperText}>فقط کلیدهای تغییرکرده ارسال می‌شوند؛ پاک‌کردن تاریخ نیازمند دکمهٔ صریح «پاک‌کردن» است.</p>
            {Object.entries(flagsBySection).map(([section, items]) => (
              <fieldset key={section} className={styles.flagGroup}>
                <legend>{section}</legend>
                <div className={styles.gridThree}>
                  {items.map((item) => (
                    <div key={item.flag_key} className={styles.flagField}>
                      {item.flag_type === "bool" ? (
                        <label className={styles.checkboxLabel}>
                          <input type="checkbox" checked={Boolean(flagDraft[item.flag_key])} onChange={(event) => updateFlag(item, event.target.checked)} />
                          {item.label}
                        </label>
                      ) : item.flag_type === "enum" ? (
                        <label>
                          {item.label}
                          <select value={String(flagDraft[item.flag_key] ?? "")} onChange={(event) => updateFlag(item, event.target.value)}>
                            <option value="">انتخاب نشده</option>
                            {item.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                          </select>
                        </label>
                      ) : item.flag_type === "date" ? (
                        <label>
                          {item.label}
                          <div className={styles.dateWithClear}>
                            <input type="date" value={String(flagDraft[item.flag_key] ?? "")} onChange={(event) => updateFlag(item, event.target.value)} />
                            <button type="button" onClick={() => clearDateFlag(item)}>پاک‌کردن</button>
                          </div>
                        </label>
                      ) : (
                        <label>
                          {item.label}
                          <input value={String(flagDraft[item.flag_key] ?? "")} onChange={(event) => updateFlag(item, event.target.value)} />
                        </label>
                      )}
                      {item.notes && <small>{item.notes}</small>}
                    </div>
                  ))}
                </div>
              </fieldset>
            ))}
            <div className={styles.formActions}>
              <button type="button" className={styles.primaryButton} onClick={saveFlags} disabled={busyKey !== null || flagTouched.size === 0}>ذخیرهٔ تغییرات فلگ‌ها</button>
            </div>
          </section>

          <div className={styles.gridTwoTop}>
            <section className={styles.formCard}>
              <div className={styles.formTitle}>سابقهٔ جراحی</div>
              <form onSubmit={submitSurgery}>
                <label>عنوان<input value={surgery.title} onChange={(event) => setSurgery((current) => ({ ...current, title: event.target.value }))} required /></label>
                <div className={styles.gridTwo}>
                  <label>تاریخ<input type="date" value={surgery.date} onChange={(event) => setSurgery((current) => ({ ...current, date: event.target.value }))} /></label>
                  <label>یادداشت<input value={surgery.note} onChange={(event) => setSurgery((current) => ({ ...current, note: event.target.value }))} /></label>
                </div>
                <div className={styles.formActions}><button type="submit" className={styles.primaryButton} disabled={busyKey !== null}>ثبت جراحی</button></div>
              </form>
              <ul className={styles.recordRows}>
                {record.surgeries.map((item) => (
                  <li key={item.id}><span><strong>{item.title}</strong><small>{item.performed_on ? formatJalali(item.performed_on) : "بدون تاریخ"}{item.note ? ` — ${item.note}` : ""}</small></span><button type="button" onClick={() => runAction(`surgery:${item.id}`, () => apiDeletePatientSurgery(uuid, item.id), "سابقهٔ جراحی حذف شد.")}>حذف</button></li>
                ))}
              </ul>
            </section>

            <section className={styles.formCard}>
              <div className={styles.formTitle}>سابقهٔ پزشکی</div>
              <form onSubmit={submitHistory}>
                <label>عنوان<input value={history.title} onChange={(event) => setHistory((current) => ({ ...current, title: event.target.value }))} required /></label>
                <div className={styles.gridTwo}>
                  <label>از تاریخ<input type="date" value={history.date} onChange={(event) => setHistory((current) => ({ ...current, date: event.target.value }))} /></label>
                  <label>یادداشت<input value={history.note} onChange={(event) => setHistory((current) => ({ ...current, note: event.target.value }))} /></label>
                </div>
                <div className={styles.formActions}><button type="submit" className={styles.primaryButton} disabled={busyKey !== null}>ثبت سابقه</button></div>
              </form>
              <ul className={styles.recordRows}>
                {record.medical_history.map((item) => (
                  <li key={item.id}><span><strong>{item.title}</strong><small>{item.since ? formatJalali(item.since) : "بدون تاریخ"}{item.note ? ` — ${item.note}` : ""}</small></span><button type="button" onClick={() => runAction(`history:${item.id}`, () => apiDeletePatientMedicalHistory(uuid, item.id), "سابقهٔ پزشکی حذف شد.")}>حذف</button></li>
                ))}
              </ul>
            </section>
          </div>

          <section className={styles.formCard}>
            <div className={styles.formTitle}>یادداشت‌های بالینی</div>
            <form onSubmit={submitNote}>
              <div className={styles.gridTwo}>
                <label>
                  نوع
                  <select value={noteKind} onChange={(event) => setNoteKind(event.target.value as typeof noteKind)}>
                    <option value="general">عمومی</option>
                    <option value="symptom">علائم</option>
                    <option value="exam">معاینه</option>
                    <option value="lifestyle">سبک زندگی</option>
                  </select>
                </label>
                <label>متن<textarea rows={3} value={noteBody} onChange={(event) => setNoteBody(event.target.value)} required /></label>
              </div>
              <div className={styles.formActions}><button type="submit" className={styles.primaryButton} disabled={busyKey !== null}>ثبت یادداشت</button></div>
            </form>
            <ul className={styles.recordRows}>
              {record.clinical_notes.map((item) => (
                <li key={item.id}><span><strong>{NOTE_LABELS[item.kind] ?? item.kind}</strong><small>{formatJalali(item.recorded_at)} — {item.body}</small></span><button type="button" onClick={() => runAction(`note:${item.id}`, () => apiDeletePatientClinicalNote(uuid, item.id), "یادداشت حذف شد.")}>حذف</button></li>
              ))}
            </ul>
          </section>

          <section className={styles.formCard}>
            <div className={styles.formTitle}>نتایج آزمایش</div>
            <form onSubmit={submitLab}>
              <div className={styles.gridFour}>
                <label>
                  آزمایش کاتالوگ
                  <select value={lab.catalogKey} onChange={(event) => chooseLab(event.target.value)}>
                    <option value="">آزمایش آزاد</option>
                    {record.lab_catalog.map((item) => <option key={item.id} value={item.test_key}>{item.suggested ? "★ " : ""}{item.name_fa}</option>)}
                  </select>
                </label>
                <label>نام آزاد<input value={lab.testName} disabled={Boolean(lab.catalogKey)} onChange={(event) => setLab((current) => ({ ...current, testName: event.target.value }))} /></label>
                <label>مقدار<input inputMode="decimal" dir="ltr" value={lab.value} onChange={(event) => setLab((current) => ({ ...current, value: event.target.value }))} /></label>
                <label>واحد<input value={lab.unit} onChange={(event) => setLab((current) => ({ ...current, unit: event.target.value }))} /></label>
              </div>
              <div className={styles.gridFour}>
                <label>حد پایین<input inputMode="decimal" dir="ltr" value={lab.refLow} onChange={(event) => setLab((current) => ({ ...current, refLow: event.target.value }))} /></label>
                <label>حد بالا<input inputMode="decimal" dir="ltr" value={lab.refHigh} onChange={(event) => setLab((current) => ({ ...current, refHigh: event.target.value }))} /></label>
                <label>زمان<input type="datetime-local" value={lab.takenAt} onChange={(event) => setLab((current) => ({ ...current, takenAt: event.target.value }))} /></label>
                <label>یادداشت<input value={lab.notes} onChange={(event) => setLab((current) => ({ ...current, notes: event.target.value }))} /></label>
              </div>
              <div className={styles.formActions}><button type="submit" className={styles.primaryButton} disabled={busyKey !== null}>ثبت آزمایش</button></div>
            </form>
            <div className={styles.tableWrap}>
              <table>
                <thead><tr><th>آزمایش</th><th>مقدار</th><th>محدوده</th><th>زمان</th><th>عملیات</th></tr></thead>
                <tbody>
                  {record.labs.map((item) => (
                    <tr key={item.id}><td>{item.test_name}</td><td>{item.value ?? "—"} {item.unit || ""}</td><td>{item.ref_low ?? "—"} تا {item.ref_high ?? "—"}</td><td>{formatJalali(item.taken_at)}</td><td><button type="button" className={styles.textDangerButton} onClick={() => runAction(`lab:${item.id}`, () => apiDeletePatientLabResult(uuid, item.id), "نتیجهٔ آزمایش حذف شد.")}>حذف</button></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className={styles.gridTwoTop}>
            <section className={styles.readCard}>
              <h3>نوبت‌ها</h3>
              <ul className={styles.recordRows}>
                {record.appointments.slice(0, 20).map((item) => <li key={item.id}><span><strong>{item.appt_type || "نوبت"}</strong><small>{formatJalali(item.scheduled_at)} — {statusLabel(item.status)}</small></span></li>)}
              </ul>
            </section>
            <section className={styles.readCard}>
              <h3>پیگیری‌ها</h3>
              <ul className={styles.recordRows}>
                {record.followups.slice(0, 20).map((item) => <li key={item.id}><span><strong>{item.reason || "پیگیری"}</strong><small>{item.due_date ? formatJalali(item.due_date) : "بدون سررسید"} — {statusLabel(item.status)}</small>{item.detail && <small>{item.detail}</small>}</span></li>)}
              </ul>
            </section>
          </div>

          <section className={styles.readCard}>
            <h3>نسخه‌های قبلی</h3>
            <div className={styles.prescriptionGrid}>
              {record.prescriptions.map((item) => (
                <article key={item.id} className={styles.prescriptionCard}>
                  <div className={styles.recordItemHeader}><strong>{item.kind}</strong><span>{formatJalali(item.issued_at)}</span></div>
                  <small>{item.mode === "insurance" ? `بیمه: ${item.insurer || "—"}` : "نسخه آزاد"}</small>
                  <ul>{item.items.map((line, index) => <li key={line.id ?? `${item.id}:${index}`}><strong>{line.drug_name}</strong> {[line.dose_value, line.dose_unit, line.frequency].filter(Boolean).join(" — ")}</li>)}</ul>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

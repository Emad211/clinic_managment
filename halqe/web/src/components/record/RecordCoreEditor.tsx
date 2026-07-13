"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  apiAddClinicalNote,
  apiAddMedicalHistory,
  apiAddRecordCondition,
  apiAddSurgery,
  apiDeleteClinicalNote,
  apiDeleteMedicalHistory,
  apiDeleteSurgery,
  apiRemoveRecordCondition,
  apiUpdateRecordFlags,
  type ClinicalNoteDTO,
  type PatientRecordDataDTO,
  type RecordFlagCatalogDTO,
} from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import styles from "./record-editor.module.css";

interface Props {
  uuid: string;
  data: PatientRecordDataDTO;
  onChanged: () => Promise<void> | void;
}

const NOTE_LABELS: Record<ClinicalNoteDTO["kind"], string> = {
  symptom: "علائم و شکایت",
  exam: "معاینه",
  lifestyle: "سبک زندگی",
  general: "یادداشت عمومی",
};

const FLAG_SECTION_LABELS: Record<RecordFlagCatalogDTO["record_section"], string> = {
  disease: "بیماری و ریسک",
  lifestyle: "سبک زندگی",
  exam: "معاینه و غربالگری",
  general: "وضعیت عمومی",
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function RecordCoreEditor({ uuid, data, onChanged }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [conditionId, setConditionId] = useState("");
  const [conditionStage, setConditionStage] = useState("");
  const [conditionOnset, setConditionOnset] = useState("");
  const [conditionNotes, setConditionNotes] = useState("");

  const [surgeryTitle, setSurgeryTitle] = useState("");
  const [surgeryDate, setSurgeryDate] = useState("");
  const [surgeryNote, setSurgeryNote] = useState("");

  const [historyTitle, setHistoryTitle] = useState("");
  const [historySince, setHistorySince] = useState("");
  const [historyNote, setHistoryNote] = useState("");

  const [noteKind, setNoteKind] = useState<ClinicalNoteDTO["kind"]>("symptom");
  const [noteBody, setNoteBody] = useState("");

  const [flagValues, setFlagValues] = useState<Record<string, string | boolean>>({});

  const activeConditions = data.conditions.filter((row) => row.is_active);
  const inactiveConditions = data.conditions.filter((row) => !row.is_active);

  const flagGroups = useMemo(() => {
    const result: Record<string, RecordFlagCatalogDTO[]> = {};
    for (const definition of data.flag_catalog) {
      const section = definition.record_section || "general";
      (result[section] ??= []).push(definition);
    }
    return result;
  }, [data.flag_catalog]);

  useEffect(() => {
    const next: Record<string, string | boolean> = {};
    for (const definition of data.flag_catalog) {
      const stored = data.patient_flags[definition.flag_key];
      next[definition.flag_key] =
        definition.flag_type === "bool" ? stored === "1" : stored ?? "";
    }
    setFlagValues(next);
  }, [data.flag_catalog, data.patient_flags]);

  async function mutate(
    key: string,
    action: () => Promise<unknown>,
    successText: string,
  ): Promise<boolean> {
    setBusy(key);
    setError(null);
    setSuccess(null);
    try {
      await action();
      await onChanged();
      setSuccess(successText);
      return true;
    } catch (err) {
      setError(errorText(err, "ثبت تغییرات پرونده ناموفق بود."));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function addCondition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!conditionId) {
      setError("یک بیماری انتخاب کنید.");
      return;
    }
    const ok = await mutate(
      "condition-add",
      () =>
        apiAddRecordCondition(uuid, {
          condition_id: Number(conditionId),
          stage: conditionStage.trim() || null,
          onset_date: conditionOnset || null,
          notes: conditionNotes.trim() || null,
        }),
      "بیماری به پرونده افزوده شد.",
    );
    if (ok) {
      setConditionId("");
      setConditionStage("");
      setConditionOnset("");
      setConditionNotes("");
    }
  }

  async function addSurgery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await mutate(
      "surgery-add",
      () =>
        apiAddSurgery(uuid, {
          title: surgeryTitle.trim(),
          performed_on: surgeryDate || null,
          note: surgeryNote.trim() || null,
        }),
      "سابقهٔ جراحی ثبت شد.",
    );
    if (ok) {
      setSurgeryTitle("");
      setSurgeryDate("");
      setSurgeryNote("");
    }
  }

  async function addHistory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await mutate(
      "history-add",
      () =>
        apiAddMedicalHistory(uuid, {
          title: historyTitle.trim(),
          since: historySince || null,
          note: historyNote.trim() || null,
        }),
      "سابقهٔ پزشکی ثبت شد.",
    );
    if (ok) {
      setHistoryTitle("");
      setHistorySince("");
      setHistoryNote("");
    }
  }

  async function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await mutate(
      "note-add",
      () => apiAddClinicalNote(uuid, { kind: noteKind, body: noteBody.trim() }),
      "یادداشت بالینی ثبت شد.",
    );
    if (ok) setNoteBody("");
  }

  async function saveFlagSection(section: string, definitions: RecordFlagCatalogDTO[]) {
    const managedKeys = definitions.map((item) => item.flag_key);
    const values = Object.fromEntries(
      managedKeys.map((key) => [key, flagValues[key] ?? ""]),
    );
    await mutate(
      `flags-${section}`,
      () => apiUpdateRecordFlags(uuid, { managed_keys: managedKeys, values }),
      `بخش «${FLAG_SECTION_LABELS[section as RecordFlagCatalogDTO["record_section"]] ?? section}» ذخیره شد.`,
    );
  }

  function renderFlag(definition: RecordFlagCatalogDTO) {
    const value = flagValues[definition.flag_key];
    if (definition.flag_type === "bool") {
      return (
        <label className={styles.checkField} key={definition.flag_key}>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) =>
              setFlagValues((current) => ({
                ...current,
                [definition.flag_key]: event.target.checked,
              }))
            }
          />
          {definition.label}
        </label>
      );
    }

    if (definition.flag_type === "enum") {
      return (
        <label className={styles.field} key={definition.flag_key}>
          {definition.label}
          <select
            value={typeof value === "string" ? value : ""}
            onChange={(event) =>
              setFlagValues((current) => ({
                ...current,
                [definition.flag_key]: event.target.value,
              }))
            }
          >
            <option value="">ثبت نشده</option>
            {definition.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      );
    }

    return (
      <label className={styles.field} key={definition.flag_key}>
        {definition.label}
        <input
          type={definition.flag_type === "date" ? "date" : "text"}
          value={typeof value === "string" ? value : ""}
          onChange={(event) =>
            setFlagValues((current) => ({
              ...current,
              [definition.flag_key]: event.target.value,
            }))
          }
        />
        {definition.flag_type === "date" && (
          <span className={styles.listMeta}>
            خالی گذاشتن تاریخ، مقدار قبلی را حفظ می‌کند.
          </span>
        )}
      </label>
    );
  }

  return (
    <div className={styles.stack}>
      {(error || success) && (
        <div className={styles.statusRow} role={error ? "alert" : "status"} aria-live="polite">
          <span className={error ? styles.error : styles.success}>{error ?? success}</span>
        </div>
      )}

      <section className={styles.section} aria-labelledby="record-conditions-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-conditions-title">بیماری‌های مزمن</h2>
            <p>افزودن تکراری مسدود و حذف به‌صورت غیرفعال‌سازی قابل بازگشت انجام می‌شود.</p>
          </div>
          <span className={styles.count}>{toFarsiDigits(activeConditions.length)} بیماری فعال</span>
        </header>
        <div className={`${styles.sectionBody} ${styles.gridTwo}`}>
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>وضعیت فعلی</h3>
            <div className={styles.subsectionBody}>
              {activeConditions.length === 0 ? (
                <div className={styles.empty}>بیماری فعالی ثبت نشده است.</div>
              ) : (
                <ul className={styles.list}>
                  {activeConditions.map((condition) => (
                    <li className={styles.listItem} key={condition.id}>
                      <div className={styles.listMain}>
                        <div className={styles.listTitle}>
                          {condition.condition_name || condition.condition_code || "بیماری"}
                          {condition.stage && <span className={styles.badge}>{condition.stage}</span>}
                        </div>
                        <div className={styles.listMeta}>
                          شروع: {formatJalali(condition.onset_date)} · ثبت: {formatJalali(condition.diagnosed_at)}
                        </div>
                        {condition.notes && <div className={styles.listNote}>{condition.notes}</div>}
                      </div>
                      <button
                        type="button"
                        className={styles.dangerButton}
                        disabled={busy !== null}
                        onClick={() =>
                          mutate(
                            `condition-delete-${condition.id}`,
                            () => apiRemoveRecordCondition(uuid, condition.id),
                            "بیماری از فهرست فعال خارج شد.",
                          )
                        }
                      >
                        {busy === `condition-delete-${condition.id}` ? "…" : "غیرفعال‌کردن"}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {inactiveConditions.length > 0 && (
                <div className={styles.listMeta}>
                  {toFarsiDigits(inactiveConditions.length)} بیماری غیرفعال در سابقه نگهداری شده است.
                </div>
              )}
            </div>
          </div>

          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>افزودن یا فعال‌سازی مجدد</h3>
            <div className={styles.subsectionBody}>
              <form className={styles.form} onSubmit={addCondition}>
                <label className={styles.field}>
                  بیماری
                  <select value={conditionId} onChange={(event) => setConditionId(event.target.value)} required>
                    <option value="">انتخاب کنید</option>
                    {data.condition_catalog.map((condition) => (
                      <option key={condition.id} value={condition.id}>{condition.name}</option>
                    ))}
                  </select>
                </label>
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    مرحله / نوع
                    <input value={conditionStage} onChange={(event) => setConditionStage(event.target.value)} />
                  </label>
                  <label className={styles.field}>
                    تاریخ شروع
                    <input type="date" value={conditionOnset} onChange={(event) => setConditionOnset(event.target.value)} />
                  </label>
                </div>
                <label className={styles.field}>
                  توضیحات
                  <textarea value={conditionNotes} onChange={(event) => setConditionNotes(event.target.value)} rows={3} />
                </label>
                <button className={styles.button} disabled={busy !== null} type="submit">
                  {busy === "condition-add" ? "در حال ثبت…" : "ثبت بیماری"}
                </button>
              </form>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="record-history-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-history-title">سوابق پزشکی و جراحی</h2>
            <p>سوابق ساختاریافته با تاریخ و توضیح مستقل نگهداری می‌شوند.</p>
          </div>
        </header>
        <div className={`${styles.sectionBody} ${styles.gridTwo}`}>
          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>سابقه پزشکی</h3>
            <div className={`${styles.subsectionBody} ${styles.stack}`}>
              <form className={styles.form} onSubmit={addHistory}>
                <label className={styles.field}>عنوان<input value={historyTitle} onChange={(event) => setHistoryTitle(event.target.value)} required /></label>
                <label className={styles.field}>از تاریخ<input type="date" value={historySince} onChange={(event) => setHistorySince(event.target.value)} /></label>
                <label className={styles.field}>توضیح<textarea value={historyNote} onChange={(event) => setHistoryNote(event.target.value)} rows={2} /></label>
                <button className={styles.button} disabled={busy !== null} type="submit">ثبت سابقه پزشکی</button>
              </form>
              {data.medical_history.length === 0 ? <div className={styles.empty}>سابقه‌ای ثبت نشده است.</div> : (
                <ul className={styles.list}>
                  {data.medical_history.map((row) => (
                    <li className={styles.listItem} key={row.id}>
                      <div className={styles.listMain}>
                        <div className={styles.listTitle}>{row.title}</div>
                        <div className={styles.listMeta}>{formatJalali(row.since)}</div>
                        {row.note && <div className={styles.listNote}>{row.note}</div>}
                      </div>
                      <button type="button" className={styles.dangerButton} disabled={busy !== null} onClick={() => mutate(`history-delete-${row.id}`, () => apiDeleteMedicalHistory(uuid, row.id), "سابقه پزشکی حذف شد.")}>حذف</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className={styles.subsection}>
            <h3 className={styles.subsectionHeader}>سابقه جراحی</h3>
            <div className={`${styles.subsectionBody} ${styles.stack}`}>
              <form className={styles.form} onSubmit={addSurgery}>
                <label className={styles.field}>عنوان جراحی<input value={surgeryTitle} onChange={(event) => setSurgeryTitle(event.target.value)} required /></label>
                <label className={styles.field}>تاریخ جراحی<input type="date" value={surgeryDate} onChange={(event) => setSurgeryDate(event.target.value)} /></label>
                <label className={styles.field}>توضیح<textarea value={surgeryNote} onChange={(event) => setSurgeryNote(event.target.value)} rows={2} /></label>
                <button className={styles.button} disabled={busy !== null} type="submit">ثبت سابقه جراحی</button>
              </form>
              {data.surgeries.length === 0 ? <div className={styles.empty}>جراحی‌ای ثبت نشده است.</div> : (
                <ul className={styles.list}>
                  {data.surgeries.map((row) => (
                    <li className={styles.listItem} key={row.id}>
                      <div className={styles.listMain}>
                        <div className={styles.listTitle}>{row.title}</div>
                        <div className={styles.listMeta}>{formatJalali(row.performed_on)}</div>
                        {row.note && <div className={styles.listNote}>{row.note}</div>}
                      </div>
                      <button type="button" className={styles.dangerButton} disabled={busy !== null} onClick={() => mutate(`surgery-delete-${row.id}`, () => apiDeleteSurgery(uuid, row.id), "سابقه جراحی حذف شد.")}>حذف</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="record-flags-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-flags-title">ورودی‌های ساختاریافتهٔ بالینی</h2>
            <p>هر گروه مستقل ذخیره می‌شود؛ تغییر یک گروه سایر فلگ‌ها را پاک نمی‌کند.</p>
          </div>
        </header>
        <div className={`${styles.sectionBody} ${styles.flagGroups}`}>
          {Object.entries(flagGroups).map(([section, definitions]) => (
            <div className={styles.subsection} key={section}>
              <h3 className={styles.subsectionHeader}>
                {FLAG_SECTION_LABELS[section as RecordFlagCatalogDTO["record_section"]] ?? section}
              </h3>
              <div className={`${styles.subsectionBody} ${styles.flagList}`}>
                {definitions.map(renderFlag)}
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={busy !== null}
                  onClick={() => saveFlagSection(section, definitions)}
                >
                  {busy === `flags-${section}` ? "در حال ذخیره…" : "ذخیره این بخش"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="record-notes-title">
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="record-notes-title">علائم، معاینه و یادداشت‌های بالینی</h2>
            <p>متن بالینی در پرونده می‌ماند و در توضیح audit کپی نمی‌شود.</p>
          </div>
          <span className={styles.count}>{toFarsiDigits(data.notes.length)} یادداشت</span>
        </header>
        <div className={`${styles.sectionBody} ${styles.gridTwo}`}>
          <form className={styles.form} onSubmit={addNote}>
            <label className={styles.field}>
              نوع یادداشت
              <select value={noteKind} onChange={(event) => setNoteKind(event.target.value as ClinicalNoteDTO["kind"])}>
                {Object.entries(NOTE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label className={styles.field}>
              متن
              <textarea value={noteBody} onChange={(event) => setNoteBody(event.target.value)} rows={6} required />
            </label>
            <button className={styles.button} disabled={busy !== null} type="submit">ثبت یادداشت</button>
          </form>
          <div>
            {data.notes.length === 0 ? <div className={styles.empty}>یادداشتی ثبت نشده است.</div> : (
              <ul className={styles.list}>
                {data.notes.map((note) => (
                  <li className={styles.listItem} key={note.id}>
                    <div className={styles.listMain}>
                      <div className={styles.listTitle}>{NOTE_LABELS[note.kind]}</div>
                      <div className={styles.listMeta}>{formatJalali(note.recorded_at)} · {note.recorded_by || "—"}</div>
                      <div className={styles.listNote}>{note.body}</div>
                    </div>
                    <button type="button" className={styles.dangerButton} disabled={busy !== null} onClick={() => mutate(`note-delete-${note.id}`, () => apiDeleteClinicalNote(uuid, note.id), "یادداشت حذف شد.")}>حذف</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

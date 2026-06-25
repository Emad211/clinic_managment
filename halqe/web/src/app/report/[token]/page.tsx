/**
 * /report/[token] — فرمِ self-reportِ بیمار (PWA، عمومی، بدونِ JWT)
 *
 * قراردادِ بک‌اند (تأییدشده):
 *   POST /api/v1/patient-report/{token}
 *   body: { readings: [{ type, value }] }
 *   200 → { status:"ok", accepted, count, message }  — توکن مصرف می‌شود
 *   404 → توکن used/invalid/expired
 *   422 → validation/خارج‌از‌بازه  — توکن مصرف نمی‌شود
 *   429 → rate-limit
 *
 * آفلاین‌سینک: هنگامِ آفلاین/خطای شبکه → صف در localStorage.
 * رویدادِ online + بارگذاری → flush صف.
 *
 * محدودیت‌ها:
 *   - بدونِ dependency جدید
 *   - بدونِ PHI در URL (فقط token)
 *   - بدونِ useAuth
 *   - RTL/فارسی، inputهای درشت (بیمارِ سالمندِ موبایل)
 *   - validation کلاینت هم‌تراز با بک‌اند (همان بازه‌ها)
 */

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import {
  submitReport,
  ApiError,
  type SelfReportReading,
} from "@/lib/api";
import { toFarsiDigits } from "@/lib/jalali";
import styles from "./report.module.css";

// ────────────────────────────────────────────────────────────
// ثابت‌های validation (هم‌تراز با بک‌اند)
// ────────────────────────────────────────────────────────────

const RANGES: Record<SelfReportReading["type"], { min: number; max: number }> =
  {
    fbs: { min: 20, max: 800 },
    bp_systolic: { min: 50, max: 300 },
    bp_diastolic: { min: 20, max: 200 },
  };

// ────────────────────────────────────────────────────────────
// صف آفلاین در localStorage
// ────────────────────────────────────────────────────────────

const QUEUE_KEY = "halqe_report_queue";

interface QueuedReport {
  token: string;
  readings: SelfReportReading[];
  queuedAt: number; // unix ms
}

function loadQueue(): QueuedReport[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as QueuedReport[];
  } catch {
    return [];
  }
}

function saveQueue(queue: QueuedReport[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  } catch {
    // storage full — نادیده بگیر
  }
}

function enqueue(token: string, readings: SelfReportReading[]): void {
  const q = loadQueue();
  // اگر همین توکن قبلاً در صف هست، جایگزین کن
  const filtered = q.filter((item) => item.token !== token);
  filtered.push({ token, readings, queuedAt: Date.now() });
  saveQueue(filtered);
}

function dequeue(token: string): void {
  const q = loadQueue().filter((item) => item.token !== token);
  saveQueue(q);
}

// ────────────────────────────────────────────────────────────
// تبدیلِ رقمِ فارسی/عربی به ASCII (برای parse)
// ────────────────────────────────────────────────────────────

function normalizeDigits(str: string): string {
  return str
    .replace(/[۰-۹]/g, (d) =>
      String.fromCharCode(d.charCodeAt(0) - 0x06f0 + 0x30),
    )
    .replace(/[٠-٩]/g, (d) =>
      String.fromCharCode(d.charCodeAt(0) - 0x0660 + 0x30),
    );
}

// ────────────────────────────────────────────────────────────
// نوع‌های state
// ────────────────────────────────────────────────────────────

type SubmitPhase =
  | "idle"        // منتظرِ ورودی
  | "submitting"  // در حالِ ارسال
  | "success"     // ۲۰۰ — مصرف‌شده
  | "expired"     // ۴۰۴ — مصرف یا نامعتبر
  | "rate_limit"  // ۴۲۹
  | "server_error"; // ۵xx / خطای دیگر

// ────────────────────────────────────────────────────────────
// تعریفِ فیلدهای فرم
// ────────────────────────────────────────────────────────────

interface FieldDef {
  key: SelfReportReading["type"];
  label: string;
  unit: string;
  hint: string;
  placeholder: string;
}

const FIELDS: FieldDef[] = [
  {
    key: "fbs",
    label: "قند ناشتا",
    unit: "mg/dL",
    hint: `بازهٔ مجاز: ${toFarsiDigits(20)}–${toFarsiDigits(800)}`,
    placeholder: "مثال: ۱۲۰",
  },
  {
    key: "bp_systolic",
    label: "فشار خون — عدد بالا (سیستول)",
    unit: "mmHg",
    hint: `بازهٔ مجاز: ${toFarsiDigits(50)}–${toFarsiDigits(300)}`,
    placeholder: "مثال: ۱۲۰",
  },
  {
    key: "bp_diastolic",
    label: "فشار خون — عدد پایین (دیاستول)",
    unit: "mmHg",
    hint: `بازهٔ مجاز: ${toFarsiDigits(20)}–${toFarsiDigits(200)}`,
    placeholder: "مثال: ۸۰",
  },
];

// ────────────────────────────────────────────────────────────
// صفحهٔ اصلی
// ────────────────────────────────────────────────────────────

export default function SelfReportPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";

  // ── مقادیرِ فیلدها (string — همانطور که کاربر تایپ می‌کند) ──
  const [values, setValues] = useState<Record<string, string>>({
    fbs: "",
    bp_systolic: "",
    bp_diastolic: "",
  });

  // ── خطاهای validation کلاینت ──
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // ── وضعیتِ submit ──
  const [phase, setPhase] = useState<SubmitPhase>("idle");

  // ── پیامِ خطای submit ──
  const [submitErrorMsg, setSubmitErrorMsg] = useState<string>("");

  // ── آفلاین ──
  const [isOffline, setIsOffline] = useState<boolean>(
    typeof navigator !== "undefined" ? !navigator.onLine : false,
  );
  const [showQueuedMsg, setShowQueuedMsg] = useState<boolean>(false);

  // ── ref برای جلوگیری از double-flush ──
  const flushing = useRef(false);

  // ────────────────────────────────────────────────────────
  // flush صف آفلاین
  // ────────────────────────────────────────────────────────
  const flushQueue = useCallback(async () => {
    if (flushing.current) return;
    flushing.current = true;
    try {
      const queue = loadQueue();
      if (queue.length === 0) return;
      for (const item of queue) {
        try {
          await submitReport(item.token, item.readings);
          dequeue(item.token);
          // اگر توکنِ این صفحه مصرف شد، فرم را قفل کن
          if (item.token === token) {
            setPhase("success");
            setShowQueuedMsg(false);
          }
        } catch (err) {
          if (err instanceof ApiError) {
            if (err.status === 404 || err.status === 422) {
              // قابلِ اصلاح نیست — از صف حذف کن
              dequeue(item.token);
              if (item.token === token) {
                if (err.status === 404) setPhase("expired");
                else {
                  setPhase("server_error");
                  setSubmitErrorMsg(
                    "داده‌های ذخیره‌شده معتبر نبودند. دوباره اقدام کنید.",
                  );
                }
                setShowQueuedMsg(false);
              }
            }
            // ۴۲۹ یا غیره → نگه‌دار در صف
          }
          // خطای شبکه → نگه‌دار در صف
        }
      }
    } finally {
      flushing.current = false;
    }
  }, [token]);

  // ────────────────────────────────────────────────────────
  // رویدادهای online/offline
  // ────────────────────────────────────────────────────────
  useEffect(() => {
    function handleOnline() {
      setIsOffline(false);
      flushQueue();
    }
    function handleOffline() {
      setIsOffline(true);
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    // flush در بارگذاری صفحه اگر آنلاینیم
    if (navigator.onLine) flushQueue();
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [flushQueue]);

  // ────────────────────────────────────────────────────────
  // تغییرِ ورودی
  // ────────────────────────────────────────────────────────
  function handleChange(key: string, raw: string) {
    setValues((prev) => ({ ...prev, [key]: raw }));
    // پاکِ کردنِ خطای آن فیلد
    if (fieldErrors[key]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  }

  // ────────────────────────────────────────────────────────
  // validation کلاینت
  // ────────────────────────────────────────────────────────
  function validate(): SelfReportReading[] | null {
    const errors: Record<string, string> = {};
    const readings: SelfReportReading[] = [];

    for (const field of FIELDS) {
      const raw = values[field.key].trim();
      if (raw === "") continue; // خالی = بیمار ندارد

      const normalized = normalizeDigits(raw);
      const num = Number(normalized);
      if (!Number.isFinite(num) || normalized === "") {
        errors[field.key] = "مقدار وارد شده عدد نیست.";
        continue;
      }
      const { min, max } = RANGES[field.key];
      if (num < min || num > max) {
        errors[field.key] =
          `مقدارِ ${field.label} باید بین ${toFarsiDigits(min)} و ${toFarsiDigits(max)} باشد.`;
        continue;
      }
      readings.push({ type: field.key, value: num });
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return null;
    }

    if (readings.length === 0) {
      setFieldErrors({ _form: "حداقل یک مقدار را وارد کنید." });
      return null;
    }

    return readings;
  }

  // ────────────────────────────────────────────────────────
  // ارسال فرم
  // ────────────────────────────────────────────────────────
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFieldErrors({});
    setSubmitErrorMsg("");

    const readings = validate();
    if (!readings) return;

    // آفلاین → صف
    if (!navigator.onLine) {
      enqueue(token, readings);
      setShowQueuedMsg(true);
      return;
    }

    setPhase("submitting");
    try {
      await submitReport(token, readings);
      setPhase("success");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          setPhase("expired");
        } else if (err.status === 422) {
          setPhase("idle");
          setSubmitErrorMsg(
            err.message || "مقداری خارج از بازهٔ مجاز است. دوباره بررسی کنید.",
          );
        } else if (err.status === 429) {
          setPhase("rate_limit");
        } else {
          setPhase("server_error");
          setSubmitErrorMsg("خطای سرور. کمی بعد دوباره امتحان کنید.");
        }
      } else {
        // خطای شبکه
        enqueue(token, readings);
        setShowQueuedMsg(true);
        setPhase("idle");
      }
    }
  }

  // ────────────────────────────────────────────────────────
  // رندر — وضعیت‌های خاص
  // ────────────────────────────────────────────────────────

  if (phase === "success") {
    return (
      <div className={styles.page} dir="rtl">
        <header className={styles.header}>
          <div className={styles.clinicName}>درمانگاهِ حلقه</div>
        </header>
        <div
          className={styles.successBox}
          role="alert"
          data-testid="report-success-box"
        >
          <span className={styles.successIcon} aria-hidden="true">
            &#10003;
          </span>
          <p className={styles.successTitle}>اطلاعات ثبت شد</p>
          <p className={styles.successHint}>
            پزشک شما این اطلاعات را بررسی خواهد کرد.
          </p>
        </div>
        <footer className={styles.footer}>
          <p className={styles.footerNote}>
            این اطلاعات فقط برای اطلاع‌رسانی به پزشک است.
          </p>
        </footer>
      </div>
    );
  }

  if (phase === "expired") {
    return (
      <div className={styles.page} dir="rtl">
        <div
          className={styles.expiredBox}
          role="alert"
          data-testid="report-expired-box"
        >
          <div className={styles.expiredIcon} aria-hidden="true">!</div>
          <p className={styles.expiredTitle}>این لینک قبلاً استفاده شده یا نامعتبر است</p>
          <p className={styles.expiredHint}>
            برای دریافتِ لینکِ جدید با درمانگاه تماس بگیرید.
          </p>
        </div>
      </div>
    );
  }

  if (phase === "rate_limit") {
    return (
      <div className={styles.page} dir="rtl">
        <div
          className={styles.errorBanner}
          role="alert"
          data-testid="report-rate-limit"
        >
          کمی بعد دوباره امتحان کنید.
        </div>
      </div>
    );
  }

  // ────────────────────────────────────────────────────────
  // رندرِ فرم
  // ────────────────────────────────────────────────────────
  const isSubmitting = phase === "submitting";
  const isLocked = isSubmitting;

  return (
    <div className={styles.page} dir="rtl">
      <header className={styles.header}>
        <div className={styles.clinicName}>درمانگاهِ حلقه</div>
        <h1 className={styles.title}>گزارشِ اندازه‌گیری</h1>
        <p className={styles.subtitle}>
          مقادیری که دارید وارد کنید. هر فیلد که ندارید خالی بگذارید.
        </p>
      </header>

      {/* banner آفلاین / صف‌شده */}
      {showQueuedMsg && (
        <div
          className={styles.offlineBanner}
          role="status"
          aria-live="polite"
          data-testid="report-queued-msg"
        >
          اطلاعات ذخیره شد؛ هنگامِ اتصال به اینترنت ارسال می‌شود.
        </div>
      )}

      {/* پیامِ خطای آفلاین (قبل از صف) */}
      {isOffline && !showQueuedMsg && (
        <div
          className={styles.offlineBanner}
          role="status"
          aria-live="polite"
          data-testid="report-offline-msg"
        >
          اتصال به اینترنت ندارید. پس از ارسال، ذخیره خواهد شد.
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        noValidate
        aria-label="فرمِ گزارشِ اندازه‌گیری"
        className={styles.form}
        data-testid="report-form"
      >
        {FIELDS.map((field) => (
          <div key={field.key} className={styles.fieldGroup}>
            <label
              htmlFor={`input-${field.key}`}
              className={styles.label}
            >
              {field.label}
              <span
                style={{ fontWeight: 400, fontSize: "0.8125rem", marginRight: "0.375rem", color: "#6b7d8f" }}
              >
                ({field.unit})
              </span>
            </label>
            <p className={styles.hint}>{field.hint}</p>
            <input
              id={`input-${field.key}`}
              type="text"
              inputMode="numeric"
              className={styles.input}
              value={values[field.key]}
              onChange={(e) => handleChange(field.key, e.target.value)}
              placeholder={field.placeholder}
              disabled={isLocked}
              aria-label={`${field.label} به ${field.unit}`}
              aria-describedby={
                fieldErrors[field.key] ? `error-${field.key}` : undefined
              }
              aria-invalid={fieldErrors[field.key] ? "true" : undefined}
              data-testid={`input-${field.key}`}
              autoComplete="off"
            />
            {fieldErrors[field.key] && (
              <p
                id={`error-${field.key}`}
                className={styles.fieldError}
                role="alert"
                data-testid={`error-${field.key}`}
              >
                {fieldErrors[field.key]}
              </p>
            )}
          </div>
        ))}

        {/* خطای کلِ فرم */}
        {fieldErrors._form && (
          <p
            className={styles.fieldError}
            role="alert"
            data-testid="error-form"
          >
            {fieldErrors._form}
          </p>
        )}

        {/* خطای submit */}
        {submitErrorMsg && (
          <div
            className={styles.errorBanner}
            role="alert"
            data-testid="report-submit-error"
          >
            {submitErrorMsg}
          </div>
        )}

        <button
          type="submit"
          className={styles.submitBtn}
          disabled={isLocked}
          aria-busy={isSubmitting}
          data-testid="report-submit-btn"
        >
          {isSubmitting ? "در حالِ ارسال…" : "ارسالِ اطلاعات"}
        </button>
      </form>

      <footer className={styles.footer}>
        <p className={styles.footerNote}>
          این اطلاعات فقط برای اطلاع‌رسانی به پزشک است. تصمیمِ درمانی با پزشک است.
        </p>
      </footer>
    </div>
  );
}

/**
 * /card/[token] — صفحهٔ کارتِ بیمارِ عمومی
 *
 * این صفحه کاملاً عمومی است (بدونِ JWT / useAuth).
 * بیمار لینکِ کارت را از درمانگاه دریافت می‌کند و با گوشی باز می‌کند.
 *
 * قراردادِ بک‌اند (تأییدشده):
 *   GET /api/v1/card/{token}  → CardResponse (بدونِ national_id/PHI)
 *   توکنِ نامعتبر/منقضی/revoked → 404
 *
 * محدودیت‌های UI:
 *   - read-only مطلق: هیچ فرم/دکمهٔ اقدام
 *   - هیچ national_id/PHI در UI یا URL (فقط توکن در path)
 *   - ارقام فارسی با toFarsiDigits
 *   - تاریخ جلالی با formatJalali
 *   - RTL/Vazirmatn، موبایل-اول
 */

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getCard, ApiError, type CardResponse, type CardVital } from "@/lib/api";
import { formatJalali, toFarsiDigits } from "@/lib/jalali";
import styles from "./card.module.css";

// ────────────────────────────────────────────────────────────
// Status helpers
// ────────────────────────────────────────────────────────────

const STATUS_CLASS: Record<CardVital["status"], string> = {
  ok: styles.statusOk,
  warn: styles.statusWarn,
  danger: styles.statusDanger,
};

const STATUS_LABEL: Record<CardVital["status"], string> = {
  ok: "عادی",
  warn: "احتیاط",
  danger: "خطر",
};

const STATUS_ARIA: Record<CardVital["status"], string> = {
  ok: "وضعیت: عادی",
  warn: "وضعیت: احتیاط — نیاز به بررسی",
  danger: "وضعیت: خطر — بررسی فوری",
};

// ────────────────────────────────────────────────────────────
// کامپوننتِ کارتِ یک ویتال
// ────────────────────────────────────────────────────────────

function VitalCard({ vital }: { vital: CardVital }) {
  const cls = STATUS_CLASS[vital.status] ?? styles.statusOk;
  const label = STATUS_LABEL[vital.status] ?? "";
  const aria = STATUS_ARIA[vital.status] ?? "";

  return (
    <div
      className={`${styles.vitalCard} ${cls}`}
      role="listitem"
      aria-label={`${vital.label}: ${toFarsiDigits(vital.value)} ${vital.unit} — ${label}`}
      data-status={vital.status}
      data-testid={`vital-card-${vital.key}`}
    >
      <div className={styles.vitalLabel}>{vital.label}</div>
      <div className={styles.vitalValueRow} aria-label={aria}>
        <span className={styles.vitalValue} data-testid={`vital-value-${vital.key}`}>
          {toFarsiDigits(vital.value)}
        </span>
        {vital.unit && (
          <span className={styles.vitalUnit}>{vital.unit}</span>
        )}
      </div>
      <div
        className={styles.statusBadge}
        aria-hidden="true"
        data-testid={`vital-status-${vital.key}`}
      >
        {label}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// صفحهٔ اصلی
// ────────────────────────────────────────────────────────────

type PageState =
  | { phase: "loading" }
  | { phase: "error404" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; data: CardResponse };

export default function PatientCardPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";

  const [state, setState] = useState<PageState>({ phase: "loading" });

  useEffect(() => {
    if (!token) {
      setState({ phase: "error404" });
      return;
    }

    let cancelled = false;

    getCard(token)
      .then((data) => {
        if (!cancelled) setState({ phase: "loaded", data });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setState({ phase: "error404" });
        } else {
          const msg =
            err instanceof ApiError
              ? `خطا: ${err.message}`
              : "بارگذاری کارت ناموفق بود. دوباره امتحان کنید.";
          setState({ phase: "error", message: msg });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  // ── Loading ─────────────────────────────────────────────
  if (state.phase === "loading") {
    return (
      <div className={styles.page} dir="rtl">
        <div className={styles.stateBox} role="status" aria-live="polite">
          <span className={styles.spinner} aria-hidden="true" />
          در حال بارگذاری کارت…
        </div>
      </div>
    );
  }

  // ── 404 (توکنِ نامعتبر/منقضی/revoked) ─────────────────
  if (state.phase === "error404") {
    return (
      <div className={styles.page} dir="rtl">
        <div
          className={styles.errorBox}
          role="alert"
          data-testid="card-expired-message"
        >
          <div className={styles.errorIcon} aria-hidden="true">!</div>
          <p className={styles.errorTitle}>کارت منقضی شده یا نامعتبر است</p>
          <p className={styles.errorHint}>
            برای دریافتِ کارتِ جدید با درمانگاه تماس بگیرید.
          </p>
        </div>
      </div>
    );
  }

  // ── خطای دیگر ──────────────────────────────────────────
  if (state.phase === "error") {
    return (
      <div className={styles.page} dir="rtl">
        <div className={styles.errorBox} role="alert">
          <p className={styles.errorTitle}>{state.message}</p>
        </div>
      </div>
    );
  }

  // ── Loaded ──────────────────────────────────────────────
  const { data } = state;

  return (
    <div className={styles.page} dir="rtl">
      {/* Header: خوشامد */}
      <header className={styles.header}>
        <div className={styles.clinicName} data-testid="card-clinic-name">
          {data.clinic_name ?? "درمانگاه حلقه"}
        </div>
        {data.first_name && (
          <p className={styles.greeting} data-testid="card-greeting">
            سلام{" "}
            <span className={styles.greetingName}>{data.first_name}</span>
            {"‌"}عزیز
          </p>
        )}
      </header>

      {/* Framing — safety note */}
      {data.framing && (
        <div
          className={styles.framingBanner}
          role="note"
          data-testid="card-framing"
        >
          {data.framing}
        </div>
      )}

      {/* Vitals */}
      {data.vitals.length > 0 ? (
        <section
          className={styles.vitalsSection}
          aria-label="شاخص‌های سلامت"
          data-testid="card-vitals-section"
        >
          <h2 className={styles.sectionTitle}>شاخص‌های سلامت</h2>
          <div
            className={styles.vitalsGrid}
            role="list"
            aria-label="فهرست شاخص‌های سلامت"
          >
            {data.vitals.map((v) => (
              <VitalCard key={v.key} vital={v} />
            ))}
          </div>
        </section>
      ) : (
        <section className={styles.vitalsSection} aria-label="شاخص‌های سلامت">
          <p className={styles.emptyNote} data-testid="card-no-vitals">
            اطلاعاتِ اندازه‌گیری ثبت نشده است.
          </p>
        </section>
      )}

      {/*
        یادآورِ غربالگری — بخشِ informationalِ بیمار-ایمن (قدم ۴۸، خوشهٔ J).

        فقط وقتی رندر می‌شود که reminder_message غیرnull/غیرخالی باشد.
        رنگِ خنثی/آبی — هرگز danger و هرگز هم‌سطحِ ویتالِ خطر.
        متن دقیقاً همان رشتهٔ از-قبل-رندرشدهٔ بک‌اند است؛ هیچ‌چیز اضافه/استنتاج نمی‌کنیم.
        null/خالی → هیچ بخشی رندر نمی‌شود (نه بخشِ خالی).
      */}
      {data.reminder_message && (
        <section
          className={styles.reminderSection}
          role="note"
          aria-label="یادآوریِ مراقبت"
          data-testid="card-reminder-section"
        >
          <span className={styles.reminderIcon} aria-hidden="true">
            {/* آیکونِ زنگِ یادآوری — inline SVG، بدونِ CDN */}
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
          </span>
          <p className={styles.reminderText} data-testid="card-reminder-text">
            {data.reminder_message}
          </p>
        </section>
      )}

      {/* نوبتِ بعدی */}
      <section
        className={styles.appointmentSection}
        aria-label="نوبتِ بعدی"
        data-testid="card-appointment-section"
      >
        <h2 className={styles.sectionTitle}>نوبتِ بعدی</h2>
        <div
          className={styles.appointmentDate}
          data-testid="card-next-appointment"
        >
          {data.next_appointment
            ? formatJalali(data.next_appointment)
            : "—"}
        </div>
      </section>

      {/* Footer */}
      <footer className={styles.footer}>
        <p className={styles.footerNote}>
          این کارت فقط برای اطلاع‌رسانی است. تصمیمِ درمانی با پزشک است.
        </p>
      </footer>
    </div>
  );
}

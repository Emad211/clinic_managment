/**
 * PatientCardShare — افزونهٔ staff برای کارتِ عمومیِ بیمار (قدم ۴۸، خوشهٔ J).
 *
 * در صفحهٔ پروندهٔ بیمار رندر می‌شود. به staff اجازه می‌دهد:
 *   ۱) توکنِ کارتِ عمومی را صادر کند (POST /patients/{uuid}/card-token).
 *   ۲) لینکِ کارت را با یک کلیک کپی کند (از card_url).
 *   ۳) «ارسالِ پیامکِ کارت» — دکمهٔ گِیت‌شده و disabled.
 *
 * تصمیمِ امنیتی (option ب — گِیت‌شده، بدونِ ارسالِ واقعی):
 *   دکمهٔ SMS همیشه disabled است و هیچ‌گاه هیچ فراخوانیِ APIِ پیامک نمی‌کند.
 *   تا تکمیلِ احراز هویتِ پنلِ پیامکی (KYC) و راه‌اندازیِ دامنهٔ امن غیرفعال می‌ماند.
 *
 * ایمنی/حریمِ خصوصی:
 *   - هیچ PHI در URL: card_url فقط /card/<token> است (توکنِ opaque).
 *   - توکن یک‌بار در پاسخِ issue نمایش داده می‌شود؛ این کامپوننت آن را persist نمی‌کند.
 */

"use client";

import { useState } from "react";
import { issueCardToken, ApiError, type CardTokenOut } from "@/lib/api";
import { formatJalali } from "@/lib/jalali";
import styles from "./PatientCardShare.module.css";

/**
 * پیامِ کنارِ دکمهٔ SMSِ گِیت‌شده. متن دقیق و ثابت — بخشی از قراردادِ امنیتی.
 */
const SMS_GATE_NOTE =
  "پس از تکمیلِ احراز هویتِ پنلِ پیامکی (KYC) و راه‌اندازیِ دامنهٔ امن فعال می‌شود.";

/**
 * Build an absolute, copy-able URL from the backend's relative card_url path.
 * The backend returns only a path (LAN-only). On the server (no window) we
 * fall back to the bare path — the copy button only runs in the browser.
 */
function absoluteCardUrl(cardUrl: string): string {
  if (typeof window === "undefined") return cardUrl;
  return `${window.location.origin}${cardUrl}`;
}

export function PatientCardShare({ uuid }: { uuid: string }) {
  const [tokenData, setTokenData] = useState<CardTokenOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleIssue() {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const data = await issueCardToken(uuid);
      setTokenData(data);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `صدورِ کارت ناموفق بود: ${err.message}`
          : "صدورِ کارت ناموفق بود. دوباره امتحان کنید.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy() {
    if (!tokenData) return;
    const url = absoluteCardUrl(tokenData.card_url);
    try {
      // مسیرِ مدرن
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        // fallback: انتخابِ متنِ یک textarea موقت
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      // برگرداندنِ برچسب به حالتِ اولیه بعد از ۲ ثانیه
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // اگر کپی شکست خورد، لینک همچنان روی صفحه برای کپیِ دستی هست
      setError("کپیِ خودکار ناموفق بود — لینک را دستی کپی کنید.");
    }
  }

  return (
    <section
      className={`${styles.cardShare}`}
      aria-label="کارتِ عمومیِ بیمار"
      data-testid="patient-card-share"
    >
      <h2 className={styles.title}>کارتِ بیمار</h2>
      <p className={styles.hint}>
        کارتِ خلاصهٔ سلامتِ بیمار — قابلِ نمایش با موبایل (QR/لینک). بدونِ کدِ ملی یا تشخیص.
      </p>

      {/* دکمهٔ صدور / تجدیدِ توکن */}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.issueBtn}
          onClick={handleIssue}
          disabled={busy}
          aria-busy={busy}
          data-testid="card-issue-btn"
        >
          {busy
            ? "در حال صدور…"
            : tokenData
              ? "صدورِ لینکِ جدید"
              : "صدورِ لینکِ کارت"}
        </button>
      </div>

      {error && (
        <div className={styles.error} role="alert" data-testid="card-share-error">
          {error}
        </div>
      )}

      {/* لینکِ صادرشده + اکشن‌ها */}
      {tokenData && (
        <div className={styles.tokenBox} data-testid="card-token-box">
          <label className={styles.linkLabel} htmlFor="card-link-field">
            لینکِ کارت
          </label>
          <input
            id="card-link-field"
            className={styles.linkField}
            type="text"
            value={absoluteCardUrl(tokenData.card_url)}
            readOnly
            dir="ltr"
            onFocus={(e) => e.currentTarget.select()}
            data-testid="card-link-field"
            aria-label="لینکِ کارتِ بیمار"
          />

          <p className={styles.expiry} data-testid="card-expiry">
            معتبر تا: {formatJalali(tokenData.expires_at)}
          </p>

          <div className={styles.linkActions}>
            {/* کپیِ لینک — کارآمد */}
            <button
              type="button"
              className={styles.copyBtn}
              onClick={handleCopy}
              data-testid="card-copy-btn"
              aria-live="polite"
            >
              {copied ? "کپی شد ✓" : "کپیِ لینکِ کارت"}
            </button>

            {/* ارسالِ پیامک — گِیت‌شده، disabled، بدونِ ارسالِ واقعی */}
            <button
              type="button"
              className={styles.smsBtn}
              disabled
              aria-disabled="true"
              data-testid="card-sms-btn"
              aria-describedby="card-sms-gate-note"
              title={SMS_GATE_NOTE}
            >
              ارسالِ پیامکِ کارت به بیمار
            </button>
          </div>

          <p
            id="card-sms-gate-note"
            className={styles.smsNote}
            role="note"
            data-testid="card-sms-gate-note"
          >
            {SMS_GATE_NOTE}
          </p>
        </div>
      )}
    </section>
  );
}

export default PatientCardShare;

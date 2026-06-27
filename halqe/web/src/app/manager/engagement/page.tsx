"use client";

/**
 * Manager Engagement — /manager/engagement  (cluster L, step 52).
 *
 * Manager-only. Two tabs:
 *   1) صف تأیید  — the human gate before any message goes out.
 *   2) تنظیمات   — event→channel routing + guardrails (quiet hours, daily cap).
 *
 * SAFETY (locked by the ux-ui + clinical-product gathering):
 *   - A persistent simulation banner sits at the very top: the live Kavenegar
 *     account is in KYC hold (code 430), so /send only SIMULATES (NullProvider).
 *     The UI NEVER says «ارسال شد» — a successful send shows «ثبت‌شده (شبیه‌سازی)».
 *   - ANTI RUBBER-STAMPING: every pending item is a CARD that renders the exact
 *     verbatim message (dir="auto", distinct surface), opt-out / consent badges,
 *     and a stale-contact warning. There is NO «approve all» — each item is an
 *     individual decision. Send requires a confirm dialog.
 *
 * All copy Persian/RTL, Jalali dates, offline (no chart lib, no new deps).
 */

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import {
  getRole,
  getEngagementApprovals,
  approveEngagementApproval,
  rejectEngagementApproval,
  sendEngagementApproval,
  getEngagementEvents,
  updateEngagementEvent,
  getEngagementSettings,
  updateEngagementSettings,
  ApiError,
  ENGAGEMENT_CHANNEL_LABEL,
  type EngagementApproval,
  type EngagementEvent,
  type EngagementChannel,
  type EngagementSettings,
  type SendApprovalResult,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { toFarsiDigits, formatJalali } from "@/lib/jalali";
import Nav from "@/components/Nav";
import styles from "./engagement.module.css";

type TabKey = "queue" | "settings";

// ─────────────────────────────────────────────────────────────
// Persistent simulation banner — always at the top of the page.
// ─────────────────────────────────────────────────────────────

function SimulationBanner() {
  return (
    <div
      className={styles.simBanner}
      role="note"
      aria-label="هشدارِ حالتِ شبیه‌سازی"
    >
      <span className={styles.simBannerTitle}>حالتِ شبیه‌سازی</span>
      <span className={styles.simBannerBody}>
        به‌دلیلِ تکمیل‌نشدنِ احرازِ هویتِ پنل (KYC)، پیام واقعاً ارسال نمی‌شود و
        فقط در سیستم ثبت می‌گردد.
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Per-card send result → a neutral/blocked/pending chip.
// In simulation, ok=true renders the NEUTRAL «ثبت‌شده (شبیه‌سازی)» chip,
// NEVER a green «ارسال شد».
// ─────────────────────────────────────────────────────────────

function sendResultText(r: SendApprovalResult): {
  text: string;
  cls: string;
} {
  if (r.pending) {
    return { text: "در انتظارِ سامانه", cls: styles.resultPending };
  }
  if (r.ok) {
    return { text: "ثبت‌شده (شبیه‌سازی)", cls: styles.resultNeutral };
  }
  // blocked by a guardrail
  switch (r.reason) {
    case "opt_out":
      return { text: "ردشده: انصراف", cls: styles.resultBlocked };
    case "no_phone":
      return { text: "ردشده: بدونِ شماره", cls: styles.resultBlocked };
    case "quiet":
      return { text: "ردشده: ساعتِ سکوت", cls: styles.resultBlocked };
    default:
      return { text: "انجام نشد", cls: styles.resultBlocked };
  }
}

// ─────────────────────────────────────────────────────────────
// Stale-contact heuristic — if the last contact is AFTER the due date
// (or there is no due date but a recent contact), the action may no
// longer be necessary. Surfaced as a soft yellow note.
// ─────────────────────────────────────────────────────────────

function isStale(item: EngagementApproval): boolean {
  if (!item.last_contact_at) return false;
  if (!item.due_date) return false;
  // Compare date parts only (last_contact_at is a datetime).
  const contactDay = item.last_contact_at.slice(0, 10);
  return contactDay >= item.due_date;
}

// ─────────────────────────────────────────────────────────────
// Approval card — the anti rubber-stamp unit.
// ─────────────────────────────────────────────────────────────

function ApprovalCard({
  item,
  busy,
  result,
  onApprove,
  onReject,
  onSend,
}: {
  item: EngagementApproval;
  busy: boolean;
  result: SendApprovalResult | null;
  onApprove: () => void;
  onReject: () => void;
  onSend: () => void;
}) {
  const stale = isStale(item);
  // Once a send has a result, the message is recorded — block re-sending.
  const canSend = item.status === "approved" && !result;

  return (
    <article
      className={styles.card}
      aria-label={`پیامِ ${item.patient_name} — ${item.event_label}`}
      aria-busy={busy}
    >
      <div className={styles.cardHeader}>
        <span className={styles.cardPatient}>{item.patient_name}</span>
        <span className={styles.cardEvent}>{item.event_label}</span>
        <span className={styles.cardDue}>
          سررسید: {formatJalali(item.due_date)}
        </span>
      </div>

      {/* Verbatim message — exactly what would be sent. */}
      <div>
        <span className={styles.messageLabel}>متنِ پیام (عیناً ارسال می‌شود):</span>
        <blockquote className={styles.message} dir="auto">
          {item.message}
        </blockquote>
      </div>

      {/* Metadata strip */}
      <div className={styles.metaStrip}>
        <span className={`${styles.badge} ${styles.badgeNeutral}`}>
          کانال: {item.channel}
        </span>
        {item.sms_opt_out && (
          <span className={`${styles.badge} ${styles.badgeDanger}`}>
            انصراف از پیامک
          </span>
        )}
        {!item.sms_consent && (
          <span
            className={`${styles.badge} ${styles.badgeWarn}`}
            title="وضعیتِ رضایت فقط نمایشی است؛ هنوز به‌صورتِ خودکار مانعِ ارسال نمی‌شود — تصمیمِ ارسال با مدیر است."
          >
            بدونِ رضایتِ پیامک
          </span>
        )}
        {!item.sms_consent && (
          <span className={styles.consentNote}>
            (نمایشی — هنوز اعمال نمی‌شود)
          </span>
        )}
        <span className={styles.metaItem}>
          آخرین تماس: {formatJalali(item.last_contact_at)}
        </span>
        {stale && (
          <span className={styles.staleNote}>
            ممکن است دیگر لازم نباشد
          </span>
        )}
      </div>

      {/* Actions — NO «approve all». Each item decided on its own. */}
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={onApprove}
          disabled={busy || item.status !== "pending"}
        >
          تأیید
        </button>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnDanger}`}
          onClick={onReject}
          disabled={busy || item.status !== "pending"}
        >
          رد
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={onSend}
          disabled={busy || !canSend}
          title={canSend ? undefined : "ابتدا باید تأیید شود"}
        >
          ارسال
        </button>
        {result && (
          <span className={`${styles.resultChip} ${sendResultText(result).cls}`}>
            {sendResultText(result).text}
          </span>
        )}
      </div>
    </article>
  );
}

// ─────────────────────────────────────────────────────────────
// Reject modal — optional reason.
// ─────────────────────────────────────────────────────────────

function RejectModal({
  item,
  onCancel,
  onConfirm,
}: {
  item: EngagementApproval;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className={styles.modalOverlay} role="presentation" onClick={onCancel}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-label="ردِ پیام"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className={styles.modalTitle}>ردِ پیامِ {item.patient_name}</h2>
        <p className={styles.modalBody}>
          این پیام رد می‌شود و از صف خارج می‌گردد. علتِ رد اختیاری است.
        </p>
        <label className={styles.fieldLabel} htmlFor="reject-reason">
          علتِ رد (اختیاری)
        </label>
        <textarea
          id="reject-reason"
          className={styles.modalTextarea}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          dir="auto"
        />
        <div className={styles.modalActions}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnDanger}`}
            onClick={() => onConfirm(reason.trim())}
          >
            ردِ پیام
          </button>
          <button type="button" className={styles.btn} onClick={onCancel}>
            انصراف
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Send confirm modal — summary + verbatim text + simulation sentence.
// ─────────────────────────────────────────────────────────────

function SendConfirmModal({
  item,
  onCancel,
  onConfirm,
}: {
  item: EngagementApproval;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className={styles.modalOverlay} role="presentation" onClick={onCancel}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-label="تأییدِ ارسال"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className={styles.modalTitle}>ارسالِ پیام به {item.patient_name}</h2>
        <p className={styles.modalBody}>
          متنِ زیر برای «{item.event_label}» ثبت می‌شود:
        </p>
        <blockquote className={styles.modalQuote} dir="auto">
          {item.message}
        </blockquote>
        <p className={styles.modalSim}>
          در حالتِ شبیه‌سازی پیام واقعاً ارسال نمی‌شود و فقط در سیستم ثبت می‌گردد.
        </p>
        <div className={styles.modalActions}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={onConfirm}
          >
            ثبتِ ارسال
          </button>
          <button type="button" className={styles.btn} onClick={onCancel}>
            انصراف
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Queue tab
// ─────────────────────────────────────────────────────────────

interface QueueState {
  items: EngagementApproval[];
  loading: boolean;
  error: string | null;
}

function QueueTab({
  onCount,
  on401,
}: {
  onCount: (n: number) => void;
  on401: (err: unknown) => boolean;
}) {
  const [state, setState] = useState<QueueState>({
    items: [],
    loading: true,
    error: null,
  });
  const [busyId, setBusyId] = useState<number | null>(null);
  const [results, setResults] = useState<Record<number, SendApprovalResult>>({});
  const [rejecting, setRejecting] = useState<EngagementApproval | null>(null);
  const [sending, setSending] = useState<EngagementApproval | null>(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await getEngagementApprovals();
      setState({ items: res.items, loading: false, error: null });
      onCount(res.items.length);
    } catch (err) {
      if (on401(err)) return;
      let msg = "خطا در دریافتِ صف";
      if (err instanceof ApiError) {
        msg = err.status === 403 ? "دسترسی محدود است." : err.message;
      }
      setState({ items: [], loading: false, error: msg });
    }
  }, [onCount, on401]);

  useEffect(() => {
    load();
  }, [load]);

  // Remove an item from the queue (optimistic exit after a decision).
  const removeItem = useCallback(
    (id: number) => {
      setState((s) => {
        const items = s.items.filter((it) => it.id !== id);
        onCount(items.length);
        return { ...s, items };
      });
    },
    [onCount],
  );

  const doApprove = useCallback(
    async (item: EngagementApproval) => {
      setBusyId(item.id);
      try {
        await approveEngagementApproval(item.id);
        // Approved items leave the *pending* queue.
        removeItem(item.id);
      } catch (err) {
        if (on401(err)) return;
        const msg =
          err instanceof ApiError ? err.message : "خطا در تأیید";
        setState((s) => ({ ...s, error: msg }));
      } finally {
        setBusyId(null);
      }
    },
    [removeItem, on401],
  );

  const doReject = useCallback(
    async (item: EngagementApproval, reason: string) => {
      setRejecting(null);
      setBusyId(item.id);
      try {
        await rejectEngagementApproval(item.id, reason || undefined);
        removeItem(item.id);
      } catch (err) {
        if (on401(err)) return;
        const msg = err instanceof ApiError ? err.message : "خطا در رد";
        setState((s) => ({ ...s, error: msg }));
      } finally {
        setBusyId(null);
      }
    },
    [removeItem, on401],
  );

  const doSend = useCallback(
    async (item: EngagementApproval) => {
      setSending(null);
      setBusyId(item.id);
      try {
        const result = await sendEngagementApproval(item.id);
        // Keep the card in place and surface the result chip on it
        // («ثبت‌شده (شبیه‌سازی)» / «ردشده: انصراف» / …) — never «ارسال شد».
        // The card is NOT removed, so the manager sees exactly what
        // happened to each message and cannot re-send the same one.
        setResults((r) => ({ ...r, [item.id]: result }));
      } catch (err) {
        if (on401(err)) return;
        const msg = err instanceof ApiError ? err.message : "خطا در ارسال";
        setState((s) => ({ ...s, error: msg }));
      } finally {
        setBusyId(null);
      }
    },
    [removeItem, on401],
  );

  if (state.loading) {
    return (
      <div className={styles.stateBox} role="status" aria-live="polite">
        <span className={styles.spinner} aria-hidden="true" />
        در حال بارگذاری…
      </div>
    );
  }

  if (state.error) {
    return (
      <div className={styles.errorBox} role="alert">
        <p>{state.error}</p>
        <button type="button" className={styles.retryBtn} onClick={load}>
          تلاش مجدد
        </button>
      </div>
    );
  }

  if (state.items.length === 0) {
    return (
      <div className={styles.emptyBox} role="status">
        <span className={styles.emptyTitle}>صف خالی است</span>
        پیامی در انتظارِ تأیید نیست. وقتی رویدادی نیازمندِ تماس شود، اینجا ظاهر
        می‌شود.
      </div>
    );
  }

  return (
    <>
      <div className={styles.queue}>
        {state.items.map((item) => (
          <ApprovalCard
            key={item.id}
            item={item}
            busy={busyId === item.id}
            result={results[item.id] ?? null}
            onApprove={() => doApprove(item)}
            onReject={() => setRejecting(item)}
            onSend={() => setSending(item)}
          />
        ))}
      </div>

      {rejecting && (
        <RejectModal
          item={rejecting}
          onCancel={() => setRejecting(null)}
          onConfirm={(reason) => doReject(rejecting, reason)}
        />
      )}
      {sending && (
        <SendConfirmModal
          item={sending}
          onCancel={() => setSending(null)}
          onConfirm={() => doSend(sending)}
        />
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Settings tab — event→channel + quiet hours + daily cap.
// ─────────────────────────────────────────────────────────────

const CHANNEL_ORDER: EngagementChannel[] = ["sms", "worklist", "both", "off"];

/** A channel change toward sms/both means MORE items enter the queue. */
function increasesQueue(from: EngagementChannel, to: EngagementChannel): boolean {
  const sendsSms = (c: EngagementChannel) => c === "sms" || c === "both";
  return !sendsSms(from) && sendsSms(to);
}

function ChannelSegmented({
  value,
  disabled,
  onChange,
}: {
  value: EngagementChannel;
  disabled: boolean;
  onChange: (c: EngagementChannel) => void;
}) {
  return (
    <div
      className={styles.segmented}
      role="group"
      aria-label="کانالِ رویداد"
    >
      {CHANNEL_ORDER.map((c) => (
        <button
          key={c}
          type="button"
          className={`${styles.segment}${
            c === value ? ` ${styles.segmentActive}` : ""
          }`}
          aria-pressed={c === value}
          disabled={disabled}
          onClick={() => onChange(c)}
        >
          {ENGAGEMENT_CHANNEL_LABEL[c]}
        </button>
      ))}
    </div>
  );
}

function Stepper({
  value,
  min,
  max,
  disabled,
  label,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  label: string;
  onChange: (n: number) => void;
}) {
  return (
    <div className={styles.stepper}>
      <button
        type="button"
        className={styles.stepperBtn}
        aria-label={`کاهشِ ${label}`}
        disabled={disabled || value <= min}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <span className={styles.stepperValue} aria-label={label}>
        {toFarsiDigits(value)}
      </span>
      <button
        type="button"
        className={styles.stepperBtn}
        aria-label={`افزایشِ ${label}`}
        disabled={disabled || value >= max}
        onClick={() => onChange(value + 1)}
      >
        +
      </button>
    </div>
  );
}

interface SettingsData {
  events: EngagementEvent[];
  settings: EngagementSettings;
}

function SettingsTab({ on401 }: { on401: (err: unknown) => boolean }) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyEvent, setBusyEvent] = useState<string | null>(null);
  // Pending channel change awaiting confirmation: {event_key, to}.
  const [confirmChange, setConfirmChange] = useState<{
    event: EngagementEvent;
    to: EngagementChannel;
  } | null>(null);

  // Settings form draft + save state.
  const [draft, setDraft] = useState<EngagementSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"ok" | "err" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [events, settings] = await Promise.all([
        getEngagementEvents(),
        getEngagementSettings(),
      ]);
      setData({ events, settings });
      setDraft(settings);
    } catch (err) {
      if (on401(err)) return;
      let msg = "خطا در دریافتِ تنظیمات";
      if (err instanceof ApiError) {
        msg = err.status === 403 ? "دسترسی محدود است." : err.message;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [on401]);

  useEffect(() => {
    load();
  }, [load]);

  const applyChannel = useCallback(
    async (ev: EngagementEvent, channel: EngagementChannel) => {
      setBusyEvent(ev.event_key);
      try {
        const updated = await updateEngagementEvent(ev.event_key, {
          channel,
          cooldown_days: ev.cooldown_days,
        });
        // The server is the source of truth, but if it returns nothing
        // (e.g. 204), fall back to the requested change so the UI stays
        // consistent instead of crashing on `updated.event_key`.
        const next: EngagementEvent = updated ?? { ...ev, channel };
        setData((d) =>
          d
            ? {
                ...d,
                events: d.events.map((e) =>
                  e.event_key === next.event_key ? next : e,
                ),
              }
            : d,
        );
      } catch (err) {
        if (on401(err)) return;
        const msg = err instanceof ApiError ? err.message : "خطا در ذخیره";
        setError(msg);
      } finally {
        setBusyEvent(null);
      }
    },
    [on401],
  );

  const onChannelChange = useCallback(
    (ev: EngagementEvent, to: EngagementChannel) => {
      if (to === ev.channel) return;
      // Light confirm when MORE messages would enter the queue.
      if (increasesQueue(ev.channel, to)) {
        setConfirmChange({ event: ev, to });
        return;
      }
      applyChannel(ev, to);
    },
    [applyChannel],
  );

  const applyCooldown = useCallback(
    async (ev: EngagementEvent, cooldown: number) => {
      setBusyEvent(ev.event_key);
      try {
        const updated = await updateEngagementEvent(ev.event_key, {
          channel: ev.channel,
          cooldown_days: cooldown,
        });
        const next: EngagementEvent = updated ?? { ...ev, cooldown_days: cooldown };
        setData((d) =>
          d
            ? {
                ...d,
                events: d.events.map((e) =>
                  e.event_key === next.event_key ? next : e,
                ),
              }
            : d,
        );
      } catch (err) {
        if (on401(err)) return;
        const msg = err instanceof ApiError ? err.message : "خطا در ذخیره";
        setError(msg);
      } finally {
        setBusyEvent(null);
      }
    },
    [on401],
  );

  const saveSettings = useCallback(async () => {
    if (!draft) return;
    setSavingSettings(true);
    setSaveStatus(null);
    try {
      const saved = await updateEngagementSettings(draft);
      setData((d) => (d ? { ...d, settings: saved } : d));
      setDraft(saved);
      setSaveStatus("ok");
    } catch (err) {
      if (on401(err)) return;
      setSaveStatus("err");
    } finally {
      setSavingSettings(false);
    }
  }, [draft, on401]);

  if (loading) {
    return (
      <div className={styles.stateBox} role="status" aria-live="polite">
        <span className={styles.spinner} aria-hidden="true" />
        در حال بارگذاری…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className={styles.errorBox} role="alert">
        <p>{error}</p>
        <button type="button" className={styles.retryBtn} onClick={load}>
          تلاش مجدد
        </button>
      </div>
    );
  }

  if (!data || !draft) return null;

  return (
    <>
      {/* Event → channel table */}
      <section className={styles.settingsSection} aria-label="مسیریابیِ رویداد به کانال">
        <h2 className={styles.settingsTitle}>کانالِ هر رویداد</h2>
        <p className={styles.settingsSub}>
          هر رویداد را به پیامک، کارِ روزانه (worklist)، هردو یا خاموش بسپارید.
          فاصلهٔ تکرار (cooldown) از ارسالِ مکرر جلوگیری می‌کند.
        </p>
        {error && (
          <p className={styles.saveStatusError} role="alert">
            {error}
          </p>
        )}
        <div className={styles.tableWrap}>
          <table className={styles.eventTable}>
            <thead>
              <tr>
                <th scope="col">رویداد</th>
                <th scope="col">کانال</th>
                <th scope="col">فاصلهٔ تکرار (روز)</th>
              </tr>
            </thead>
            <tbody>
              {data.events.map((ev) => (
                <tr key={ev.event_key}>
                  <td>
                    <span className={styles.eventName}>{ev.label}</span>
                    <span className={styles.eventCategory}>{ev.category}</span>
                  </td>
                  <td>
                    <ChannelSegmented
                      value={ev.channel}
                      disabled={busyEvent === ev.event_key}
                      onChange={(c) => onChannelChange(ev, c)}
                    />
                  </td>
                  <td>
                    <Stepper
                      value={ev.cooldown_days}
                      min={0}
                      max={365}
                      disabled={busyEvent === ev.event_key}
                      label={`فاصلهٔ تکرارِ ${ev.label}`}
                      onChange={(n) => applyCooldown(ev, n)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Guardrails: quiet hours + daily cap */}
      <section className={styles.settingsSection} aria-label="گاردریل‌ها">
        <h2 className={styles.settingsTitle}>گاردریل‌ها</h2>
        <p className={styles.settingsSub}>
          ساعتِ مجازِ ارسال و سقفِ روزانهٔ پیام به ازای هر بیمار.
        </p>
        <div className={styles.settingsGrid}>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="quiet-start">
              شروعِ بازهٔ مجاز
            </label>
            <input
              id="quiet-start"
              type="time"
              className={styles.timeInput}
              value={draft.quiet_start}
              onChange={(e) =>
                setDraft({ ...draft, quiet_start: e.target.value })
              }
            />
          </div>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="quiet-end">
              پایانِ بازهٔ مجاز
            </label>
            <input
              id="quiet-end"
              type="time"
              className={styles.timeInput}
              value={draft.quiet_end}
              onChange={(e) =>
                setDraft({ ...draft, quiet_end: e.target.value })
              }
            />
          </div>
          <div className={styles.field}>
            <span className={styles.fieldLabel}>سقفِ روزانه</span>
            <Stepper
              value={draft.daily_cap}
              min={0}
              max={50}
              disabled={savingSettings}
              label="سقفِ روزانهٔ پیام"
              onChange={(n) => setDraft({ ...draft, daily_cap: n })}
            />
          </div>
        </div>
        <div className={styles.saveBar}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveSettings}
            disabled={savingSettings}
            aria-busy={savingSettings}
          >
            ذخیرهٔ گاردریل‌ها
          </button>
          {saveStatus === "ok" && (
            <span className={styles.saveStatus} role="status">
              ذخیره شد.
            </span>
          )}
          {saveStatus === "err" && (
            <span className={styles.saveStatusError} role="alert">
              ذخیره ناموفق بود.
            </span>
          )}
        </div>
      </section>

      {/* Channel-increase confirm modal */}
      {confirmChange && (
        <div
          className={styles.modalOverlay}
          role="presentation"
          onClick={() => setConfirmChange(null)}
        >
          <div
            className={styles.modal}
            role="dialog"
            aria-modal="true"
            aria-label="تأییدِ تغییرِ کانال"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className={styles.modalTitle}>تغییرِ کانالِ «{confirmChange.event.label}»</h2>
            <p className={styles.modalBody}>
              با فعال‌کردنِ پیامک برای این رویداد، پیام‌های بیشتری وارد صفِ تأیید
              می‌شود. ادامه می‌دهید؟
            </p>
            <div className={styles.modalActions}>
              <button
                type="button"
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={() => {
                  const { event, to } = confirmChange;
                  setConfirmChange(null);
                  applyChannel(event, to);
                }}
              >
                بله، تغییر بده
              </button>
              <button
                type="button"
                className={styles.btn}
                onClick={() => setConfirmChange(null)}
              >
                انصراف
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────

export default function ManagerEngagementPage() {
  const { ready, logout } = useAuth();
  const pathname = usePathname();

  const [isManager, setIsManager] = useState<boolean | null>(null);
  const [tab, setTab] = useState<TabKey>("queue");
  const [queueCount, setQueueCount] = useState<number | null>(null);

  const on401 = useCallback(
    (err: unknown): boolean => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return true;
      }
      return false;
    },
    [logout],
  );

  useEffect(() => {
    if (!ready) return;
    setIsManager(getRole() === "manager");
  }, [ready]);

  if (!ready) return null;

  // Non-manager: access restricted, NO fetch.
  if (isManager === false) {
    return (
      <div className={styles.layout}>
        <Nav currentPath={pathname ?? "/manager/engagement"} onLogout={logout} />
        <main className={styles.main} id="main-content">
          <div className={styles.restrictedBox} role="alert">
            <p className={styles.restrictedTitle}>دسترسی محدود</p>
            <p>این صفحه فقط برای مدیر در دسترس است.</p>
          </div>
        </main>
      </div>
    );
  }

  if (isManager === null) return null;

  return (
    <div className={styles.layout}>
      <Nav
        currentPath={pathname ?? "/manager/engagement"}
        pageTitle="صفِ تعامل"
        onLogout={logout}
        showManagerLinks
      />

      <main className={styles.main} id="main-content" aria-label="مدیریتِ تعامل">
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>تعامل با بیماران</h1>
        </div>

        <SimulationBanner />

        {/* Tabs */}
        <div className={styles.tabBar} role="tablist" aria-label="بخش‌های تعامل">
          <button
            type="button"
            role="tab"
            id="tab-queue"
            aria-selected={tab === "queue"}
            aria-controls="panel-queue"
            className={`${styles.tab}${tab === "queue" ? ` ${styles.tabActive}` : ""}`}
            onClick={() => setTab("queue")}
          >
            صفِ تأیید
            {queueCount !== null && queueCount > 0 && (
              <span className={styles.tabBadge}>{toFarsiDigits(queueCount)}</span>
            )}
          </button>
          <button
            type="button"
            role="tab"
            id="tab-settings"
            aria-selected={tab === "settings"}
            aria-controls="panel-settings"
            className={`${styles.tab}${tab === "settings" ? ` ${styles.tabActive}` : ""}`}
            onClick={() => setTab("settings")}
          >
            تنظیمات
          </button>
        </div>

        {tab === "queue" ? (
          <div role="tabpanel" id="panel-queue" aria-labelledby="tab-queue">
            <QueueTab onCount={setQueueCount} on401={on401} />
          </div>
        ) : (
          <div role="tabpanel" id="panel-settings" aria-labelledby="tab-settings">
            <SettingsTab on401={on401} />
          </div>
        )}
      </main>
    </div>
  );
}

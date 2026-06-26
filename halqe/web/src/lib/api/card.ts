/**
 * Patient Card domain.
 *   - GET  /api/v1/card/{token}            (public — no JWT)  → CardResponse
 *   - POST /api/v1/patients/{uuid}/card-token (staff JWT)     → CardTokenOut
 */
import { API_BASE, ApiError, apiFetch } from "./_core";

/**
 * One vital shown on the public patient card.
 * status ∈ 'ok' | 'warn' | 'danger'.
 * value is a number (not a string).
 */
export interface CardVital {
  key: string;
  label: string;
  value: number;
  unit: string;
  status: "ok" | "warn" | "danger";
}

/**
 * Response from GET /api/v1/card/{token}.
 * Contains no national_id, phone, medications, or diagnoses —
 * the backend guarantees that only these fields are returned.
 */
export interface CardResponse {
  first_name: string | null;
  clinic_name: string | null;
  vitals: CardVital[];
  /** ISO date YYYY-MM-DD, or null when no appointment is scheduled. */
  next_appointment: string | null;
  /** Safety framing text, e.g. "پیشنهاد — تأیید با پزشک". */
  framing: string | null;
  /**
   * Pre-rendered, patient-safe screening reminder line (step 48, cluster J).
   *
   * The backend guarantees this string contains NO patient name, diagnosis,
   * medication, or exact clinical number — it is a single neutral
   * informational sentence (e.g. "چند موردِ مراقبتِ دوره‌ای… با کلینیک تماس بگیرید").
   *
   * - null  → no reminder is due → render NOTHING (no empty section).
   * - non-null → render exactly this string, verbatim, in a soft neutral
   *   (informational) banner. The UI must never add/infer extra detail and
   *   must never show it with danger styling / at the level of a danger vital.
   *
   * Marked optional (`?`) so the UI is forward/backward compatible: the live
   * backend `PublicCardResponse` may not yet serialise this field — absence is
   * treated identically to null.
   */
  reminder_message?: string | null;
}

/**
 * Fetch the public patient card by token.
 *
 * This is a PUBLIC endpoint — no Authorization header is attached.
 * An invalid/expired/revoked token returns ApiError with status 404.
 */
export async function getCard(token: string): Promise<CardResponse> {
  const res = await fetch(`${API_BASE}/card/${encodeURIComponent(token)}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    // No Authorization header — deliberately public
  });

  if (!res.ok) {
    let detail = res.statusText;
    let code: string | null = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
      code = typeof body?.code === "string" ? body.code : null;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail, code);
  }

  return res.json() as Promise<CardResponse>;
}

// ────────────────────────────────────────────────────────────
// Patient Card Token (staff — JWT)  — mirrors CardTokenOut
// POST /api/v1/patients/{uuid}/card-token
// ────────────────────────────────────────────────────────────

/**
 * Response from POST /patients/{uuid}/card-token (mirrors CardTokenOut).
 *
 * `card_url` is a relative PATH only (e.g. "/card/<token>"), not an absolute
 * URL — the deployment is LAN-only for now. The UI builds the copy-able link
 * by prepending window.location.origin.
 */
export interface CardTokenOut {
  token: string;
  expires_at: string;     // ISO datetime
  card_url: string;       // relative path, e.g. "/card/<token>"
}

/**
 * POST /patients/{uuid}/card-token  (staff JWT) → 201 CardTokenOut
 * Issues a new public-card token for the patient. one-active-at-a-time:
 * the backend revokes any previous active token for this patient first.
 */
export async function issueCardToken(uuid: string): Promise<CardTokenOut> {
  return apiFetch<CardTokenOut>(`/patients/${uuid}/card-token`, {
    method: "POST",
  });
}

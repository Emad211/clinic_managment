/**
 * Patient Self-Report domain (public — no JWT).
 * POST /api/v1/patient-report/{token}
 */
import { API_BASE, ApiError } from "./_core";

/**
 * One vital reading submitted by the patient themselves.
 * type ∈ 'fbs' | 'bp_systolic' | 'bp_diastolic' — no weight.
 */
export interface SelfReportReading {
  type: "fbs" | "bp_systolic" | "bp_diastolic";
  value: number;
}

/**
 * Accepted reading echoed back in the 200 response.
 */
export interface AcceptedReading {
  type: string;
  value: number;
}

/**
 * 200 response from POST /patient-report/{token}.
 */
export interface SelfReportResponse {
  status: "ok";
  accepted: AcceptedReading[];
  count: number;
  message: string;
}

/**
 * Submit a batch of self-reported vital readings for a patient.
 *
 * PUBLIC endpoint — no Authorization header attached (same pattern as getCard).
 * Token is one-time-use: consumed after a 200 response.
 *
 * Error codes:
 *   404 — token invalid/used/expired → do NOT retry
 *   422 — validation failure (out-of-range / empty batch) → token NOT consumed; fix and retry
 *   429 — rate limit → wait and retry
 */
export async function submitReport(
  token: string,
  readings: SelfReportReading[],
): Promise<SelfReportResponse> {
  const res = await fetch(
    `${API_BASE}/patient-report/${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // No Authorization header — deliberately public
      body: JSON.stringify({ readings }),
    },
  );

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

  return res.json() as Promise<SelfReportResponse>;
}

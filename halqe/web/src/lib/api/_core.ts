/**
 * Shared core of the Halqe API client.
 *
 * Holds the cross-cutting pieces every per-domain module depends on:
 *   - API_BASE             — base URL (NEXT_PUBLIC_API_BASE)
 *   - token storage        — saveToken / getToken / clearToken / getRole
 *   - ApiError             — typed error with backend status + machine code
 *   - errorMessageFromCode — code → Persian message
 *   - apiFetch             — the JWT-attaching fetch wrapper
 *
 * Per-domain modules (./patients, ./record, …) import ONLY from this file.
 * This module imports nothing from those domains — keeps the dependency graph
 * acyclic (_core → domains, never the reverse).
 *
 * Reads NEXT_PUBLIC_API_BASE (default: "/api/v1" — relative, same-origin behind nginx).
 * Attaches Bearer JWT from localStorage when present.
 * All request/response shapes mirror the django-ninja schemas in config/api.py.
 */

// Default to a RELATIVE same-origin path (step 79 / T1): in production the web is
// served behind the SAME nginx as the API (/ → web, /api/v1 → backend), so a
// relative base means no CORS and no build-time host baking (NEXT_PUBLIC_* is
// inlined at build). Dev sets NEXT_PUBLIC_API_BASE=http://127.0.0.1:8099/api/v1
// to reach the local backend on a different port.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

// ────────────────────────────────────────────────────────────
// Token storage  (localStorage — simplest for this slice)
// ────────────────────────────────────────────────────────────

const TOKEN_KEY = "halqe_token";

export function saveToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

/**
 * Decode a JWT payload (base64url) without any library.
 * Returns the parsed claims object, or null on any decode error.
 * Does NOT verify the signature — used only for the `exp` claim check.
 */
function _decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    // base64url → base64: replace -/_ and pad
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
    const json = atob(b64 + pad);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Return the stored JWT only if it is present AND not expired.
 * A token is considered expired when its `exp` claim (Unix seconds) is in
 * the past. Tokens without an `exp` claim are treated as non-expiring.
 * Returns null (and clears storage) when the token is missing or expired.
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return null;

  const claims = _decodeJwtPayload(token);
  if (claims !== null && typeof claims.exp === "number") {
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (claims.exp <= nowSeconds) {
      // Expired — evict silently so the next getToken call starts clean
      localStorage.removeItem(TOKEN_KEY);
      return null;
    }
  }

  return token;
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

/**
 * Read the `role` claim ("manager" | "staff") from the stored JWT.
 *
 * Decodes the (un-verified) payload only — the backend remains the source of
 * truth and re-checks role on every privileged endpoint (manager-only routes
 * return 403). This client read is purely for UI gating / link visibility, so a
 * tampered token gains nothing: the server still rejects the request.
 *
 * Returns null when there is no valid token or the claim is missing.
 */
export function getRole(): string | null {
  const token = getToken();
  if (!token) return null;
  const claims = _decodeJwtPayload(token);
  if (claims !== null && typeof claims.role === "string") {
    return claims.role;
  }
  return null;
}

// ────────────────────────────────────────────────────────────
// Core fetch wrapper
// ────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    /** Stable machine-readable error code from backend (e.g. 'not_found', 'encounter_sealed'). */
    public readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Map a backend error code to a human-readable Persian message.
 * Falls back to `fallback` (typically `err.message`) when code is unknown.
 *
 * Codes come from `config/errors.py` (halqe backend) — only stable codes that
 * are declared in that file and actively returned by endpoints are listed here.
 * Add new entries as new codes are introduced in the backend.
 */
export function errorMessageFromCode(
  code: string | null | undefined,
  fallback: string,
): string {
  switch (code) {
    // Auth
    case "invalid_credentials":
      return "نام کاربری یا رمز عبور اشتباه است.";
    case "account_locked":
      return "حساب کاربری قفل شده است. لطفاً ۱۵ دقیقه بعد تلاش کنید.";
    // Resource not found
    case "not_found":
      return "مورد درخواستی پیدا نشد.";
    // State transition conflicts
    case "conflict":
      return "این عملیات در وضعیت فعلی مجاز نیست.";
    case "encounter_sealed":
      return "ویزیت بسته شده و امکان ثبت اطلاعات جدید وجود ندارد.";
    case "invalid_transition":
      return "تغییر وضعیت مجاز نیست.";
    // Duplicate data
    case "duplicate_vital":
      return "این علامت حیاتی قبلاً برای این ویزیت ثبت شده است.";
    // Validation
    case "validation_error":
      return "مقدار وارد شده معتبر نیست.";
    // Prescription
    case "insurance_prescription_not_supported":
      return "نسخهٔ بیمه‌ای در این نسخه پشتیبانی نمی‌شود.";
    default:
      return fallback;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    let code: string | null = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
      // Read the stable machine-readable code from the backend error contract
      code = typeof body?.code === "string" ? body.code : null;
    } catch {
      // ignore parse errors — use statusText fallback
    }
    throw new ApiError(res.status, detail, code);
  }

  return res.json() as Promise<T>;
}

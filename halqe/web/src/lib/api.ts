/**
 * API client for the Halqe platform backend.
 *
 * Reads NEXT_PUBLIC_API_BASE (default: http://127.0.0.1:8099/api/v1).
 * Attaches Bearer JWT from localStorage when present.
 * All request/response shapes mirror the django-ninja schemas in config/api.py.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8099/api/v1";

// ────────────────────────────────────────────────────────────
// Token storage  (localStorage — simplest for this slice)
// ────────────────────────────────────────────────────────────

const TOKEN_KEY = "halqe_token";

export function saveToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

// ────────────────────────────────────────────────────────────
// Core fetch wrapper
// ────────────────────────────────────────────────────────────

class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
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
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

// ────────────────────────────────────────────────────────────
// Auth
// ────────────────────────────────────────────────────────────

export interface LoginResponse {
  token: string;
}

export async function apiLogin(
  username: string,
  password: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

// ────────────────────────────────────────────────────────────
// Patients list  — mirrors EnrolledPatientDTO + PatientListResponse
// ────────────────────────────────────────────────────────────

export interface EnrolledPatient {
  link_id: number;
  patient_id: number;
  is_active: boolean;
  enrolled_at: string;            // ISO datetime string
  full_name: string | null;
  national_id: string | null;
  phone_number: string | null;
  patient_uuid: string | null;
}

export interface PatientListResponse {
  items: EnrolledPatient[];
  total: number;
  limit: number;
  offset: number;
}

export async function apiGetPatients(
  limit = 20,
  offset = 0,
): Promise<PatientListResponse> {
  return apiFetch<PatientListResponse>(
    `/patients?limit=${limit}&offset=${offset}`,
  );
}

export { ApiError };

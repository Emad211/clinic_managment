/**
 * API client for the Halqe platform backend — barrel module.
 *
 * Reads NEXT_PUBLIC_API_BASE (default: http://127.0.0.1:8099/api/v1).
 * Attaches Bearer JWT from localStorage when present.
 * All request/response shapes mirror the django-ninja schemas in config/api.py.
 *
 * ─────────────────────────────────────────────────────────────
 * Cleanup step 8: this file used to hold the entire client (~1.3k lines).
 * It is now a thin barrel that re-exports the per-domain modules under
 * `./api/*`. The PUBLIC surface is unchanged — every symbol that pages
 * imported from `@/lib/api` (the same names + identical signatures) is
 * still exported here. Page/component imports were NOT touched.
 *
 * Internals that were never exported before stay internal: the shared
 * `apiFetch`, `API_BASE`, `TOKEN_KEY`, and `_decodeJwtPayload` live in
 * `./api/_core` and are deliberately NOT re-exported, so the public
 * export set is byte-identical to the pre-refactor file.
 *
 * Dependency direction is acyclic: `_core` imports nothing from the
 * domain modules; every domain module imports only from `_core`.
 * ─────────────────────────────────────────────────────────────
 */

// Core — only the previously-public symbols (NOT apiFetch / API_BASE).
export {
  saveToken,
  getToken,
  clearToken,
  getRole,
  ApiError,
  errorMessageFromCode,
} from "./api/_core";

// Per-domain modules — every symbol below was public before the split.
export * from "./api/auth";
export * from "./api/patients";
export * from "./api/record";
export * from "./api/suggestions";
export * from "./api/worklist";
export * from "./api/encounters";
export * from "./api/doctor-queue";
export * from "./api/prescriptions";
export * from "./api/screening";
export * from "./api/card";
export * from "./api/self-report";
export * from "./api/manager-analytics";
export * from "./api/engagement";
export * from "./api/control-room";

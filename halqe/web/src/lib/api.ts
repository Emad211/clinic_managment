/**
 * API client for the Halqe platform backend — barrel module.
 * Shared request/auth internals remain private in `./api/_core`.
 */

export {
  saveToken,
  getToken,
  clearToken,
  getRole,
  ApiError,
  errorMessageFromCode,
} from "./api/_core";

export * from "./api/auth";
export * from "./api/patients";
export * from "./api/record";
export * from "./api/record-data";
export * from "./api/record-vitals";
export * from "./api/allergies";
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

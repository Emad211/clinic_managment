/** Unified Halqe web API barrel. */
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
export * from "./api/patient-record";
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
export * from "./api/accounting";
export * from "./api/accounting-payments";
export * from "./api/accounting-nursing";
export * from "./api/accounting-procedures";
export * from "./api/accounting-invoice-workbench";

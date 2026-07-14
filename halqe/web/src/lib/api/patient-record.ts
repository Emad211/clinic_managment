/**
 * Public structured patient-record client facade.
 *
 * The generated domain contracts and ordinary request helpers live in
 * `_patient-record-core`.  Catalog laboratory requests are narrowed here so the
 * browser sends only the catalog key and clinical value fields; name, unit and
 * reference range remain server-authoritative even before the backend enforces
 * the same boundary.
 */
export * from "./_patient-record-core";

import {
  apiAddPatientLabResult as coreAddPatientLabResult,
  type AddLabInput,
  type StructuredLabResultDTO,
} from "./_patient-record-core";

export function apiAddPatientLabResult(
  uuid: string,
  payload: AddLabInput,
): Promise<StructuredLabResultDTO> {
  const testKey = payload.test_key?.trim() || null;
  if (!testKey) {
    return coreAddPatientLabResult(uuid, {
      ...payload,
      test_key: null,
    });
  }

  const safePayload: AddLabInput = { test_key: testKey };
  if (Object.prototype.hasOwnProperty.call(payload, "value")) {
    safePayload.value = payload.value ?? null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, "taken_at")) {
    safePayload.taken_at = payload.taken_at ?? null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, "notes")) {
    safePayload.notes = payload.notes ?? null;
  }

  return coreAddPatientLabResult(uuid, safePayload);
}

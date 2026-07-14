"""Public clinician-review sampler with strict verifier-report binding.

The deterministic set-cover implementation lives in
:mod:`clinical._specialist_record_review_sample_core`. This facade adds release
contract checks and keeps the clinical → accounting dependency one-way: clinical
queries collect only ``patient_id`` and UUIDs are fetched in one SELECT-only
batch through :mod:`accounting_port.review`.
"""
from __future__ import annotations

from collections import Counter
import re
import stat
from typing import Any, Mapping

from django.db import connection

from accounting_port.review import get_accounting_patient_uuids_for_review
from clinical import _specialist_record_review_sample_core as _core
from platform_core.tenant_context import set_tenant_guc

# ``_select`` in the extracted core performs deterministic set-cover accounting.
_core.Counter = Counter

ReviewScenario = _core.ReviewScenario
ReviewCandidate = _core.ReviewCandidate
SpecialistRecordReviewSample = _core.SpecialistRecordReviewSample
SpecialistRecordReviewSampleError = _core.SpecialistRecordReviewSampleError
SCENARIOS = _core.SCENARIOS

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_PASS_CHECKS = frozenset(
    {
        "apply_report_contract",
        "apply_table_accounting",
        "unresolved_patient_policy",
        "apply_report_ledger_count",
        "idempotent_replay_report",
        "relational_dry_run_reproduction",
        "durable_ledger_count",
        "ledger_source_table_counts",
        "ledger_row_shape",
        "ledger_manifest",
        "ledger_target_existence",
        "target_payload_fingerprints",
        "medication_event_orphans",
        "verified_patient_self_reports",
        "lab_observation_visibility",
        "appointment_parent_orphans",
        "followup_appointment_orphans",
        "prescription_followup_orphans",
    }
)


class SpecialistRecordReviewSampler(_core.SpecialistRecordReviewSampler):
    """Sampler that accepts only a complete, untampered release-verifier result."""

    def _load_verification_report(self) -> tuple[dict[str, Any], str]:
        payload, report_hash = super()._load_verification_report()
        mode = stat.S_IMODE(self.verification_report_path.stat().st_mode)
        if mode & 0o077:
            raise SpecialistRecordReviewSampleError(
                "Verification report must be owner-only (mode 0600 or stricter)."
            )

        for key in ("source_file_sha256", "source_manifest_sha256"):
            value = payload.get(key)
            if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
                raise SpecialistRecordReviewSampleError(
                    f"Verification report field {key} is not a valid SHA-256 digest."
                )

        summary = payload.get("summary")
        if not isinstance(summary, dict) or int(summary.get("failed", -1)) != 0:
            raise SpecialistRecordReviewSampleError(
                "Verification report summary is missing or contains failed checks."
            )
        checks = payload.get("checks")
        if not isinstance(checks, list):
            raise SpecialistRecordReviewSampleError(
                "Verification report does not contain a checks list."
            )

        by_name: dict[str, str] = {}
        duplicates: set[str] = set()
        for item in checks:
            if not isinstance(item, dict):
                raise SpecialistRecordReviewSampleError(
                    "Verification report contains a malformed check entry."
                )
            name = item.get("name")
            status_value = item.get("status")
            if not isinstance(name, str) or not isinstance(status_value, str):
                raise SpecialistRecordReviewSampleError(
                    "Verification check name/status is malformed."
                )
            if name in by_name:
                duplicates.add(name)
            by_name[name] = status_value
        if duplicates:
            raise SpecialistRecordReviewSampleError(
                "Verification report contains duplicate check names: "
                + ", ".join(sorted(duplicates))
            )

        missing = sorted(_REQUIRED_PASS_CHECKS - set(by_name))
        nonpassing = sorted(
            name
            for name in _REQUIRED_PASS_CHECKS
            if by_name.get(name) != "pass"
        )
        if missing or nonpassing:
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if nonpassing:
                details.append("not_pass=" + ",".join(nonpassing))
            raise SpecialistRecordReviewSampleError(
                "Verification report is not sufficient for clinical sign-off sampling: "
                + "; ".join(details)
            )
        return payload, report_hash

    def _load_candidates(self) -> list[ReviewCandidate]:
        """Load clinical feature counts, then resolve UUIDs via accounting read port."""
        set_tenant_guc(self.tenant_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH imported_patients AS (
                    SELECT l.source_row_id AS source_patient_link_id,
                           pl.id AS patient_link_id,
                           pl.patient_id AS accounting_patient_id
                    FROM clinical.record_import_ledger l
                    JOIN clinical.patient_links pl
                      ON pl.tenant_id=l.tenant_id AND pl.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='patient_links'
                      AND l.target_table='clinical.patient_links'
                      AND l.target_row_id IS NOT NULL
                      AND pl.is_active=TRUE
                ),
                conditions AS (
                    SELECT pc.patient_link_id, COUNT(*)::int AS condition_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.patient_conditions pc
                      ON pc.tenant_id=l.tenant_id AND pc.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='patient_conditions'
                    GROUP BY pc.patient_link_id
                ),
                medication_events AS (
                    SELECT e.patient_link_id,
                           COUNT(*)::int AS medication_event_count,
                           COUNT(*) FILTER (
                               WHERE e.event_type IN ('dose_change','stop')
                           )::int AS medication_change_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.medication_events e
                      ON e.tenant_id=l.tenant_id AND e.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='medication_events'
                    GROUP BY e.patient_link_id
                ),
                allergies AS (
                    SELECT a.patient_link_id,
                           COUNT(*)::int AS allergy_count,
                           COUNT(*) FILTER (
                               WHERE a.severity IN ('severe','anaphylaxis')
                           )::int AS severe_allergy_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.allergies a
                      ON a.tenant_id=l.tenant_id AND a.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='allergies'
                    GROUP BY a.patient_link_id
                ),
                vitals AS (
                    SELECT v.patient_link_id,
                           COUNT(*)::int AS vital_count,
                           COUNT(*) FILTER (
                               WHERE v.source IN ('patient_self','self')
                           )::int AS self_report_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.vital_readings v
                      ON v.tenant_id=l.tenant_id AND v.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='vital_readings'
                    GROUP BY v.patient_link_id
                ),
                labs AS (
                    SELECT r.patient_link_id, COUNT(*)::int AS lab_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.lab_results r
                      ON r.tenant_id=l.tenant_id AND r.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='lab_results'
                    GROUP BY r.patient_link_id
                ),
                flags AS (
                    SELECT f.patient_link_id,
                           COUNT(*)::int AS flag_count,
                           COUNT(*) FILTER (WHERE c.flag_type='enum')::int AS enum_flag_count,
                           COUNT(*) FILTER (WHERE c.flag_type='date')::int AS date_flag_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.patient_flags f
                      ON f.tenant_id=l.tenant_id AND f.id=l.target_row_id
                    LEFT JOIN clinical.flag_catalog c
                      ON c.tenant_id=f.tenant_id AND c.flag_key=f.flag_key
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='patient_flags'
                    GROUP BY f.patient_link_id
                ),
                surgeries AS (
                    SELECT s.patient_link_id, COUNT(*)::int AS surgery_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.surgery_history s
                      ON s.tenant_id=l.tenant_id AND s.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='surgery_history'
                    GROUP BY s.patient_link_id
                ),
                history AS (
                    SELECT h.patient_link_id, COUNT(*)::int AS medical_history_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.medical_history h
                      ON h.tenant_id=l.tenant_id AND h.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='medical_history'
                    GROUP BY h.patient_link_id
                ),
                notes AS (
                    SELECT n.patient_link_id, COUNT(*)::int AS clinical_note_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.clinical_notes n
                      ON n.tenant_id=l.tenant_id AND n.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='clinical_notes'
                    GROUP BY n.patient_link_id
                ),
                appointments AS (
                    SELECT a.patient_link_id, COUNT(*)::int AS appointment_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.appointments a
                      ON a.tenant_id=l.tenant_id AND a.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='appointments'
                    GROUP BY a.patient_link_id
                ),
                followups AS (
                    SELECT f.patient_link_id, COUNT(*)::int AS followup_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.followup_tasks f
                      ON f.tenant_id=l.tenant_id AND f.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='followup_tasks'
                    GROUP BY f.patient_link_id
                ),
                prescriptions AS (
                    SELECT p.patient_link_id, COUNT(*)::int AS prescription_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.prescriptions p
                      ON p.tenant_id=l.tenant_id AND p.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='prescriptions'
                    GROUP BY p.patient_link_id
                )
                SELECT ip.source_patient_link_id,
                       ip.patient_link_id,
                       ip.accounting_patient_id,
                       COALESCE(c.condition_count,0),
                       COALESCE(me.medication_event_count,0),
                       COALESCE(me.medication_change_count,0),
                       COALESCE(a.allergy_count,0),
                       COALESCE(a.severe_allergy_count,0),
                       COALESCE(v.vital_count,0),
                       COALESCE(v.self_report_count,0),
                       COALESCE(lb.lab_count,0),
                       COALESCE(fl.flag_count,0),
                       COALESCE(fl.enum_flag_count,0),
                       COALESCE(fl.date_flag_count,0),
                       COALESCE(s.surgery_count,0),
                       COALESCE(h.medical_history_count,0),
                       COALESCE(n.clinical_note_count,0),
                       COALESCE(ap.appointment_count,0),
                       COALESCE(fo.followup_count,0),
                       COALESCE(pr.prescription_count,0)
                FROM imported_patients ip
                LEFT JOIN conditions c ON c.patient_link_id=ip.patient_link_id
                LEFT JOIN medication_events me ON me.patient_link_id=ip.patient_link_id
                LEFT JOIN allergies a ON a.patient_link_id=ip.patient_link_id
                LEFT JOIN vitals v ON v.patient_link_id=ip.patient_link_id
                LEFT JOIN labs lb ON lb.patient_link_id=ip.patient_link_id
                LEFT JOIN flags fl ON fl.patient_link_id=ip.patient_link_id
                LEFT JOIN surgeries s ON s.patient_link_id=ip.patient_link_id
                LEFT JOIN history h ON h.patient_link_id=ip.patient_link_id
                LEFT JOIN notes n ON n.patient_link_id=ip.patient_link_id
                LEFT JOIN appointments ap ON ap.patient_link_id=ip.patient_link_id
                LEFT JOIN followups fo ON fo.patient_link_id=ip.patient_link_id
                LEFT JOIN prescriptions pr ON pr.patient_link_id=ip.patient_link_id
                ORDER BY ip.source_patient_link_id, ip.patient_link_id
                """,
                [self.tenant_id, self.source_id] * 13,
            )
            rows = cursor.fetchall()

        accounting_ids = [int(row[2]) for row in rows]
        uuid_by_patient = get_accounting_patient_uuids_for_review(
            accounting_patient_ids=accounting_ids,
            tenant_id=self.tenant_id,
        )
        missing_ids = sorted(set(accounting_ids) - set(uuid_by_patient))
        if missing_ids:
            raise SpecialistRecordReviewSampleError(
                "One or more imported clinical links no longer resolve through the "
                "accounting read port; missing accounting patient count="
                f"{len(missing_ids)}."
            )

        candidates: list[ReviewCandidate] = []
        for row in rows:
            counts: Mapping[str, int] = {
                "condition_count": int(row[3]),
                "medication_event_count": int(row[4]),
                "medication_change_count": int(row[5]),
                "allergy_count": int(row[6]),
                "severe_allergy_count": int(row[7]),
                "vital_count": int(row[8]),
                "self_report_count": int(row[9]),
                "lab_count": int(row[10]),
                "flag_count": int(row[11]),
                "enum_flag_count": int(row[12]),
                "date_flag_count": int(row[13]),
                "surgery_count": int(row[14]),
                "medical_history_count": int(row[15]),
                "clinical_note_count": int(row[16]),
                "appointment_count": int(row[17]),
                "followup_count": int(row[18]),
                "prescription_count": int(row[19]),
            }
            candidates.append(
                ReviewCandidate(
                    source_patient_link_id=int(row[0]),
                    target_patient_link_id=int(row[1]),
                    patient_uuid=uuid_by_patient[int(row[2])],
                    scenarios=self._candidate_scenarios(counts),
                    feature_counts=dict(counts),
                )
            )
        return candidates


__all__ = [
    "ReviewScenario",
    "ReviewCandidate",
    "SpecialistRecordReviewSample",
    "SpecialistRecordReviewSampleError",
    "SpecialistRecordReviewSampler",
    "SCENARIOS",
]

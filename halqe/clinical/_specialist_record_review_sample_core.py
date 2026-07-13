"""Deterministic, ledger-bound clinician review sampling for record migration.

The release verifier answers whether the import is mechanically consistent.  A
clinician still needs a deliberate set of patients covering the risky clinical
shapes.  This module selects a compact, deterministic sample from patients
actually represented by one import ledger, maximizing scenario coverage without
printing direct identifiers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from django.db import connection

from platform_core.tenant_context import set_tenant_guc


class SpecialistRecordReviewSampleError(Exception):
    """Raised when a sample cannot be bound to a verified rehearsal."""


@dataclass(frozen=True)
class ReviewScenario:
    key: str
    label: str
    description: str


SCENARIOS = (
    ReviewScenario(
        "multiple_conditions",
        "چند بیماری مزمن",
        "حداقل دو تشخیص واردشده برای بررسی stage، تاریخ و وضعیت فعال.",
    ),
    ReviewScenario(
        "medication_lifecycle",
        "چرخهٔ دارویی",
        "شروع به‌همراه تغییر دوز یا قطع دارو و timeline رویدادها.",
    ),
    ReviewScenario(
        "severe_allergy",
        "حساسیت شدید",
        "حساسیت severe یا anaphylaxis و نمایش هشدار بالای پرونده.",
    ),
    ReviewScenario(
        "patient_self_report",
        "دادهٔ خوداظهاری",
        "vital خوداظهاری که تا بازبینی پزشک تأییدنشده باقی مانده است.",
    ),
    ReviewScenario(
        "laboratory_result",
        "نتیجهٔ آزمایش",
        "نتیجه، واحد، محدودهٔ مرجع و حضور در Observation کانونیک.",
    ),
    ReviewScenario(
        "typed_enum_flag",
        "فلگ انتخابی",
        "فلگ enum با option و مقدار منتقل‌شده.",
    ),
    ReviewScenario(
        "dated_flag",
        "فلگ تاریخی",
        "تاریخ معاینه/غربالگری و رفتار پاک‌کردن صریح.",
    ),
    ReviewScenario(
        "surgery_history",
        "سابقهٔ جراحی",
        "عنوان، تاریخ و توضیح سابقهٔ جراحی.",
    ),
    ReviewScenario(
        "medical_history",
        "سابقهٔ پزشکی",
        "عنوان، تاریخ شروع و توضیح سابقهٔ پزشکی.",
    ),
    ReviewScenario(
        "clinical_note",
        "یادداشت بالینی",
        "یادداشت علائم، معاینه، سبک زندگی یا عمومی.",
    ),
    ReviewScenario(
        "appointment_followup",
        "نوبت و پیگیری",
        "ارتباط نوبت، پیگیری، سررسید و وضعیت.",
    ),
    ReviewScenario(
        "prescription",
        "نسخهٔ قبلی",
        "نسخه و اقلام ساختاریافته یا JSON قدیمی آن.",
    ),
    ReviewScenario(
        "complex_full_record",
        "پروندهٔ پیچیده",
        "یک بیمار با حداقل شش حوزهٔ بالینی واردشده برای مرور انتها‌به‌انتها.",
    ),
)


@dataclass
class ReviewCandidate:
    source_patient_link_id: int
    target_patient_link_id: int
    patient_uuid: str
    scenarios: list[str]
    feature_counts: dict[str, int]


@dataclass
class SpecialistRecordReviewSample:
    source_id: str
    tenant_id: int
    generated_at: str
    verification_report_sha256: str
    source_file_sha256: str
    source_manifest_sha256: str
    per_scenario: int
    max_patients: int
    scenarios: list[dict[str, str]]
    coverage: dict[str, dict[str, Any]]
    patients: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    signoff_template: dict[str, Any] = field(
        default_factory=lambda: {
            "reviewed_by": None,
            "reviewed_at": None,
            "decision": None,
            "discrepancies": [],
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpecialistRecordReviewSampler:
    """Build a compact deterministic sample from one successful verifier report."""

    def __init__(
        self,
        *,
        verification_report_path: str | Path,
        source_id: str,
        tenant_id: int,
        per_scenario: int = 1,
        max_patients: int = 25,
    ):
        self.verification_report_path = (
            Path(verification_report_path).expanduser().absolute()
        )
        self.source_id = source_id.strip()
        self.tenant_id = int(tenant_id)
        self.per_scenario = int(per_scenario)
        self.max_patients = int(max_patients)

    def run(self) -> SpecialistRecordReviewSample:
        verified, report_hash = self._load_verification_report()
        candidates = self._load_candidates()
        selected, coverage, warnings = self._select(candidates)
        scenario_map = {scenario.key: scenario for scenario in SCENARIOS}

        patients = []
        for candidate in selected:
            patients.append(
                {
                    "source_patient_link_id": candidate.source_patient_link_id,
                    "target_patient_link_id": candidate.target_patient_link_id,
                    "patient_uuid": candidate.patient_uuid,
                    "cockpit_path": f"/patients/{candidate.patient_uuid}",
                    "scenarios": [
                        {
                            "key": key,
                            "label": scenario_map[key].label,
                        }
                        for key in candidate.scenarios
                    ],
                    "feature_counts": candidate.feature_counts,
                    "review_checklist": [
                        scenario_map[key].description
                        for key in candidate.scenarios
                    ],
                    "review_status": "pending",
                    "review_notes": None,
                }
            )

        return SpecialistRecordReviewSample(
            source_id=self.source_id,
            tenant_id=self.tenant_id,
            generated_at=datetime.now(UTC).isoformat(),
            verification_report_sha256=report_hash,
            source_file_sha256=str(verified["source_file_sha256"]),
            source_manifest_sha256=str(verified["source_manifest_sha256"]),
            per_scenario=self.per_scenario,
            max_patients=self.max_patients,
            scenarios=[asdict(scenario) for scenario in SCENARIOS],
            coverage=coverage,
            patients=patients,
            warnings=warnings,
        )

    # -------------------------------------------------------------- verification
    def _load_verification_report(self) -> tuple[dict[str, Any], str]:
        path = self.verification_report_path
        if path.is_symlink():
            raise SpecialistRecordReviewSampleError(
                f"Refusing to read verification report through a symlink: {path}"
            )
        if not path.exists() or not path.is_file():
            raise SpecialistRecordReviewSampleError(
                f"Verification report is missing or not a regular file: {path}"
            )
        if path.stat().st_size > 20 * 1024 * 1024:
            raise SpecialistRecordReviewSampleError(
                "Verification report exceeds the 20 MiB safety limit."
            )
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecialistRecordReviewSampleError(
                "Verification report is not valid UTF-8 JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise SpecialistRecordReviewSampleError(
                "Verification report root must be a JSON object."
            )
        if payload.get("decision") != "GO":
            raise SpecialistRecordReviewSampleError(
                "Clinical review sampling requires a verifier report with decision=GO."
            )
        if payload.get("source_id") != self.source_id:
            raise SpecialistRecordReviewSampleError(
                "Verification report source_id does not match --source-id."
            )
        try:
            report_tenant = int(payload.get("tenant_id"))
        except (TypeError, ValueError) as exc:
            raise SpecialistRecordReviewSampleError(
                "Verification report tenant_id is invalid."
            ) from exc
        if report_tenant != self.tenant_id:
            raise SpecialistRecordReviewSampleError(
                "Verification report tenant_id does not match --tenant-id."
            )
        for key in ("source_file_sha256", "source_manifest_sha256"):
            value = payload.get(key)
            if not isinstance(value, str) or len(value) != 64:
                raise SpecialistRecordReviewSampleError(
                    f"Verification report field {key} is missing or invalid."
                )
        if self.per_scenario <= 0 or self.per_scenario > 10:
            raise SpecialistRecordReviewSampleError(
                "per_scenario must be between 1 and 10."
            )
        if self.max_patients <= 0 or self.max_patients > 200:
            raise SpecialistRecordReviewSampleError(
                "max_patients must be between 1 and 200."
            )
        return payload, hashlib.sha256(raw).hexdigest()

    # ---------------------------------------------------------------- candidates
    def _load_candidates(self) -> list[ReviewCandidate]:
        set_tenant_guc(self.tenant_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH imported_patients AS (
                    SELECT l.source_row_id AS source_patient_link_id,
                           l.target_row_id AS patient_link_id,
                           p.uuid::text AS patient_uuid
                    FROM clinical.record_import_ledger l
                    JOIN clinical.patient_links pl
                      ON pl.tenant_id=l.tenant_id AND pl.id=l.target_row_id
                    JOIN accounting.patients p
                      ON p.tenant_id=pl.tenant_id AND p.id=pl.patient_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='patient_links'
                      AND l.target_row_id IS NOT NULL
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
                           COUNT(*) FILTER (
                               WHERE c.flag_type='enum'
                           )::int AS enum_flag_count,
                           COUNT(*) FILTER (
                               WHERE c.flag_type='date'
                           )::int AS date_flag_count
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
                    SELECT h.patient_link_id,
                           COUNT(*)::int AS medical_history_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.medical_history h
                      ON h.tenant_id=l.tenant_id AND h.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='medical_history'
                    GROUP BY h.patient_link_id
                ),
                notes AS (
                    SELECT n.patient_link_id,
                           COUNT(*)::int AS clinical_note_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.clinical_notes n
                      ON n.tenant_id=l.tenant_id AND n.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='clinical_notes'
                    GROUP BY n.patient_link_id
                ),
                appointments AS (
                    SELECT a.patient_link_id,
                           COUNT(*)::int AS appointment_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.appointments a
                      ON a.tenant_id=l.tenant_id AND a.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='appointments'
                    GROUP BY a.patient_link_id
                ),
                followups AS (
                    SELECT f.patient_link_id,
                           COUNT(*)::int AS followup_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.followup_tasks f
                      ON f.tenant_id=l.tenant_id AND f.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='followup_tasks'
                    GROUP BY f.patient_link_id
                ),
                prescriptions AS (
                    SELECT p.patient_link_id,
                           COUNT(*)::int AS prescription_count
                    FROM clinical.record_import_ledger l
                    JOIN clinical.prescriptions p
                      ON p.tenant_id=l.tenant_id AND p.id=l.target_row_id
                    WHERE l.tenant_id=%s AND l.source_id=%s
                      AND l.source_table='prescriptions'
                    GROUP BY p.patient_link_id
                )
                SELECT ip.source_patient_link_id,
                       ip.patient_link_id,
                       ip.patient_uuid,
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

        candidates: list[ReviewCandidate] = []
        for row in rows:
            counts = {
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
            scenarios = self._candidate_scenarios(counts)
            candidates.append(
                ReviewCandidate(
                    source_patient_link_id=int(row[0]),
                    target_patient_link_id=int(row[1]),
                    patient_uuid=str(row[2]),
                    scenarios=scenarios,
                    feature_counts=counts,
                )
            )
        return candidates

    @staticmethod
    def _candidate_scenarios(counts: Mapping[str, int]) -> list[str]:
        predicates: dict[str, Callable[[Mapping[str, int]], bool]] = {
            "multiple_conditions": lambda c: c["condition_count"] >= 2,
            "medication_lifecycle": lambda c: (
                c["medication_event_count"] >= 2
                and c["medication_change_count"] >= 1
            ),
            "severe_allergy": lambda c: c["severe_allergy_count"] >= 1,
            "patient_self_report": lambda c: c["self_report_count"] >= 1,
            "laboratory_result": lambda c: c["lab_count"] >= 1,
            "typed_enum_flag": lambda c: c["enum_flag_count"] >= 1,
            "dated_flag": lambda c: c["date_flag_count"] >= 1,
            "surgery_history": lambda c: c["surgery_count"] >= 1,
            "medical_history": lambda c: c["medical_history_count"] >= 1,
            "clinical_note": lambda c: c["clinical_note_count"] >= 1,
            "appointment_followup": lambda c: (
                c["appointment_count"] >= 1 and c["followup_count"] >= 1
            ),
            "prescription": lambda c: c["prescription_count"] >= 1,
        }
        scenarios = [
            scenario.key
            for scenario in SCENARIOS
            if scenario.key in predicates and predicates[scenario.key](counts)
        ]
        domain_count = sum(
            (
                counts["condition_count"] > 0,
                counts["medication_event_count"] > 0,
                counts["allergy_count"] > 0,
                counts["vital_count"] > 0,
                counts["lab_count"] > 0,
                counts["flag_count"] > 0,
                counts["surgery_count"] > 0,
                counts["medical_history_count"] > 0,
                counts["clinical_note_count"] > 0,
                counts["appointment_count"] > 0,
                counts["followup_count"] > 0,
                counts["prescription_count"] > 0,
            )
        )
        if domain_count >= 6:
            scenarios.append("complex_full_record")
        return scenarios

    # ---------------------------------------------------------------- selection
    def _select(
        self,
        candidates: list[ReviewCandidate],
    ) -> tuple[list[ReviewCandidate], dict[str, dict[str, Any]], list[str]]:
        scenario_keys = [scenario.key for scenario in SCENARIOS]
        eligible: dict[str, list[ReviewCandidate]] = {
            key: sorted(
                [candidate for candidate in candidates if key in candidate.scenarios],
                key=lambda item: (
                    item.source_patient_link_id,
                    item.target_patient_link_id,
                ),
            )
            for key in scenario_keys
        }
        desired = {
            key: min(self.per_scenario, len(items))
            for key, items in eligible.items()
        }
        selected: list[ReviewCandidate] = []
        selected_ids: set[int] = set()
        covered = Counter()

        while len(selected) < self.max_patients:
            unmet = {
                key for key in scenario_keys if covered[key] < desired[key]
            }
            if not unmet:
                break
            choices = [
                candidate
                for candidate in candidates
                if candidate.target_patient_link_id not in selected_ids
            ]
            if not choices:
                break
            ranked = sorted(
                choices,
                key=lambda candidate: (
                    -sum(key in unmet for key in candidate.scenarios),
                    candidate.source_patient_link_id,
                    candidate.target_patient_link_id,
                ),
            )
            best = ranked[0]
            gain = sum(key in unmet for key in best.scenarios)
            if gain == 0:
                break
            selected.append(best)
            selected_ids.add(best.target_patient_link_id)
            for key in best.scenarios:
                covered[key] += 1

        coverage: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        scenario_map = {scenario.key: scenario for scenario in SCENARIOS}
        for key in scenario_keys:
            chosen = [
                candidate.source_patient_link_id
                for candidate in selected
                if key in candidate.scenarios
            ]
            coverage[key] = {
                "label": scenario_map[key].label,
                "eligible_patients": len(eligible[key]),
                "desired_samples": desired[key],
                "selected_samples": len(chosen),
                "selected_source_patient_link_ids": chosen,
                "status": (
                    "not_present_in_source"
                    if not eligible[key]
                    else "covered"
                    if len(chosen) >= desired[key]
                    else "uncovered_due_to_limit"
                ),
            }
            if eligible[key] and len(chosen) < desired[key]:
                warnings.append(
                    f"Scenario {key} was not fully covered within max_patients={self.max_patients}."
                )

        if not candidates:
            warnings.append(
                "No imported patient_links were found for this source-id."
            )
        return selected, coverage, warnings

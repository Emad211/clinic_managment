"""Read-only context builder for the native five-tab Patient Workspace.

The service reuses existing repositories and source-backed projections. It does not
interpret clinical values, invent lead/referral data or count un-attributed accounting
activity as specialist-clinic revenue.
"""
from __future__ import annotations

from datetime import datetime
import json

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
from src.adapters.sqlite.encounter_documentation_repo import (
    EncounterDocumentationRepository,
)
from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.record_repo import RecordRepository
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.adapters.sqlite.specialist_service_lineage_repo import (
    SpecialistServiceLineageRepository,
)
from src.adapters.sqlite.vitals_repo import VITAL_TYPES, VitalsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.common.utils import iran_now
from src.services.analytics_service import AnalyticsService
from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade
from src.services.patient_cockpit_service import PatientCockpitService
from src.services.patient_service import PatientService
from src.services.sms.governance_service import SmsGovernanceService


WORKSPACE_TABS = {
    "summary": "خلاصه",
    "actions": "اقدامات",
    "clinical": "داده‌های بالینی",
    "meds": "دارو و نسخه",
    "encounters": "ویزیت‌ها و اسناد",
}

_CONTACT_CHANNEL_LABELS = {
    "PHONE": "تماس تلفنی",
    "SMS": "پیامک",
    "IN_PERSON": "حضوری",
    "SYSTEM": "سیستمی",
    "OTHER": "سایر",
}
_CONTACT_OUTCOME_LABELS = {
    "REACHED": "تماس موفق",
    "NO_ANSWER": "پاسخ نداد",
    "BUSY": "خط مشغول",
    "CALLBACK_REQUESTED": "درخواست تماس مجدد",
    "PHONE_INVALID": "شماره نامعتبر",
    "APPOINTMENT_BOOKED": "نوبت ثبت شده",
    "ESCALATED_TO_PHYSICIAN": "ارجاع به پزشک",
    "BOOKED": "نوبت ثبت شده",
    "OTHER": "سایر",
}
_MESSAGE_STATUS_LABELS = {
    "Delivered": "تحویل‌شده",
    "Queued": "در صف",
    "Submitting": "در حال ارسال",
    "PendingApproval": "منتظر تأیید",
    "RetryableFailure": "نیازمند تلاش مجدد",
    "Failed": "ناموفق",
    "Undelivered": "تحویل‌نشده",
    "SubmissionUnknown": "وضعیت ارسال نامشخص",
    "StatusUnknown": "وضعیت تحویل نامشخص",
}


class PatientWorkspaceService:
    @staticmethod
    def _naive_now() -> datetime:
        current = iran_now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return current

    def _contact_summary(self, patient_link_id: int) -> dict:
        rows = get_db().execute(
            """SELECT event.*
               FROM followup_contact_events event
               WHERE event.patient_link_id=?
               ORDER BY event.occurred_at DESC, event.id DESC LIMIT 5""",
            (int(patient_link_id),),
        ).fetchall()
        contacts = []
        for row in rows:
            item = dict(row)
            item["channel_label"] = _CONTACT_CHANNEL_LABELS.get(
                str(item.get("channel") or "").upper(),
                item.get("channel") or "نامشخص",
            )
            item["outcome_label"] = _CONTACT_OUTCOME_LABELS.get(
                str(item.get("outcome") or "").upper(),
                item.get("outcome") or "نامشخص",
            )
            contacts.append(item)
        return {
            "last": contacts[0] if contacts else None,
            "recent": contacts,
            "count": int(
                get_db().execute(
                    """SELECT COUNT(*) AS count FROM followup_contact_events
                       WHERE patient_link_id=?""",
                    (int(patient_link_id),),
                ).fetchone()["count"]
                or 0
            ),
        }

    def _message_summary(self, patient_link_id: int) -> dict:
        rows = get_db().execute(
            """SELECT message.id, message.status, message.delivery_status,
                      message.source_type, message.source_ref,
                      message.created_at, message.sent_at, message.delivered_at,
                      campaign.name AS campaign_name
               FROM sms_messages message
               LEFT JOIN sms_campaigns campaign ON campaign.id=message.campaign_id
               WHERE message.patient_link_id=?
               ORDER BY message.id DESC LIMIT 5""",
            (int(patient_link_id),),
        ).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            status = item.get("delivery_status") or item.get("status") or "نامشخص"
            item["status_label"] = _MESSAGE_STATUS_LABELS.get(str(status), str(status))
            item["display_at"] = (
                item.get("delivered_at")
                or item.get("sent_at")
                or item.get("created_at")
            )
            messages.append(item)
        return {
            "last": messages[0] if messages else None,
            "recent": messages,
            "count": int(
                get_db().execute(
                    """SELECT COUNT(*) AS count FROM sms_messages
                       WHERE patient_link_id=?""",
                    (int(patient_link_id),),
                ).fetchone()["count"]
                or 0
            ),
        }

    def _appointment_lifecycle(self, appointments: list[dict]) -> dict:
        current = self._naive_now()
        scheduled = []
        counts = {
            "scheduled": 0,
            "done": 0,
            "no_show": 0,
            "cancelled": 0,
        }
        for appointment in appointments:
            status = str(appointment.get("status") or "").lower()
            if status in counts:
                counts[status] += 1
            if status != "scheduled":
                continue
            try:
                when = datetime.fromisoformat(str(appointment["scheduled_at"]))
            except (KeyError, TypeError, ValueError):
                continue
            if when.tzinfo is not None:
                when = when.replace(tzinfo=None)
            if when >= current:
                scheduled.append((when, appointment))
        scheduled.sort(key=lambda pair: pair[0])
        return {
            **counts,
            "next": scheduled[0][1] if scheduled else None,
        }

    @staticmethod
    def _financial_summary(patient_link_id: int) -> dict:
        observations = [
            row
            for row in SpecialistFinancialFunnelRepository().latest_observations()
            if int(row.get("patient_link_id") or 0) == int(patient_link_id)
            and str(row.get("invoice_status") or "") == "closed"
        ]
        billed = sum(int(row.get("billed_amount") or 0) for row in observations)
        collected = sum(int(row.get("collected_amount") or 0) for row in observations)
        return {
            "available": bool(observations),
            "invoice_count": len(observations),
            "billed": billed,
            "collected": collected,
            "outstanding": max(billed - collected, 0),
            "latest_observed_at": max(
                (str(row.get("observed_at")) for row in observations if row.get("observed_at")),
                default=None,
            ),
            "evidence_label": "فقط فاکتورهای دارای Encounter و انتساب صریح",
        }

    @staticmethod
    def _enrollment_summary(patient: dict) -> dict:
        accounting_id = patient.get("accounting_patient_id")
        return {
            "source_code": "ACCOUNTING" if accounting_id else "MANUAL",
            "source_label": "ثبت از حسابداری" if accounting_id else "ثبت دستی",
            "enrolled_by": patient.get("enrolled_by"),
            "enrolled_at": patient.get("enrolled_at"),
            "referrer": None,
            "referrer_label": "ثبت نشده",
        }

    def build(self, patient_link_id: int) -> dict | None:
        pid = int(patient_link_id)
        profile = PatientService().get_full_profile(pid)
        if not profile:
            return None

        patient_repo = PatientRepository()
        analytics = AnalyticsService().patient_analytics(pid)
        clinical_v2 = ClinicalEngineReadOnlyFacade().patient_detail(pid)
        vitals_repo = VitalsRepository()
        rules_repo = ClinicalRulesRepository()
        flags_repo = ClinicalFlagsRepository()
        record_repo = RecordRepository()

        condition_codes = [
            condition.get("condition_code")
            for condition in profile["conditions"]
            if condition.get("condition_code")
        ]
        entry_indicators = [
            indicator
            for indicator in rules_repo.for_conditions(condition_codes)
            if indicator.get("is_vital")
        ]
        indicator_labels = {
            indicator["key"]: indicator
            for indicator in rules_repo.all_indicators(active_only=False)
        }
        recent_vitals = vitals_repo.get_readings(pid, limit=50)
        for reading in recent_vitals:
            metadata = indicator_labels.get(reading["type"]) or VITAL_TYPES.get(
                reading["type"], {}
            )
            reading["type_label"] = metadata.get("label", reading["type"])
            reading["unit"] = reading.get("unit") or metadata.get("unit")

        labs = vitals_repo.get_labs(pid)
        appointments = AppointmentRepository().list_for_patient(pid)
        all_followups = FollowupRepository().list_for_patient(pid)
        open_followups = [
            item for item in all_followups if item.get("status") == "open"
        ]

        medications = patient_repo.get_medications(pid, active_only=False)
        medication_events = patient_repo.get_medication_events(pid)
        prescriptions = record_repo.list_prescriptions(pid)
        for prescription in prescriptions:
            try:
                parsed = json.loads(prescription.get("items") or "[]")
            except (TypeError, ValueError):
                parsed = []
            prescription["item_count"] = (
                len(parsed) if isinstance(parsed, (list, dict)) else 0
            )

        service_lines = (
            SpecialistServiceLineageRepository().current_lines_for_patient(
                pid, limit=200
            )
        )
        service_line_summary = {
            "total": len(service_lines),
            "visits": sum(
                1 for row in service_lines if row.get("item_type") == "VISIT"
            ),
            "injections": sum(
                1 for row in service_lines if row.get("item_type") == "INJECTION"
            ),
            "procedures": sum(
                1 for row in service_lines if row.get("item_type") == "PROCEDURE"
            ),
        }
        encounter_documents = (
            EncounterDocumentationRepository().current_signed_documents_for_patient(
                pid, limit=50
            )
        )
        cockpit = PatientCockpitService()
        next_action = cockpit.next_action(
            clinical_v2=clinical_v2,
            followups=open_followups,
            refill_due=analytics["refill_due"],
            appointments=appointments,
            indicators=analytics["indicators"],
        )
        care_timeline = cockpit.timeline(
            appointments=appointments,
            visits=profile["visit_history"],
            labs=labs,
            followups=all_followups,
            medication_events=medication_events,
            service_lines=service_lines,
            encounter_documents=encounter_documents,
        )

        contact_summary = self._contact_summary(pid)
        message_summary = self._message_summary(pid)
        appointment_lifecycle = self._appointment_lifecycle(appointments)
        financial_summary = self._financial_summary(pid)
        enrollment_summary = self._enrollment_summary(profile["patient"])

        wallet_repo = WalletRepository()
        return {
            "patient": profile["patient"],
            "conditions": profile["conditions"],
            "medications": medications,
            "allergies": profile["allergies"],
            "visit_history": profile["visit_history"],
            "reconciliation": profile.get("reconciliation") or {},
            "clinical_v2": clinical_v2,
            "next_action": next_action,
            "entry_indicators": entry_indicators,
            "recent_vitals": recent_vitals,
            "labs": labs,
            "appointments": appointments,
            "appointment_lifecycle": appointment_lifecycle,
            "all_followups": all_followups,
            "followups": open_followups,
            "condition_catalog": patient_repo.list_condition_catalog(),
            "flags_by_section": flags_repo.catalog_by_record_section(),
            "patient_flags": flags_repo.get_flag_states(pid),
            "drug_class_options": flags_repo.drug_classes(),
            "drug_class_map": flags_repo.drug_class_map(),
            "surgeries": record_repo.list_surgeries(pid),
            "medical_history": record_repo.list_history(pid),
            "notes_symptom": record_repo.list_notes(pid, "symptom"),
            "notes_exam": record_repo.list_notes(pid, "exam"),
            "notes_lifestyle": record_repo.list_notes(pid, "lifestyle"),
            "lab_catalog": LabCatalogRepository().all(),
            "drug_catalog": DrugCatalogRepository().all(),
            "medication_events": medication_events,
            "prescriptions": prescriptions,
            "indicators": analytics["indicators"],
            "by_category": analytics["by_category"],
            "per_disease": analytics["per_disease"],
            "refill_due": analytics["refill_due"],
            "appt_summary": analytics["appointments"],
            "visits_count": analytics["visits_count"],
            "last_visit": analytics["last_visit"],
            "care_timeline": care_timeline,
            "encounter_documents": encounter_documents,
            "service_lines": service_lines,
            "service_line_summary": service_line_summary,
            "contact_summary": contact_summary,
            "message_summary": message_summary,
            "financial_summary": financial_summary,
            "enrollment_summary": enrollment_summary,
            "sms_consent": SmsGovernanceService().summary(pid),
            "wallet_balance": wallet_repo.get_balance(pid),
            "wallet_tx": wallet_repo.transactions(pid, limit=20),
        }


__all__ = ["PatientWorkspaceService", "WORKSPACE_TABS"]

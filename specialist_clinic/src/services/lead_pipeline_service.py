"""Small lead lifecycle service focused on conversion, not generic CRM features."""
from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.leads_repo import LeadRepository
from src.common.utils import iran_now
from src.services.patient_service import PatientService


LEAD_SOURCES = {
    "INSTAGRAM": "اینستاگرام",
    "PATIENT_REFERRAL": "معرفی بیمار",
    "DOCTOR_REFERRAL": "معرفی پزشک",
    "CAMPAIGN": "کمپین",
    "WEBSITE": "وب‌سایت",
    "GOOGLE": "گوگل",
    "WALK_IN": "مراجعه حضوری",
    "PHONE": "تماس ورودی",
    "OTHER": "سایر",
}
LEAD_INTERESTS = {
    "GENERAL_VISIT": "ویزیت عمومی",
    "DIABETES": "دیابت",
    "HYPERTENSION": "فشار خون",
    "CHRONIC_CARE": "مراقبت مزمن",
    "BEAUTY": "زیبایی",
    "DENTAL": "دندان‌پزشکی",
    "OTHER": "سایر",
}
LEAD_STATUS_LABELS = {
    "NEW": "جدید",
    "CONTACTED": "تماس گرفته شد",
    "APPOINTMENT_BOOKED": "زمان مراجعه تعیین شد",
    "ATTENDED": "مراجعه کرد",
    "CONVERTED": "تبدیل به بیمار",
    "LOST": "از دست رفته",
}
LEAD_LOST_REASONS = {
    "NO_ANSWER": "پاسخ نداد",
    "PRICE": "هزینه",
    "NO_INTEREST": "عدم تمایل",
    "CHOSE_OTHER_CLINIC": "انتخاب مرکز دیگر",
    "DISTANCE": "فاصله",
    "INVALID_PHONE": "شماره نامعتبر",
    "DUPLICATE": "تکراری",
    "OTHER": "سایر",
}

_ALLOWED_TRANSITIONS = {
    "NEW": {"CONTACTED", "APPOINTMENT_BOOKED", "LOST"},
    "CONTACTED": {"APPOINTMENT_BOOKED", "LOST"},
    "APPOINTMENT_BOOKED": {"ATTENDED", "LOST"},
    "ATTENDED": {"CONVERTED", "LOST"},
    "CONVERTED": set(),
    "LOST": set(),
}


class LeadPipelineError(RuntimeError):
    pass


def _now() -> datetime:
    current = iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.replace(microsecond=0)


def _time_text(value: datetime | str | None) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise LeadPipelineError("زمان انتخاب‌شده معتبر نیست.") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")


class LeadPipelineService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db
        self.repo = LeadRepository(db)

    def create(
        self,
        *,
        full_name: str,
        phone_number: str,
        source_code: str,
        actor_username: str,
        national_id: str | None = None,
        source_detail: str | None = None,
        referrer_name: str | None = None,
        interest_code: str | None = None,
        owner_username: str | None = None,
        next_action_at: datetime | str | None = None,
        notes: str | None = None,
    ) -> dict:
        name = " ".join(str(full_name or "").split())
        phone = self.repo.normalize_phone(phone_number)
        source = str(source_code or "").strip().upper()
        interest = str(interest_code or "").strip().upper() or None
        if not name:
            raise LeadPipelineError("نام سرنخ الزامی است.")
        if len(phone) < 10:
            raise LeadPipelineError("شماره تماس معتبر نیست.")
        if source not in LEAD_SOURCES:
            raise LeadPipelineError("منبع جذب معتبر نیست.")
        if interest and interest not in LEAD_INTERESTS:
            raise LeadPipelineError("خدمت موردعلاقه معتبر نیست.")
        due = _time_text(next_action_at)
        if due is None:
            due = (_now() + timedelta(hours=2)).isoformat(
                sep=" ", timespec="seconds"
            )
        return self.repo.create(
            full_name=name,
            phone_number=phone,
            national_id=str(national_id or "").strip() or None,
            source_code=source,
            source_detail=str(source_detail or "").strip() or None,
            referrer_name=str(referrer_name or "").strip() or None,
            interest_code=interest,
            owner_username=str(owner_username or "").strip() or actor_username,
            next_action_at=due,
            notes=str(notes or "").strip() or None,
            actor_username=actor_username,
        )

    def transition(
        self,
        lead_id: int,
        *,
        to_status: str,
        actor_username: str,
        next_action_at: datetime | str | None = None,
        appointment_at: datetime | str | None = None,
        lost_reason: str | None = None,
        note: str | None = None,
        owner_username: str | None = None,
    ) -> dict:
        lead = self.repo.get(lead_id)
        if not lead:
            raise LeadPipelineError("سرنخ پیدا نشد.")
        target = str(to_status or "").strip().upper()
        if target not in _ALLOWED_TRANSITIONS.get(str(lead["status"]), set()):
            raise LeadPipelineError("این تغییر وضعیت برای مرحله فعلی مجاز نیست.")

        due = _time_text(next_action_at)
        appointment = _time_text(appointment_at)
        reason = str(lost_reason or "").strip().upper() or None
        if target in {"NEW", "CONTACTED"} and not due:
            due = (_now() + timedelta(days=1)).isoformat(
                sep=" ", timespec="seconds"
            )
        if target == "APPOINTMENT_BOOKED":
            if not appointment:
                raise LeadPipelineError("زمان مراجعه الزامی است.")
            if datetime.fromisoformat(appointment) <= _now():
                raise LeadPipelineError("زمان مراجعه باید در آینده باشد.")
            due = appointment
        if target == "ATTENDED":
            due = _now().isoformat(sep=" ", timespec="seconds")
        if target == "LOST":
            if reason not in LEAD_LOST_REASONS:
                raise LeadPipelineError("علت از دست رفتن الزامی است.")
            due = None
        else:
            reason = None

        return self.repo.update_state(
            int(lead_id),
            to_status=target,
            owner_username=owner_username,
            next_action_at=due,
            appointment_at=appointment,
            lost_reason=reason,
            note=str(note or "").strip() or None,
            actor_username=actor_username,
        )

    def convert(self, lead_id: int, *, actor_username: str) -> dict:
        lead = self.repo.get(lead_id)
        if not lead:
            raise LeadPipelineError("سرنخ پیدا نشد.")
        if lead["status"] not in {"ATTENDED", "APPOINTMENT_BOOKED"}:
            raise LeadPipelineError(
                "تبدیل فقط پس از تعیین زمان مراجعه یا ثبت حضور انجام می‌شود."
            )
        if lead.get("patient_link_id"):
            return {
                **lead,
                "patient_link_id": int(lead["patient_link_id"]),
                "duplicate": True,
            }

        db = self.repo._db()
        existing = None
        if lead.get("national_id"):
            existing = db.execute(
                """SELECT id FROM patient_links
                   WHERE national_id=? AND is_active=1 ORDER BY id LIMIT 1""",
                (lead["national_id"],),
            ).fetchone()
        if existing is None:
            existing = db.execute(
                """SELECT id FROM patient_links
                   WHERE phone_number=? AND is_active=1 ORDER BY id LIMIT 1""",
                (lead["phone_number"],),
            ).fetchone()

        if existing:
            patient_id = int(existing["id"])
            created_patient = False
        else:
            patient_id = PatientService().enroll_manual(
                full_name=lead["full_name"],
                national_id=lead.get("national_id"),
                phone_number=lead["phone_number"],
                gender=None,
                birthdate=None,
                address=None,
                enrolled_by=actor_username,
            )
            created_patient = True

        appointment_id = None
        appointment_status = None
        appointment_at = lead.get("appointment_at")
        if appointment_at:
            try:
                when = datetime.fromisoformat(str(appointment_at))
            except ValueError:
                when = None
            if when:
                appointment_repo = AppointmentRepository(db)
                appointment_id = appointment_repo.create(
                    patient_id,
                    scheduled_at=appointment_at,
                    appt_type="visit",
                    notes=(
                        "مراجعه منتقل‌شده از سرنخ؛ منبع: "
                        + LEAD_SOURCES.get(lead["source_code"], lead["source_code"])
                    ),
                    created_by=actor_username,
                )
                if lead["status"] == "ATTENDED" or when <= _now():
                    appointment_repo.set_status(appointment_id, "done")
                    appointment_status = "done"
                else:
                    appointment_status = "scheduled"

        converted_at = _now().isoformat(sep=" ", timespec="seconds")
        updated = self.repo.update_state(
            int(lead_id),
            to_status="CONVERTED",
            next_action_at=None,
            appointment_at=appointment_at,
            lost_reason=None,
            note="تبدیل صریح سرنخ به بیمار",
            actor_username=actor_username,
            patient_link_id=patient_id,
            appointment_id=appointment_id,
            converted_at=converted_at,
            payload={
                "created_patient": created_patient,
                "appointment_status": appointment_status,
            },
        )
        return {
            **updated,
            "patient_link_id": patient_id,
            "appointment_id": appointment_id,
            "appointment_status": appointment_status,
            "created_patient": created_patient,
            "duplicate": False,
        }

    def dashboard(self, *, status=None, owner_username=None, query=None) -> dict:
        leads = self.repo.list(
            status=status,
            owner_username=owner_username,
            query=query,
        )
        now_text = _now().isoformat(sep=" ", timespec="seconds")
        due_count = sum(
            1
            for lead in leads
            if lead.get("next_action_at")
            and lead["status"] in {"NEW", "CONTACTED", "APPOINTMENT_BOOKED", "ATTENDED"}
            and str(lead["next_action_at"]) <= now_text
        )
        counts = self.repo.counts()
        total_decided = counts.get("CONVERTED", 0) + counts.get("LOST", 0)
        conversion_rate = (
            round(counts.get("CONVERTED", 0) * 100 / total_decided, 1)
            if total_decided
            else 0.0
        )
        return {
            "leads": leads,
            "counts": counts,
            "due_count": due_count,
            "conversion_rate": conversion_rate,
        }


__all__ = [
    "LEAD_INTERESTS",
    "LEAD_LOST_REASONS",
    "LEAD_SOURCES",
    "LEAD_STATUS_LABELS",
    "LeadPipelineError",
    "LeadPipelineService",
]

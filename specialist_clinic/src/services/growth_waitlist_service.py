"""Appointment waitlist and cancellation-slot fill orchestration."""
from __future__ import annotations

from datetime import date, datetime
import sqlite3

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.growth_waitlist_repo import GrowthWaitlistRepository
from src.common.utils import iran_now


TIME_WINDOWS = {
    "ANY": "هر زمان",
    "MORNING": "صبح",
    "AFTERNOON": "بعدازظهر",
    "EVENING": "عصر",
}
WAITLIST_STATUS_LABELS = {
    "WAITING": "در انتظار",
    "OFFERED": "Slot پیشنهاد شده",
    "BOOKED": "نوبت ثبت شد",
    "CANCELLED": "لغوشده",
}


class GrowthWaitlistError(RuntimeError):
    pass


def _now() -> datetime:
    current = iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.replace(microsecond=0)


class GrowthWaitlistService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db or get_db()
        self.repo = GrowthWaitlistRepository(self.db)
        self.appointments = AppointmentRepository(self.db)
        self.followups = FollowupRepository(self.db)

    def create_entry(
        self,
        *,
        patient_link_id: int,
        appt_type: str,
        date_from: str | None,
        date_to: str | None,
        time_window: str,
        auto_fill: bool,
        priority: int,
        notes: str | None,
        created_by: str,
        source_code: str = "STAFF_REQUEST",
    ) -> dict:
        patient = self.db.execute(
            "SELECT id FROM patient_links WHERE id=? AND is_active=1",
            (int(patient_link_id),),
        ).fetchone()
        if not patient:
            raise GrowthWaitlistError("بیمار فعال پیدا نشد.")
        window = str(time_window or "ANY").strip().upper()
        if window not in TIME_WINDOWS:
            raise GrowthWaitlistError("بازهٔ زمانی معتبر نیست.")
        start = str(date_from or "").strip() or None
        end = str(date_to or "").strip() or None
        try:
            parsed_start = date.fromisoformat(start) if start else None
            parsed_end = date.fromisoformat(end) if end else None
        except ValueError as exc:
            raise GrowthWaitlistError("بازهٔ تاریخ معتبر نیست.") from exc
        if parsed_start and parsed_end and parsed_end < parsed_start:
            raise GrowthWaitlistError("پایان بازه نمی‌تواند قبل از شروع باشد.")
        normalized_priority = max(1, min(int(priority or 100), 999))
        return self.repo.create(
            patient_link_id=int(patient_link_id),
            appt_type=str(appt_type or "visit").strip() or "visit",
            date_from=start,
            date_to=end,
            time_window=window,
            auto_fill=bool(auto_fill),
            priority=normalized_priority,
            source_code=str(source_code or "STAFF_REQUEST"),
            notes=str(notes or "").strip() or None,
            created_by=created_by,
        )

    def _cancelled_slots(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT appointment.*
               FROM appointments appointment
               WHERE appointment.status='cancelled'
                 AND datetime(appointment.scheduled_at)>
                     datetime('now','+3 hours','+30 minutes')
                 AND NOT EXISTS (
                   SELECT 1 FROM growth_slot_fill_events event
                   WHERE event.cancelled_appointment_id=appointment.id
                 )
               ORDER BY appointment.scheduled_at,appointment.id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def fill_cancelled_slots(
        self,
        *,
        actor_username: str,
        assigned_to: str | None = None,
    ) -> dict:
        auto_booked = []
        offers = []
        unmatched = []
        for slot in self._cancelled_slots():
            candidates = self.repo.matching_for_slot(
                slot_at=str(slot["scheduled_at"]),
                appt_type=str(slot.get("appt_type") or "visit"),
            )
            if not candidates:
                unmatched.append(int(slot["id"]))
                continue
            entry = candidates[0]
            if int(entry.get("auto_fill") or 0):
                replacement_id = self.appointments.create(
                    int(entry["patient_link_id"]),
                    scheduled_at=str(slot["scheduled_at"]),
                    appt_type=str(slot.get("appt_type") or entry["appt_type"]),
                    notes=(
                        "رزرو خودکار از صف انتظار؛ Slot آزادشده از نوبت "
                        f"{int(slot['id'])}"
                    ),
                    created_by=actor_username,
                )
                self.repo.set_status(
                    int(entry["id"]),
                    status="BOOKED",
                    offered_slot_at=str(slot["scheduled_at"]),
                    booked_appointment_id=replacement_id,
                )
                self.repo.record_slot_fill(
                    cancelled_appointment_id=int(slot["id"]),
                    waitlist_entry_id=int(entry["id"]),
                    replacement_appointment_id=replacement_id,
                    mode="AUTO_BOOKED",
                    slot_at=str(slot["scheduled_at"]),
                    created_by=actor_username,
                )
                task_id = self.followups.create(
                    int(entry["patient_link_id"]),
                    reason="waitlist_auto_booked_notification",
                    detail=(
                        f"نوبت {replacement_id} از صف انتظار خودکار ثبت شد؛ "
                        "اطلاع‌رسانی به بیمار را تکمیل کنید."
                    ),
                    due_date=_now().isoformat(sep=" ", timespec="seconds"),
                    assigned_to=assigned_to,
                    source_rule=f"growth:waitlist-auto:{int(slot['id'])}",
                    source_event="waitlist_auto_booked",
                    appointment_id=replacement_id,
                    fulfillment="remote",
                )
                auto_booked.append(
                    {
                        "slot_id": int(slot["id"]),
                        "entry_id": int(entry["id"]),
                        "appointment_id": replacement_id,
                        "task_id": task_id,
                    }
                )
            else:
                self.repo.set_status(
                    int(entry["id"]),
                    status="OFFERED",
                    offered_slot_at=str(slot["scheduled_at"]),
                )
                self.repo.record_slot_fill(
                    cancelled_appointment_id=int(slot["id"]),
                    waitlist_entry_id=int(entry["id"]),
                    replacement_appointment_id=None,
                    mode="OFFER_CREATED",
                    slot_at=str(slot["scheduled_at"]),
                    created_by=actor_username,
                )
                task_id = self.followups.create(
                    int(entry["patient_link_id"]),
                    reason="waitlist_slot_offer",
                    detail=(
                        f"Slot آزاد {slot['scheduled_at']} را به "
                        f"{entry['patient_name']} پیشنهاد دهید."
                    ),
                    due_date=_now().isoformat(sep=" ", timespec="seconds"),
                    assigned_to=assigned_to,
                    source_rule=f"growth:waitlist-offer:{int(slot['id'])}",
                    source_event="waitlist_slot_offer",
                    fulfillment="remote",
                )
                offers.append(
                    {
                        "slot_id": int(slot["id"]),
                        "entry_id": int(entry["id"]),
                        "task_id": task_id,
                    }
                )
        return {
            "slots": len(auto_booked) + len(offers) + len(unmatched),
            "auto_booked": len(auto_booked),
            "offers": len(offers),
            "unmatched": len(unmatched),
            "auto_booked_items": auto_booked,
            "offer_items": offers,
            "unmatched_slot_ids": unmatched,
        }

    def book_offered_entry(
        self,
        entry_id: int,
        *,
        actor_username: str,
    ) -> dict:
        entry = self.repo.get(entry_id)
        if not entry or entry["status"] != "OFFERED":
            raise GrowthWaitlistError("پیشنهاد فعال پیدا نشد.")
        event = self.db.execute(
            """SELECT event.*,appointment.appt_type
               FROM growth_slot_fill_events event
               JOIN appointments appointment
                 ON appointment.id=event.cancelled_appointment_id
               WHERE event.waitlist_entry_id=? AND event.mode='OFFER_CREATED'
                 AND event.replacement_appointment_id IS NULL
               ORDER BY event.id DESC LIMIT 1""",
            (int(entry_id),),
        ).fetchone()
        if not event:
            raise GrowthWaitlistError("Slot پیشنهادی پیدا نشد.")
        if datetime.fromisoformat(str(event["slot_at"])) <= _now():
            raise GrowthWaitlistError("زمان Slot پیشنهادی گذشته است.")
        appointment_id = self.appointments.create(
            int(entry["patient_link_id"]),
            scheduled_at=str(event["slot_at"]),
            appt_type=str(event["appt_type"] or entry["appt_type"]),
            notes="رزرو تأییدشده از صف انتظار",
            created_by=actor_username,
        )
        self.db.execute(
            """UPDATE growth_slot_fill_events
               SET replacement_appointment_id=? WHERE id=?""",
            (appointment_id, int(event["id"])),
        )
        self.repo.set_status(
            int(entry_id),
            status="BOOKED",
            booked_appointment_id=appointment_id,
        )
        task = self.db.execute(
            """SELECT id FROM followup_tasks
               WHERE source_rule=? AND status='open' ORDER BY id DESC LIMIT 1""",
            (f"growth:waitlist-offer:{int(event['cancelled_appointment_id'])}",),
        ).fetchone()
        if task:
            self.followups.set_appointment(int(task["id"]), appointment_id)
            self.followups.resolve(
                int(task["id"]),
                "done",
                call_log=f"پیشنهاد پذیرفته شد; appointment={appointment_id}",
            )
        self.db.commit()
        return {
            "entry_id": int(entry_id),
            "appointment_id": appointment_id,
            "patient_link_id": int(entry["patient_link_id"]),
        }

    def cancel_entry(self, entry_id: int) -> dict:
        entry = self.repo.get(entry_id)
        if not entry:
            raise GrowthWaitlistError("ورودی صف انتظار پیدا نشد.")
        if entry["status"] == "BOOKED":
            raise GrowthWaitlistError("نوبت ثبت‌شده را از صفحه نوبت‌ها مدیریت کنید.")
        return self.repo.set_status(int(entry_id), status="CANCELLED")

    def dashboard(self, *, status: str | None = None) -> dict:
        return {
            "entries": self.repo.list(status=status),
            "counts": self.repo.counts(),
            "open_slots": len(self._cancelled_slots()),
        }


__all__ = [
    "GrowthWaitlistError",
    "GrowthWaitlistService",
    "TIME_WINDOWS",
    "WAITLIST_STATUS_LABELS",
]

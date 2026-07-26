"""Atomic BOOKED transition across appointment, tasks and contact history."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.clinical_care_loop_repo import (
    ClinicalCareLoopRepository,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followup_operations_repo import (
    FollowupOperationsRepository,
)
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.encounter_plan_commitment_repo import (
    EncounterPlanCommitmentRepository,
)
from src.common.utils import iran_now


_NON_TERMINAL_CLINICAL = {
    "OPEN",
    "ASSIGNED",
    "SCHEDULED",
    "IN_PROGRESS",
    "DEFERRED",
}


class FollowupBookingError(RuntimeError):
    pass


def _hash(payload: dict) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class FollowupBookingService:
    def __init__(self, db: sqlite3.Connection | None = None, clock=None):
        self._connection = db
        self.clock = clock or iran_now

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def book(
        self,
        *,
        patient_link_id: int,
        task_ids: list[int],
        scheduled_at: str,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
    ) -> dict:
        patient_id = int(patient_link_id)
        normalized_ids = sorted({int(value) for value in task_ids if value})
        key = str(idempotency_key or "").strip()
        actor = str(actor_username or "").strip()
        if not normalized_ids:
            raise FollowupBookingError("حداقل یک پیگیری الزامی است")
        if len(key) < 12:
            raise FollowupBookingError("شناسهٔ یکتای درخواست رزرو نامعتبر است")
        if not actor:
            raise FollowupBookingError("ثبت‌کنندهٔ رزرو الزامی است")
        try:
            datetime.fromisoformat(str(scheduled_at))
        except ValueError as exc:
            raise FollowupBookingError("زمان نوبت نامعتبر است") from exc

        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            prior = db.execute(
                "SELECT * FROM followup_booking_requests WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if prior:
                prior_tasks = json.loads(prior["task_ids_json"])
                if (
                    int(prior["patient_link_id"]) != patient_id
                    or str(prior["scheduled_at"]) != str(scheduled_at)
                    or prior_tasks != normalized_ids
                ):
                    raise FollowupBookingError(
                        "شناسهٔ رزرو قبلاً برای درخواست دیگری مصرف شده است"
                    )
                db.commit()
                return {
                    "appointment_id": int(prior["appointment_id"]),
                    "admin_booked": sum(
                        1 for task_id in normalized_ids
                        if self._task_kind(db, task_id) == "admin"
                    ),
                    "clinical_scheduled": sum(
                        1 for task_id in normalized_ids
                        if self._task_kind(db, task_id) == "clinical_v2"
                    ),
                    "plan_scheduled": sum(
                        1 for task_id in normalized_ids
                        if self._task_kind(db, task_id) == "encounter_plan"
                    ),
                    "duplicate": True,
                }

            marks = ",".join("?" for _ in normalized_ids)
            task_rows = db.execute(
                f"""SELECT * FROM followup_tasks
                    WHERE id IN ({marks}) AND patient_link_id=?""",
                (*normalized_ids, patient_id),
            ).fetchall()
            if len(task_rows) != len(normalized_ids):
                raise FollowupBookingError(
                    "یکی از پیگیری‌ها وجود ندارد یا متعلق به بیمار دیگری است"
                )

            clinical_repo = ClinicalCareLoopRepository(db)
            plan_repo = EncounterPlanCommitmentRepository(db)
            admin_ids: list[int] = []
            clinical_heads: dict[int, dict] = {}
            plan_heads: dict[int, dict] = {}
            for row in task_rows:
                task_id = int(row["id"])
                if row["source_engine"] == "clinical_v2":
                    current = clinical_repo.current_task(task_id)
                    if current["current_status"] not in _NON_TERMINAL_CLINICAL:
                        raise FollowupBookingError(
                            f"پیگیری بالینی {task_id} دیگر باز نیست"
                        )
                    clinical_heads[task_id] = current
                elif row["source_engine"] == "encounter_plan":
                    current = plan_repo.current_for_task(task_id)
                    if not current or current["current_status"] not in {
                        "OPEN", "IN_PROGRESS", "SCHEDULED"
                    }:
                        raise FollowupBookingError(
                            f"تعهد طرح {task_id} دیگر باز نیست"
                        )
                    plan_heads[task_id] = current
                else:
                    if row["status"] != "open":
                        raise FollowupBookingError(
                            f"پیگیری اداری {task_id} دیگر باز نیست"
                        )
                    admin_ids.append(task_id)

            appointment_id = AppointmentRepository(db).create(
                patient_id,
                scheduled_at=scheduled_at,
                appt_type="visit",
                notes=(
                    "ویزیت ناشی از ورک‌لیست؛ BOOKED مرحلهٔ میانی است و "
                    "پیگیری تا حضور یا نتیجه باز می‌ماند"
                ),
                created_by=actor,
                commit=False,
            )
            if admin_ids:
                FollowupRepository(db).assign_appointment_bulk(
                    admin_ids, appointment_id, commit=False
                )

            contacts = FollowupOperationsRepository(db)
            for task_id in normalized_ids:
                contacts.create_contact(
                    task_id=task_id,
                    channel="SYSTEM",
                    outcome="BOOKED",
                    actor_username=actor,
                    actor_user_id=actor_user_id,
                    idempotency_key=f"{key}:task:{task_id}",
                    note=(
                        f"نوبت #{appointment_id} از ورک‌لیست رزرو شد؛ "
                        "task تا حضور یا نتیجه باز است."
                    ),
                    commit=False,
                )

            for task_id, current in clinical_heads.items():
                clinical_repo.append_task_event(
                    task_id,
                    event_type="SCHEDULED",
                    expected_current_event_id=int(current["current_event_id"]),
                    actor_username=actor,
                    actor_user_id=actor_user_id,
                    appointment_id=appointment_id,
                    note="از ورک‌لیست به ویزیت زمان‌بندی شد",
                    commit=False,
                )
            for task_id, current in plan_heads.items():
                plan_repo.append_event(
                    task_id=task_id,
                    event_type="SCHEDULED",
                    expected_current_event_id=int(current["current_event_id"]),
                    actor_username=actor,
                    actor_user_id=actor_user_id,
                    appointment_id=appointment_id,
                    idempotency_key=f"{key}:plan:{task_id}",
                    note="تعهد طرح Encounter به نوبت زمان‌بندی شد",
                    commit=False,
                )

            created_at = self.clock()
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            created_text = created_at.isoformat(sep=" ", timespec="seconds")
            payload = {
                "idempotency_key": key,
                "patient_link_id": patient_id,
                "appointment_id": appointment_id,
                "scheduled_at": str(scheduled_at),
                "task_ids": normalized_ids,
                "actor_user_id": int(actor_user_id) if actor_user_id else None,
                "actor_username": actor,
                "created_at": created_text,
            }
            db.execute(
                """INSERT INTO followup_booking_requests
                   (idempotency_key, patient_link_id, appointment_id,
                    scheduled_at, task_ids_json, actor_user_id,
                    actor_username, created_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    patient_id,
                    appointment_id,
                    str(scheduled_at),
                    json.dumps(normalized_ids, separators=(",", ":")),
                    payload["actor_user_id"],
                    actor,
                    created_text,
                    _hash(payload),
                ),
            )
            db.commit()
            return {
                "appointment_id": appointment_id,
                "admin_booked": len(admin_ids),
                "clinical_scheduled": len(clinical_heads),
                "plan_scheduled": len(plan_heads),
                "duplicate": False,
            }
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _task_kind(db: sqlite3.Connection, task_id: int) -> str:
        row = db.execute(
            "SELECT COALESCE(source_engine,'') AS source_engine "
            "FROM followup_tasks WHERE id=?",
            (int(task_id),),
        ).fetchone()
        return str(row["source_engine"] or "admin") if row else "missing"

    @classmethod
    def _is_clinical(cls, db: sqlite3.Connection, task_id: int) -> bool:
        return cls._task_kind(db, task_id) == "clinical_v2"

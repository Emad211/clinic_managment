from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A10 booking target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 booking anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''from src.adapters.sqlite.followups_repo import FollowupRepository
''',
    '''from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.encounter_plan_commitment_repo import (
    EncounterPlanCommitmentRepository,
)
''',
)
# Duplicate response counts.
replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''                    "clinical_scheduled": sum(
                        1
                        for task_id in normalized_ids
                        if self._is_clinical(db, task_id)
                    ),
                    "duplicate": True,
''',
    '''                    "clinical_scheduled": sum(
                        1 for task_id in normalized_ids
                        if self._task_kind(db, task_id) == "clinical_v2"
                    ),
                    "plan_scheduled": sum(
                        1 for task_id in normalized_ids
                        if self._task_kind(db, task_id) == "encounter_plan"
                    ),
                    "duplicate": True,
''',
)
# Categorize current task heads.
replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''            clinical_repo = ClinicalCareLoopRepository(db)
            admin_ids: list[int] = []
            clinical_heads: dict[int, dict] = {}
            for row in task_rows:
                task_id = int(row["id"])
                if row["source_engine"] == "clinical_v2":
''',
    '''            clinical_repo = ClinicalCareLoopRepository(db)
            plan_repo = EncounterPlanCommitmentRepository(db)
            admin_ids: list[int] = []
            clinical_heads: dict[int, dict] = {}
            plan_heads: dict[int, dict] = {}
            for row in task_rows:
                task_id = int(row["id"])
                if row["source_engine"] == "clinical_v2":
''',
)
replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''                    clinical_heads[task_id] = current
                else:
                    if row["status"] != "open":
''',
    '''                    clinical_heads[task_id] = current
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
''',
)
# Append Plan SCHEDULED after clinical schedules.
replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''            for task_id, current in clinical_heads.items():
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

            created_at = self.clock()
''',
    '''            for task_id, current in clinical_heads.items():
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
''',
)
replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''                "clinical_scheduled": len(clinical_heads),
                "duplicate": False,
''',
    '''                "clinical_scheduled": len(clinical_heads),
                "plan_scheduled": len(plan_heads),
                "duplicate": False,
''',
)
# Replace kind helper while preserving compatibility.
replace_once(
    "specialist_clinic/src/services/followup_booking_service.py",
    '''    @staticmethod
    def _is_clinical(db: sqlite3.Connection, task_id: int) -> bool:
        row = db.execute(
            "SELECT source_engine FROM followup_tasks WHERE id=?",
            (int(task_id),),
        ).fetchone()
        return bool(row and row["source_engine"] == "clinical_v2")
''',
    '''    @staticmethod
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
''',
)

# Booking route permission checks Plan tasks separately.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''    if any(row["source_engine"] == "clinical_v2" for row in rows) and not has_permission(
        Permission.CLINICAL_TASK_TRANSITION
    ):
        flash("مجوز زمان‌بندی پیگیری بالینی ثبت نشده است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
''',
    '''    if any(row["source_engine"] == "clinical_v2" for row in rows) and not has_permission(
        Permission.CLINICAL_TASK_TRANSITION
    ):
        flash("مجوز زمان‌بندی پیگیری بالینی ثبت نشده است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    if any(row["source_engine"] == "encounter_plan" for row in rows) and not has_permission(
        Permission.FOLLOWUP_PLAN_TRANSITION
    ):
        flash("مجوز زمان‌بندی تعهد طرح Encounter ثبت نشده است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
''',
)

Path(__file__).unlink()

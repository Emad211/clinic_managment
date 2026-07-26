from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A1 transaction anchor missing: {relative}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# FollowupRepository can participate in a caller-owned booking unit of work.
patch(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    '''from __future__ import annotations

from src.adapters.sqlite.clinical_care_loop_schema import (
''',
    '''from __future__ import annotations

import sqlite3

from src.adapters.sqlite.clinical_care_loop_schema import (
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    '''class FollowupRepository:
    def active_patient_ids(self) -> list[int]:
''',
    '''class FollowupRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def active_patient_ids(self) -> list[int]:
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    '''    def assign_appointment_bulk(
        self,
        task_ids: list,
        appointment_id,
    ):
''',
    '''    def assign_appointment_bulk(
        self,
        task_ids: list,
        appointment_id,
        *,
        commit: bool = True,
    ):
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    '''        db = get_db()
        self._assert_administrative(db, normalized)
''',
    '''        db = self._db()
        self._assert_administrative(db, normalized)
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    '''        db.commit()

    def exists_open''',
    '''        if commit:
            db.commit()

    def exists_open''',
)

# ClinicalCareLoopRepository preserves default atomic behavior but can join a larger UoW.
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''    def _db(self):
        db = self._connection or get_db()
        ensure_clinical_care_loop_storage(db)
        return db
''',
    '''    def _db(self):
        if self._connection is not None:
            return self._connection
        db = get_db()
        ensure_clinical_care_loop_storage(db)
        return db
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''        recorded_at: datetime | None = None,
    ) -> dict:
''',
    '''        recorded_at: datetime | None = None,
        commit: bool = True,
    ) -> dict:
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''        db.execute("BEGIN IMMEDIATE")
        try:
''',
    '''        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
''',
)
# The first occurrence above modifies record_outcome. Add commit-aware completion there.
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise

    def append_task_event(
''',
    '''            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def append_task_event(
''',
)
# append_task_event signature and transaction controls.
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''        effective_at: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> dict:
''',
    '''        effective_at: datetime | None = None,
        recorded_at: datetime | None = None,
        commit: bool = True,
    ) -> dict:
''',
)
# There is a second BEGIN IMMEDIATE, now patch the remaining literal.
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''        db.execute("BEGIN IMMEDIATE")
        try:
            self._task(db, task_id)
''',
    '''        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            self._task(db, task_id)
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise
''',
    '''            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise
''',
)

# Health/audit include idempotent booking ledger too.
patch(
    "specialist_clinic/src/api/health.py",
    '''        "followup_contact_events",
''',
    '''        "followup_contact_events",
        "followup_booking_requests",
''',
)
patch(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "followup_contact_events",
    "security_permission_events",
''',
    '''    "followup_contact_events",
    "followup_booking_requests",
    "security_permission_events",
''',
)

Path(__file__).unlink()

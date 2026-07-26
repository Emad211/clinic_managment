"""Repository for atomic local enrollment and immutable specialist cutovers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)


class SpecialistEnrollmentConflict(RuntimeError):
    pass


_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _canonical_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _text(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


class SpecialistEnrollmentRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        ensure_specialist_revenue_boundary_storage(db)
        return db

    def connection(self) -> sqlite3.Connection:
        """Expose the canonical connection so the service can own one Unit of Work."""
        return self._db()

    def local_link_by_accounting_patient(
        self, accounting_patient_id: int
    ) -> dict | None:
        row = self._db().execute(
            """SELECT id, national_id, accounting_patient_id, full_name, enrolled_at
               FROM patient_links WHERE accounting_patient_id=?""",
            (int(accounting_patient_id),),
        ).fetchone()
        return dict(row) if row else None

    def local_link_by_national_id(self, national_id: str | None) -> dict | None:
        value = str(national_id or "").strip()
        if not value:
            return None
        row = self._db().execute(
            """SELECT id, national_id, accounting_patient_id, full_name, enrolled_at
               FROM patient_links WHERE national_id=?""",
            (value,),
        ).fetchone()
        return dict(row) if row else None

    def get_by_patient(self, patient_link_id: int) -> dict | None:
        row = self._db().execute(
            "SELECT * FROM specialist_program_enrollments WHERE patient_link_id=?",
            (int(patient_link_id),),
        ).fetchone()
        return dict(row) if row else None

    def get_by_accounting_patient(self, accounting_patient_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT * FROM specialist_program_enrollments
               WHERE accounting_patient_id=?""",
            (int(accounting_patient_id),),
        ).fetchone()
        return dict(row) if row else None

    def create_local_link_from_accounting(
        self,
        *,
        accounting_patient: dict,
        accounting_patient_id: int,
        enrolled_at: datetime | str,
        created_by: str,
        commit: bool = True,
    ) -> int:
        """Insert the local patient mirror without mutating accounting.

        This method deliberately refuses to adopt a pre-existing local row. Adoption
        needs a reviewed migration because it would also choose a financial cutover.
        """
        db = self._db()
        accounting_id = int(accounting_patient_id)
        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("created_by is required")
        full_name = str(accounting_patient.get("full_name") or "").strip()
        if not full_name:
            raise ValueError("accounting patient full_name is required")
        national_id = str(accounting_patient.get("national_id") or "").strip() or None

        existing_accounting = self.local_link_by_accounting_patient(accounting_id)
        if existing_accounting:
            raise SpecialistEnrollmentConflict(
                "LEGACY_LINK_WITHOUT_CUTOVER: accounting patient already has a local row"
            )
        existing_national = self.local_link_by_national_id(national_id)
        if existing_national:
            raise SpecialistEnrollmentConflict(
                "LOCAL_IDENTITY_ALREADY_EXISTS: do not infer accounting linkage or cutover"
            )

        when = _text(enrolled_at)
        cursor = db.execute(
            """INSERT INTO patient_links
               (national_id, accounting_patient_id, full_name, phone_number,
                gender, birthdate, address, enrolled_by, enrolled_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                national_id,
                accounting_id,
                full_name,
                str(accounting_patient.get("phone_number") or "").strip() or None,
                str(accounting_patient.get("gender") or "").strip() or None,
                str(accounting_patient.get("birthdate") or "").strip() or None,
                str(accounting_patient.get("address") or "").strip() or None,
                actor,
                when,
                when,
            ),
        )
        if commit:
            db.commit()
        return int(cursor.lastrowid)

    def create_once(
        self,
        *,
        patient_link_id: int,
        accounting_patient_id: int,
        effective_at: datetime | str,
        accounting_snapshot_at: datetime | str,
        accounting_invoice_cutoff_id: int,
        created_by: str,
        commit: bool = True,
    ) -> dict:
        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("created_by is required")
        effective = _text(effective_at)
        snapshot = _text(accounting_snapshot_at)
        cutoff = int(accounting_invoice_cutoff_id or 0)
        if cutoff < 0:
            raise ValueError("accounting_invoice_cutoff_id cannot be negative")
        if datetime.fromisoformat(snapshot) < datetime.fromisoformat(effective):
            raise ValueError("accounting snapshot cannot precede enrollment effective_at")
        payload = {
            "patient_link_id": int(patient_link_id),
            "accounting_patient_id": int(accounting_patient_id),
            "effective_at": effective,
            "accounting_snapshot_at": snapshot,
            "accounting_invoice_cutoff_id": cutoff,
            "history_policy": "VISIBLE_EXCLUDED",
            "created_by": actor,
        }
        digest = _canonical_hash(payload)
        db = self._db()
        local = db.execute(
            "SELECT id, accounting_patient_id FROM patient_links WHERE id=?",
            (int(patient_link_id),),
        ).fetchone()
        if not local:
            raise LookupError("specialist patient link not found")
        if int(local["accounting_patient_id"] or 0) != int(accounting_patient_id):
            raise SpecialistEnrollmentConflict(
                "local patient/accounting identity mismatch"
            )

        existing = self.get_by_patient(patient_link_id)
        if existing:
            same = all(
                (
                    int(existing["accounting_patient_id"]) == int(accounting_patient_id),
                    int(existing["accounting_invoice_cutoff_id"]) == cutoff,
                    existing["content_hash"] == digest,
                )
            )
            if not same:
                raise SpecialistEnrollmentConflict(
                    "specialist enrollment cutover is immutable"
                )
            return existing

        cursor = db.execute(
            """INSERT INTO specialist_program_enrollments
               (patient_link_id, accounting_patient_id, effective_at,
                accounting_snapshot_at, accounting_invoice_cutoff_id,
                history_policy, created_by, content_hash, created_at)
               VALUES (?, ?, ?, ?, ?, 'VISIBLE_EXCLUDED', ?, ?, ?)""",
            (
                int(patient_link_id),
                int(accounting_patient_id),
                effective,
                snapshot,
                cutoff,
                actor,
                digest,
                snapshot,
            ),
        )
        if commit:
            db.commit()
        row = db.execute(
            "SELECT * FROM specialist_program_enrollments WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)

    def count(self) -> int:
        row = self._db().execute(
            "SELECT COUNT(*) AS count FROM specialist_program_enrollments"
        ).fetchone()
        return int(row["count"] or 0)

    def missing_scope_count(self) -> int:
        row = self._db().execute(
            """SELECT COUNT(*) AS count
               FROM patient_links patient
               WHERE patient.accounting_patient_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM specialist_program_enrollments enrollment
                     WHERE enrollment.patient_link_id=patient.id
                 )"""
        ).fetchone()
        return int(row["count"] or 0)

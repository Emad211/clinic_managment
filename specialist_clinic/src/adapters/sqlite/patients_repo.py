"""Repository for patient_links and their longitudinal clinical records."""
from __future__ import annotations

from typing import Any, Optional

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, today_str


class PatientRepository:
    # ---- patient_links ----
    def get_by_id(self, pid: int) -> Optional[dict]:
        row = get_db().execute(
            "SELECT * FROM patient_links WHERE id = ?", (pid,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_national_id(self, national_id: str) -> Optional[dict]:
        row = get_db().execute(
            "SELECT * FROM patient_links WHERE national_id = ?", (national_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_patients(self, query: str = "") -> list[dict]:
        db = get_db()
        q = (query or "").strip()
        if q:
            like = f"%{q}%"
            rows = db.execute(
                """SELECT * FROM patient_links
                   WHERE is_active=1
                     AND (full_name LIKE ? OR COALESCE(national_id,'') LIKE ?
                          OR COALESCE(phone_number,'') LIKE ?)
                   ORDER BY id DESC""",
                (like, like, like),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM patient_links
                   WHERE is_active=1 ORDER BY id DESC LIMIT 500"""
            ).fetchall()
        return [dict(row) for row in rows]

    def create(
        self,
        *,
        national_id,
        accounting_patient_id,
        full_name,
        phone_number,
        gender,
        birthdate,
        address,
        enrolled_by,
        commit: bool = True,
    ) -> int:
        db = get_db()
        cursor = db.execute(
            """INSERT INTO patient_links
               (national_id, accounting_patient_id, full_name, phone_number,
                gender, birthdate, address, enrolled_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                national_id,
                accounting_patient_id,
                full_name,
                phone_number,
                gender,
                birthdate,
                address,
                enrolled_by,
            ),
        )
        if commit:
            db.commit()
        return int(cursor.lastrowid)

    def update_contact(self, pid: int, *, phone_number, address, notes):
        db = get_db()
        db.execute(
            """UPDATE patient_links
               SET phone_number=?, address=?, notes=?, updated_at=? WHERE id=?""",
            (
                phone_number,
                address,
                notes,
                iran_now().strftime("%Y-%m-%d %H:%M:%S"),
                pid,
            ),
        )
        db.commit()

    # ---- conditions / problem list ----
    def list_condition_catalog(self) -> list[dict]:
        rows = get_db().execute(
            "SELECT * FROM conditions WHERE is_active=1 ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_patient_conditions(self, pid: int) -> list[dict]:
        rows = get_db().execute(
            """SELECT pc.*, c.name AS condition_name, c.code AS condition_code
               FROM patient_conditions pc
               JOIN conditions c ON c.id=pc.condition_id
               WHERE pc.patient_link_id=? AND pc.is_active=1
               ORDER BY pc.id DESC""",
            (pid,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_condition(
        self,
        pid: int,
        condition_id: int,
        stage: str | None = None,
        onset_date: str | None = None,
        notes: str | None = None,
        source_system: str = "clinic",
        source_record_id: str | None = None,
        source_assertion: str = "PRESENT",
        verification: str = "CONFIRMED",
        recorded_by: str | None = None,
    ) -> int:
        db = get_db()
        catalog = db.execute(
            "SELECT id FROM conditions WHERE id=? AND is_active=1",
            (condition_id,),
        ).fetchone()
        if not catalog:
            raise ValueError("condition is not available in the active catalog")
        if source_record_id:
            existing = db.execute(
                """SELECT id FROM patient_conditions
                   WHERE patient_link_id=? AND source_system=?
                     AND source_record_id=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (pid, source_system, source_record_id),
            ).fetchone()
        else:
            existing = db.execute(
                """SELECT id FROM patient_conditions
                   WHERE patient_link_id=? AND condition_id=?
                     AND source_system=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (pid, condition_id, source_system),
            ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = db.execute(
            """INSERT INTO patient_conditions
               (patient_link_id, condition_id, stage, onset_date, notes,
                source_system, source_record_id, source_assertion, verification,
                recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid, condition_id, stage, onset_date, notes,
                source_system, source_record_id, source_assertion, verification,
                recorded_by,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)

    def remove_condition(
        self,
        pc_id: int,
        *,
        patient_link_id: int | None = None,
        resolved_at: str | None = None,
    ) -> bool:
        db = get_db()
        row = db.execute(
            "SELECT * FROM patient_conditions WHERE id=?", (pc_id,)
        ).fetchone()
        if not row:
            return False
        if patient_link_id is not None and int(row["patient_link_id"]) != int(
            patient_link_id
        ):
            raise LookupError("condition row does not belong to this patient")
        if not int(row["is_active"] or 0):
            return False
        effective = resolved_at or today_str()
        if row["onset_date"] and effective < str(row["onset_date"])[:10]:
            raise ValueError("condition resolution cannot precede onset")
        db.execute(
            """UPDATE patient_conditions
               SET is_active=0, resolved_at=? WHERE id=?""",
            (effective, pc_id),
        )
        db.commit()
        return True

    # ---- medications ----
    def get_medications(self, pid: int, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM patient_medications WHERE patient_link_id=?"
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY is_active DESC, id DESC"
        return [dict(row) for row in get_db().execute(sql, (pid,)).fetchall()]

    def get_medication(
        self, med_id: int, *, patient_link_id: int | None = None
    ) -> Optional[dict]:
        sql = "SELECT * FROM patient_medications WHERE id=?"
        params: list[Any] = [med_id]
        if patient_link_id is not None:
            sql += " AND patient_link_id=?"
            params.append(patient_link_id)
        row = get_db().execute(sql, params).fetchone()
        return dict(row) if row else None

    def add_medication(
        self,
        pid: int,
        *,
        drug_name,
        dose,
        schedule,
        start_date,
        refill_due_date,
        notes,
        drug_class=None,
        drug_catalog_id: int | None = None,
        created_by=None,
        source_system: str = "clinic",
        source_record_id: str | None = None,
        source_assertion: str = "PRESENT",
        verification: str = "CONFIRMED",
        recorded_by: str | None = None,
    ) -> int:
        db = get_db()
        name = " ".join(str(drug_name or "").strip().split())
        canonical_class = (str(drug_class or "").strip() or None)
        catalog_id = int(drug_catalog_id) if drug_catalog_id is not None else None
        if catalog_id is not None:
            catalog = db.execute(
                """SELECT id, generic_fa, drug_class_key FROM drug_catalog
                   WHERE id=? AND is_active=1""",
                (catalog_id,),
            ).fetchone()
            if not catalog:
                raise ValueError("selected medication is not in the active catalog")
            name = str(catalog["generic_fa"]).strip()
            canonical_class = str(catalog["drug_class_key"] or "").strip() or None
        if not name:
            raise ValueError("drug_name is required")

        if source_record_id:
            existing = db.execute(
                """SELECT id FROM patient_medications
                   WHERE patient_link_id=? AND source_system=?
                     AND source_record_id=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (pid, source_system, source_record_id),
            ).fetchone()
        elif catalog_id is not None:
            existing = db.execute(
                """SELECT id FROM patient_medications
                   WHERE patient_link_id=? AND drug_catalog_id=?
                     AND source_system=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (pid, catalog_id, source_system),
            ).fetchone()
        else:
            existing = db.execute(
                """SELECT id FROM patient_medications
                   WHERE patient_link_id=? AND lower(trim(drug_name))=lower(trim(?))
                     AND COALESCE(drug_class,'')=COALESCE(?, '')
                     AND source_system=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (pid, name, canonical_class, source_system),
            ).fetchone()
        if existing:
            return int(existing["id"])

        cursor = db.execute(
            """INSERT INTO patient_medications
               (patient_link_id, drug_name, dose, schedule, start_date,
                refill_due_date, notes, drug_class, drug_catalog_id,
                source_system, source_record_id, source_assertion, verification,
                recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                name,
                dose,
                schedule,
                start_date,
                refill_due_date,
                notes,
                canonical_class,
                catalog_id,
                source_system,
                source_record_id,
                source_assertion,
                verification,
                recorded_by or created_by,
            ),
        )
        med_id = int(cursor.lastrowid)
        self._log_med_event(
            pid,
            med_id,
            name,
            "start",
            dose=dose,
            event_date=start_date,
            created_by=created_by,
            db=db,
        )
        db.commit()
        return med_id

    def stop_medication(
        self,
        med_id: int,
        end_date: str | None = None,
        created_by=None,
        *,
        patient_link_id: int | None = None,
    ) -> bool:
        db = get_db()
        med = self.get_medication(med_id, patient_link_id=patient_link_id)
        if not med:
            raise LookupError("medication row does not belong to this patient")
        if not int(med["is_active"] or 0):
            return False
        effective = end_date or today_str()
        if effective > today_str():
            raise ValueError("future medication stop dates are not supported")
        if med.get("start_date") and effective < str(med["start_date"])[:10]:
            raise ValueError("medication stop cannot precede start")
        db.execute(
            """UPDATE patient_medications
               SET is_active=0, end_date=? WHERE id=?""",
            (effective, med_id),
        )
        self._log_med_event(
            med["patient_link_id"],
            med_id,
            med["drug_name"],
            "stop",
            dose=med.get("dose"),
            event_date=effective,
            created_by=created_by,
            db=db,
        )
        db.commit()
        return True

    def change_dose(
        self,
        med_id: int,
        new_dose: str,
        change_date: str | None = None,
        note: str | None = None,
        created_by=None,
        *,
        patient_link_id: int | None = None,
    ) -> bool:
        db = get_db()
        med = self.get_medication(med_id, patient_link_id=patient_link_id)
        if not med:
            raise LookupError("medication row does not belong to this patient")
        if not int(med["is_active"] or 0):
            raise ValueError("dose cannot be changed for an inactive medication")
        effective = change_date or today_str()
        if effective > today_str():
            raise ValueError("future dose changes are not supported")
        if med.get("start_date") and effective < str(med["start_date"])[:10]:
            raise ValueError("dose change cannot precede medication start")
        self._log_med_event(
            med["patient_link_id"],
            med_id,
            med["drug_name"],
            "dose_change",
            dose=new_dose,
            event_date=effective,
            note=note,
            created_by=created_by,
            db=db,
        )
        # A back-dated correction must not overwrite a newer dose. Recompute the
        # current value from the ordered event history after appending the event.
        latest = db.execute(
            """SELECT dose FROM medication_events
               WHERE medication_id=? AND event_type IN ('start','dose_change')
                 AND event_date<=?
               ORDER BY event_date DESC, id DESC LIMIT 1""",
            (med_id, today_str()),
        ).fetchone()
        db.execute(
            "UPDATE patient_medications SET dose=? WHERE id=?",
            (latest["dose"] if latest else new_dose, med_id),
        )
        db.commit()
        return True

    # ---- medication events (start / stop / dose-change timeline) ----
    def _log_med_event(
        self,
        pid,
        med_id,
        drug_name,
        event_type,
        *,
        dose=None,
        event_date=None,
        note=None,
        created_by=None,
        db=None,
    ) -> int:
        db = db or get_db()
        cursor = db.execute(
            """INSERT INTO medication_events
               (patient_link_id, medication_id, drug_name, event_type, dose,
                event_date, note, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                med_id,
                drug_name,
                event_type,
                dose,
                event_date or today_str(),
                note,
                created_by,
            ),
        )
        return int(cursor.lastrowid)

    def get_medication_events(
        self, pid: int, med_id: int | None = None
    ) -> list[dict]:
        sql = "SELECT * FROM medication_events WHERE patient_link_id=?"
        params: list[Any] = [pid]
        if med_id is not None:
            sql += " AND medication_id=?"
            params.append(med_id)
        sql += " ORDER BY event_date, id"
        return [dict(row) for row in get_db().execute(sql, params).fetchall()]

    # ---- allergies ----
    def get_allergies(self, pid: int, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM allergies WHERE patient_link_id=?"
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY is_active DESC, id DESC"
        return [dict(row) for row in get_db().execute(sql, (pid,)).fetchall()]

    def add_allergy(
        self,
        pid: int,
        *,
        substance,
        reaction,
        severity,
        allergy_concept_id: int | None = None,
        source_system: str = "clinic",
        source_record_id: str | None = None,
        source_assertion: str = "PRESENT",
        verification: str = "CONFIRMED",
        recorded_by: str | None = None,
    ) -> int:
        db = get_db()
        normalized = " ".join(str(substance or "").strip().split())
        if not normalized:
            raise ValueError("allergy substance is required")
        concept_id = int(allergy_concept_id) if allergy_concept_id is not None else None
        if concept_id is None:
            matches = db.execute(
                """SELECT DISTINCT catalog.id
                   FROM allergy_catalog catalog
                   LEFT JOIN json_each(catalog.aliases_json) alias ON 1=1
                   WHERE catalog.is_active=1
                     AND (lower(trim(catalog.display_name))=lower(trim(?))
                          OR lower(trim(CAST(alias.value AS TEXT)))=lower(trim(?)))""",
                (normalized, normalized),
            ).fetchall()
            if len(matches) == 1:
                concept_id = int(matches[0]["id"])
        if concept_id is not None:
            catalog = db.execute(
                "SELECT id FROM allergy_catalog WHERE id=? AND is_active=1",
                (concept_id,),
            ).fetchone()
            if not catalog:
                raise ValueError("selected allergy concept is not active")
        if source_record_id:
            existing = db.execute(
                """SELECT id FROM allergies
                   WHERE patient_link_id=? AND source_system=?
                     AND source_record_id=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (pid, source_system, source_record_id),
            ).fetchone()
        elif concept_id is not None:
            existing = db.execute(
                """SELECT id FROM allergies
                   WHERE patient_link_id=? AND allergy_concept_id=? AND is_active=1
                     AND source_system=?
                   ORDER BY id DESC LIMIT 1""",
                (pid, concept_id, source_system),
            ).fetchone()
        else:
            existing = db.execute(
                """SELECT id FROM allergies
                   WHERE patient_link_id=? AND lower(trim(substance))=lower(trim(?))
                     AND is_active=1 AND source_system=?
                   ORDER BY id DESC LIMIT 1""",
                (pid, normalized, source_system),
            ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = db.execute(
            """INSERT INTO allergies
               (patient_link_id, substance, reaction, severity, is_active,
                allergy_concept_id, source_system, source_record_id,
                source_assertion, verification, recorded_by)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (
                pid, normalized, reaction, severity, concept_id, source_system,
                source_record_id, source_assertion, verification, recorded_by,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)

    def delete_allergy(
        self,
        allergy_id: int,
        *,
        patient_link_id: int | None = None,
        resolved_at: str | None = None,
    ) -> bool:
        db = get_db()
        row = db.execute(
            "SELECT * FROM allergies WHERE id=?", (allergy_id,)
        ).fetchone()
        if not row:
            return False
        if patient_link_id is not None and int(row["patient_link_id"]) != int(
            patient_link_id
        ):
            raise LookupError("allergy row does not belong to this patient")
        if not int(row["is_active"] or 0):
            return False
        db.execute(
            """UPDATE allergies
               SET is_active=0, resolved_at=? WHERE id=?""",
            (resolved_at or today_str(), allergy_id),
        )
        db.commit()
        return True

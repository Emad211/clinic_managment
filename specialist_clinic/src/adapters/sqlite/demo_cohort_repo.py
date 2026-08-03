"""Persistence boundary for the canonical synthetic v2 activation cohort."""
from __future__ import annotations

from datetime import datetime
import json
from uuid import uuid4

from src.adapters.sqlite.clinical_data_conflict_repo import (
    ClinicalDataConflictRepository,
)
from src.adapters.sqlite.clinical_reconciliation_repo import (
    ClinicalReconciliationRepository,
)
from src.adapters.sqlite.clinical_flag_event_repo import (
    ClinicalFlagEventRepositoryMixin,
)
from src.domain.clinical_engine.flag_history import ClinicalFlagState
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


_VERSION_KEY = "clinical_engine_v2_demo_cohort_version"


def _clean(value) -> str:
    return " ".join(str(value or "").strip().split())


class DemoCohortRepository:
    """Atomically replace only TEST0001..TEST0010 clinical source records."""

    def version(self) -> str | None:
        row = get_db().execute(
            "SELECT value FROM settings WHERE key=?",
            (_VERSION_KEY,),
        ).fetchone()
        return str(row["value"]) if row else None

    @staticmethod
    def _canonical_allergy_catalog(db) -> dict[str, dict]:
        """Return one exact active concept for every canonical name and alias.

        Synthetic fixtures are safety controls, not free-text imports.  An alias that
        resolves to two active concepts or a fixture substance without an exact match
        aborts the whole cohort rebuild.
        """
        catalog: dict[str, dict] = {}
        rows = db.execute(
            """SELECT id, concept_key, display_name, aliases_json
               FROM allergy_catalog WHERE is_active=1 ORDER BY id"""
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            aliases = [row["display_name"], *json.loads(row["aliases_json"])]
            for alias in aliases:
                key = _clean(alias).casefold()
                if not key:
                    continue
                prior = catalog.get(key)
                if prior and int(prior["id"]) != int(row["id"]):
                    raise RuntimeError(
                        "active allergy catalog contains an ambiguous exact alias: "
                        f"{alias!r}"
                    )
                catalog[key] = row
        return catalog

    @staticmethod
    def _canonical_drug_catalog(db) -> dict[tuple[str, str], dict]:
        catalog: dict[tuple[str, str], dict] = {}
        rows = db.execute(
            """SELECT id, generic_fa, drug_class_key
               FROM drug_catalog
               WHERE is_active=1 AND drug_class_key IS NOT NULL
               ORDER BY id"""
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            key = (
                _clean(row["generic_fa"]),
                _clean(row["drug_class_key"]),
            )
            if key in catalog:
                raise RuntimeError(
                    "active drug catalog contains duplicate synthetic identity: "
                    f"{key[0]} / {key[1]}"
                )
            catalog[key] = row
        return catalog

    def replace_all(
        self,
        cohort: tuple[dict, ...],
        *,
        version: str,
        actor: str,
        reference_at: datetime,
    ) -> list[int]:
        db = get_db()
        now = iran_now().isoformat(sep=" ", timespec="seconds")
        patient_ids: list[int] = []
        db.execute("BEGIN IMMEDIATE")
        try:
            condition_rows = db.execute(
                "SELECT id, code FROM conditions WHERE code IS NOT NULL"
            ).fetchall()
            condition_ids = {
                row["code"]: int(row["id"])
                for row in condition_rows
            }
            drug_catalog = self._canonical_drug_catalog(db)
            allergy_catalog = self._canonical_allergy_catalog(db)
            for patient in cohort:
                national_id = patient["nid"]
                if not (
                    national_id.startswith("TEST")
                    and len(national_id) == 8
                ):
                    raise ValueError(
                        "demo cohort may only contain TESTxxxx identifiers"
                    )
                db.execute(
                    """INSERT INTO patient_links
                       (national_id, full_name, phone_number, gender, birthdate,
                        address, notes, enrolled_by, is_active, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                       ON CONFLICT(national_id) DO UPDATE SET
                         full_name=excluded.full_name,
                         phone_number=excluded.phone_number,
                         gender=excluded.gender,
                         birthdate=excluded.birthdate,
                         address=excluded.address,
                         notes=excluded.notes,
                         enrolled_by=excluded.enrolled_by,
                         is_active=1,
                         updated_at=excluded.updated_at""",
                    (
                        national_id,
                        patient["name"],
                        patient["phone"],
                        patient["gender"],
                        patient["birth"],
                        patient["address"],
                        patient["summary"],
                        actor,
                        now,
                    ),
                )
                patient_id = int(
                    db.execute(
                        "SELECT id FROM patient_links WHERE national_id=?",
                        (national_id,),
                    ).fetchone()["id"]
                )
                patient_ids.append(patient_id)
                self._clear_patient(db, patient_id)
                self._insert_patient_records(
                    db,
                    patient_id,
                    patient,
                    fixture_national_id=national_id,
                    condition_ids=condition_ids,
                    drug_catalog=drug_catalog,
                    allergy_catalog=allergy_catalog,
                    actor=actor,
                    now=now,
                    reference_at=reference_at,
                )
            db.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (_VERSION_KEY, version),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return patient_ids

    @staticmethod
    def _clear_patient(db, patient_id: int) -> None:
        # Delete mutable children before parents. Engine runs, decisions and
        # reconciliation events are immutable and deliberately retained; new
        # events below supersede the prior reviewed collection snapshots.
        tables = (
            "prescriptions",
            "clinical_notes",
            "surgery_history",
            "medical_history",
            "appointments",
            "allergies",
            "medication_events",
            "patient_medications",
            "lab_results",
            "vital_readings",
            "patient_conditions",
        )
        for table in tables:
            db.execute(
                f"DELETE FROM {table} WHERE patient_link_id=?",
                (patient_id,),
            )
        # Preserve administrative demo follow-up row IDs so immutable Episode links
        # remain valid across repeated canonical seed runs. Governed clinical/plan
        # tasks are still reset with the rest of the synthetic clinical source set.
        db.execute(
            """DELETE FROM followup_tasks
               WHERE patient_link_id=?
                 AND COALESCE(source_engine,'') IN ('clinical_v2','encounter_plan')""",
            (patient_id,),
        )

    @staticmethod
    def _insert_patient_records(
        db,
        patient_id: int,
        patient: dict,
        *,
        fixture_national_id: str,
        condition_ids: dict[str, int],
        drug_catalog: dict[tuple[str, str], dict],
        allergy_catalog: dict[str, dict],
        actor: str,
        now: str,
        reference_at: datetime,
    ) -> None:
        for condition in patient["conditions"]:
            condition_id = condition_ids.get(condition["code"])
            if not condition_id:
                raise LookupError(
                    "condition catalog entry missing: "
                    f"{condition['code']}"
                )
            db.execute(
                """INSERT INTO patient_conditions
                   (patient_link_id, condition_id, stage, onset_date, notes,
                    diagnosed_at, source_system, source_record_id,
                    source_assertion, verification, recorded_by)
                   VALUES (?, ?, ?, ?, ?, ?, 'system', ?, 'PRESENT',
                           'CONFIRMED', ?)""",
                (
                    patient_id,
                    condition_id,
                    condition.get("stage"),
                    condition.get("onset"),
                    condition.get("notes"),
                    condition.get("onset") or now,
                    f"demo-condition:{patient_id}:{condition['code']}",
                    actor,
                ),
            )

        flag_catalog = {
            str(row["flag_key"]): dict(row)
            for row in db.execute(
                "SELECT * FROM flag_catalog WHERE is_active=1 ORDER BY id"
            ).fetchall()
        }
        unknown_fixture_flags = sorted(
            set(patient["flags"]) - set(flag_catalog)
        )
        if unknown_fixture_flags:
            raise LookupError(
                "synthetic cohort references unknown clinical flags: "
                + ", ".join(unknown_fixture_flags)
            )
        flag_updates = {
            key: (
                {
                    "state": ClinicalFlagState.PRESENT.value,
                    "value": patient["flags"][key],
                }
                if key in patient["flags"]
                else {
                    "state": ClinicalFlagState.NOT_ASKED.value,
                    "value": None,
                }
            )
            for key in flag_catalog
        }
        ClinicalFlagEventRepositoryMixin.append_batch_in_transaction(
            db,
            patient_id,
            flag_updates,
            actor_username=actor,
            source="system",
            verification="CONFIRMED",
            effective_at=reference_at,
            recorded_at=reference_at,
            batch_id=f"demo-cohort:{patient_id}:{uuid4()}",
            note="Deterministic synthetic cohort flag review.",
            record_unchanged=True,
        )

        db.executemany(
            """INSERT INTO vital_readings
               (patient_link_id, type, value, unit, measured_at, source, notes,
                recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    patient_id,
                    row["type"],
                    row["value"],
                    row.get("unit"),
                    row["measured_at"],
                    row.get("source", "clinic"),
                    row.get("notes"),
                    actor,
                )
                for row in patient["vitals"]
            ],
        )
        db.executemany(
            """INSERT INTO lab_results
               (patient_link_id, test_name, test_key, value, unit, ref_low,
                ref_high, taken_at, notes, recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    patient_id,
                    row["test_name"],
                    row["test_key"],
                    row["value"],
                    row.get("unit"),
                    row.get("ref_low"),
                    row.get("ref_high"),
                    row["taken_at"],
                    row.get("notes"),
                    actor,
                )
                for row in patient["labs"]
            ],
        )

        for medication_index, medication in enumerate(patient["meds"], start=1):
            key = (
                _clean(medication["name"]),
                _clean(medication["drug_class"]),
            )
            catalog = drug_catalog.get(key)
            if not catalog:
                raise LookupError(
                    "synthetic medication lacks one exact active catalog concept: "
                    f"{key[0]} / {key[1]}"
                )
            final_dose = (
                medication["changes"][-1][1]
                if medication["changes"]
                else medication["dose"]
            )
            cursor = db.execute(
                """INSERT INTO patient_medications
                   (patient_link_id, drug_name, dose, schedule, start_date,
                    refill_due_date, is_active, end_date, notes, drug_class,
                    drug_catalog_id, source_system, source_record_id,
                    source_assertion, verification, recorded_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'system', ?,
                           'PRESENT', 'CONFIRMED', ?)""",
                (
                    patient_id,
                    catalog["generic_fa"],
                    final_dose,
                    medication["schedule"],
                    medication["start"],
                    "2026-10-22",
                    0 if medication["stop"] else 1,
                    medication["stop"],
                    medication.get("notes"),
                    catalog["drug_class_key"],
                    int(catalog["id"]),
                    f"demo-medication:{patient_id}:{medication_index}",
                    actor,
                ),
            )
            medication_id = int(cursor.lastrowid)
            events = [
                (
                    "start",
                    medication["dose"],
                    medication["start"],
                    "شروع درمان",
                )
            ]
            events.extend(
                ("dose_change", dose, when, note)
                for when, dose, note in medication["changes"]
            )
            if medication["stop"]:
                events.append(
                    (
                        "stop",
                        final_dose,
                        medication["stop"],
                        medication.get("notes"),
                    )
                )
            db.executemany(
                """INSERT INTO medication_events
                   (patient_link_id, medication_id, drug_name, event_type, dose,
                    event_date, note, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        patient_id,
                        medication_id,
                        catalog["generic_fa"],
                        event_type,
                        dose,
                        event_date,
                        note,
                        actor,
                        event_date + " 10:30:00",
                    )
                    for event_type, dose, event_date, note in events
                ],
            )

        allergy_rows = []
        for index, (substance, reaction, severity) in enumerate(
            patient["allergies"], start=1
        ):
            catalog = allergy_catalog.get(_clean(substance).casefold())
            if not catalog:
                raise LookupError(
                    "synthetic allergy lacks one exact active catalog concept: "
                    f"{substance}"
                )
            allergy_rows.append(
                (
                    patient_id,
                    substance,
                    reaction,
                    severity,
                    int(catalog["id"]),
                    f"demo-allergy:{patient_id}:{index}",
                    actor,
                )
            )
        db.executemany(
            """INSERT INTO allergies
               (patient_link_id, substance, reaction, severity, is_active,
                allergy_concept_id, source_system, source_record_id,
                source_assertion, verification, recorded_by)
               VALUES (?, ?, ?, ?, 1, ?, 'system', ?, 'PRESENT',
                       'CONFIRMED', ?)""",
            allergy_rows,
        )

        # The activation cohort represents fully reviewed synthetic records.
        # Record that fact explicitly; a bare empty list is never interpreted as
        # confirmed absence by the runtime.
        for collection_key in (
            "conditions",
            "medications",
            "allergies",
        ):
            ClinicalReconciliationRepository.record_in_transaction(
                db,
                patient_link_id=patient_id,
                collection_key=collection_key,
                completeness="complete",
                actor_username=actor,
                actor_user_id=None,
                source="system",
                patient_confirmed=False,
                reconciled_at=reference_at,
                note=(
                    "Synthetic activation cohort: collection generated and "
                    "reviewed by the deterministic fixture contract."
                ),
            )

        db.executemany(
            """INSERT INTO medical_history
               (patient_link_id, title, note, since)
               VALUES (?, ?, ?, ?)""",
            [
                (patient_id, title, note, since)
                for title, note, since in patient["history"]
            ],
        )
        db.executemany(
            """INSERT INTO surgery_history
               (patient_link_id, title, performed_on, note)
               VALUES (?, ?, ?, ?)""",
            [
                (patient_id, title, performed_on, note)
                for title, performed_on, note in patient["surgeries"]
            ],
        )
        db.executemany(
            """INSERT INTO clinical_notes
               (patient_link_id, kind, body, recorded_at, recorded_by)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    patient_id,
                    row["kind"],
                    row["body"],
                    row["recorded_at"],
                    actor,
                )
                for row in patient["notes"]
            ],
        )
        db.executemany(
            """INSERT INTO appointments
               (patient_link_id, scheduled_at, appt_type, status, notes,
                created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    patient_id,
                    row["scheduled_at"],
                    row["appt_type"],
                    row["status"],
                    row.get("notes"),
                    actor,
                )
                for row in patient["appointments"]
            ],
        )
        DemoCohortRepository._sync_followups(
            db, patient_id, patient,
            fixture_national_id=fixture_national_id, actor=actor, now=now
        )
        db.executemany(
            """INSERT INTO prescriptions
               (patient_link_id, kind, items, mode, issued_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    patient_id,
                    row["kind"],
                    json.dumps(row["items"], ensure_ascii=False),
                    row.get("mode", "free"),
                    row["issued_at"],
                )
                for row in patient["prescriptions"]
            ],
        )

    @staticmethod
    def _sync_followups(
        db, patient_id: int, patient: dict, *,
        fixture_national_id: str, actor: str, now: str
    ) -> None:
        """Upsert only canonical fixture-owned follow-ups with stable IDs.

        Ownership is recorded in the synthetic seed's settings namespace instead
        of modifying source provenance fields. This preserves an existing immutable
        Episode link revision and leaves user-created TEST-patient tasks untouched.
        """
        for index, row in enumerate(patient["followups"], start=1):
            fixture_key = (
                f"demo_followup_task_id:{fixture_national_id}:{index}"
            )
            fulfillment = "remote" if row["reason"] == "refill" else "in_person"
            mapped = db.execute(
                "SELECT value FROM settings WHERE key=?",
                (fixture_key,),
            ).fetchone()
            existing = None
            if mapped and str(mapped["value"] or "").isdigit():
                existing = db.execute(
                    """SELECT id FROM followup_tasks
                       WHERE id=? AND patient_link_id=?""",
                    (int(mapped["value"]), patient_id),
                ).fetchone()

            if not existing:
                # Adopt exact rows produced by releases before the mapping existed.
                existing = db.execute(
                    """SELECT id FROM followup_tasks
                       WHERE patient_link_id=?
                         AND COALESCE(source_engine,'')=''
                         AND COALESCE(source_rule,'')=''
                         AND COALESCE(source_event,'')=''
                         AND due_date IS ?
                         AND reason IS ?
                         AND detail IS ?
                         AND status=?
                         AND COALESCE(assigned_to,'')='تیم درمان'
                         AND COALESCE(fulfillment,'in_person')=?
                         AND resolved_at IS ?
                       ORDER BY id LIMIT 1""",
                    (
                        patient_id, row["due_date"], row["reason"], row["detail"],
                        row["status"], fulfillment, row.get("resolved_at"),
                    ),
                ).fetchone()

            values = (
                row["due_date"], row["reason"], row["detail"], row["status"],
                "تیم درمان", fulfillment, row.get("resolved_at"),
            )
            if existing:
                task_id = int(existing["id"])
                db.execute(
                    """UPDATE followup_tasks
                       SET due_date=?, reason=?, detail=?, status=?, assigned_to=?,
                           fulfillment=?, resolved_at=?
                       WHERE id=? AND patient_link_id=?""",
                    (*values, task_id, patient_id),
                )
            else:
                cursor = db.execute(
                    """INSERT INTO followup_tasks
                       (patient_link_id, due_date, reason, detail, status,
                        assigned_to, fulfillment, resolved_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (patient_id, *values, now),
                )
                task_id = int(cursor.lastrowid)

            db.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (fixture_key, str(task_id)),
            )

    def summary(self, *, expected_version: str) -> dict:
        ids = [f"TEST{index:04d}" for index in range(1, 11)]
        marks = ",".join("?" for _ in ids)
        db = get_db()
        patients = [
            dict(row)
            for row in db.execute(
                f"""SELECT id, national_id, full_name FROM patient_links
                    WHERE national_id IN ({marks}) ORDER BY national_id""",
                ids,
            ).fetchall()
        ]
        patient_ids = [int(row["id"]) for row in patients]
        totals = {
            key: 0
            for key in (
                "vitals",
                "labs",
                "medications",
                "medication_events",
                "notes",
                "appointments",
                "followups",
                "prescriptions",
                "history",
                "allergies",
                "surgeries",
                "conditions",
                "reconciled_collections",
                "unmapped_active_medications",
                "unmapped_active_allergies",
                "unresolved_conflicts",
                "flag_heads",
                "active_flag_definitions",
            )
        }
        table_map = {
            "vitals": "vital_readings",
            "labs": "lab_results",
            "medications": "patient_medications",
            "medication_events": "medication_events",
            "notes": "clinical_notes",
            "appointments": "appointments",
            "prescriptions": "prescriptions",
            "history": "medical_history",
            "allergies": "allergies",
            "surgeries": "surgery_history",
            "conditions": "patient_conditions",
        }
        if patient_ids:
            patient_marks = ",".join("?" for _ in patient_ids)
            for key, table in table_map.items():
                totals[key] = int(
                    db.execute(
                        f"""SELECT COUNT(*) AS count FROM {table}
                            WHERE patient_link_id IN ({patient_marks})""",
                        patient_ids,
                    ).fetchone()["count"]
                )
            totals["followups"] = int(
                db.execute(
                    f"""SELECT COUNT(DISTINCT task.id) AS count
                        FROM settings seed_map
                        JOIN followup_tasks task
                          ON task.id=CAST(seed_map.value AS INTEGER)
                        WHERE seed_map.key LIKE 'demo_followup_task_id:TEST%:%'
                          AND task.patient_link_id IN ({patient_marks})""",
                    patient_ids,
                ).fetchone()["count"]
            )
            totals["reconciled_collections"] = int(
                db.execute(
                    f"""SELECT COUNT(*) AS count FROM (
                           SELECT patient_link_id, collection_key
                           FROM clinical_reconciliation_events
                           WHERE patient_link_id IN ({patient_marks})
                           GROUP BY patient_link_id, collection_key
                       )""",
                    patient_ids,
                ).fetchone()["count"]
            )
            totals["unmapped_active_medications"] = int(
                db.execute(
                    f"""SELECT COUNT(*) AS count
                        FROM patient_medications
                        WHERE patient_link_id IN ({patient_marks})
                          AND is_active=1
                          AND drug_catalog_id IS NULL""",
                    patient_ids,
                ).fetchone()["count"]
            )
            totals["unmapped_active_allergies"] = int(
                db.execute(
                    f"""SELECT COUNT(*) AS count
                        FROM allergies
                        WHERE patient_link_id IN ({patient_marks})
                          AND is_active=1
                          AND source_assertion='PRESENT'
                          AND allergy_concept_id IS NULL""",
                    patient_ids,
                ).fetchone()["count"]
            )
            conflicts = ClinicalDataConflictRepository(db)
            totals["unresolved_conflicts"] = sum(
                conflicts.projection(
                    patient_id,
                    collection_key,
                ).unresolved_count
                for patient_id in patient_ids
                for collection_key in ("conditions", "medications", "allergies")
            )
            totals["active_flag_definitions"] = int(
                db.execute(
                    "SELECT COUNT(*) AS count FROM flag_catalog WHERE is_active=1"
                ).fetchone()["count"]
            )
            totals["flag_heads"] = int(
                db.execute(
                    f"""SELECT COUNT(*) AS count
                        FROM clinical_flag_events event
                        JOIN flag_catalog catalog
                          ON catalog.flag_key=event.flag_key
                         AND catalog.is_active=1
                        WHERE event.patient_link_id IN ({patient_marks})
                          AND NOT EXISTS (
                            SELECT 1 FROM clinical_flag_events child
                             WHERE child.supersedes_event_id=event.id
                          )""",
                    patient_ids,
                ).fetchone()["count"]
            )
        version = self.version()
        return {
            "ready": (
                len(patients) == 10
                and version == expected_version
                and totals["unmapped_active_medications"] == 0
                and totals["unmapped_active_allergies"] == 0
                and totals["unresolved_conflicts"] == 0
                and totals["flag_heads"]
                    == len(patients) * totals["active_flag_definitions"]
            ),
            "version": version,
            "patient_count": len(patients),
            "patients": patients,
            "totals": totals,
        }

"""Repository for follow-up tasks (worklist)."""
import json
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.clinical_engine_runtime_schema import ensure_runtime_schema
from src.common.utils import iran_now


def _snapshot_revision(snapshot_json: str | None) -> int | None:
    try:
        payload = json.loads(snapshot_json or "{}")
        value = payload.get("clinical_data_revision")
        return int(value) if value is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _same_optional_int(left, right) -> bool:
    return (int(left) if left is not None else None) == (
        int(right) if right is not None else None
    )


def _engine_matches(actual: str, expected: str, allow_legacy_test_run: bool) -> bool:
    return str(actual) == str(expected) or bool(
        allow_legacy_test_run and str(actual).startswith("2.")
    )


class FollowupRepository:

    def active_patient_ids(self) -> list[int]:
        return [
            int(row["id"])
            for row in get_db().execute(
                "SELECT id FROM patient_links WHERE is_active=1 ORDER BY id"
            ).fetchall()
        ]

    def last_observation_at(self, pid: int, keys: list[str]):
        """Latest canonical observation timestamp across clinic and lab channels."""
        if not keys:
            return None
        placeholders = ",".join("?" for _ in keys)
        row = get_db().execute(
            f"""SELECT MAX(ts) AS measured_at FROM (
                  SELECT measured_at AS ts FROM vital_readings
                    WHERE patient_link_id=? AND type IN ({placeholders})
                  UNION ALL
                  SELECT taken_at AS ts FROM lab_results
                    WHERE patient_link_id=? AND test_key IN ({placeholders})
                )""",
            (pid, *keys, pid, *keys),
        ).fetchone()
        return row["measured_at"] if row else None

    def create(self, pid: int, *, reason, detail=None, due_date=None, assigned_to=None,
               source_rule=None, source_event=None, appointment_id=None,
               fulfillment=None) -> int:
        """fulfillment in remote|in_person — how the task is meant to be closed.
        appointment_id links the task to the visit that fulfills it (or None).

        When fulfillment is None it is derived from the reason: refill (renewal /
        periodic-Rx) is remote-closeable, everything else needs an in-person visit.
        Explicit values are always respected."""
        if fulfillment is None:
            fulfillment = 'remote' if reason == 'refill' else 'in_person'
        db = get_db()
        cur = db.execute(
            """INSERT INTO followup_tasks
                 (patient_link_id, reason, detail, due_date, assigned_to, source_rule,
                  source_event, appointment_id, fulfillment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, reason, detail, due_date, assigned_to, source_rule, source_event,
             appointment_id, fulfillment),
        )
        db.commit()
        return cur.lastrowid

    @staticmethod
    def _assert_current_clinical_source(db, task: dict) -> None:
        """Recheck the complete runtime contract inside the task write lock."""
        row = db.execute(
            """SELECT r.engine_version, r.ruleset_id, r.fact_snapshot_json,
                      r.run_status, p.clinical_data_revision,
                      (SELECT value FROM settings
                       WHERE key='clinical_engine_v2_mode') AS raw_mode,
                      rs.status AS ruleset_status,
                      EXISTS(
                          SELECT 1 FROM clinical_recommendation_events e
                          WHERE e.id=? AND e.run_id=r.run_id
                            AND e.event_type='CREATED'
                      ) AS recommendation_matches
               FROM clinical_engine_runs r
               JOIN patient_links p ON p.id=r.patient_link_id
               LEFT JOIN clinical_rulesets rs ON rs.id=r.ruleset_id
               WHERE r.run_id=? AND r.patient_link_id=?""",
            (
                task["source_recommendation_event_id"],
                task["source_run_id"],
                task["patient_link_id"],
            ),
        ).fetchone()
        if not row or not row["recommendation_matches"]:
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")
        if row["run_status"] not in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")

        allow_legacy = bool(task.get("allow_legacy_test_run"))
        snapshot_revision = _snapshot_revision(row["fact_snapshot_json"])
        expected_revision = int(task["source_clinical_data_revision"])
        if snapshot_revision is None and allow_legacy and expected_revision == 0:
            snapshot_revision = 0
        if not _engine_matches(
            str(row["engine_version"]),
            str(task["source_engine_version"]),
            allow_legacy,
        ):
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")
        if not _same_optional_int(row["ruleset_id"], task.get("source_ruleset_id")):
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")
        if snapshot_revision != expected_revision:
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")
        if int(row["clinical_data_revision"] or 0) != expected_revision:
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")
        if str(row["raw_mode"] or "off") != str(task.get("source_mode") or "off"):
            raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")

        # Production visible runs always have a concrete, executable ruleset.
        # Test-only hand-built audit rows may intentionally omit one.
        if not allow_legacy:
            expected_statuses = (
                {"SILENT", "ACTIVE"}
                if task.get("source_mode") == "on_selected"
                else {"ACTIVE"}
            )
            if row["ruleset_status"] not in expected_statuses:
                raise RuntimeError("STALE_CLINICAL_TASK_SOURCE")

    def create_clinical_task_once(self, task: dict) -> tuple[int, bool]:
        """Atomically create one task only from a still-current v2 evidence run."""
        db = get_db()
        ensure_runtime_schema(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            self._assert_current_clinical_source(db, task)
            existing = db.execute(
                """SELECT id FROM followup_tasks
                   WHERE clinical_task_key=?
                      OR (patient_link_id=? AND clinical_semantic_key=?
                          AND source_engine='clinical_v2' AND status='open')
                   ORDER BY id LIMIT 1""",
                (
                    task["clinical_task_key"], task["patient_link_id"],
                    task["clinical_semantic_key"],
                ),
            ).fetchone()
            if existing:
                db.commit()
                return int(existing["id"]), False
            cur = db.execute(
                """INSERT INTO followup_tasks
                   (patient_link_id, reason, detail, due_date, fulfillment,
                    source_rule, source_event, source_engine, source_run_id,
                    source_recommendation_event_id, clinical_semantic_key,
                    clinical_task_key)
                   VALUES (?, ?, ?, ?, 'in_person', ?, 'clinical_due',
                           'clinical_v2', ?, ?, ?, ?)""",
                (
                    task["patient_link_id"], task["reason"], task["detail"],
                    task["due_date"], task["source_rule"], task["source_run_id"],
                    task["source_recommendation_event_id"],
                    task["clinical_semantic_key"], task["clinical_task_key"],
                ),
            )
            db.commit()
            return int(cur.lastrowid), True
        except sqlite3.IntegrityError:
            db.rollback()
            existing = db.execute(
                """SELECT id FROM followup_tasks
                   WHERE clinical_task_key=?
                      OR (patient_link_id=? AND clinical_semantic_key=?
                          AND source_engine='clinical_v2' AND status='open')
                   ORDER BY id LIMIT 1""",
                (
                    task["clinical_task_key"], task["patient_link_id"],
                    task["clinical_semantic_key"],
                ),
            ).fetchone()
            if existing:
                return int(existing["id"]), False
            raise
        except Exception:
            db.rollback()
            raise

    def set_appointment(self, task_id: int, appointment_id):
        """Link an open task to the visit that will fulfill it."""
        db = get_db()
        db.execute("UPDATE followup_tasks SET appointment_id=? WHERE id=?",
                   (appointment_id, task_id))
        db.commit()

    def assign_appointment_bulk(self, task_ids: list, appointment_id):
        """Attach several open tasks to a single visit (merge same-due follow-ups)."""
        if not task_ids:
            return
        db = get_db()
        placeholders = ",".join("?" for _ in task_ids)
        db.execute(
            f"UPDATE followup_tasks SET appointment_id=? WHERE id IN ({placeholders})",
            [appointment_id, *task_ids],
        )
        db.commit()

    def exists_open(self, pid: int, reason: str) -> bool:
        db = get_db()
        row = db.execute(
            "SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND reason=? AND status='open' LIMIT 1",
            (pid, reason),
        ).fetchone()
        return bool(row)

    def recently_handled_source(self, pid: int, source_rule: str, months: int = None) -> bool:
        """True if there's an OPEN task for this rule, or a DONE one within `months`."""
        db = get_db()
        if db.execute(
            "SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND source_rule=? AND status='open' LIMIT 1",
            (pid, source_rule),
        ).fetchone():
            return True
        if months:
            row = db.execute(
                f"""SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND source_rule=? AND status='done'
                    AND resolved_at >= datetime('now','+3 hours','+30 minutes','-{int(months)} months') LIMIT 1""",
                (pid, source_rule),
            ).fetchone()
        else:
            # one-time item (e.g. zoster): suppress once it has ever been done
            row = db.execute(
                "SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND source_rule=? AND status='done' LIMIT 1",
                (pid, source_rule),
            ).fetchone()
        return bool(row)

    def list_open(self, reason: str = None) -> list[dict]:
        db = get_db()
        sql = """SELECT f.*, p.full_name AS patient_name, p.phone_number
                 FROM followup_tasks f JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'"""
        params = []
        if reason:
            sql += " AND f.reason = ?"
            params.append(reason)
        sql += " ORDER BY f.due_date IS NULL, f.due_date ASC, f.id DESC"
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    def search_open(self, q: str) -> list[dict]:
        """Open tasks whose patient matches `q` by national_id OR full_name OR
        phone_number (LIKE). Returns rows enriched with patient fields."""
        db = get_db()
        like = f"%{(q or '').strip()}%"
        sql = """SELECT f.*, p.full_name AS patient_name, p.phone_number, p.national_id
                 FROM followup_tasks f JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'
                   AND (p.national_id LIKE ? OR p.full_name LIKE ? OR p.phone_number LIKE ?)
                 ORDER BY f.due_date IS NULL, f.due_date ASC, f.id DESC"""
        return [dict(r) for r in db.execute(sql, (like, like, like)).fetchall()]

    def list_for_patient(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM followup_tasks WHERE patient_link_id=? ORDER BY id DESC", (pid,)).fetchall()]

    def resolve(self, task_id: int, status: str, call_log: str = None):
        db = get_db()
        db.execute(
            "UPDATE followup_tasks SET status=?, call_log=COALESCE(?, call_log), resolved_at=? WHERE id=?",
            (status, call_log, iran_now().strftime('%Y-%m-%d %H:%M:%S'), task_id),
        )
        db.commit()

    def counts_by_reason(self) -> dict:
        db = get_db()
        rows = db.execute(
            "SELECT reason, COUNT(*) c FROM followup_tasks WHERE status='open' GROUP BY reason"
        ).fetchall()
        return {r['reason']: r['c'] for r in rows}

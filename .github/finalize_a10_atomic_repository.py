from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_repo.py"
text = path.read_text(encoding="utf-8")
start = text.index("    def append_event(\n")
end = text.index("    def list_current(\n", start)
method = '''    def append_event(
        self,
        *,
        task_id: int,
        event_type: str,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        expected_current_event_id: int,
        due_at: datetime | str | None = None,
        assigned_to: str | None = None,
        appointment_id: int | None = None,
        evidence_type: str | None = None,
        evidence_ref: str | None = None,
        outcome_code: str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        owns_transaction = bool(commit)
        if owns_transaction:
            if db.in_transaction:
                raise EncounterPlanCommitmentConflict("CALLER_TRANSACTION_ACTIVE")
            db.execute("BEGIN IMMEDIATE")
        try:
            current = self.current_for_task(task_id)
            if not current:
                raise LookupError("plan commitment task not found")
            key = str(idempotency_key or "").strip()
            actor = str(actor_username or "").strip()
            if len(key) < 12 or not actor:
                raise EncounterPlanCommitmentValidationError(
                    "commitment event actor and idempotency key are required"
                )
            prior = db.execute(
                "SELECT * FROM care_plan_commitment_events WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if prior:
                if prior["commitment_id"] != current["commitment_id"]:
                    raise EncounterPlanCommitmentConflict(
                        "commitment idempotency scope mismatch"
                    )
                if owns_transaction:
                    db.commit()
                return dict(prior)
            if int(current["current_event_id"]) != int(expected_current_event_id):
                raise EncounterPlanCommitmentConflict("STALE_PLAN_COMMITMENT")
            event = str(event_type or "").strip().upper()
            if event not in {
                "STARTED", "ASSIGNED", "RESCHEDULED", "SCHEDULED",
                "COMPLETED", "CANCELLED", "ENTERED_IN_ERROR",
            }:
                raise EncounterPlanCommitmentValidationError(
                    "invalid plan commitment event"
                )
            current_status = str(current["current_status"])
            if current_status in _TERMINAL_STATUSES:
                raise EncounterPlanCommitmentConflict(
                    "plan commitment is terminal"
                )
            status_by_event = {
                "STARTED": "IN_PROGRESS",
                "ASSIGNED": current_status,
                "RESCHEDULED": current_status,
                "SCHEDULED": "SCHEDULED",
                "COMPLETED": "COMPLETED",
                "CANCELLED": "CANCELLED",
                "ENTERED_IN_ERROR": "ENTERED_IN_ERROR",
            }
            next_due = _time(due_at or current["current_due_at"])
            next_assigned = (
                str(assigned_to).strip()
                if assigned_to is not None and str(assigned_to).strip()
                else current.get("current_assigned_to")
            )
            next_appointment = (
                int(appointment_id)
                if appointment_id is not None
                else current.get("current_appointment_id")
            )
            payload = {
                "commitment_id": str(current["commitment_id"]),
                "event_type": event,
                "status": status_by_event[event],
                "due_at": next_due,
                "assigned_to": next_assigned,
                "appointment_id": next_appointment,
                "evidence_type": (
                    str(evidence_type).strip().upper() if evidence_type else None
                ),
                "evidence_ref": str(evidence_ref).strip() if evidence_ref else None,
                "outcome_code": (
                    str(outcome_code).strip().upper() if outcome_code else None
                ),
                "note": str(note).strip() if note else None,
                "recorded_at": _time(),
                "actor_user_id": int(actor_user_id) if actor_user_id else None,
                "actor_username": actor,
                "idempotency_key": key,
                "supersedes_event_id": int(current["current_event_id"]),
            }
            cursor = db.execute(
                """INSERT INTO care_plan_commitment_events
                   (commitment_id,event_type,status,due_at,assigned_to,
                    appointment_id,evidence_type,evidence_ref,outcome_code,
                    note,recorded_at,actor_user_id,actor_username,
                    idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM care_plan_commitment_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if owns_transaction:
                db.commit()
            return dict(row)
        except Exception:
            if owns_transaction:
                db.rollback()
            raise

'''
text = text[:start] + method + text[end:]
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()

"""Repository for immutable FOUX-V1 FO-6 SMS auto-guard records."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.sms_auto_guard_schema import (
    ensure_sms_auto_guard_storage,
    storage_ready,
)
from src.services.followup_orchestration.identity import (
    canonical_hash,
    canonical_json,
)


class SmsAutoGuardConflict(RuntimeError):
    pass


class SmsAutoGuardNotReady(RuntimeError):
    pass


def _text(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    return str(value or "").strip()


def _parse(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _payload(row: sqlite3.Row | dict | None) -> dict:
    if not row:
        return {}
    try:
        value = json.loads(str(row["payload_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class SmsAutoGuardRepository:
    def __init__(self, db: sqlite3.Connection, *, ensure: bool = False):
        self.db = db
        self.db.row_factory = sqlite3.Row
        if ensure:
            ensure_sms_auto_guard_storage(self.db)

    def ready(self) -> bool:
        return storage_ready(self.db)

    def require_ready(self) -> None:
        if not self.ready():
            raise SmsAutoGuardNotReady("FO-6 SMS auto-guard storage is not installed")

    # ---- immutable policy and template versions ----
    def latest_policy(self, policy_key: str) -> dict | None:
        self.require_ready()
        row = self.db.execute(
            """SELECT * FROM sms_auto_guard_policy_versions
               WHERE policy_key=? ORDER BY version DESC LIMIT 1""",
            (str(policy_key),),
        ).fetchone()
        return dict(row) if row else None

    def publish_policy(
        self,
        *,
        policy_key: str,
        purpose: str,
        policy: dict,
        actor_username: str,
        created_at: datetime,
    ) -> tuple[dict, bool]:
        self.require_ready()
        normalized = {
            "policy_key": str(policy_key),
            "purpose": str(purpose).upper(),
            "policy": policy,
        }
        digest = canonical_hash(normalized)
        latest = self.latest_policy(policy_key)
        if latest and str(latest["content_hash"]) == digest:
            return latest, False
        version = int(latest["version"]) + 1 if latest else 1
        try:
            cur = self.db.execute(
                """INSERT INTO sms_auto_guard_policy_versions
                   (policy_key, version, purpose, policy_json, content_hash,
                    created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(policy_key),
                    version,
                    str(purpose).upper(),
                    canonical_json(policy),
                    digest,
                    str(actor_username),
                    _text(created_at),
                ),
            )
            self.db.commit()
        except sqlite3.IntegrityError:
            self.db.rollback()
            row = self.db.execute(
                """SELECT * FROM sms_auto_guard_policy_versions
                   WHERE policy_key=? AND content_hash=?""",
                (str(policy_key), digest),
            ).fetchone()
            if row:
                return dict(row), False
            raise
        row = self.db.execute(
            "SELECT * FROM sms_auto_guard_policy_versions WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row), True

    def latest_template(self, event_key: str) -> dict | None:
        self.require_ready()
        row = self.db.execute(
            """SELECT * FROM sms_auto_guard_template_versions
               WHERE event_key=? ORDER BY version DESC LIMIT 1""",
            (str(event_key),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def template_digest(
        *,
        event_key: str,
        policy_version_id: int,
        template_text: str,
        message_type: str,
    ) -> str:
        return canonical_hash(
            {
                "event_key": str(event_key),
                "message_type": str(message_type),
                "policy_version_id": int(policy_version_id),
                "template_text": str(template_text),
            }
        )

    def publish_template(
        self,
        *,
        event_key: str,
        policy_version_id: int,
        template_text: str,
        message_type: str,
        actor_username: str,
        approved_at: datetime,
    ) -> tuple[dict, bool]:
        self.require_ready()
        digest = self.template_digest(
            event_key=event_key,
            policy_version_id=policy_version_id,
            template_text=template_text,
            message_type=message_type,
        )
        latest = self.latest_template(event_key)
        if latest and str(latest["content_hash"]) == digest:
            return latest, False
        version = int(latest["version"]) + 1 if latest else 1
        try:
            cur = self.db.execute(
                """INSERT INTO sms_auto_guard_template_versions
                   (event_key, version, policy_version_id, template_text,
                    message_type, content_hash, approved_by, approved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(event_key),
                    version,
                    int(policy_version_id),
                    str(template_text),
                    str(message_type),
                    digest,
                    str(actor_username),
                    _text(approved_at),
                ),
            )
            self.db.commit()
        except sqlite3.IntegrityError:
            self.db.rollback()
            row = self.db.execute(
                """SELECT * FROM sms_auto_guard_template_versions
                   WHERE event_key=? AND content_hash=?""",
                (str(event_key), digest),
            ).fetchone()
            if row:
                return dict(row), False
            raise
        row = self.db.execute(
            "SELECT * FROM sms_auto_guard_template_versions WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row), True

    # ---- candidate snapshots and append-only decisions ----
    def get_candidate(self, candidate_id: int) -> dict | None:
        self.require_ready()
        row = self.db.execute(
            "SELECT * FROM sms_auto_guard_candidates WHERE id=?",
            (int(candidate_id),),
        ).fetchone()
        return dict(row) if row else None

    def _decision_rows(self, candidate_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT * FROM sms_auto_guard_decision_events
               WHERE candidate_id=? ORDER BY id""",
            (int(candidate_id),),
        ).fetchall()

    def state(self, candidate_id: int, *, now: datetime | None = None) -> dict:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            raise LookupError(candidate_id)
        rows = self._decision_rows(candidate_id)
        submitted = next(
            (dict(row) for row in reversed(rows) if row["decision_type"] == "SUBMITTED"),
            None,
        )
        superseded = next(
            (
                dict(row)
                for row in reversed(rows)
                if row["decision_type"] == "SUPERSEDED"
            ),
            None,
        )
        claims = [row for row in rows if row["decision_type"] == "CLAIMED"]
        latest_claim = dict(claims[-1]) if claims else None
        in_flight = False
        if latest_claim:
            attempt = int(latest_claim["attempt_no"])
            terminal = next(
                (
                    row
                    for row in rows
                    if int(row["attempt_no"]) == attempt
                    and row["decision_type"]
                    in {"SUBMITTED", "SUBMISSION_FAILED"}
                ),
                None,
            )
            if terminal is None:
                expires = _parse(_payload(latest_claim).get("claim_expires_at"))
                in_flight = bool(expires and expires > (now or datetime.now()))
        expired = bool(
            _parse(candidate["expires_at"])
            and _parse(candidate["expires_at"]) <= (now or datetime.now())
        )
        if submitted:
            code = "SUBMITTED"
        elif superseded:
            code = "SUPERSEDED"
        elif expired:
            code = "EXPIRED"
        elif in_flight:
            code = "IN_FLIGHT"
        else:
            code = "AVAILABLE"
        return {
            "code": code,
            "candidate": candidate,
            "submitted": submitted,
            "superseded": superseded,
            "latest_claim": latest_claim,
            "in_flight": in_flight,
            "expired": expired,
            "decision_count": len(rows),
        }

    def _append_decision(
        self,
        *,
        candidate_id: int,
        decision_type: str,
        reason_code: str,
        actor_username: str,
        idempotency_key: str,
        recorded_at: datetime,
        attempt_no: int = 0,
        revalidation_hash: str | None = None,
        message_id: int | None = None,
        payload: dict | None = None,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        try:
            cur = self.db.execute(
                """INSERT INTO sms_auto_guard_decision_events
                   (candidate_id, decision_type, attempt_no, reason_code,
                    revalidation_hash, message_id, payload_json,
                    actor_username, idempotency_key, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(candidate_id),
                    str(decision_type),
                    int(attempt_no),
                    str(reason_code),
                    revalidation_hash,
                    int(message_id) if message_id is not None else None,
                    canonical_json(payload or {}),
                    str(actor_username),
                    str(idempotency_key),
                    _text(recorded_at),
                ),
            )
            if commit:
                self.db.commit()
        except sqlite3.IntegrityError as exc:
            if commit:
                self.db.rollback()
            row = self.db.execute(
                """SELECT * FROM sms_auto_guard_decision_events
                   WHERE idempotency_key=?""",
                (str(idempotency_key),),
            ).fetchone()
            if row:
                return dict(row), False
            raise SmsAutoGuardConflict(str(exc)) from exc
        row = self.db.execute(
            "SELECT * FROM sms_auto_guard_decision_events WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row), True

    def create_or_reuse_candidate(
        self,
        *,
        patient_link_id: int,
        event_key: str,
        period_key: str,
        policy_version_id: int,
        template_version_id: int,
        consent_event_id: int,
        phone_hash: str,
        source_hash: str,
        body_hash: str,
        provider_name: str,
        snapshot_hash: str,
        actor_username: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> tuple[dict, bool]:
        self.require_ready()
        try:
            self.db.execute("BEGIN IMMEDIATE")
            latest = self.db.execute(
                """SELECT * FROM sms_auto_guard_candidates
                   WHERE patient_link_id=? AND event_key=? AND period_key=?
                   ORDER BY generation_no DESC LIMIT 1""",
                (int(patient_link_id), str(event_key), str(period_key)),
            ).fetchone()
            generation = 1
            if latest:
                generation = int(latest["generation_no"]) + 1
                latest_state = self.state(int(latest["id"]), now=created_at)
                if (
                    str(latest["snapshot_hash"]) == str(snapshot_hash)
                    and latest_state["code"] in {"AVAILABLE", "IN_FLIGHT"}
                ):
                    self.db.rollback()
                    return dict(latest), False
                if latest_state["code"] not in {"SUBMITTED", "SUPERSEDED"}:
                    self._append_decision(
                        candidate_id=int(latest["id"]),
                        decision_type="SUPERSEDED",
                        reason_code=(
                            "EXPIRED_REPLACED"
                            if latest_state["code"] == "EXPIRED"
                            else "FRESH_SNAPSHOT_REPLACED"
                        ),
                        actor_username=actor_username,
                        idempotency_key=f"fo6-supersede:{int(latest['id'])}",
                        recorded_at=created_at,
                        payload={"replacement_generation": generation},
                        commit=False,
                    )
            cur = self.db.execute(
                """INSERT INTO sms_auto_guard_candidates
                   (patient_link_id, event_key, period_key, generation_no,
                    policy_version_id, template_version_id, purpose,
                    consent_event_id, phone_hash, source_hash, body_hash,
                    provider_name, snapshot_hash, created_by, created_at,
                    expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'CARE', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(patient_link_id),
                    str(event_key),
                    str(period_key),
                    generation,
                    int(policy_version_id),
                    int(template_version_id),
                    int(consent_event_id),
                    str(phone_hash),
                    str(source_hash),
                    str(body_hash),
                    str(provider_name),
                    str(snapshot_hash),
                    str(actor_username),
                    _text(created_at),
                    _text(expires_at),
                ),
            )
            candidate_id = int(cur.lastrowid)
            self._append_decision(
                candidate_id=candidate_id,
                decision_type="CREATED",
                reason_code="SNAPSHOT_CREATED",
                actor_username=actor_username,
                idempotency_key=f"fo6-created:{candidate_id}",
                recorded_at=created_at,
                revalidation_hash=snapshot_hash,
                payload={"generation_no": generation},
                commit=False,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        row = self.db.execute(
            "SELECT * FROM sms_auto_guard_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
        return dict(row), True

    def deny(
        self,
        *,
        candidate_id: int,
        reason_code: str,
        revalidation_hash: str,
        actor_username: str,
        recorded_at: datetime,
        payload: dict | None = None,
    ) -> tuple[dict, bool]:
        digest = canonical_hash(
            {
                "candidate_id": int(candidate_id),
                "reason_code": str(reason_code),
                "revalidation_hash": str(revalidation_hash),
            }
        )
        return self._append_decision(
            candidate_id=candidate_id,
            decision_type="DENIED",
            reason_code=reason_code,
            actor_username=actor_username,
            idempotency_key=f"fo6-deny:{digest}",
            recorded_at=recorded_at,
            revalidation_hash=revalidation_hash,
            payload=payload,
        )

    def claim(
        self,
        *,
        candidate_id: int,
        revalidation_hash: str,
        actor_username: str,
        claimed_at: datetime,
        lease_minutes: int = 10,
    ) -> int:
        self.require_ready()
        lease = min(max(int(lease_minutes), 1), 30)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.state(candidate_id, now=claimed_at)
            if state["code"] in {"SUBMITTED", "SUPERSEDED", "EXPIRED"}:
                raise SmsAutoGuardConflict(state["code"])
            if state["code"] == "IN_FLIGHT":
                raise SmsAutoGuardConflict("IN_FLIGHT")
            rows = self.db.execute(
                """SELECT MAX(attempt_no) AS maximum
                   FROM sms_auto_guard_decision_events
                   WHERE candidate_id=? AND decision_type='CLAIMED'""",
                (int(candidate_id),),
            ).fetchone()
            attempt = int(rows["maximum"] or 0) + 1
            self._append_decision(
                candidate_id=candidate_id,
                decision_type="CLAIMED",
                reason_code="EXECUTION_CLAIMED",
                actor_username=actor_username,
                idempotency_key=f"fo6-claim:{int(candidate_id)}:{attempt}",
                recorded_at=claimed_at,
                attempt_no=attempt,
                revalidation_hash=revalidation_hash,
                payload={
                    "claim_expires_at": _text(
                        claimed_at + timedelta(minutes=lease)
                    )
                },
                commit=False,
            )
            self.db.commit()
            return attempt
        except Exception:
            self.db.rollback()
            raise

    def finish_attempt(
        self,
        *,
        candidate_id: int,
        attempt_no: int,
        accepted: bool,
        reason_code: str,
        revalidation_hash: str,
        actor_username: str,
        recorded_at: datetime,
        message_id: int | None = None,
        payload: dict | None = None,
    ) -> tuple[dict, bool]:
        kind = "SUBMITTED" if accepted else "SUBMISSION_FAILED"
        return self._append_decision(
            candidate_id=candidate_id,
            decision_type=kind,
            reason_code=reason_code,
            actor_username=actor_username,
            idempotency_key=(
                f"fo6-{kind.lower()}:{int(candidate_id)}:{int(attempt_no)}"
            ),
            recorded_at=recorded_at,
            attempt_no=attempt_no,
            revalidation_hash=revalidation_hash,
            message_id=message_id,
            payload=payload,
        )

    def message_for_candidate(self, candidate_id: int) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM sms_messages
               WHERE source_type='fo6_auto_guard' AND source_ref=?
               ORDER BY id DESC LIMIT 1""",
            (str(int(candidate_id)),),
        ).fetchone()
        return dict(row) if row else None

    def list_candidates(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[dict]:
        self.require_ready()
        bounded = min(max(int(limit), 1), 500)
        rows = self.db.execute(
            """SELECT * FROM sms_auto_guard_candidates
               ORDER BY id DESC LIMIT ?""",
            (bounded,),
        ).fetchall()
        output = []
        for row in rows:
            state = self.state(int(row["id"]), now=now)
            output.append({**dict(row), "state": state["code"]})
        return output

    def decision_events(
        self,
        *,
        candidate_id: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        self.require_ready()
        bounded = min(max(int(limit), 1), 1000)
        if candidate_id is None:
            rows = self.db.execute(
                """SELECT * FROM sms_auto_guard_decision_events
                   ORDER BY id DESC LIMIT ?""",
                (bounded,),
            ).fetchall()
        else:
            rows = self.db.execute(
                """SELECT * FROM sms_auto_guard_decision_events
                   WHERE candidate_id=? ORDER BY id DESC LIMIT ?""",
                (int(candidate_id), bounded),
            ).fetchall()
        return [dict(row) for row in rows]


__all__ = [
    "SmsAutoGuardConflict",
    "SmsAutoGuardNotReady",
    "SmsAutoGuardRepository",
]

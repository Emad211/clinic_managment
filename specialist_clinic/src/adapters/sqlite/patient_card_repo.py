"""Repository for `patient_card_tokens` — per-patient public-card access tokens (ADR-0004).

Writes (issue / revoke) are STAFF-initiated and live here. The PUBLIC card route never
calls a write method — it only ever calls `get_by_token` (a SELECT) via the read-only
`card_projection_service`. All SQL for the card tokens lives in this repo.
"""
import secrets
from datetime import timedelta

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now

DEFAULT_TTL_HOURS = 8


class PatientCardRepository:

    def create_token(self, patient_link_id: int, *, ttl_hours: int = DEFAULT_TTL_HOURS,
                     issued_by: str | None = None) -> str:
        """Issue a fresh card token for a patient, revoking any prior active one (one
        active link at a time). Returns the new opaque token string."""
        now = iran_now()
        now_s = now.strftime('%Y-%m-%d %H:%M:%S')
        expires = (now + timedelta(hours=ttl_hours)).strftime('%Y-%m-%d %H:%M:%S')
        token = secrets.token_urlsafe(32)
        db = get_db()
        db.execute(
            "UPDATE patient_card_tokens SET revoked_at=? "
            "WHERE patient_link_id=? AND revoked_at IS NULL",
            (now_s, patient_link_id))
        db.execute(
            "INSERT INTO patient_card_tokens (patient_link_id, token, expires_at, issued_by) "
            "VALUES (?, ?, ?, ?)",
            (patient_link_id, token, expires, issued_by))
        db.commit()
        return token

    def get_by_token(self, token: str) -> dict | None:
        """Read-only token lookup. The ONLY method the public card route uses."""
        if not token:
            return None
        r = get_db().execute(
            "SELECT * FROM patient_card_tokens WHERE token=?", (token,)).fetchone()
        return dict(r) if r else None

    def active_for_patient(self, patient_link_id: int) -> dict | None:
        r = get_db().execute(
            "SELECT * FROM patient_card_tokens WHERE patient_link_id=? AND revoked_at IS NULL "
            "AND expires_at >= ? ORDER BY id DESC LIMIT 1",
            (patient_link_id, iran_now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()
        return dict(r) if r else None

    def list_for_patient(self, patient_link_id: int) -> list[dict]:
        return [dict(r) for r in get_db().execute(
            "SELECT * FROM patient_card_tokens WHERE patient_link_id=? ORDER BY id DESC",
            (patient_link_id,)).fetchall()]

    def revoke(self, token_id: int, patient_link_id: int | None = None) -> None:
        now_s = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        db = get_db()
        if patient_link_id is not None:
            db.execute(
                "UPDATE patient_card_tokens SET revoked_at=? WHERE id=? AND patient_link_id=? "
                "AND revoked_at IS NULL",
                (now_s, token_id, patient_link_id))
        else:
            db.execute(
                "UPDATE patient_card_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (now_s, token_id))
        db.commit()

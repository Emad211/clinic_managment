"""Hardened public repository facade for FOUX-V1 FO-6 SMS auto-guard.

The implementation remains isolated in ``sms_auto_guard_repo_impl``.  Version
publication is serialized with ``BEGIN IMMEDIATE`` so an A -> B -> A reversion
creates a new immutable head while concurrent identical publishers converge on
the same latest version.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite import sms_auto_guard_repo_impl as _impl
from src.services.followup_orchestration.identity import (
    canonical_hash,
    canonical_json,
)


SmsAutoGuardConflict = _impl.SmsAutoGuardConflict
SmsAutoGuardNotReady = _impl.SmsAutoGuardNotReady


class SmsAutoGuardRepository(_impl.SmsAutoGuardRepository):
    """Public FO-6 repository with atomic immutable version allocation."""

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
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                """SELECT * FROM sms_auto_guard_policy_versions
                   WHERE policy_key=? ORDER BY version DESC LIMIT 1""",
                (str(policy_key),),
            ).fetchone()
            latest = dict(row) if row else None
            if latest and str(latest["content_hash"]) == digest:
                self.db.rollback()
                return latest, False
            version = int(latest["version"]) + 1 if latest else 1
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
                    _impl._text(created_at),
                ),
            )
            policy_id = int(cur.lastrowid)
            self.db.commit()
        except sqlite3.IntegrityError:
            self.db.rollback()
            current = self.latest_policy(policy_key)
            if current and str(current["content_hash"]) == digest:
                return current, False
            raise
        except Exception:
            self.db.rollback()
            raise
        created = self.db.execute(
            "SELECT * FROM sms_auto_guard_policy_versions WHERE id=?",
            (policy_id,),
        ).fetchone()
        return dict(created), True

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
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                """SELECT * FROM sms_auto_guard_template_versions
                   WHERE event_key=? ORDER BY version DESC LIMIT 1""",
                (str(event_key),),
            ).fetchone()
            latest = dict(row) if row else None
            if latest and str(latest["content_hash"]) == digest:
                self.db.rollback()
                return latest, False
            version = int(latest["version"]) + 1 if latest else 1
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
                    _impl._text(approved_at),
                ),
            )
            template_id = int(cur.lastrowid)
            self.db.commit()
        except sqlite3.IntegrityError:
            self.db.rollback()
            current = self.latest_template(event_key)
            if current and str(current["content_hash"]) == digest:
                return current, False
            raise
        except Exception:
            self.db.rollback()
            raise
        created = self.db.execute(
            "SELECT * FROM sms_auto_guard_template_versions WHERE id=?",
            (template_id,),
        ).fetchone()
        return dict(created), True


__all__ = [
    "SmsAutoGuardConflict",
    "SmsAutoGuardNotReady",
    "SmsAutoGuardRepository",
]

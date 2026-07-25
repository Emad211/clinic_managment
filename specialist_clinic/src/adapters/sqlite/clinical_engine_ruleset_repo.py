"""Immutable Clinical Engine v2 ruleset persistence and lifecycle gates."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine import RuleLifecycleStatus, RulesetStatus

from .clinical_engine_rules_common import (
    ClinicalEngineStorageConflict,
    content_hash,
    now_text,
)


class RulesetRepositoryMixin:
    """Create, read and activate frozen ruleset membership."""

    def create_ruleset(
        self,
        ruleset_code: str,
        version: str,
        members: Sequence[Mapping[str, Any]],
        *,
        created_by: str,
        note: str | None = None,
    ) -> int:
        code = (ruleset_code or "").strip()
        normalized_version = (version or "").strip()
        actor = (created_by or "").strip()
        if not code or not normalized_version or not actor:
            raise ValueError(
                "ruleset_code, version and created_by are required"
            )
        if not members:
            raise ValueError("a ruleset must contain at least one rule version")

        normalized: list[dict[str, Any]] = []
        seen: set[int] = set()
        db = get_db()
        for member in members:
            rule_version_id = int(member["rule_version_id"])
            if rule_version_id in seen:
                raise ValueError("duplicate rule_version_id in ruleset")
            seen.add(rule_version_id)
            row = db.execute(
                "SELECT id, phase, content_hash FROM clinical_rule_versions "
                "WHERE id=?",
                (rule_version_id,),
            ).fetchone()
            if not row:
                raise LookupError(f"rule version {rule_version_id} not found")
            normalized.append(
                {
                    "rule_version_id": rule_version_id,
                    "phase": row["phase"],
                    "sort_order": int(member.get("sort_order", 100)),
                    "content_hash": row["content_hash"],
                }
            )

        phase_order = {"PREFLIGHT": 0, "SAFETY": 1, "ROUTINE": 2}
        normalized.sort(
            key=lambda item: (
                phase_order[item["phase"]],
                item["sort_order"],
                item["rule_version_id"],
            )
        )
        ruleset_hash = content_hash(
            {
                "ruleset_code": code,
                "version": normalized_version,
                "members": normalized,
            }
        )

        existing = db.execute(
            "SELECT id, content_hash FROM clinical_rulesets "
            "WHERE ruleset_code=? AND version=?",
            (code, normalized_version),
        ).fetchone()
        if existing:
            if existing["content_hash"] == ruleset_hash:
                return int(existing["id"])
            raise ClinicalEngineStorageConflict(
                "ruleset_code/version already exists with different membership"
            )

        with db:
            cursor = db.execute(
                """INSERT INTO clinical_rulesets
                   (ruleset_code, version, content_hash, status, created_by,
                    created_at, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    normalized_version,
                    ruleset_hash,
                    RulesetStatus.DRAFT.value,
                    actor,
                    now_text(),
                    note,
                ),
            )
            ruleset_id = int(cursor.lastrowid)
            db.executemany(
                """INSERT INTO clinical_ruleset_members
                   (ruleset_id, rule_version_id, phase, sort_order)
                   VALUES (?, ?, ?, ?)""",
                [
                    (
                        ruleset_id,
                        item["rule_version_id"],
                        item["phase"],
                        item["sort_order"],
                    )
                    for item in normalized
                ],
            )
        return ruleset_id

    def get_ruleset(self, ruleset_id: int) -> dict | None:
        db = get_db()
        row = db.execute(
            "SELECT * FROM clinical_rulesets WHERE id=?",
            (ruleset_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["members"] = [
            dict(item)
            for item in db.execute(
                """SELECT m.*, r.rule_code, r.version AS rule_version,
                          r.content_hash, r.lifecycle_status, r.rule_json
                   FROM clinical_ruleset_members m
                   JOIN clinical_rule_versions r ON r.id=m.rule_version_id
                   WHERE m.ruleset_id=?
                   ORDER BY CASE m.phase
                              WHEN 'PREFLIGHT' THEN 0
                              WHEN 'SAFETY' THEN 1
                              ELSE 2
                            END,
                            m.sort_order, m.rule_version_id""",
                (ruleset_id,),
            ).fetchall()
        ]
        return result

    def latest_ruleset(self, ruleset_code: str) -> dict | None:
        """Return the latest package in any lifecycle state for review."""
        row = get_db().execute(
            "SELECT id FROM clinical_rulesets WHERE ruleset_code=? "
            "ORDER BY id DESC LIMIT 1",
            ((ruleset_code or "").strip(),),
        ).fetchone()
        return self.get_ruleset(int(row["id"])) if row else None

    def retire_workflow_rulesets(
        self,
        ruleset_code: str,
        *,
        retired_by: str,
    ) -> int:
        """Retire setup attempts while preserving immutable history."""
        code = (ruleset_code or "").strip()
        actor = (retired_by or "").strip()
        if not code or not actor:
            raise ValueError("ruleset_code and retired_by are required")
        now = now_text()
        with get_db() as db:
            cursor = db.execute(
                """UPDATE clinical_rulesets
                   SET status='RETIRED', retired_at=?,
                       note=COALESCE(note, '') || ?
                   WHERE ruleset_code=?
                     AND status IN ('DRAFT', 'SILENT', 'ACTIVE')""",
                (now, f"\nReset by {actor} at {now}", code),
            )
        return int(cursor.rowcount)

    def activate_ruleset(
        self,
        ruleset_id: int,
        *,
        activated_by: str,
        silent: bool = True,
    ) -> None:
        actor = (activated_by or "").strip()
        if not actor:
            raise ValueError("activated_by is required")
        db = get_db()
        ruleset = self.get_ruleset(ruleset_id)
        if not ruleset:
            raise LookupError("ruleset not found")
        target = RulesetStatus.SILENT if silent else RulesetStatus.ACTIVE
        if ruleset["status"] == target.value:
            return
        if ruleset["status"] != RulesetStatus.DRAFT.value:
            raise ValueError("only a DRAFT ruleset can be activated")
        if not ruleset["members"]:
            raise ValueError("cannot activate an empty ruleset")

        activation_ready = {
            RuleLifecycleStatus.APPROVED.value,
            RuleLifecycleStatus.SILENT.value,
            RuleLifecycleStatus.ACTIVE.value,
        }
        invalid = [
            item
            for item in ruleset["members"]
            if item["lifecycle_status"] not in activation_ready
        ]
        if invalid:
            raise ValueError(
                "every ruleset member must be APPROVED before activation"
            )

        now = now_text()
        with db:
            db.execute(
                """UPDATE clinical_rulesets
                   SET status='RETIRED', retired_at=?
                   WHERE ruleset_code=?
                     AND status IN ('SILENT', 'ACTIVE')
                     AND id<>?""",
                (now, ruleset["ruleset_code"], ruleset_id),
            )
            db.execute(
                """UPDATE clinical_rulesets
                   SET status=?, activated_by=?, activated_at=?
                   WHERE id=?""",
                (target.value, actor, now, ruleset_id),
            )
            db.execute(
                """UPDATE clinical_rule_versions SET lifecycle_status=?
                   WHERE id IN (
                       SELECT rule_version_id
                       FROM clinical_ruleset_members
                       WHERE ruleset_id=?
                   )
                     AND lifecycle_status='APPROVED'""",
                (
                    RuleLifecycleStatus.SILENT.value
                    if silent
                    else RuleLifecycleStatus.ACTIVE.value,
                    ruleset_id,
                ),
            )

    def active_ruleset(
        self,
        ruleset_code: str,
        *,
        include_silent: bool = True,
    ) -> dict | None:
        statuses = (
            RulesetStatus.ACTIVE.value,
            RulesetStatus.SILENT.value,
        )
        sql = (
            "SELECT id FROM clinical_rulesets "
            "WHERE ruleset_code=? AND status IN (?, ?)"
        )
        params: tuple[Any, ...] = (ruleset_code, *statuses)
        if not include_silent:
            sql = (
                "SELECT id FROM clinical_rulesets "
                "WHERE ruleset_code=? AND status=?"
            )
            params = (ruleset_code, RulesetStatus.ACTIVE.value)
        row = get_db().execute(
            sql + " ORDER BY id DESC LIMIT 1",
            params,
        ).fetchone()
        return self.get_ruleset(int(row["id"])) if row else None

    def promote_silent_ruleset(
        self,
        ruleset_id: int,
        *,
        promoted_by: str,
    ) -> None:
        """Promote the exact frozen SILENT membership without content changes."""
        actor = (promoted_by or "").strip()
        if not actor:
            raise ValueError("promoted_by is required")
        ruleset = self.get_ruleset(ruleset_id)
        if not ruleset:
            raise LookupError("ruleset not found")
        if ruleset["status"] == RulesetStatus.ACTIVE.value:
            return
        if ruleset["status"] != RulesetStatus.SILENT.value:
            raise ValueError("only a SILENT ruleset can be promoted")
        with get_db() as db:
            db.execute(
                """UPDATE clinical_rulesets
                   SET status='ACTIVE', activated_by=?, activated_at=?
                   WHERE id=?""",
                (actor, now_text(), ruleset_id),
            )
            db.execute(
                """UPDATE clinical_rule_versions
                   SET lifecycle_status='ACTIVE'
                   WHERE id IN (
                       SELECT rule_version_id
                       FROM clinical_ruleset_members
                       WHERE ruleset_id=?
                   )
                     AND lifecycle_status='SILENT'""",
                (ruleset_id,),
            )

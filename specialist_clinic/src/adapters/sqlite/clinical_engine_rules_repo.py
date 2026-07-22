"""Persistence for immutable Clinical Engine v2 rule and ruleset versions.

This repository never reads or mutates the legacy ``clinical_rules`` catalog.
Only a successfully compiled rule can enter the v2 version store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now
from src.domain.clinical_engine import (
    CompiledRule,
    RuleLifecycleStatus,
    RulesetStatus,
)


class ClinicalEngineStorageConflict(ValueError):
    """A version identifier was reused with different immutable content."""


def _now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class ClinicalEngineRulesRepository:
    """SQLite boundary for versioned rules and immutable ruleset membership."""

    def create_rule_version(
        self,
        compiled: CompiledRule,
        *,
        created_by: str,
        change_note: str | None = None,
        supersedes_rule_version_id: int | None = None,
    ) -> int:
        if not isinstance(compiled, CompiledRule):
            raise TypeError("compiled must be a CompiledRule")
        actor = (created_by or "").strip()
        if not actor:
            raise ValueError("created_by is required")

        definition = compiled.definition
        db = get_db()
        existing = db.execute(
            "SELECT id, content_hash FROM clinical_rule_versions "
            "WHERE rule_code=? AND version=?",
            (definition.rule_code, definition.version),
        ).fetchone()
        if existing:
            if existing["content_hash"] == compiled.content_hash:
                return int(existing["id"])
            raise ClinicalEngineStorageConflict(
                "rule_code/version already exists with different content"
            )

        same_hash = db.execute(
            "SELECT rule_code, version FROM clinical_rule_versions WHERE content_hash=?",
            (compiled.content_hash,),
        ).fetchone()
        if same_hash:
            raise ClinicalEngineStorageConflict(
                "content_hash already belongs to "
                f"{same_hash['rule_code']}@{same_hash['version']}"
            )

        if supersedes_rule_version_id is not None:
            prior = db.execute(
                "SELECT rule_code FROM clinical_rule_versions WHERE id=?",
                (supersedes_rule_version_id,),
            ).fetchone()
            if not prior or prior["rule_code"] != definition.rule_code:
                raise ValueError("superseded version must exist for the same rule_code")

        with db:
            cur = db.execute(
                """INSERT INTO clinical_rule_versions
                   (rule_code, version, schema_version, dsl_version, phase,
                    action_type, rule_json, content_hash, source_legacy_rule_id,
                    lifecycle_status, created_by, created_at,
                    supersedes_rule_version_id, change_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    definition.rule_code,
                    definition.version,
                    definition.schema_version,
                    definition.dsl_version,
                    definition.phase.value,
                    definition.action_type.value,
                    compiled.canonical_json,
                    compiled.content_hash,
                    definition.legacy_rule_id,
                    RuleLifecycleStatus.DRAFT.value,
                    actor,
                    _now_text(),
                    supersedes_rule_version_id,
                    change_note,
                ),
            )
        return int(cur.lastrowid)

    def get_rule_version(self, rule_version_id: int) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM clinical_rule_versions WHERE id=?", (rule_version_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_rule(self, rule_code: str, version: str) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM clinical_rule_versions WHERE rule_code=? AND version=?",
            (rule_code, version),
        ).fetchone()
        return dict(row) if row else None

    def mark_validated(self, rule_version_id: int, compiled: CompiledRule) -> None:
        """Record successful compilation without trusting caller-provided JSON/hash."""
        row = self.get_rule_version(rule_version_id)
        if not row:
            raise LookupError("rule version not found")
        if row["content_hash"] != compiled.content_hash or row["rule_json"] != compiled.canonical_json:
            raise ClinicalEngineStorageConflict("compiled rule does not match stored content")
        if row["lifecycle_status"] == RuleLifecycleStatus.VALIDATED.value:
            return
        if row["lifecycle_status"] != RuleLifecycleStatus.DRAFT.value:
            raise ValueError("only a DRAFT rule can be marked VALIDATED")
        with get_db() as db:
            db.execute(
                "UPDATE clinical_rule_versions SET lifecycle_status=? WHERE id=?",
                (RuleLifecycleStatus.VALIDATED.value, rule_version_id),
            )

    def approve_rule_version(self, rule_version_id: int, *, approved_by: str) -> None:
        actor = (approved_by or "").strip()
        if not actor:
            raise ValueError("approved_by is required")
        db = get_db()
        row = db.execute(
            "SELECT lifecycle_status FROM clinical_rule_versions WHERE id=?",
            (rule_version_id,),
        ).fetchone()
        if not row:
            raise LookupError("rule version not found")
        if row["lifecycle_status"] == RuleLifecycleStatus.APPROVED.value:
            return
        if row["lifecycle_status"] != RuleLifecycleStatus.VALIDATED.value:
            raise ValueError("only a VALIDATED rule can be approved")
        with db:
            db.execute(
                """UPDATE clinical_rule_versions
                   SET lifecycle_status=?, approved_by=?, approved_at=? WHERE id=?""",
                (RuleLifecycleStatus.APPROVED.value, actor, _now_text(), rule_version_id),
            )

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
        version = (version or "").strip()
        actor = (created_by or "").strip()
        if not code or not version or not actor:
            raise ValueError("ruleset_code, version and created_by are required")
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
                "SELECT id, phase, content_hash FROM clinical_rule_versions WHERE id=?",
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
        hash_payload = {
            "ruleset_code": code,
            "version": version,
            "members": normalized,
        }
        content_hash = hashlib.sha256(_canonical_json(hash_payload).encode("utf-8")).hexdigest()

        existing = db.execute(
            "SELECT id, content_hash FROM clinical_rulesets "
            "WHERE ruleset_code=? AND version=?",
            (code, version),
        ).fetchone()
        if existing:
            if existing["content_hash"] == content_hash:
                return int(existing["id"])
            raise ClinicalEngineStorageConflict(
                "ruleset_code/version already exists with different membership"
            )

        with db:
            cur = db.execute(
                """INSERT INTO clinical_rulesets
                   (ruleset_code, version, content_hash, status, created_by,
                    created_at, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    version,
                    content_hash,
                    RulesetStatus.DRAFT.value,
                    actor,
                    _now_text(),
                    note,
                ),
            )
            ruleset_id = int(cur.lastrowid)
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
            "SELECT * FROM clinical_rulesets WHERE id=?", (ruleset_id,)
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
                              WHEN 'PREFLIGHT' THEN 0 WHEN 'SAFETY' THEN 1 ELSE 2 END,
                            m.sort_order, m.rule_version_id""",
                (ruleset_id,),
            ).fetchall()
        ]
        return result

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
            raise ValueError("every ruleset member must be APPROVED before activation")

        now = _now_text()
        with db:
            db.execute(
                """UPDATE clinical_rulesets
                   SET status='RETIRED', retired_at=?
                   WHERE ruleset_code=? AND status IN ('SILENT', 'ACTIVE') AND id<>?""",
                (now, ruleset["ruleset_code"], ruleset_id),
            )
            db.execute(
                """UPDATE clinical_rulesets
                   SET status=?, activated_by=?, activated_at=? WHERE id=?""",
                (target.value, actor, now, ruleset_id),
            )
            db.execute(
                """UPDATE clinical_rule_versions SET lifecycle_status=?
                   WHERE id IN (SELECT rule_version_id FROM clinical_ruleset_members
                                WHERE ruleset_id=?)
                     AND lifecycle_status='APPROVED'""",
                (
                    RuleLifecycleStatus.SILENT.value
                    if silent
                    else RuleLifecycleStatus.ACTIVE.value,
                    ruleset_id,
                ),
            )

    def active_ruleset(self, ruleset_code: str, *, include_silent: bool = True) -> dict | None:
        statuses = (RulesetStatus.ACTIVE.value, RulesetStatus.SILENT.value)
        sql = "SELECT id FROM clinical_rulesets WHERE ruleset_code=? AND status IN (?, ?)"
        params: tuple[Any, ...] = (ruleset_code, *statuses)
        if not include_silent:
            sql = "SELECT id FROM clinical_rulesets WHERE ruleset_code=? AND status=?"
            params = (ruleset_code, RulesetStatus.ACTIVE.value)
        row = get_db().execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()
        return self.get_ruleset(int(row["id"])) if row else None

    def promote_silent_ruleset(self, ruleset_id: int, *, promoted_by: str) -> None:
        """Promote the exact frozen SILENT membership; no rule content changes."""
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
                "UPDATE clinical_rulesets SET status='ACTIVE', activated_by=?, activated_at=? WHERE id=?",
                (actor, _now_text(), ruleset_id),
            )
            db.execute(
                """UPDATE clinical_rule_versions SET lifecycle_status='ACTIVE'
                   WHERE id IN (SELECT rule_version_id FROM clinical_ruleset_members WHERE ruleset_id=? )
                     AND lifecycle_status='SILENT'""",
                (ruleset_id,),
            )

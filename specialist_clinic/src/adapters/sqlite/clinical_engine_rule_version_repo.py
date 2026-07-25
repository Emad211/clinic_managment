"""Immutable Clinical Engine v2 rule-version persistence."""
from __future__ import annotations

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine import CompiledRule, RuleLifecycleStatus

from .clinical_engine_rules_common import (
    ClinicalEngineStorageConflict,
    now_text,
)


class RuleVersionRepositoryMixin:
    """Create and govern compiled rule versions without v1 lineage fields."""

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
            "SELECT rule_code, version FROM clinical_rule_versions "
            "WHERE content_hash=?",
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
                raise ValueError(
                    "superseded version must exist for the same rule_code"
                )

        with db:
            cursor = db.execute(
                """INSERT INTO clinical_rule_versions
                   (rule_code, version, schema_version, dsl_version, phase,
                    action_type, rule_json, content_hash, lifecycle_status,
                    created_by, created_at, supersedes_rule_version_id,
                    change_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    definition.rule_code,
                    definition.version,
                    definition.schema_version,
                    definition.dsl_version,
                    definition.phase.value,
                    definition.action_type.value,
                    compiled.canonical_json,
                    compiled.content_hash,
                    RuleLifecycleStatus.DRAFT.value,
                    actor,
                    now_text(),
                    supersedes_rule_version_id,
                    change_note,
                ),
            )
        return int(cursor.lastrowid)

    def get_rule_version(self, rule_version_id: int) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM clinical_rule_versions WHERE id=?",
            (rule_version_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_rule(self, rule_code: str, version: str) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM clinical_rule_versions "
            "WHERE rule_code=? AND version=?",
            (rule_code, version),
        ).fetchone()
        return dict(row) if row else None

    def mark_validated(
        self,
        rule_version_id: int,
        compiled: CompiledRule,
    ) -> None:
        """Record compilation only when canonical JSON and hash match storage."""
        row = self.get_rule_version(rule_version_id)
        if not row:
            raise LookupError("rule version not found")
        if (
            row["content_hash"] != compiled.content_hash
            or row["rule_json"] != compiled.canonical_json
        ):
            raise ClinicalEngineStorageConflict(
                "compiled rule does not match stored content"
            )
        if row["lifecycle_status"] == RuleLifecycleStatus.VALIDATED.value:
            return
        if row["lifecycle_status"] != RuleLifecycleStatus.DRAFT.value:
            raise ValueError("only a DRAFT rule can be marked VALIDATED")
        with get_db() as db:
            db.execute(
                "UPDATE clinical_rule_versions SET lifecycle_status=? "
                "WHERE id=?",
                (RuleLifecycleStatus.VALIDATED.value, rule_version_id),
            )

    def approve_rule_version(
        self,
        rule_version_id: int,
        *,
        approved_by: str,
    ) -> None:
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
                   SET lifecycle_status=?, approved_by=?, approved_at=?
                   WHERE id=?""",
                (
                    RuleLifecycleStatus.APPROVED.value,
                    actor,
                    now_text(),
                    rule_version_id,
                ),
            )

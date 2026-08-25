"""Append-only, content-bound dual review for Clinical Engine rule packages."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.adapters.sqlite.core import get_db

from .clinical_engine_rules_common import content_hash, now_text


_ROLES = frozenset({"CLINICAL", "TECHNICAL"})
_DECISIONS = frozenset({"APPROVE", "REQUEST_CHANGES"})


class RuleReviewRepositoryMixin:
    """Persist latest-by-event review projections without mutable review rows."""

    def append_package_reviews(
        self,
        ruleset_id: int,
        *,
        role: str,
        decisions: Mapping[str, str],
        package_hash: str,
        case_bundle_hash: str,
        reviewer_username: str,
        reviewer_display_name: str,
        note: str,
    ) -> dict[str, Any]:
        normalized_role = str(role or "").strip().upper()
        username = str(reviewer_username or "").strip()
        display_name = str(reviewer_display_name or "").strip()
        review_note = str(note or "").strip()
        package_digest = str(package_hash or "").strip()
        case_digest = str(case_bundle_hash or "").strip()
        if normalized_role not in _ROLES:
            raise ValueError("review role must be CLINICAL or TECHNICAL")
        if not username or not display_name or not review_note:
            raise ValueError("authenticated reviewer identity and note are required")
        if not package_digest or not case_digest:
            raise ValueError("package and validation-case hashes are required")

        ruleset = self.get_ruleset(int(ruleset_id))
        if not ruleset:
            raise LookupError("ruleset not found")
        if ruleset["status"] != "DRAFT":
            raise ValueError("reviews can only be appended to a DRAFT ruleset")
        expected_codes = {str(item["rule_code"]) for item in ruleset["members"]}
        normalized_decisions = {
            str(code): str(decision or "").strip().upper()
            for code, decision in dict(decisions or {}).items()
        }
        if set(normalized_decisions) != expected_codes:
            raise ValueError("every ruleset member requires an explicit review decision")
        invalid = sorted(
            code for code, decision in normalized_decisions.items()
            if decision not in _DECISIONS
        )
        if invalid:
            raise ValueError("invalid review decision for: " + ", ".join(invalid))

        db = get_db()
        created_at = now_text()
        with db:
            for member in ruleset["members"]:
                rule_code = str(member["rule_code"])
                rule_version_id = int(member["rule_version_id"])
                prior = db.execute(
                    """SELECT * FROM clinical_rule_review_events
                       WHERE ruleset_id=? AND rule_version_id=? AND role=?
                       ORDER BY id DESC LIMIT 1""",
                    (int(ruleset_id), rule_version_id, normalized_role),
                ).fetchone()
                if prior and all((
                    str(prior["decision"]) == normalized_decisions[rule_code],
                    str(prior["ruleset_content_hash"]) == str(ruleset["content_hash"]),
                    str(prior["rule_content_hash"]) == str(member["content_hash"]),
                    str(prior["package_hash"]) == package_digest,
                    str(prior["case_bundle_hash"]) == case_digest,
                    str(prior["reviewer_username"]) == username,
                    str(prior["reviewer_display_name"]) == display_name,
                    str(prior["note"]) == review_note,
                )):
                    continue
                identity = {
                    "ruleset_id": int(ruleset_id),
                    "rule_version_id": rule_version_id,
                    "role": normalized_role,
                    "decision": normalized_decisions[rule_code],
                    "ruleset_content_hash": str(ruleset["content_hash"]),
                    "rule_content_hash": str(member["content_hash"]),
                    "package_hash": package_digest,
                    "case_bundle_hash": case_digest,
                    "reviewer_username": username,
                    "reviewer_display_name": display_name,
                    "note": review_note,
                    "supersedes_event_id": int(prior["id"]) if prior else None,
                }
                idempotency_key = content_hash(identity)
                if db.execute(
                    "SELECT id FROM clinical_rule_review_events WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone():
                    continue
                db.execute(
                    """INSERT INTO clinical_rule_review_events
                       (ruleset_id, rule_version_id, role, decision,
                        ruleset_content_hash, rule_content_hash, package_hash,
                        case_bundle_hash, reviewer_username, reviewer_display_name,
                        note, supersedes_event_id, idempotency_key, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(ruleset_id), rule_version_id, normalized_role,
                        normalized_decisions[rule_code], str(ruleset["content_hash"]),
                        str(member["content_hash"]), package_digest, case_digest,
                        username, display_name, review_note,
                        int(prior["id"]) if prior else None,
                        idempotency_key, created_at,
                    ),
                )
        return self.rule_review_summary(int(ruleset_id))

    def latest_rule_reviews(self, ruleset_id: int) -> list[dict[str, Any]]:
        rows = get_db().execute(
            """SELECT event.*, version.rule_code
               FROM clinical_rule_review_events event
               JOIN clinical_rule_versions version
                 ON version.id=event.rule_version_id
               WHERE event.ruleset_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_rule_review_events child
                     WHERE child.ruleset_id=event.ruleset_id
                       AND child.rule_version_id=event.rule_version_id
                       AND child.role=event.role
                       AND child.id>event.id
                 )
               ORDER BY version.rule_code, event.role""",
            (int(ruleset_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def rule_review_summary(self, ruleset_id: int) -> dict[str, Any]:
        ruleset = self.get_ruleset(int(ruleset_id))
        if not ruleset:
            raise LookupError("ruleset not found")
        events = self.latest_rule_reviews(int(ruleset_id))
        by_rule: dict[str, dict[str, dict[str, Any] | None]] = {
            str(member["rule_code"]): {"clinical": None, "technical": None}
            for member in ruleset["members"]
        }
        for event in events:
            by_rule[str(event["rule_code"])][str(event["role"]).lower()] = event

        role_projection: dict[str, dict[str, Any]] = {}
        for role in ("clinical", "technical"):
            records = [by_rule[code][role] for code in sorted(by_rule)]
            reviewers = {
                str(record["reviewer_username"])
                for record in records if record is not None
            }
            complete = bool(records) and all(
                record is not None and record["decision"] == "APPROVE"
                for record in records
            ) and len(reviewers) == 1
            role_projection[role] = {
                "complete": complete,
                "reviewer_username": next(iter(reviewers)) if len(reviewers) == 1 else None,
                "reviewer_display_name": (
                    next(
                        str(record["reviewer_display_name"])
                        for record in records if record is not None
                    ) if len(reviewers) == 1 else None
                ),
                "approved_count": sum(
                    1 for record in records
                    if record is not None and record["decision"] == "APPROVE"
                ),
                "changes_requested_count": sum(
                    1 for record in records
                    if record is not None and record["decision"] == "REQUEST_CHANGES"
                ),
                "total": len(records),
            }

        distinct = bool(
            role_projection["clinical"]["reviewer_username"]
            and role_projection["technical"]["reviewer_username"]
        )
        ready = bool(
            ruleset["status"] == "DRAFT"
            and role_projection["clinical"]["complete"]
            and role_projection["technical"]["complete"]
            and distinct
        )
        blockers: list[str] = []
        for role, label in (("clinical", "بازبینی بالینی"), ("technical", "بازبینی فنی")):
            if not role_projection[role]["complete"]:
                blockers.append(label + " همهٔ قواعد کامل و تأییدشده نیست")
        return {
            "rules": by_rule,
            "roles": role_projection,
            "distinct_reviewers": distinct,
            "ready_to_freeze": ready,
            "blockers": blockers,
            "event_count": len(events),
        }

"""Read-only projections over one governed Clinical Engine v2 ruleset."""
from __future__ import annotations

from collections import Counter
import json

from src.adapters.sqlite.core import get_db


class RuleProjectionRepositoryMixin:
    """Produce manager-facing counts without exposing mutable rule storage."""

    def condition_rule_counts(
        self,
        ruleset_code: str = "general-outpatient",
    ) -> dict[str, int]:
        """Count rules in the current governed package by condition scope.

        Prefer the executable ACTIVE/SILENT ruleset. Before activation, show the
        newest DRAFT package under review. Historical RETIRED versions are never
        mixed into the count. A rule with no condition scope contributes to ``all``.
        """
        db = get_db()
        row = db.execute(
            """SELECT id
                 FROM clinical_rulesets
                WHERE ruleset_code=? AND status IN ('ACTIVE', 'SILENT')
                ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, id DESC
                LIMIT 1""",
            ((ruleset_code or "").strip(),),
        ).fetchone()
        if not row:
            row = db.execute(
                """SELECT id
                     FROM clinical_rulesets
                    WHERE ruleset_code=? AND status='DRAFT'
                    ORDER BY id DESC LIMIT 1""",
                ((ruleset_code or "").strip(),),
            ).fetchone()
        if not row:
            return {}

        counts: Counter[str] = Counter()
        members = db.execute(
            """SELECT version.rule_json
                 FROM clinical_ruleset_members member
                 JOIN clinical_rule_versions version
                   ON version.id=member.rule_version_id
                WHERE member.ruleset_id=?
                ORDER BY member.rule_version_id""",
            (int(row["id"]),),
        ).fetchall()
        for member in members:
            raw = json.loads(member["rule_json"])
            values = (raw.get("scope") or {}).get("condition_codes") or ["all"]
            codes = {str(value).strip() for value in values if str(value).strip()}
            for code in codes or {"all"}:
                counts[code] += 1
        return dict(sorted(counts.items()))

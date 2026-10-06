"""Cut-off drafts and approval (docs/05 §6, ADR-0009, docs/06 §6).

Drafting: manager or director doctor. Approval: director doctor only. The
previously approved version is retired; walk-ins keep the id they used.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from typing import Any

from ..adapters.sqlite import account_repo, journey_repo as repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT
from ..common.jalali import jalali_datetime
from ..domain import cutoffs as domain


class CutoffError(ValueError):
    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


def state(conn: sqlite3.Connection) -> dict[str, Any]:
    approved, draft = repo.approved_cutoff(conn), repo.draft_cutoff(conn)

    def view(row):
        if row is None:
            return None
        rules = json.loads(row["rules"])
        return {"id": row["id"], "version": row["version"], "rules": rules, "drafted_by": row["drafted_by"],
                "drafted_at": row["drafted_at"], "approved_at": row["approved_at"],
                "drafted_at_fa": jalali_datetime(row["drafted_at"]), "approved_at_fa": jalali_datetime(row["approved_at"]),
                "approved_by_staff_id": row["approved_by_staff_id"], "problems": domain.validate(rules)}
    return {"approved": view(approved), "draft": view(draft),
            "blank": copy.deepcopy(approved and json.loads(approved["rules"]) or domain.EMPTY_TEMPLATE)}


def approved_rules(conn: sqlite3.Connection) -> tuple[int, dict] | None:
    row = repo.approved_cutoff(conn)
    return (row["id"], json.loads(row["rules"])) if row else None


def save_draft(conn: sqlite3.Connection, rules: Any, *, actor: str, now: datetime) -> dict[str, Any]:
    """Drafts may be incomplete (empty numbers); only approval demands a valid set."""
    if not isinstance(rules, dict) or set(rules) - {"bp", "bs", "series"}:
        raise CutoffError("قالب کات‌آف نامعتبر است")
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        rid = repo.save_cutoff_draft(conn, rules, actor, at)
        account_repo.audit(conn, at, actor, "cutoff.draft", "cutoff_ruleset", rid, after=rules)
    return {"id": rid, "problems": domain.validate(rules)}


def approve(conn: sqlite3.Connection, *, director_staff_id: int, actor: str, now: datetime) -> int:
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        draft = repo.draft_cutoff(conn)
        if draft is None:
            raise CutoffError("پیش‌نویسی برای تأیید وجود ندارد")
        rules = json.loads(draft["rules"])
        problems = domain.validate(rules)
        if problems:
            raise CutoffError("پیش‌نویس کامل نیست و قابل تأیید نیست", problems)
        before = repo.approved_cutoff(conn)
        repo.approve_cutoff(conn, draft["id"], director_staff_id, at)
        account_repo.audit(conn, at, actor, "cutoff.approve", "cutoff_ruleset", draft["id"],
                           before={"approved_version": before["version"]} if before else None,
                           after={"version": draft["version"], "rules": rules})
    return int(draft["version"])

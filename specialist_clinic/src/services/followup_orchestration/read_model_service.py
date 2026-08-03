"""Bounded, read-only FO-3 projection queries for the Unified Worklist.

This service never installs schema, rebuilds projection rows, or mutates a source of
truth.  It is deliberately limited to paginated reads over the FO-2 cache plus the
minimum patient identity and source-link metadata needed by the UI.
"""
from __future__ import annotations

from datetime import datetime
import math
import sqlite3


STATE_LABELS = {
    "ACTION_REQUIRED": "نیازمند اقدام",
    "WAITING": "در انتظار",
    "BLOCKED": "مسدود",
    "TERMINAL": "پایان‌یافته",
}
ROLE_LABELS = {
    "RECEPTION": "صف پیشنهادی پذیرش",
    "NURSING": "صف پیشنهادی پرستاری",
    "PHYSICIAN": "نیازمند بررسی پزشک",
    "MANAGER": "نیازمند بررسی مدیر عملیات",
}
_ALLOWED_STATES = frozenset(STATE_LABELS)
_ALLOWED_ROLES = frozenset(ROLE_LABELS)
_ALLOWED_SLA = frozenset({"ON_TIME", "DUE_SOON", "OVERDUE", "BLOCKED", "NONE"})


def _as_datetime(value: object) -> datetime | None:
    rendered = str(value or "").strip()
    if not rendered:
        return None
    try:
        return datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except ValueError:
        return None


def _masked_national_id(value: object) -> str:
    rendered = str(value or "").strip()
    if len(rendered) < 4:
        return ""
    return "••••••" + rendered[-4:]


class FollowupUnifiedReadModelService:
    """Serve deterministic list/detail models without N+1 or request-time writes."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def _table(self, name: str) -> bool:
        return bool(
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        )

    @staticmethod
    def _normalize_page(value: object, *, default: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return min(max(parsed, 1), maximum)

    @staticmethod
    def _explanation(row: dict) -> str:
        if row["state_class"] == "ACTION_REQUIRED":
            return str(row.get("next_action_label") or "اقدام بعدی مشخص نشده است")
        if row["state_class"] == "WAITING":
            return str(row.get("waiting_reason_label") or "در انتظار رویداد بعدی")
        if row["state_class"] == "BLOCKED":
            return str(row.get("blocked_reason_label") or "یک مانع نیازمند بررسی است")
        return "این مسیر پایان یافته است"

    @staticmethod
    def _source_map(rows: list[sqlite3.Row]) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for row in rows:
            item = {
                "source_type": str(row["source_type"]),
                "source_id": str(row["source_id"]),
                "relation_type": str(row["relation_type"]),
                "linked_at": str(row["linked_at"]),
            }
            result.setdefault(str(row["episode_id"]), []).append(item)
        return result

    def _links_for(self, episode_ids: list[str]) -> dict[str, list[dict]]:
        if not episode_ids or not self._table("followup_episode_links"):
            return {}
        placeholders = ",".join("?" for _ in episode_ids)
        rows = self.db.execute(
            f"""SELECT episode_id, source_type, source_id, relation_type, linked_at
                FROM followup_episode_links
                WHERE episode_id IN ({placeholders})
                ORDER BY episode_id,
                         CASE relation_type WHEN 'PRIMARY' THEN 0 ELSE 1 END,
                         linked_at, id""",
            episode_ids,
        ).fetchall()
        return self._source_map(rows)

    def _decorate(
        self,
        row: sqlite3.Row | dict,
        *,
        sources: list[dict],
        now: datetime,
        stale_after_minutes: int,
    ) -> dict:
        item = dict(row)
        rebuilt_at = _as_datetime(item.get("rebuilt_at"))
        compare_now = now
        if rebuilt_at and rebuilt_at.tzinfo and compare_now.tzinfo is None:
            compare_now = compare_now.replace(tzinfo=rebuilt_at.tzinfo)
        if rebuilt_at and rebuilt_at.tzinfo is None and compare_now.tzinfo:
            rebuilt_at = rebuilt_at.replace(tzinfo=compare_now.tzinfo)
        age_minutes = (
            max(int((compare_now - rebuilt_at).total_seconds() // 60), 0)
            if rebuilt_at
            else None
        )
        due_at = _as_datetime(item.get("action_due_at"))
        due_now = now
        if due_at and due_at.tzinfo and due_now.tzinfo is None:
            due_now = due_now.replace(tzinfo=due_at.tzinfo)
        if due_at and due_at.tzinfo is None and due_now.tzinfo:
            due_at = due_at.replace(tzinfo=due_now.tzinfo)
        item.update(
            {
                "patient_national_id_masked": _masked_national_id(
                    item.pop("patient_national_id", "")
                ),
                "state_label": STATE_LABELS.get(
                    str(item.get("state_class") or ""), "وضعیت نامشخص"
                ),
                "role_label": ROLE_LABELS.get(
                    str(item.get("owner_role_proposal") or ""), "بدون صف پیشنهادی"
                ),
                "primary_explanation": self._explanation(item),
                "projection_age_minutes": age_minutes,
                "is_stale": age_minutes is None or age_minutes > stale_after_minutes,
                "is_overdue": bool(
                    due_at
                    and item.get("state_class") != "TERMINAL"
                    and due_at < due_now
                ),
                "sources": sources,
                "source_types": list(dict.fromkeys(
                    source["source_type"] for source in sources
                )),
                "primary_source": next(
                    (
                        source
                        for source in sources
                        if source["relation_type"] == "PRIMARY"
                    ),
                    sources[0] if sources else None,
                ),
            }
        )
        return item

    def list_items(
        self,
        *,
        page: object = 1,
        per_page: object = 20,
        query: str | None = None,
        state_class: str | None = None,
        role: str | None = None,
        sla_state: str | None = None,
        now: datetime | None = None,
        stale_after_minutes: int = 120,
    ) -> dict:
        page_number = self._normalize_page(page, default=1, maximum=1_000_000)
        page_size = self._normalize_page(per_page, default=20, maximum=50)
        current = now or datetime.now().replace(microsecond=0)

        if not self._table("followup_work_item_projection"):
            return {
                "projection_ready": False,
                "items": [],
                "page": 1,
                "per_page": page_size,
                "total": 0,
                "pages": 0,
                "has_previous": False,
                "has_next": False,
                "filters": {},
            }

        clauses: list[str] = []
        params: list[object] = []
        normalized_state = str(state_class or "").strip().upper()
        normalized_role = str(role or "").strip().upper()
        normalized_sla = str(sla_state or "").strip().upper()
        normalized_query = str(query or "").strip()[:120]

        if normalized_state in _ALLOWED_STATES:
            clauses.append("projection.state_class=?")
            params.append(normalized_state)
        else:
            normalized_state = ""
        if normalized_role in _ALLOWED_ROLES:
            clauses.append("projection.owner_role_proposal=?")
            params.append(normalized_role)
        else:
            normalized_role = ""
        if normalized_sla in _ALLOWED_SLA:
            clauses.append("projection.sla_state=?")
            params.append(normalized_sla)
        else:
            normalized_sla = ""
        if normalized_query:
            like = f"%{normalized_query}%"
            clauses.append(
                "(patient.full_name LIKE ? OR patient.national_id LIKE ? "
                "OR patient.phone_number LIKE ? OR projection.reason_label LIKE ? "
                "OR projection.why_created LIKE ?)"
            )
            params.extend((like, like, like, like, like))

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        base = """ FROM followup_work_item_projection projection
                   JOIN patient_links patient
                     ON patient.id=projection.patient_link_id"""
        total = int(
            self.db.execute(
                "SELECT COUNT(*)" + base + where,
                params,
            ).fetchone()[0]
        )
        pages = int(math.ceil(total / page_size)) if total else 0
        if pages and page_number > pages:
            page_number = pages
        offset = (page_number - 1) * page_size
        rows = self.db.execute(
            """SELECT projection.*,
                      patient.full_name AS patient_name,
                      patient.national_id AS patient_national_id
               """
            + base
            + where
            + """ ORDER BY
                    CASE projection.state_class
                      WHEN 'BLOCKED' THEN 0
                      WHEN 'ACTION_REQUIRED' THEN 1
                      WHEN 'WAITING' THEN 2
                      ELSE 3
                    END,
                    projection.priority DESC,
                    COALESCE(
                      projection.action_due_at,
                      projection.target_at,
                      '9999-12-31 23:59:59'
                    ),
                    projection.episode_id
                   LIMIT ? OFFSET ?""",
            [*params, page_size, offset],
        ).fetchall()
        episode_ids = [str(row["episode_id"]) for row in rows]
        links = self._links_for(episode_ids)
        items = [
            self._decorate(
                row,
                sources=links.get(str(row["episode_id"]), []),
                now=current,
                stale_after_minutes=stale_after_minutes,
            )
            for row in rows
        ]
        return {
            "projection_ready": True,
            "items": items,
            "page": page_number,
            "per_page": page_size,
            "total": total,
            "pages": pages,
            "has_previous": page_number > 1,
            "has_next": bool(pages and page_number < pages),
            "filters": {
                "q": normalized_query,
                "state": normalized_state,
                "role": normalized_role,
                "sla": normalized_sla,
            },
        }

    def get_item(
        self,
        episode_id: str,
        *,
        now: datetime | None = None,
        stale_after_minutes: int = 120,
    ) -> dict | None:
        if not self._table("followup_work_item_projection"):
            return None
        row = self.db.execute(
            """SELECT projection.*,
                      patient.full_name AS patient_name,
                      patient.national_id AS patient_national_id
               FROM followup_work_item_projection projection
               JOIN patient_links patient
                 ON patient.id=projection.patient_link_id
               WHERE projection.episode_id=?""",
            (str(episode_id),),
        ).fetchone()
        if not row:
            return None
        links = self._links_for([str(episode_id)])
        return self._decorate(
            row,
            sources=links.get(str(episode_id), []),
            now=now or datetime.now().replace(microsecond=0),
            stale_after_minutes=stale_after_minutes,
        )


__all__ = [
    "FollowupUnifiedReadModelService",
    "ROLE_LABELS",
    "STATE_LABELS",
]

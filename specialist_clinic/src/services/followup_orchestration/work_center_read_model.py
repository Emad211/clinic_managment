"""Read-only Work Center composition over the existing FO-3/FO-4 projections.

This module adds no workflow state and performs no mutations. It only applies the
approved frontend scopes (my work, unassigned, active, completed and manager view)
to the existing projection and ownership event stream.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime

from src.common.utils import iran_now
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
    _EFFECTIVE_SLA_SQL,
    _readiness_payload,
)


WORK_VIEW_LABELS = {
    "mine": "کارهای من",
    "unassigned": "بدون مسئول",
    "all": "همهٔ کارهای باز",
    "completed": "تکمیل‌شده",
    "manager": "نمای مدیریتی",
}

_OWNER_USER_SQL = """
(
    SELECT CASE
        WHEN json_extract(owner_event.payload_json, '$.action')='RELEASE'
            THEN NULL
        ELSE CAST(
            json_extract(owner_event.payload_json, '$.owner_user_id') AS INTEGER
        )
    END
    FROM followup_episode_events owner_event
    WHERE owner_event.episode_id=projection.episode_id
      AND owner_event.event_type IN ('ROUTED','CLAIMED','ASSIGNED')
    ORDER BY owner_event.id DESC
    LIMIT 1
)
"""

_OWNER_ROLE_SQL = """
COALESCE(
    (
        SELECT json_extract(owner_event.payload_json, '$.owner_role')
        FROM followup_episode_events owner_event
        WHERE owner_event.episode_id=projection.episode_id
          AND owner_event.event_type IN ('ROUTED','CLAIMED','ASSIGNED')
        ORDER BY owner_event.id DESC
        LIMIT 1
    ),
    projection.owner_role_proposal
)
"""


class WorkCenterReadModelService:
    """Compose paginated Work Center views without changing source records."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.base = FollowupUnifiedReadModelService(db)

    @staticmethod
    def normalize_view(value: object, *, allow_manager: bool) -> str:
        view = str(value or "mine").strip().lower()
        if view == "manager" and not allow_manager:
            return "mine"
        return view if view in WORK_VIEW_LABELS else "mine"

    def counts(self, *, actor_user_id: int) -> dict[str, int]:
        readiness = self.base.readiness()
        empty = {"mine": 0, "unassigned": 0, "all": 0, "completed": 0, "manager": 0}
        if not readiness["ready"]:
            return empty
        try:
            row = self.db.execute(
                f"""WITH owned AS (
                        SELECT projection.state_class,
                               {_OWNER_USER_SQL} AS owner_user_id
                        FROM followup_work_item_projection projection
                    )
                    SELECT
                        SUM(CASE WHEN state_class<>'TERMINAL'
                                  AND owner_user_id=? THEN 1 ELSE 0 END) AS mine,
                        SUM(CASE WHEN state_class<>'TERMINAL'
                                  AND owner_user_id IS NULL THEN 1 ELSE 0 END) AS unassigned,
                        SUM(CASE WHEN state_class<>'TERMINAL' THEN 1 ELSE 0 END) AS active,
                        SUM(CASE WHEN state_class='TERMINAL' THEN 1 ELSE 0 END) AS completed
                    FROM owned""",
                (int(actor_user_id),),
            ).fetchone()
        except sqlite3.Error:
            return empty
        active = int(row["active"] or 0)
        return {
            "mine": int(row["mine"] or 0),
            "unassigned": int(row["unassigned"] or 0),
            "all": active,
            "completed": int(row["completed"] or 0),
            "manager": active,
        }

    @staticmethod
    def _view_clause(
        view: str,
        *,
        actor_user_id: int,
    ) -> tuple[list[str], list[object]]:
        active = "projection.state_class<>'TERMINAL'"
        if view == "mine":
            return [active, f"{_OWNER_USER_SQL}=?"], [int(actor_user_id)]
        if view == "unassigned":
            return [active, f"{_OWNER_USER_SQL} IS NULL"], []
        if view in {"all", "manager"}:
            return [active], []
        return ["projection.state_class='TERMINAL'"], []

    def list_items(
        self,
        *,
        actor_user_id: int,
        allow_manager_view: bool,
        work_view: object = "mine",
        page: object = 1,
        per_page: object = 20,
        query: str | None = None,
        state_class: str | None = None,
        role: str | None = None,
        sla_state: str | None = None,
        exclude_episode_id: str | None = None,
        now: datetime | None = None,
        stale_after_minutes: int = 120,
    ) -> dict:
        page_number = self.base._normalize_page(
            page, default=1, maximum=1_000_000
        )
        page_size = self.base._normalize_page(per_page, default=20, maximum=50)
        current = now or iran_now().replace(microsecond=0)
        view = self.normalize_view(work_view, allow_manager=allow_manager_view)
        filters = self.base._normalize_filters(
            query=query,
            state_class=state_class,
            role=role,
            sla_state=sla_state,
        )
        # The view owns terminal/open separation. Conflicting raw status filters are
        # discarded so a tab can never silently render an impossible combination.
        if view == "completed":
            filters["state"] = ""
        elif filters["state"] == "TERMINAL":
            filters["state"] = ""
        filters["view"] = view

        readiness = self.base.readiness()
        if not readiness["ready"]:
            model = self.base._empty_model(
                page_size=page_size,
                filters=filters,
                readiness=readiness,
            )
            model["view"] = view
            return model

        clauses, params = self._view_clause(
            view,
            actor_user_id=int(actor_user_id),
        )
        if filters["state"]:
            clauses.append("projection.state_class=?")
            params.append(filters["state"])
        if filters["role"]:
            clauses.append(f"{_OWNER_ROLE_SQL}=?")
            params.append(filters["role"])
        if filters["sla"]:
            current_text = current.isoformat(sep=" ", timespec="seconds")
            clauses.append(f"({_EFFECTIVE_SLA_SQL})=?")
            params.extend((current_text, current_text, filters["sla"]))
        if filters["q"]:
            like = f"%{filters['q']}%"
            clauses.append(
                "(patient.full_name LIKE ? OR patient.national_id LIKE ? "
                "OR patient.phone_number LIKE ? OR projection.reason_label LIKE ? "
                "OR projection.why_created LIKE ?)"
            )
            params.extend((like, like, like, like, like))
        if exclude_episode_id:
            clauses.append("projection.episode_id<>?")
            params.append(str(exclude_episode_id))

        where = " WHERE " + " AND ".join(clauses)
        base = """ FROM followup_work_item_projection projection
                   JOIN patient_links patient
                     ON patient.id=projection.patient_link_id"""
        try:
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
            links = self.base._links_for(episode_ids)
        except sqlite3.Error:
            failed = _readiness_payload("PROJECTION_READ_FAILED")
            model = self.base._empty_model(
                page_size=page_size,
                filters=filters,
                readiness=failed,
            )
            model["view"] = view
            return model

        items = [
            self.base._decorate(
                row,
                sources=links.get(str(row["episode_id"]), []),
                now=current,
                stale_after_minutes=stale_after_minutes,
            )
            for row in rows
        ]
        return {
            "projection_ready": True,
            "readiness": readiness,
            "read_error_code": None,
            "read_error_label": "",
            "read_error_help": "",
            "items": items,
            "page": page_number,
            "per_page": page_size,
            "total": total,
            "pages": pages,
            "has_previous": page_number > 1,
            "has_next": bool(pages and page_number < pages),
            "filters": filters,
            "view": view,
        }

    def next_item(self, **kwargs) -> dict | None:
        model = self.list_items(page=1, per_page=1, **kwargs)
        if not model.get("projection_ready") or not model["items"]:
            return None
        return model["items"][0]


__all__ = ["WORK_VIEW_LABELS", "WorkCenterReadModelService"]

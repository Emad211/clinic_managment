"""Read projections for longitudinal clinical flag history."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now
from src.domain.clinical_engine.flag_history import project_flag_events

from .clinical_flag_common import text_time


class ClinicalFlagProjectionRepositoryMixin:
    def project_flags(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime | str | None = None,
        knowledge_at: datetime | str | None = None,
        active_only: bool = True,
    ) -> dict[str, dict[str, Any]]:
        db = get_db()
        if not db.execute(
            "SELECT 1 FROM patient_links WHERE id=?",
            (patient_link_id,),
        ).fetchone():
            raise LookupError("patient not found")
        effective_cutoff = as_of_at or iran_now()
        knowledge_cutoff = knowledge_at or effective_cutoff
        catalog_sql = "SELECT * FROM flag_catalog"
        if active_only:
            catalog_sql += " WHERE is_active=1"
        catalog_sql += " ORDER BY display_order, id"
        catalog = [dict(row) for row in db.execute(catalog_sql).fetchall()]
        events = [
            dict(row)
            for row in db.execute(
                """SELECT * FROM clinical_flag_events
                    WHERE patient_link_id=?
                      AND datetime(effective_at)<=datetime(?)
                      AND datetime(recorded_at)<=datetime(?)
                    ORDER BY recorded_at, id""",
                (
                    patient_link_id,
                    text_time(effective_cutoff),
                    text_time(knowledge_cutoff),
                ),
            ).fetchall()
        ]
        return project_flag_events(
            events,
            catalog,
            as_of_at=effective_cutoff,
            knowledge_at=knowledge_cutoff,
        )

    def get_flag_states(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime | str | None = None,
    ) -> dict[str, dict[str, Any]]:
        return self.project_flags(
            patient_link_id,
            as_of_at=as_of_at,
        )

    def get_flags(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Compatibility projection: return only explicit PRESENT values."""
        states = self.project_flags(
            patient_link_id,
            as_of_at=as_of_at,
        )
        return {
            key: item["value"]
            for key, item in states.items()
            if item["state"] == "PRESENT"
        }

    def flag_events(
        self,
        patient_link_id: int,
        flag_key: str | None = None,
    ) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM clinical_flag_events WHERE patient_link_id=?"
        params: list[Any] = [patient_link_id]
        if flag_key is not None:
            sql += " AND flag_key=?"
            params.append(flag_key)
        sql += " ORDER BY recorded_at, id"
        return [dict(row) for row in db.execute(sql, params).fetchall()]

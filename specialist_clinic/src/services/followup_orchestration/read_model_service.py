"""Bounded, read-only FO-3 projection queries for the Unified Worklist.

The service never installs schema, rebuilds projection rows, or mutates a source of
truth. Before issuing product queries it verifies the minimum read contract. Known
SQLite/schema drift is returned as a PHI-free controlled state instead of escaping as
an HTTP 500. Unknown programming errors are deliberately not swallowed.
"""
from __future__ import annotations

from datetime import datetime
import math
import sqlite3

from src.adapters.sqlite.followup_projection_schema import (
    PROJECTION_REQUIRED_COLUMNS,
)


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
SLA_LABELS = {
    "FUTURE": "در مهلت آینده",
    "DUE_TODAY": "موعد امروز",
    "OVERDUE": "موعدگذشته",
    "DUE_UNKNOWN": "موعد نامشخص",
    "WAITING": "در انتظار رویداد بعدی",
    "BLOCKED": "مسدود",
    "TERMINAL": "پایان‌یافته",
}
READINESS_COPY = {
    "READY": {
        "label": "نمای یکپارچه آماده است",
        "help": "",
    },
    "PROJECTION_NOT_BUILT": {
        "label": "اطلاعات نمای یکپارچه هنوز آماده نشده است",
        "help": "اطلاعات خواندنی این نما را طبق راهنمای راه‌اندازی بازسازی کنید. تا آن زمان از ورک‌لیست فعلی استفاده کنید.",
    },
    "PROJECTION_EMPTY_WITH_SOURCE_DATA": {
        "label": "دادهٔ پیگیری وجود دارد اما نمای یکپارچه هنوز آماده نشده است",
        "help": "پس از ساخت دادهٔ نمونه، seed_demo_data.py را دوباره اجرا کنید؛ یا دستور prepare_seeded_followup_view.py را اجرا کنید. هیچ داده‌ای در این صفحه حدس زده یا خودکار بازسازی نمی‌شود.",
    },
    "PROJECTION_SCHEMA_INCOMPATIBLE": {
        "label": "اطلاعات ذخیره‌شدهٔ این نما با نسخهٔ جدید سازگار نیست",
        "help": "برنامه را یک‌بار با نسخهٔ جدید اجرا کنید و سپس اطلاعات نمای یکپارچه را طبق راهنما دوباره بسازید.",
    },
    "PATIENT_IDENTITY_SCHEMA_INCOMPATIBLE": {
        "label": "ساختار هویت بیمار برای این نما کامل نیست",
        "help": "ساختار دیتابیس محلی باید با نسخهٔ فعلی هماهنگ شود. ورک‌لیست قبلی همچنان مسیر امن اقدام است.",
    },
    "EPISODE_LINK_SCHEMA_INCOMPATIBLE": {
        "label": "ساختار ارتباط مسیرهای پیگیری کامل نیست",
        "help": "هیچ رابطه‌ای حدس زده نشد. به‌روزرسانی ساختار دیتابیس را اجرا و اطلاعات نمای یکپارچه را دوباره بسازید.",
    },
    "PROJECTION_READ_FAILED": {
        "label": "خواندن نمای یکپارچه موقتاً ممکن نشد",
        "help": "از ورک‌لیست فعلی استفاده کنید و پس از راه‌اندازی مجدد دوباره تلاش کنید.",
    },
}
_ALLOWED_STATES = frozenset(STATE_LABELS)
_ALLOWED_ROLES = frozenset(ROLE_LABELS)
_ALLOWED_SLA = frozenset(SLA_LABELS)
_PATIENT_REQUIRED_COLUMNS = frozenset({"id", "full_name", "national_id", "phone_number"})
_LINK_REQUIRED_COLUMNS = frozenset(
    {"id", "episode_id", "source_type", "source_id", "relation_type", "linked_at"}
)


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


def _readiness_payload(code: str) -> dict:
    copy = READINESS_COPY[code]
    return {
        "ready": code == "READY",
        "code": code,
        "label": copy["label"],
        "help": copy["help"],
    }


class FollowupUnifiedReadModelService:
    """Serve deterministic list/detail models without N+1 or request-time writes."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def _columns(self, name: str) -> frozenset[str]:
        try:
            return frozenset(
                str(row[1]) for row in self.db.execute(f"PRAGMA table_info({name})")
            )
        except sqlite3.Error:
            return frozenset()

    def _count_rows(self, name: str) -> int:
        try:
            return int(self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        except sqlite3.Error:
            return 0

    def readiness(self) -> dict:
        """Return a PHI-free preflight result for the read-only surface."""
        projection = self._columns("followup_work_item_projection")
        if not projection:
            return _readiness_payload("PROJECTION_NOT_BUILT")
        if not PROJECTION_REQUIRED_COLUMNS <= projection:
            return _readiness_payload("PROJECTION_SCHEMA_INCOMPATIBLE")

        patient = self._columns("patient_links")
        if not _PATIENT_REQUIRED_COLUMNS <= patient:
            return _readiness_payload("PATIENT_IDENTITY_SCHEMA_INCOMPATIBLE")

        links = self._columns("followup_episode_links")
        if not _LINK_REQUIRED_COLUMNS <= links:
            return _readiness_payload("EPISODE_LINK_SCHEMA_INCOMPATIBLE")

        if self._count_rows("followup_work_item_projection") == 0:
            operational_sources = sum(
                self._count_rows(table)
                for table in (
                    "followup_tasks",
                    "care_plan_commitments",
                    "engagement_approvals",
                )
            )
            if operational_sources or self._count_rows("followup_episodes"):
                return _readiness_payload("PROJECTION_EMPTY_WITH_SOURCE_DATA")
        return _readiness_payload("READY")

    @staticmethod
    def _normalize_page(value: object, *, default: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return min(max(parsed, 1), maximum)

    @staticmethod
    def _normalize_filters(
        *, query: str | None, state_class: str | None,
        role: str | None, sla_state: str | None,
    ) -> dict:
        state = str(state_class or "").strip().upper()
        role_value = str(role or "").strip().upper()
        sla = str(sla_state or "").strip().upper()
        return {
            "q": str(query or "").strip()[:120],
            "state": state if state in _ALLOWED_STATES else "",
            "role": role_value if role_value in _ALLOWED_ROLES else "",
            "sla": sla if sla in _ALLOWED_SLA else "",
        }

    @staticmethod
    def _empty_model(*, page_size: int, filters: dict, readiness: dict) -> dict:
        return {
            "projection_ready": False,
            "readiness": readiness,
            "read_error_code": readiness["code"],
            "read_error_label": readiness["label"],
            "read_error_help": readiness["help"],
            "items": [],
            "page": 1,
            "per_page": page_size,
            "total": 0,
            "pages": 0,
            "has_previous": False,
            "has_next": False,
            "filters": filters,
        }

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
        if not episode_ids:
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
                "patient_name": str(item.get("patient_name") or "بیمار بدون نام"),
                "patient_national_id_masked": _masked_national_id(
                    item.pop("patient_national_id", "")
                ),
                "state_label": STATE_LABELS.get(
                    str(item.get("state_class") or ""), "وضعیت نامشخص"
                ),
                "sla_label": SLA_LABELS.get(
                    str(item.get("sla_state") or ""), "وضعیت موعد نامشخص"
                ),
                "sla_tone": (
                    "danger"
                    if item.get("sla_state") in {"OVERDUE", "BLOCKED"}
                    else "warn"
                    if item.get("sla_state") in {"DUE_TODAY", "DUE_UNKNOWN"}
                    else "info"
                    if item.get("sla_state") in {"FUTURE", "WAITING"}
                    else "muted"
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
                "source_types": list(
                    dict.fromkeys(source["source_type"] for source in sources)
                ),
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
        filters = self._normalize_filters(
            query=query,
            state_class=state_class,
            role=role,
            sla_state=sla_state,
        )
        readiness = self.readiness()
        if not readiness["ready"]:
            return self._empty_model(
                page_size=page_size,
                filters=filters,
                readiness=readiness,
            )

        clauses: list[str] = []
        params: list[object] = []
        if filters["state"]:
            clauses.append("projection.state_class=?")
            params.append(filters["state"])
        if filters["role"]:
            clauses.append(
                "COALESCE((SELECT json_extract(owner_event.payload_json, '$.owner_role') "
                "FROM followup_episode_events owner_event "
                "WHERE owner_event.episode_id=projection.episode_id "
                "AND owner_event.event_type IN ('ROUTED','CLAIMED','ASSIGNED') "
                "ORDER BY owner_event.id DESC LIMIT 1), "
                "projection.owner_role_proposal)=?"
            )
            params.append(filters["role"])
        if filters["sla"]:
            clauses.append("projection.sla_state=?")
            params.append(filters["sla"])
        if filters["q"]:
            like = f"%{filters['q']}%"
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
            links = self._links_for(episode_ids)
        except sqlite3.Error:
            failed = _readiness_payload("PROJECTION_READ_FAILED")
            return self._empty_model(
                page_size=page_size,
                filters=filters,
                readiness=failed,
            )

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
        }

    def get_item_result(
        self,
        episode_id: str,
        *,
        now: datetime | None = None,
        stale_after_minutes: int = 120,
    ) -> dict:
        readiness = self.readiness()
        if not readiness["ready"]:
            return {"readiness": readiness, "item": None}
        try:
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
                return {"readiness": readiness, "item": None}
            links = self._links_for([str(episode_id)])
        except sqlite3.Error:
            return {
                "readiness": _readiness_payload("PROJECTION_READ_FAILED"),
                "item": None,
            }
        return {
            "readiness": readiness,
            "item": self._decorate(
                row,
                sources=links.get(str(episode_id), []),
                now=now or datetime.now().replace(microsecond=0),
                stale_after_minutes=stale_after_minutes,
            ),
        }

    def get_item(
        self,
        episode_id: str,
        *,
        now: datetime | None = None,
        stale_after_minutes: int = 120,
    ) -> dict | None:
        return self.get_item_result(
            episode_id,
            now=now,
            stale_after_minutes=stale_after_minutes,
        )["item"]


__all__ = [
    "FollowupUnifiedReadModelService",
    "READINESS_COPY",
    "ROLE_LABELS",
    "SLA_LABELS",
    "STATE_LABELS",
]

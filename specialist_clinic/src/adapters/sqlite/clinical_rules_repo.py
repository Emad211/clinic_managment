"""Repository for descriptive observation-catalog metadata.

The historical table name ``clinical_indicators`` and compatibility class name are
retained for route compatibility. Startup migration rebuilds copied databases onto
the same descriptive-only schema as fresh installs. This repository never projects
threshold, target or risk-weight fields.  Actionable clinical logic belongs to the
governed Clinical Engine v2 rule packages.
"""
from __future__ import annotations

from flask import g

from src.adapters.sqlite.core import get_db


_DESCRIPTIVE_FIELDS = (
    "id",
    "key",
    "label",
    "unit",
    "category",
    "conditions",
    "is_vital",
    "display_order",
    "is_active",
    "notes",
)
EDITABLE_FIELDS = (
    "label",
    "unit",
    "category",
    "conditions",
    "is_vital",
    "display_order",
    "is_active",
)

CATEGORY_LABELS = {
    "glycemic": "قند خون",
    "bp": "فشار خون",
    "lipid": "چربی خون",
    "kidney": "کلیه",
    "anthro": "تن‌سنجی",
    "other": "سایر",
}

_FALLBACK = {
    "hba1c": {
        "label": "HbA1c",
        "unit": "%",
        "category": "glycemic",
        "conditions": "diabetes",
        "is_vital": 1,
        "display_order": 10,
        "is_active": 1,
    },
    "fbs": {
        "label": "قند ناشتا (FBS)",
        "unit": "mg/dL",
        "category": "glycemic",
        "conditions": "diabetes",
        "is_vital": 1,
        "display_order": 20,
        "is_active": 1,
    },
    "bp_systolic": {
        "label": "فشار سیستول",
        "unit": "mmHg",
        "category": "bp",
        "conditions": "diabetes,hypertension",
        "is_vital": 1,
        "display_order": 30,
        "is_active": 1,
    },
    "bp_diastolic": {
        "label": "فشار دیاستول",
        "unit": "mmHg",
        "category": "bp",
        "conditions": "diabetes,hypertension",
        "is_vital": 1,
        "display_order": 40,
        "is_active": 1,
    },
}


def _project(row: dict) -> dict:
    return {field: row.get(field) for field in _DESCRIPTIVE_FIELDS}


class ClinicalRulesRepository:
    """Compatibility facade for the descriptive observation catalog."""

    def all_indicators(self, active_only: bool = True) -> list[dict]:
        cache_key = f"_indicators_{active_only}"
        cached = getattr(g, cache_key, None) if g else None
        if cached is not None:
            return cached
        db = get_db()
        sql = "SELECT * FROM clinical_indicators"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, id"
        rows = [_project(dict(row)) for row in db.execute(sql).fetchall()]
        if not rows and active_only:
            rows = [
                _project({"id": None, "key": key, **value, "notes": None})
                for key, value in _FALLBACK.items()
            ]
        try:
            setattr(g, cache_key, rows)
        except Exception:
            pass
        return rows

    def as_map(self, active_only: bool = True) -> dict[str, dict]:
        return {
            indicator["key"]: indicator
            for indicator in self.all_indicators(active_only)
        }

    def get(self, key: str) -> dict | None:
        return self.as_map(active_only=False).get(key) or self.as_map().get(key)

    def for_conditions(self, codes: list[str]) -> list[dict]:
        codeset = {code for code in (codes or []) if code}
        result = []
        for indicator in self.all_indicators():
            conditions = (indicator.get("conditions") or "all").strip()
            if conditions == "all":
                result.append(indicator)
            elif codeset & {
                code.strip() for code in conditions.split(",") if code.strip()
            }:
                result.append(indicator)
        return result

    def update(self, indicator_id: int, fields: dict) -> None:
        sets, params = [], []
        for field in EDITABLE_FIELDS:
            if field in fields:
                sets.append(f"{field}=?")
                params.append(fields[field])
        if not sets:
            return
        params.append(indicator_id)
        db = get_db()
        db.execute(
            f"UPDATE clinical_indicators SET {', '.join(sets)} WHERE id=?",
            params,
        )
        db.commit()
        self._clear_cache()

    def create(self, fields: dict) -> int:
        key = str(fields.get("key") or "").strip()
        if not key:
            raise ValueError("indicator key is required")
        columns = ["key"] + [
            field for field in EDITABLE_FIELDS if field in fields
        ]
        values = [key] + [fields[field] for field in columns[1:]]
        db = get_db()
        cursor = db.execute(
            "INSERT OR IGNORE INTO clinical_indicators "
            f"({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
        db.commit()
        self._clear_cache()
        return int(cursor.lastrowid or 0)

    @staticmethod
    def dosage_guidance(_condition_codes: list[str]) -> list[dict]:
        """Legacy v1 titration text is retired and cannot reach patient UI."""
        return []

    @staticmethod
    def _clear_cache() -> None:
        for key in ("_indicators_True", "_indicators_False"):
            if g and hasattr(g, key):
                try:
                    delattr(g, key)
                except Exception:
                    pass

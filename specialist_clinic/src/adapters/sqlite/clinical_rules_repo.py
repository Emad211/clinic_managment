"""Repository for descriptive clinical indicators.

``clinical_indicators`` supplies chart labels, display targets and descriptive risk
stratification. It is not a clinical decision-rule runtime. The historical class name
is retained temporarily to avoid a broad import rename while Clinical Engine v1 is
being removed.
"""
from flask import g

from src.adapters.sqlite.core import get_db


# Fallback display defaults used only if the indicator table is empty. These values
# support descriptive UI rendering; they cannot produce a v1 recommendation.
_FALLBACK = {
    "hba1c": {
        "label": "HbA1c",
        "unit": "%",
        "category": "glycemic",
        "direction": "high",
        "warn": 7.0,
        "danger": 8.0,
        "target": 7.0,
        "conditions": "diabetes",
        "risk_weight": 3,
    },
    "fbs": {
        "label": "قند ناشتا (FBS)",
        "unit": "mg/dL",
        "category": "glycemic",
        "direction": "high",
        "warn": 130,
        "danger": 180,
        "target": 130,
        "conditions": "diabetes",
        "risk_weight": 2,
    },
    "bp_systolic": {
        "label": "فشار سیستول",
        "unit": "mmHg",
        "category": "bp",
        "direction": "high",
        "warn": 130,
        "danger": 140,
        "target": 130,
        "conditions": "diabetes,hypertension",
        "risk_weight": 2,
    },
    "bp_diastolic": {
        "label": "فشار دیاستول",
        "unit": "mmHg",
        "category": "bp",
        "direction": "high",
        "warn": 80,
        "danger": 90,
        "target": 80,
        "conditions": "diabetes,hypertension",
        "risk_weight": 1,
    },
}

EDITABLE_FIELDS = (
    "label",
    "unit",
    "category",
    "direction",
    "warn",
    "danger",
    "target",
    "goal_low",
    "goal_high",
    "conditions",
    "risk_weight",
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


class ClinicalRulesRepository:
    """Compatibility name for the descriptive indicator repository."""

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
        rows = [dict(row) for row in db.execute(sql).fetchall()]
        if not rows and active_only:
            rows = [dict(key=key, **value) for key, value in _FALLBACK.items()]
        try:
            setattr(g, cache_key, rows)
        except Exception:
            pass
        return rows

    def as_map(self, active_only: bool = True) -> dict:
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
                code.strip()
                for code in conditions.split(",")
                if code.strip()
            }:
                result.append(indicator)
        return result

    def update(self, indicator_id: int, fields: dict):
        sets = []
        params = []
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
        db = get_db()
        columns = ["key"] + [
            field for field in EDITABLE_FIELDS if field in fields
        ]
        values = [fields.get("key")] + [
            fields[field] for field in EDITABLE_FIELDS if field in fields
        ]
        placeholders = ", ".join("?" for _ in columns)
        cursor = db.execute(
            "INSERT OR IGNORE INTO clinical_indicators "
            f"({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        db.commit()
        self._clear_cache()
        return cursor.lastrowid

    @staticmethod
    def dosage_guidance(_condition_codes: list[str]) -> list[dict]:
        """Legacy v1 titration text is retired and can never reach the patient UI."""
        return []

    @staticmethod
    def _clear_cache():
        for key in ("_indicators_True", "_indicators_False"):
            if g and hasattr(g, key):
                try:
                    delattr(g, key)
                except Exception:
                    pass

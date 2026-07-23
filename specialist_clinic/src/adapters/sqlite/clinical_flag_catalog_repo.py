"""Canonical clinical flag catalog reads and semantic writes."""
from __future__ import annotations

from typing import Any

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine.flag_history import (
    canonical_options_json,
    flag_definition_hash,
    normalize_flag_type,
)

from .clinical_flag_common import CATEGORY_LABELS, CATEGORY_ORDER, option_list


class ClinicalFlagCatalogRepositoryMixin:
    def catalog(self, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM flag_catalog"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, id"
        rows = [dict(row) for row in db.execute(sql).fetchall()]
        for row in rows:
            row["option_list"] = option_list(row)
            row["category_label"] = CATEGORY_LABELS.get(
                row["category"], row["category"]
            )
        return rows

    def catalog_grouped(self) -> list[dict]:
        groups: dict[str, dict] = {}
        for flag in self.catalog():
            group = groups.setdefault(
                flag["category"],
                {
                    "category": flag["category"],
                    "label": CATEGORY_LABELS.get(
                        flag["category"], flag["category"]
                    ),
                    "flags": [],
                },
            )
            group["flags"].append(flag)
        return [groups[key] for key in CATEGORY_ORDER if key in groups] + [
            group
            for key, group in groups.items()
            if key not in CATEGORY_ORDER
        ]

    def catalog_by_record_section(self) -> dict[str, list[dict]]:
        sections: dict[str, list[dict]] = {}
        for flag in self.catalog():
            section = flag.get("record_section") or "general"
            sections.setdefault(section, []).append(flag)
        return sections

    def create_catalog_definition(
        self,
        *,
        flag_key: str,
        label: str,
        flag_type: str,
        options: Any = None,
        category: str = "other",
        display_order: int = 100,
        record_section: str | None = None,
        notes: str | None = None,
    ) -> int:
        key = str(flag_key or "").strip().lower()
        if not key:
            raise ValueError("flag_key is required")
        normalized_type = normalize_flag_type(flag_type)
        options_json = canonical_options_json(
            options,
            flag_type=normalized_type,
        )
        definition_version = 1
        definition_hash = flag_definition_hash(
            key,
            normalized_type,
            options_json,
            1,
            definition_version,
        )
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO flag_catalog
                   (flag_key, label, flag_type, options, options_json,
                    definition_hash, definition_version, category,
                    display_order, is_active, record_section, notes)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    key,
                    str(label or key).strip(),
                    normalized_type,
                    options_json,
                    definition_hash,
                    definition_version,
                    str(category or "other").strip() or "other",
                    int(display_order),
                    record_section,
                    notes,
                ),
            )
        return int(cursor.lastrowid)

    def update_catalog_semantics(
        self,
        flag_key: str,
        *,
        flag_type: str,
        options: Any = None,
        is_active: bool = True,
    ) -> dict:
        """Create a new semantic definition identity in the catalog row.

        Presentation-only fields are edited elsewhere and retain both version and
        hash.  A semantic update increments ``definition_version`` even when the
        requested values happen to match an older historical definition, so prior
        patient answers can never become valid again merely by toggling a catalog
        definition off and on.
        """
        key = str(flag_key or "").strip().lower()
        normalized_type = normalize_flag_type(flag_type)
        options_json = canonical_options_json(
            options,
            flag_type=normalized_type,
        )
        active = int(bool(is_active))
        db = get_db()
        current = db.execute(
            "SELECT * FROM flag_catalog WHERE flag_key=?",
            (key,),
        ).fetchone()
        if not current:
            raise LookupError("clinical flag definition not found")
        current_version = int(current["definition_version"] or 1)
        if (
            str(current["flag_type"]) == normalized_type
            and str(current["options_json"]) == options_json
            and int(current["is_active"] or 0) == active
        ):
            return dict(current)

        definition_version = current_version + 1
        definition_hash = flag_definition_hash(
            key,
            normalized_type,
            options_json,
            active,
            definition_version,
        )
        with db:
            cursor = db.execute(
                """UPDATE flag_catalog
                      SET flag_type=?, options_json=?, definition_hash=?,
                          definition_version=?, is_active=?
                    WHERE flag_key=? AND definition_version=?""",
                (
                    normalized_type,
                    options_json,
                    definition_hash,
                    definition_version,
                    active,
                    key,
                    current_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "clinical flag definition changed concurrently"
                )
        row = db.execute(
            "SELECT * FROM flag_catalog WHERE flag_key=?",
            (key,),
        ).fetchone()
        return dict(row)

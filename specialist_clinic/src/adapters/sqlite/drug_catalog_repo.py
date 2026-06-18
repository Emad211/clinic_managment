"""Repository for the drug catalog (generic name + pharmacologic class + doses).

All SQL for `drug_catalog` lives here (one repo per aggregate). Drives the
medication add-form: pick a class → search the generic name → standard doses.
Manager-editable; defaults seeded by `drug_catalog_seed.seed_drug_catalog`.

`standard_doses` is stored as a JSON-array string; rows are returned with an
extra parsed `doses` list for convenience.
"""
import json

from src.adapters.sqlite.core import get_db


def _row(r) -> dict:
    """dict-ify a row and parse its JSON `standard_doses` into a `doses` list."""
    d = dict(r)
    raw = d.get("standard_doses")
    try:
        d["doses"] = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        d["doses"] = []
    return d


class DrugCatalogRepository:

    def all(self, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM drug_catalog"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY drug_class_key, generic_fa"
        return [_row(r) for r in db.execute(sql).fetchall()]

    def get(self, drug_id: int) -> dict | None:
        db = get_db()
        row = db.execute("SELECT * FROM drug_catalog WHERE id=?", (drug_id,)).fetchone()
        return _row(row) if row else None

    def for_class(self, drug_class_key: str, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM drug_catalog WHERE drug_class_key=?"
        params = [drug_class_key]
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY generic_fa"
        return [_row(r) for r in db.execute(sql, params).fetchall()]

    def search(self, q: str, drug_class_key: str = None,
               active_only: bool = True) -> list[dict]:
        """LIKE search on `generic_fa`, optionally filtered to a class."""
        db = get_db()
        sql = "SELECT * FROM drug_catalog WHERE 1=1"
        params: list = []
        if active_only:
            sql += " AND is_active=1"
        if q:
            sql += " AND generic_fa LIKE ?"
            params.append(f"%{q.strip()}%")
        if drug_class_key:
            sql += " AND drug_class_key=?"
            params.append(drug_class_key)
        sql += " ORDER BY drug_class_key, generic_fa"
        return [_row(r) for r in db.execute(sql, params).fetchall()]

    # ---- manager editing ----
    def add(self, *, generic_fa: str, drug_class_key: str,
            standard_doses=None, is_active: int = 1) -> int:
        """Insert a catalog drug. `standard_doses` may be a list or a JSON string."""
        db = get_db()
        doses_json = self._doses_json(standard_doses)
        cur = db.execute(
            """INSERT INTO drug_catalog (generic_fa, drug_class_key, standard_doses, is_active)
               VALUES (?, ?, ?, ?)""",
            (generic_fa, drug_class_key, doses_json, is_active),
        )
        db.commit()
        return cur.lastrowid

    def update(self, drug_id: int, **fields) -> None:
        """Patch selected columns of an existing catalog drug."""
        allowed = {"generic_fa", "drug_class_key", "standard_doses", "is_active"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "standard_doses" in sets:
            sets["standard_doses"] = self._doses_json(sets["standard_doses"])
        if not sets:
            return
        db = get_db()
        assignments = ", ".join(f"{k}=?" for k in sets)
        db.execute(
            f"UPDATE drug_catalog SET {assignments} WHERE id=?",
            (*sets.values(), drug_id),
        )
        db.commit()

    def set_active(self, drug_id: int, is_active: int) -> None:
        db = get_db()
        db.execute("UPDATE drug_catalog SET is_active=? WHERE id=?",
                   (1 if is_active else 0, drug_id))
        db.commit()

    @staticmethod
    def _doses_json(standard_doses) -> str | None:
        if standard_doses is None:
            return None
        if isinstance(standard_doses, str):
            return standard_doses  # assume already a JSON string
        return json.dumps(list(standard_doses), ensure_ascii=False)

"""Repository for the lab-test catalog and per-disease test mappings.

All SQL for `lab_test_catalog` and `condition_lab_tests` lives here (one repo per
aggregate). The catalog supplies the lab dropdown (name/unit/reference range) and
the per-disease frequent-test chips. Manager-editable; defaults seeded by
`lab_catalog_seed.seed_lab_catalog`.
"""
from src.adapters.sqlite.core import get_db


class LabCatalogRepository:

    # ---- catalog ----
    def all(self, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM lab_test_catalog"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, test_key"
        return [dict(r) for r in db.execute(sql).fetchall()]

    def get(self, test_key: str) -> dict | None:
        db = get_db()
        row = db.execute(
            "SELECT * FROM lab_test_catalog WHERE test_key=?", (test_key,)
        ).fetchone()
        return dict(row) if row else None

    def grouped_by_category(self, active_only: bool = True) -> list[dict]:
        """Catalog bucketed by `category` (preserving display order)."""
        groups: dict[str, dict] = {}
        for t in self.all(active_only=active_only):
            g = groups.setdefault(t["category"], {"category": t["category"], "tests": []})
            g["tests"].append(t)
        return list(groups.values())

    # ---- per-disease mapping ----
    def for_conditions(self, condition_codes: list) -> list[dict]:
        """Frequent lab tests for the given disease condition codes.

        Joins `condition_lab_tests` → `lab_test_catalog`, returns each catalog row
        once (de-duped across diseases), ordered by the mapping's display_order.
        """
        codes = [c for c in (condition_codes or []) if c]
        if not codes:
            return []
        db = get_db()
        placeholders = ",".join("?" for _ in codes)
        rows = db.execute(
            f"""SELECT l.*, MIN(c.display_order) AS map_order
                FROM condition_lab_tests c
                JOIN lab_test_catalog l ON l.test_key = c.lab_test_key
                WHERE c.condition_code IN ({placeholders}) AND l.is_active=1
                GROUP BY l.test_key
                ORDER BY map_order, l.display_order, l.test_key""",
            tuple(codes),
        ).fetchall()
        return [dict(r) for r in rows]

    def condition_test_keys(self, condition_code: str) -> list[str]:
        """Ordered lab_test_key list mapped to a single disease."""
        db = get_db()
        rows = db.execute(
            """SELECT lab_test_key FROM condition_lab_tests
               WHERE condition_code=? ORDER BY display_order""",
            (condition_code,),
        ).fetchall()
        return [r["lab_test_key"] for r in rows]

    # ---- manager editing ----
    def upsert(self, *, test_key: str, name_fa: str, unit: str = None,
               ref_low=None, ref_high=None, category: str = "other",
               display_order: int = 100, is_active: int = 1) -> None:
        """Insert a new catalog test or update an existing one (by test_key)."""
        db = get_db()
        db.execute(
            """INSERT INTO lab_test_catalog
               (test_key, name_fa, unit, ref_low, ref_high, category, display_order, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(test_key) DO UPDATE SET
                 name_fa=excluded.name_fa, unit=excluded.unit,
                 ref_low=excluded.ref_low, ref_high=excluded.ref_high,
                 category=excluded.category, display_order=excluded.display_order,
                 is_active=excluded.is_active""",
            (test_key, name_fa, unit, ref_low, ref_high, category,
             display_order, is_active),
        )
        db.commit()

    def update(self, test_key: str, **fields) -> None:
        """Patch selected columns of an existing catalog row."""
        allowed = {"name_fa", "unit", "ref_low", "ref_high", "category",
                   "display_order", "is_active"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        db = get_db()
        assignments = ", ".join(f"{k}=?" for k in sets)
        db.execute(
            f"UPDATE lab_test_catalog SET {assignments} WHERE test_key=?",
            (*sets.values(), test_key),
        )
        db.commit()

    def set_active(self, test_key: str, is_active: int) -> None:
        db = get_db()
        db.execute("UPDATE lab_test_catalog SET is_active=? WHERE test_key=?",
                   (1 if is_active else 0, test_key))
        db.commit()

    # ---- mapping editing ----
    def set_condition_test(self, condition_code: str, lab_test_key: str,
                           display_order: int = 100) -> None:
        db = get_db()
        db.execute(
            """INSERT OR IGNORE INTO condition_lab_tests
               (condition_code, lab_test_key, display_order) VALUES (?, ?, ?)""",
            (condition_code, lab_test_key, display_order),
        )
        db.commit()

    def remove_condition_test(self, condition_code: str, lab_test_key: str) -> None:
        db = get_db()
        db.execute(
            "DELETE FROM condition_lab_tests WHERE condition_code=? AND lab_test_key=?",
            (condition_code, lab_test_key),
        )
        db.commit()

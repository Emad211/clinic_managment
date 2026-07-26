from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"missing transaction patch anchor: {relative}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Repositories never run DDL inside a caller-owned transaction. Bootstrap/readiness
# installs and verifies the schema before application services begin work.
patch(
    "specialist_clinic/src/adapters/sqlite/specialist_enrollment_repo.py",
    '''from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
''',
    '''from src.adapters.sqlite.core import get_db
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/specialist_enrollment_repo.py",
    '''    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        ensure_specialist_revenue_boundary_storage(db)
        return db
''',
    '''    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/care_journey_repo.py",
    '''from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
''',
    '''from src.adapters.sqlite.core import get_db
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/care_journey_repo.py",
    '''    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        ensure_specialist_revenue_boundary_storage(db)
        return db
''',
    '''    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()
''',
)
patch(
    "specialist_clinic/src/services/care_journey_service.py",
    '''        except (CareJourneyConflict, Exception):
            if owns_transaction:
                db.rollback()
            raise
''',
    '''        except Exception:
            if owns_transaction:
                db.rollback()
            raise
''',
)

path = ROOT / ".github/finalize_a0_transactions.py"
if path.exists():
    path.unlink()

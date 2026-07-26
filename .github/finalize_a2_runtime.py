from pathlib import Path

# One-shot A2 trigger; this file removes itself after applying the runtime patch.
# Diagnostic retry: finalizers run in independent workflow steps.
ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py"
text = PATH.read_text(encoding="utf-8")

import_anchor = '''from src.adapters.sqlite.clinical_care_loop_schema import (
    ensure_clinical_care_loop_storage,
)
'''
import_new = '''from src.adapters.sqlite.clinical_care_loop_schema import (
    ensure_clinical_care_loop_storage,
)
from src.adapters.sqlite.clinical_task_contract_schema import (
    ensure_clinical_task_contract_storage,
)
'''
if import_new not in text:
    if import_anchor not in text:
        raise AssertionError("care-loop contract schema import anchor missing")
    text = text.replace(import_anchor, import_new, 1)

old_db = '''    def _db(self):
        if self._connection is not None:
            return self._connection
        db = get_db()
        ensure_clinical_care_loop_storage(db)
        return db
'''
new_db = '''    def _db(self):
        if self._connection is not None:
            return self._connection
        db = get_db()
        ensure_clinical_care_loop_storage(db)
        ensure_clinical_task_contract_storage(db)
        return db
'''
if new_db not in text:
    if old_db not in text:
        raise AssertionError("care-loop _db anchor missing")
    text = text.replace(old_db, new_db, 1)

PATH.write_text(text, encoding="utf-8")
Path(__file__).unlink()

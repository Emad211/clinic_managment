from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def path(relative: str) -> Path:
    target = ROOT / relative
    if not target.exists():
        raise AssertionError(f"A2 target missing: {relative}")
    return target


def patch(relative: str, old: str, new: str) -> None:
    target = path(relative)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A2 anchor missing in {relative}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Bootstrap/readiness/audit.
patch(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.followup_operations_schema import (
        ensure_followup_operations_storage,
    )
''',
    '''    from src.adapters.sqlite.followup_operations_schema import (
        ensure_followup_operations_storage,
    )
    from src.adapters.sqlite.clinical_task_contract_schema import (
        ensure_clinical_task_contract_storage,
    )
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
patch(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.followup_operations_schema import (
    ensure_followup_operations_storage,
)
''',
    '''from src.adapters.sqlite.followup_operations_schema import (
    ensure_followup_operations_storage,
)
from src.adapters.sqlite.clinical_task_contract_schema import (
    ensure_clinical_task_contract_storage,
)
''',
)
patch(
    "specialist_clinic/src/api/health.py",
    '''        "followup_booking_requests",
''',
    '''        "followup_booking_requests",
        "clinical_task_contracts",
        "clinical_outcome_canonical_links",
''',
)
patch(
    "specialist_clinic/src/api/health.py",
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
patch(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.3-followup-contacts"',
    'SCOPE_VERSION = "1.4-clinical-task-contracts"',
)
patch(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "followup_booking_requests",
    "security_permission_events",
''',
    '''    "followup_booking_requests",
    "clinical_task_contracts",
    "clinical_outcome_canonical_links",
    "security_permission_events",
''',
)

# Compiler semantic gates.
patch(
    "specialist_clinic/src/services/clinical_engine/compiler.py",
    '''        if recommendation.get("may_create_internal_task") and action_type not in _ALLOWED_TASK_ACTIONS:
            diagnostics.append(
                self._error(
                    "AUTOMATIC_TASK_NOT_ALLOWED",
                    "recommendation.may_create_internal_task is only valid for internal follow-up actions",
                    "$.recommendation.may_create_internal_task",
                )
            )
''',
    '''        if recommendation.get("may_create_internal_task") and action_type not in _ALLOWED_TASK_ACTIONS:
            diagnostics.append(
                self._error(
                    "AUTOMATIC_TASK_NOT_ALLOWED",
                    "recommendation.may_create_internal_task is only valid for internal follow-up actions",
                    "$.recommendation.may_create_internal_task",
                )
            )
        if recommendation.get("may_create_internal_task"):
            params = recommendation.get("params") or {}
            if not isinstance(params.get("task_contract"), dict):
                diagnostics.append(
                    self._error(
                        "MISSING_TASK_CONTRACT",
                        "internal tasks require an explicit due/completion contract",
                        "$.recommendation.params.task_contract",
                    )
                )
            due_count = int(params.get("due_in_hours") is not None) + int(
                params.get("due_in_days") is not None
            )
            if due_count != 1:
                diagnostics.append(
                    self._error(
                        "INVALID_TASK_DUE_CONTRACT",
                        "exactly one of due_in_hours or due_in_days is required",
                        "$.recommendation.params",
                    )
                )
''',
)

# Evaluation audit schema preserves params.
evaluation_schema_path = path(
    "specialist_clinic/src/domain/clinical_engine/schemas/evaluation-result.schema.json"
)
evaluation_schema = json.loads(evaluation_schema_path.read_text(encoding="utf-8"))
recommendation = evaluation_schema["properties"]["rule_results"]["items"][
    "properties"
]["recommendations"]["items"]
if "params" not in recommendation["required"]:
    recommendation["required"].append("params")
recommendation["properties"]["params"] = {"type": "object"}
evaluation_schema_path.write_text(
    json.dumps(evaluation_schema, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

# Care-loop contract validation, idempotency and canonical ingestion.
care_path = path("specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py")
care = care_path.read_text(encoding="utf-8")
import_anchor = '''from src.adapters.sqlite.core import get_db
'''
import_block = '''from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.clinical_task_contract_repo import (
    ClinicalTaskContractError,
    ClinicalTaskContractRepository,
)
'''
if import_block not in care:
    if import_anchor not in care:
        raise AssertionError("care-loop import anchor missing")
    care = care.replace(import_anchor, import_block, 1)

start = care.index("    def record_outcome(\n")
end = care.index("    def append_task_event(\n", start)
method = '''    def record_outcome(
        self,
        task_id: int,
        *,
        outcome_type: str,
        actor_username: str,
        actor_user_id: int | None = None,
        fact_key: str | None = None,
        value: Any = None,
        unit: str | None = None,
        verification: str = "CONFIRMED",
        observed_at: datetime | str | None = None,
        source_system: str = "clinician",
        source_record_id: str | None = None,
        note: str | None = None,
        recorded_at: datetime | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise ClinicalCareLoopValidationError("actor_username is required")
        kind = str(outcome_type or "").strip().upper()
        if kind not in {
            "OBSERVATION", "PATIENT_REPORTED", "ENCOUNTER_COMPLETED",
            "PROCEDURE_COMPLETED", "LAB_COMPLETED", "OTHER",
        }:
            raise ClinicalCareLoopValidationError("invalid outcome_type")
        verification = str(verification or "").strip().upper()
        if verification not in {"CONFIRMED", "PROVISIONAL", "UNVERIFIED"}:
            raise ClinicalCareLoopValidationError("invalid outcome verification")
        recorded = _now_text(recorded_at)
        observed = _datetime_text(observed_at) or recorded
        clean_fact_key = _clean(fact_key, limit=200)
        clean_unit = _clean(unit, limit=80)
        clean_source = _clean(source_system, limit=120) or "clinician"
        clean_note = _clean(note)
        stable_identity = {
            "task_id": int(task_id),
            "outcome_type": kind,
            "fact_key": clean_fact_key,
            "value": value,
            "unit": clean_unit,
            "verification": verification,
            "observed_at": observed,
            "source_system": clean_source,
            "actor_username": actor,
            "note": clean_note,
        }
        clean_source_record = _clean(source_record_id, limit=200)
        if not clean_source_record:
            clean_source_record = "task-outcome:" + _canonical_hash(
                stable_identity
            )[:48]
        value_json = (
            None if value is None or value == ""
            else json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        payload = {
            **stable_identity,
            "recorded_at": recorded,
            "source_record_id": clean_source_record,
        }
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            task = dict(self._task(db, task_id))
            head = self._head(db, task_id)
            if not head or str(head["status"]) not in _NON_TERMINAL:
                raise ClinicalCareLoopValidationError(
                    "outcome can only be added to a non-terminal clinical task"
                )
            contracts = ClinicalTaskContractRepository(db)
            contract = contracts.validate_outcome(
                task_id=task_id,
                outcome_type=kind,
                fact_key=clean_fact_key,
                verification=verification,
                value=value,
            )
            prior = db.execute(
                """SELECT * FROM clinical_outcome_events
                   WHERE source_system=? AND source_record_id=?""",
                (clean_source, clean_source_record),
            ).fetchone()
            if prior:
                if int(prior["task_id"]) != int(task_id):
                    raise ClinicalCareLoopValidationError(
                        "outcome idempotency identity belongs to another task"
                    )
                if commit:
                    db.commit()
                result = dict(prior)
                result["canonical_link"] = contracts.canonical_link(
                    int(prior["id"])
                )
                return result
            cursor = db.execute(
                """INSERT INTO clinical_outcome_events
                   (task_id, outcome_type, fact_key, value_json, unit,
                    verification, observed_at, recorded_at, source_system,
                    source_record_id, note, actor_user_id, actor_username,
                    content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(task_id), kind, clean_fact_key, value_json, clean_unit,
                    verification, observed, recorded, clean_source,
                    clean_source_record, clean_note, actor_user_id, actor,
                    _canonical_hash(payload),
                ),
            )
            outcome_id = int(cursor.lastrowid)
            canonical_link = contracts.ingest_if_applicable(
                task_id=int(task_id),
                outcome_event_id=outcome_id,
                patient_link_id=int(task["patient_link_id"]),
                fact_key=clean_fact_key,
                value=value,
                unit=clean_unit,
                observed_at=observed,
                actor_username=actor,
                note=clean_note,
                contract=contract,
            )
            row = db.execute(
                "SELECT * FROM clinical_outcome_events WHERE id=?",
                (outcome_id,),
            ).fetchone()
            if commit:
                db.commit()
            result = dict(row)
            result["canonical_link"] = canonical_link
            return result
        except (ClinicalTaskContractError, Exception):
            if commit:
                db.rollback()
            raise

'''
care = care[:start] + method + care[end:]
# Fix the remaining append_task_event transaction boundary.
append_start = care.index("    def append_task_event(\n")
append_text = care[append_start:]
append_text = append_text.replace(
    '        db.execute("BEGIN IMMEDIATE")\n        try:\n',
    '        if commit:\n            db.execute("BEGIN IMMEDIATE")\n        try:\n',
    1,
)
append_text = append_text.replace(
    '''            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise
''',
    '''            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise
''',
    1,
)
care = care[:append_start] + append_text
# Current task exposes immutable contract and canonical links.
needle = '''        task["latest_outcome_event_id"] = (
            int(outcomes[0]["id"]) if outcomes else None
        )
        return task
'''
replacement = '''        task["latest_outcome_event_id"] = (
            int(outcomes[0]["id"]) if outcomes else None
        )
        task["task_contract"] = ClinicalTaskContractRepository(db).get(task_id)
        links = db.execute(
            """SELECT * FROM clinical_outcome_canonical_links
               WHERE task_id=? ORDER BY id DESC""",
            (task_id,),
        ).fetchall()
        task["canonical_links"] = [dict(row) for row in links]
        return task
'''
if replacement not in care:
    if needle not in care:
        raise AssertionError("current_task contract anchor missing")
    care = care.replace(needle, replacement, 1)
care_path.write_text(care, encoding="utf-8")

# Follow-up projection exposes contract to UI.
projection_path = path(
    "specialist_clinic/src/services/followup_projection_service.py"
)
projection = projection_path.read_text(encoding="utf-8")
projection_import = '''from src.adapters.sqlite.followups_repo import FollowupRepository
'''
projection_import_new = '''from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.clinical_task_contract_repo import (
    ClinicalTaskContractRepository,
)
'''
if projection_import_new not in projection:
    projection = projection.replace(projection_import, projection_import_new, 1)
augment_old = '''        for row in normalized:
            row.update(
                summaries.get(
'''
augment_new = '''        contracts = ClinicalTaskContractRepository()
        for row in normalized:
            row.update(
                summaries.get(
'''
if augment_new not in projection:
    projection = projection.replace(augment_old, augment_new, 1)
return_old = '''                )
            )
        return normalized
'''
return_new = '''                )
            )
            row["task_contract"] = (
                contracts.get(int(row["id"]))
                if row.get("source_engine") == "clinical_v2"
                else None
            )
        return normalized
'''
if return_new not in projection:
    if return_old not in projection:
        raise AssertionError("projection contract anchor missing")
    projection = projection.replace(return_old, return_new, 1)
projection_path.write_text(projection, encoding="utf-8")

# Worklist makes completion criteria visible.
patch(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''                                        {% if t.latest_outcome_event_id %} · آخرین شاهد: #{{ t.latest_outcome_event_id|fa_num }}{% endif %}
                                    </div>
''',
    '''                                        {% if t.latest_outcome_event_id %} · آخرین شاهد: #{{ t.latest_outcome_event_id|fa_num }}{% endif %}
                                    </div>
                                    {% if t.task_contract %}
                                    <div class="text-xs" style="margin-top:var(--s1);">
                                        <span class="badge badge-info">{{ t.task_contract.urgency }}</span>
                                        مهلت: {{ t.task_contract.due_at|jalali }} ·
                                        شاهد مجاز: {{ t.task_contract.allowed_outcome_types|join('، ') }} ·
                                        حداقل اعتبار: {{ t.task_contract.minimum_verification }}
                                        {% if t.task_contract.required_fact_keys %} · Fact لازم: {{ t.task_contract.required_fact_keys|join('، ') }}{% endif %}
                                    </div>
                                    {% endif %}
''',
)

# Generic rule fixture carries a valid contract, so any test that toggles task=true
# remains a valid compiler input. Dedicated tests cover missing/invalid contracts.
patch(
    "specialist_clinic/tests/test_clinical_engine_v2_compiler.py",
    '''            "params": {},
''',
    '''            "params": {
                "due_in_days": 0,
                "task_contract": {
                    "urgency": "ROUTINE",
                    "allowed_outcome_types": [
                        "OBSERVATION", "PATIENT_REPORTED",
                        "ENCOUNTER_COMPLETED", "PROCEDURE_COMPLETED",
                        "LAB_COMPLETED", "OTHER"
                    ],
                    "required_fact_keys": [],
                    "minimum_verification": "UNVERIFIED",
                    "canonical_ingestion": "OPTIONAL",
                    "requires_acknowledgement": False,
                },
            },
''',
)
# Manual recommendation fixture in follow-up tests must preserve params as audit output.
patch(
    "specialist_clinic/tests/test_clinical_engine_v2_followups.py",
    '''            "params": {},
''',
    '''            "params": {
                "due_in_days": 0,
                "task_contract": {
                    "urgency": "ROUTINE",
                    "allowed_outcome_types": [
                        "OBSERVATION", "PATIENT_REPORTED",
                        "ENCOUNTER_COMPLETED", "PROCEDURE_COMPLETED",
                        "LAB_COMPLETED", "OTHER"
                    ],
                    "required_fact_keys": [],
                    "minimum_verification": "UNVERIFIED",
                    "canonical_ingestion": "OPTIONAL",
                    "requires_acknowledgement": False,
                },
            },
''',
)

# Mandatory guidance.
claude = path("specialist_clinic/CLAUDE.md")
claude_text = claude.read_text(encoding="utf-8")
marker = "## قرارداد تکمیل task بالینی و canonical outcome (A2)"
if marker not in claude_text:
    claude_text += '''

## قرارداد تکمیل task بالینی و canonical outcome (A2)

- هر Rule با `may_create_internal_task=true` باید دقیقاً یکی از `due_in_hours` یا `due_in_days` و یک `task_contract` صریح داشته باشد؛ compiler در غیر این صورت Rule را رد می‌کند.
- قرارداد task همراه task در `clinical_task_contracts` به‌صورت immutable ذخیره می‌شود و شامل urgency، due_at، outcomeهای مجاز، Factهای لازم، حداقل verification و سیاست canonical ingestion است.
- ثبت outcome نامنطبق با قرارداد در service و SQLite رد می‌شود.
- completion فقط با outcome هم-task، نوع و verification مجاز و در صورت `canonical_ingestion=REQUIRED` با لینک canonical ممکن است.
- outcomeهای `observation.*` و `lab.*` در همان transaction به `vital_readings` یا `lab_results` وارد و در `clinical_outcome_canonical_links` متصل می‌شوند.
- recommendation `params` باید در DTO، audit payload و follow-up projection حفظ شود؛ حذف آن‌ها ممنوع است.
'''
    claude.write_text(claude_text, encoding="utf-8")

Path(__file__).unlink()

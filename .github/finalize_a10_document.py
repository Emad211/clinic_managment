from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A10 document target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 document anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Encounter document event stores the exact structured commitment set.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_documentation_repo.py",
    '''def _problems(values: Iterable[str] | str | None) -> list[str]:
''',
    '''def _commitments_json(values) -> str:
    if values is None:
        decoded = []
    elif isinstance(values, str):
        try:
            decoded = json.loads(values or "[]")
        except json.JSONDecodeError as exc:
            raise EncounterDocumentationValidationError(
                "commitments JSON is invalid"
            ) from exc
    else:
        decoded = values
    if not isinstance(decoded, list) or any(
        not isinstance(item, dict) for item in decoded
    ):
        raise EncounterDocumentationValidationError(
            "commitments must be an array of objects"
        )
    return json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))


def _problems(values: Iterable[str] | str | None) -> list[str]:
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_documentation_repo.py",
    '''        problems: Iterable[str] | str | None = None,
        outcome_code: str | None = None,
''',
    '''        problems: Iterable[str] | str | None = None,
        commitments=None,
        outcome_code: str | None = None,
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_documentation_repo.py",
    '''                "problems_json": json.dumps(
                    _problems(problems), ensure_ascii=False
                ),
                "outcome_code": outcome,
''',
    '''                "problems_json": json.dumps(
                    _problems(problems), ensure_ascii=False
                ),
                "commitments_json": _commitments_json(commitments),
                "outcome_code": outcome,
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_documentation_repo.py",
    '''                    assessment,plan,followup_instructions,problems_json,outcome_code,
                    amendment_reason,authored_at,recorded_at,actor_user_id,
                    actor_username,idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
''',
    '''                    assessment,plan,followup_instructions,problems_json,
                    commitments_json,outcome_code,amendment_reason,authored_at,
                    recorded_at,actor_user_id,actor_username,idempotency_key,
                    supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_documentation_repo.py",
    '''            item["problems"] = json.loads(item.get("problems_json") or "[]")
            output.append(item)
''',
    '''            item["problems"] = json.loads(item.get("problems_json") or "[]")
            item["commitments"] = json.loads(
                item.get("commitments_json") or "[]"
            )
            output.append(item)
''',
)

# ---------------------------------------------------------------------------
# Draft/sign validate the explicit set; sign materializes Worklist commitments atomically.
# Amendment preserves the original signed commitment set.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''from src.services.care_journey_service import CareJourneyService
''',
    '''from src.services.care_journey_service import CareJourneyService
from src.services.encounter_plan_commitment_service import (
    EncounterPlanCommitmentService,
)
''',
)
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''            vital_ids = self._record_vitals(
                db,
                patient_link_id=int(visit_snapshot["patient_link_id"]),
''',
    '''            commitments = EncounterPlanCommitmentService(
                db=db
            ).validate_for_document(
                outcome_code=None,
                commitments=document.get("commitments"),
            )
            vital_ids = self._record_vitals(
                db,
                patient_link_id=int(visit_snapshot["patient_link_id"]),
''',
)
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''                problems=document.get("problems"),
                expected_current_event_id=expected_current_event_id,
''',
    '''                problems=document.get("problems"),
                commitments=commitments,
                expected_current_event_id=expected_current_event_id,
''',
)
# Second vitals anchor belongs to sign.
service_path = target("specialist_clinic/src/services/encounter_documentation_service.py")
service = service_path.read_text(encoding="utf-8")
old = '''            vital_ids = self._record_vitals(
                db,
                patient_link_id=int(visit_snapshot["patient_link_id"]),
                readings=readings,
                measured_at=measured_at,
                actor_username=actor_username,
            )
            signed = EncounterDocumentationRepository(db).append_document(
'''
new = '''            commitments = EncounterPlanCommitmentService(
                db=db
            ).validate_for_document(
                outcome_code=document.get("outcome_code"),
                commitments=document.get("commitments"),
            )
            vital_ids = self._record_vitals(
                db,
                patient_link_id=int(visit_snapshot["patient_link_id"]),
                readings=readings,
                measured_at=measured_at,
                actor_username=actor_username,
            )
            signed = EncounterDocumentationRepository(db).append_document(
'''
if new not in service:
    if old not in service:
        raise AssertionError("A10 sign validation anchor missing")
    service = service.replace(old, new, 1)
service_path.write_text(service, encoding="utf-8")
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''                problems=document.get("problems"),
                outcome_code=document.get("outcome_code"),
''',
    '''                problems=document.get("problems"),
                commitments=commitments,
                outcome_code=document.get("outcome_code"),
''',
)
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''            DoctorQueueRepository(db).mark_done(
''',
    '''            materialized = EncounterPlanCommitmentService(
                db=db
            ).materialize_signed_document(
                document_event=signed,
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                commit=False,
            )
            DoctorQueueRepository(db).mark_done(
''',
)
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''                "encounter": completed["encounter"],
            }
''',
    '''                "encounter": completed["encounter"],
                "commitments": materialized,
            }
''',
)
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''            self._completed_event(db, encounter_id)
            event = EncounterDocumentationRepository(db).append_document(
''',
    '''            self._completed_event(db, encounter_id)
            documentation = EncounterDocumentationRepository(db)
            current = documentation.current_document(encounter_id)
            if not current:
                raise LookupError("encounter document not found")
            event = documentation.append_document(
''',
)
replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''                problems=document.get("problems"),
                outcome_code=document.get("outcome_code"),
                amendment_reason=amendment_reason,
''',
    '''                problems=document.get("problems"),
                commitments=current.get("commitments_json") or "[]",
                outcome_code=document.get("outcome_code"),
                amendment_reason=amendment_reason,
''',
)

Path(__file__).unlink()

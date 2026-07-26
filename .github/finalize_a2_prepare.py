from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "specialist_clinic/src/services/clinical_engine/compiler.py"
FINALIZER = ROOT / ".github/finalize_a2.py"

compiler = COMPILER.read_text(encoding="utf-8")
anchor = '''        if (
            recommendation["may_create_internal_task"]
            and action not in INTERNAL_TASK_ACTIONS
        ):
            diagnostics.append(
                self._error(
                    "AUTOMATIC_TASK_NOT_ALLOWED",
                    "$.recommendation.may_create_internal_task",
                    f"{action.value} cannot directly create an internal task.",
                )
            )
'''
replacement = anchor + '''        if recommendation["may_create_internal_task"]:
            params = recommendation.get("params") or {}
            if not isinstance(params.get("task_contract"), dict):
                diagnostics.append(
                    self._error(
                        "MISSING_TASK_CONTRACT",
                        "$.recommendation.params.task_contract",
                        "Internal tasks require an explicit due/completion contract.",
                    )
                )
            due_count = int(params.get("due_in_hours") is not None) + int(
                params.get("due_in_days") is not None
            )
            if due_count != 1:
                diagnostics.append(
                    self._error(
                        "INVALID_TASK_DUE_CONTRACT",
                        "$.recommendation.params",
                        "Exactly one of due_in_hours or due_in_days is required.",
                    )
                )
'''
if replacement not in compiler:
    if anchor not in compiler:
        raise AssertionError("current compiler task-policy anchor is missing")
    compiler = compiler.replace(anchor, replacement, 1)
    COMPILER.write_text(compiler, encoding="utf-8")

finalizer = FINALIZER.read_text(encoding="utf-8")
obsolete = '''# Compiler semantic gates.
patch(
    "specialist_clinic/src/services/clinical_engine/compiler.py",
    \'\'\'        if recommendation.get("may_create_internal_task") and action_type not in _ALLOWED_TASK_ACTIONS:
            diagnostics.append(
                self._error(
                    "AUTOMATIC_TASK_NOT_ALLOWED",
                    "recommendation.may_create_internal_task is only valid for internal follow-up actions",
                    "$.recommendation.may_create_internal_task",
                )
            )
\'\'\',
    \'\'\'        if recommendation.get("may_create_internal_task") and action_type not in _ALLOWED_TASK_ACTIONS:
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
\'\'\',
)

'''
if obsolete in finalizer:
    finalizer = finalizer.replace(
        obsolete,
        "# Compiler semantic gates are applied by finalize_a2_prepare.py.\n\n",
        1,
    )
    FINALIZER.write_text(finalizer, encoding="utf-8")
elif "Compiler semantic gates are applied by finalize_a2_prepare.py." not in finalizer:
    raise AssertionError("obsolete A2 compiler patch block was not found")

Path(__file__).unlink()

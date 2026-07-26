from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A10 route target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 route anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


route_path = target("specialist_clinic/src/api/doctor_queue.py")
routes = route_path.read_text(encoding="utf-8")
anchor = '''def _snapshot(invoice_id: int) -> dict:
    return {"accounting_invoice_id": int(invoice_id)}


'''
helper = '''def _snapshot(invoice_id: int) -> dict:
    return {"accounting_invoice_id": int(invoice_id)}


def _commitments_from_form() -> list[dict]:
    keys = request.form.getlist("commitment_client_key")
    kinds = request.form.getlist("commitment_type")
    instructions = request.form.getlist("commitment_instruction")
    dates = request.form.getlist("commitment_due_date")
    times = request.form.getlist("commitment_due_time")
    fulfillments = request.form.getlist("commitment_fulfillment")
    assignees = request.form.getlist("commitment_assigned_to")
    width = max(
        len(keys), len(kinds), len(instructions), len(dates), len(times),
        len(fulfillments), len(assignees), 0,
    )
    output: list[dict] = []
    for index in range(width):
        def at(values, default=""):
            return values[index] if index < len(values) else default
        raw = {
            "client_key": at(keys).strip(),
            "commitment_type": at(kinds).strip(),
            "instruction": at(instructions).strip(),
            "due_date": at(dates).strip(),
            "due_time": at(times, "09:00").strip() or "09:00",
            "fulfillment": at(fulfillments, "remote").strip() or "remote",
            "assigned_to": at(assignees).strip(),
        }
        if not any(
            raw[field]
            for field in ("client_key", "commitment_type", "instruction", "due_date", "assigned_to")
        ):
            continue
        if not all(
            raw[field]
            for field in ("client_key", "commitment_type", "instruction", "due_date")
        ):
            raise ValueError(
                f"ردیف تعهد {index + 1} ناقص است؛ نوع، دستور و موعد الزامی‌اند."
            )
        due_day = jalali_to_gregorian_str(raw["due_date"])
        if not due_day:
            raise ValueError(f"تاریخ تعهد {index + 1} نامعتبر است.")
        try:
            from datetime import datetime
            due = datetime.fromisoformat(f"{due_day} {raw['due_time']}:00")
        except ValueError as exc:
            raise ValueError(f"زمان تعهد {index + 1} نامعتبر است.") from exc
        output.append(
            {
                "client_key": raw["client_key"],
                "commitment_type": raw["commitment_type"],
                "instruction": raw["instruction"],
                "due_at": due.isoformat(sep=" ", timespec="seconds"),
                "fulfillment": raw["fulfillment"],
                "assigned_to": raw["assigned_to"] or None,
            }
        )
    return output


'''
if helper not in routes:
    if anchor not in routes:
        raise AssertionError("A10 commitment form helper anchor missing")
    routes = routes.replace(anchor, helper, 1)
    route_path.write_text(routes, encoding="utf-8")

replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''    if current_document:
        import json
        current_document["problems"] = json.loads(
            current_document.get("problems_json") or "[]"
        )
''',
    '''    if current_document:
        import json
        current_document["problems"] = json.loads(
            current_document.get("problems_json") or "[]"
        )
        current_document["commitments"] = json.loads(
            current_document.get("commitments_json") or "[]"
        )
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''        "outcome_code": request.form.get("outcome_code"),
    }
''',
    '''        "outcome_code": request.form.get("outcome_code"),
        "commitments": _commitments_from_form(),
    }
''',
)
# document_detail loads commitments for display.
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''        current["problems"] = json.loads(current.get("problems_json") or "[]")
        history = repository.history(encounter["encounter_id"])
''',
    '''        current["problems"] = json.loads(current.get("problems_json") or "[]")
        current["commitments"] = json.loads(
            current.get("commitments_json") or "[]"
        )
        history = repository.history(encounter["encounter_id"])
''',
)

Path(__file__).unlink()

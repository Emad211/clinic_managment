from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Route log derives patient identity from the canonical task, never from an event payload.
route = ROOT / "specialist_clinic/src/api/followups.py"
text = route.read_text(encoding="utf-8")
old = '''        log_activity(
            "encounter_plan_commitment_transition",
            f"task={task_id} event={event['event_type']} status={event['status']}",
            patient_link_id=int(event["patient_link_id"]),
        )
'''
new = '''        patient = get_db().execute(
            "SELECT patient_link_id FROM followup_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        log_activity(
            "encounter_plan_commitment_transition",
            f"task={task_id} event={event['event_type']} status={event['status']}",
            patient_link_id=int(patient["patient_link_id"]),
        )
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 route log anchor missing")
    text = text.replace(old, new, 1)
route.write_text(text, encoding="utf-8")

# A10 unit fixture provides a strict read-only identity seam; accounting behavior itself
# remains covered by A9/A8 zero-write tests in the release gate.
test = ROOT / "specialist_clinic/tests/test_encounter_plan_commitments_a10.py"
text = test.read_text(encoding="utf-8")
text = text.replace(
    "def a10_app(tmp_path):\n",
    "def a10_app(tmp_path, monkeypatch):\n",
    1,
)
anchor = '''    core._initialized = False
    app = create_app(
'''
replacement = '''    from src.adapters import specialist_accounting_revenue
    from src.common.utils import iran_now
    monkeypatch.setattr(
        specialist_accounting_revenue,
        "invoice_identity",
        lambda invoice_id: {
            "invoice_id": int(invoice_id),
            "patient_id": int(invoice_id),
            "status": "open",
            "work_date": iran_now().strftime("%Y-%m-%d"),
            "opened_at": iran_now().strftime("%Y-%m-%d %H:%M:%S"),
            "closed_at": None,
            "total_amount": 0,
        },
    )
    core._initialized = False
    app = create_app(
'''
if replacement not in text:
    if anchor not in text:
        raise AssertionError("A10 fixture accounting seam anchor missing")
    text = text.replace(anchor, replacement, 1)
test.write_text(text, encoding="utf-8")

Path(__file__).unlink()

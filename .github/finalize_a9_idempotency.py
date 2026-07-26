from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A9 idempotency anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_documentation_repo.py",
    '''    def history(self, encounter_id: str) -> list[dict]:
''',
    '''    def document_by_idempotency(self, key: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_encounter_document_events
                   WHERE idempotency_key=?""",
                (str(key),),
            ).fetchone()
        )

    def history(self, encounter_id: str) -> list[dict]:
''',
)

replace_once(
    "specialist_clinic/src/services/encounter_documentation_service.py",
    '''        db.execute("BEGIN IMMEDIATE")
        try:
            self._active_event(db, visit_snapshot["encounter_id"])
            requirement = EncounterDocumentationRepository(db).requirement(
                visit_snapshot["encounter_id"]
            )
''',
    '''        db.execute("BEGIN IMMEDIATE")
        try:
            documentation = EncounterDocumentationRepository(db)
            existing = documentation.document_by_idempotency(idempotency_key)
            if existing:
                db.commit()
                return {"document": existing, "vital_ids": []}
            self._active_event(db, visit_snapshot["encounter_id"])
            requirement = documentation.requirement(
                visit_snapshot["encounter_id"]
            )
''',
)
# Apply the same guard to sign_and_complete (the first replacement consumed draft only).
service_path = ROOT / "specialist_clinic/src/services/encounter_documentation_service.py"
service = service_path.read_text(encoding="utf-8")
old = '''        db.execute("BEGIN IMMEDIATE")
        try:
            self._active_event(db, visit_snapshot["encounter_id"])
            requirement = EncounterDocumentationRepository(db).requirement(
                visit_snapshot["encounter_id"]
            )
'''
new = '''        db.execute("BEGIN IMMEDIATE")
        try:
            documentation = EncounterDocumentationRepository(db)
            existing = documentation.document_by_idempotency(idempotency_key)
            if existing:
                encounter = CareJourneyRepository(db).encounter(
                    visit_snapshot["encounter_id"]
                )
                db.commit()
                return {
                    "document": existing,
                    "vital_ids": [],
                    "encounter": encounter,
                }
            self._active_event(db, visit_snapshot["encounter_id"])
            requirement = documentation.requirement(
                visit_snapshot["encounter_id"]
            )
'''
if new not in service:
    if old not in service:
        raise AssertionError("A9 sign idempotency anchor missing")
    service_path.write_text(service.replace(old, new, 1), encoding="utf-8")

# Route-level double-submit recovery after the first SIGN has already completed the Encounter.
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

    measured = jalali_to_gregorian_str(request.form.get("measured_date", ""))
''',
    '''    requested_action = str(request.form.get("action") or "draft").lower()
    requested_id = request.form.get("document_request_id") or ""
    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        if requested_action == "sign" and requested_id:
            from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
            from src.adapters.sqlite.encounter_documentation_repo import (
                EncounterDocumentationRepository,
            )
            encounter = CareJourneyRepository().encounter_for_invoice(invoice_id)
            existing = (
                EncounterDocumentationRepository().document_by_idempotency(
                    f"encounter-document:sign:{encounter['encounter_id']}:{requested_id}"
                )
                if encounter else None
            )
            current = (
                CareJourneyRepository().current_encounter_event(
                    encounter["encounter_id"]
                )
                if encounter else None
            )
            if (
                existing and existing["document_status"] == "SIGNED"
                and current and current["event_type"] == "COMPLETED"
            ):
                flash("این درخواست قبلاً با موفقیت امضا و تکمیل شده است.", "success")
                return redirect(url_for("doctor_queue.index"))
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

    measured = jalali_to_gregorian_str(request.form.get("measured_date", ""))
''',
)

# Prove repeated draft and sign requests cannot duplicate vitals or documents.
test_path = ROOT / "specialist_clinic/tests/test_encounter_documentation_a9.py"
text = test_path.read_text(encoding="utf-8")
test = '''


def test_document_request_idempotency_prevents_duplicate_vitals_and_signs(a9_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    app, accounting, _specialist = a9_app
    patient_id = _enroll_and_add_invoice(accounting)
    client = app.test_client()
    _login(client)
    _start(client)
    request_id = uuid.uuid4().hex
    draft = _document_form(
        action="draft",
        document_request_id=request_id,
        pulse="82",
        outcome_code="",
    )
    client.post("/doctor-queue/101/save", data=draft)
    client.post("/doctor-queue/101/save", data=draft)
    encounter = CareJourneyRepository().encounter_for_invoice(101)
    repository = EncounterDocumentationRepository()
    assert len(repository.history(encounter["encounter_id"])) == 1
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 1

    current = repository.current_document(encounter["encounter_id"])
    sign_id = uuid.uuid4().hex
    signed = _document_form(
        action="sign",
        document_request_id=sign_id,
        expected_current_event_id=current["id"],
        bp_systolic="132",
    )
    client.post("/doctor-queue/101/save", data=signed)
    client.post("/doctor-queue/101/save", data=signed)
    assert [row["event_type"] for row in repository.history(
        encounter["encounter_id"]
    )] == ["DRAFT_SAVED", "SIGNED"]
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 2
'''
if test.strip() not in text:
    test_path.write_text(text + test, encoding="utf-8")

Path(__file__).unlink()

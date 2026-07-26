from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A9 route target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A9 route anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# DoctorQueueService: require documentation at start and remove auto-complete shortcut.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''        appointment_id: int | None = None,
        campaign_response_event_id: int | None = None,
    ) -> dict:
''',
    '''        appointment_id: int | None = None,
        campaign_response_event_id: int | None = None,
        require_documentation: bool = False,
    ) -> dict:
''',
)
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''            DoctorQueueRepository(db).start(
                **self._repo_snapshot(canonical), commit=False
            )
            db.commit()
''',
    '''            if require_documentation:
                from src.adapters.sqlite.encounter_documentation_repo import (
                    EncounterDocumentationRepository,
                )
                EncounterDocumentationRepository(db).require_for_encounter(
                    encounter["encounter_id"],
                    actor_username=actor,
                    commit=False,
                )
            DoctorQueueRepository(db).start(
                **self._repo_snapshot(canonical), commit=False
            )
            db.commit()
''',
)
service_path = target("specialist_clinic/src/services/doctor_queue_service.py")
service = service_path.read_text(encoding="utf-8")
old_end = '''    def end_visit(
        self,
        snapshot: dict,
        done_by: str,
        notes: str | None = None,
    ) -> dict:
        canonical = self.canonical_snapshot(snapshot["accounting_invoice_id"])
        if str(canonical["work_date"]) != str(self.work_date_provider()):
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_OUTSIDE_ACTIVE_DAY")
        if not canonical.get("patient_link_id"):
            self.repo.mark_done(
                done_by=done_by,
                notes=notes,
                **self._repo_snapshot(canonical),
            )
            return canonical

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            repository = CareJourneyRepository(db)
            encounter = repository.encounter_for_invoice(
                canonical["accounting_invoice_id"]
            )
            if not encounter:
                if canonical["accounting_status"] != "open":
                    raise DoctorQueueIdentityError(
                        "SPECIALIST_ENCOUNTER_MISSING_FOR_CLOSED_INVOICE"
                    )
                CareJourneyService(db=db).start_accounting_visit(
                    patient_link_id=canonical["patient_link_id"],
                    accounting_invoice_id=canonical["accounting_invoice_id"],
                    actor_username=done_by,
                    expected_work_date=canonical["work_date"],
                    effective_at=iran_now(),
                    commit=False,
                )
            DoctorQueueRepository(db).mark_done(
                done_by=done_by,
                notes=notes,
                commit=False,
                **self._repo_snapshot(canonical),
            )
            completed = CareJourneyService(db=db).complete_accounting_visit(
                accounting_invoice_id=canonical["accounting_invoice_id"],
                actor_username=done_by,
                effective_at=iran_now(),
                note=notes,
                commit=False,
            )
            db.commit()
            canonical["encounter_id"] = completed["encounter"]["encounter_id"]
            canonical["journey_id"] = completed["encounter"]["journey_id"]
            return canonical
        except Exception:
            db.rollback()
            raise
'''
new_end = '''    def end_visit(
        self,
        snapshot: dict,
        done_by: str,
        notes: str | None = None,
    ) -> dict:
        """Legacy-compatible completion; REQUIRED A9 encounters need a signed document."""
        canonical = self.canonical_snapshot(snapshot["accounting_invoice_id"])
        if str(canonical["work_date"]) != str(self.work_date_provider()):
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_OUTSIDE_ACTIVE_DAY")
        if not canonical.get("patient_link_id"):
            self.repo.mark_done(
                done_by=done_by,
                notes=notes,
                **self._repo_snapshot(canonical),
            )
            return canonical

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            repository = CareJourneyRepository(db)
            encounter = repository.encounter_for_invoice(
                canonical["accounting_invoice_id"]
            )
            if not encounter:
                raise DoctorQueueIdentityError("SPECIALIST_VISIT_NOT_STARTED")
            current = repository.current_encounter_event(encounter["encounter_id"])
            if not current or current["event_type"] != "STARTED":
                raise DoctorQueueIdentityError("SPECIALIST_VISIT_NOT_ACTIVE")
            from src.adapters.sqlite.encounter_documentation_repo import (
                EncounterDocumentationRepository,
            )
            documentation = EncounterDocumentationRepository(db)
            requirement = documentation.requirement(encounter["encounter_id"])
            if requirement and requirement["requirement_status"] == "REQUIRED":
                document = documentation.current_document(encounter["encounter_id"])
                if not document or document["document_status"] != "SIGNED":
                    raise DoctorQueueIdentityError(
                        "SIGNED_ENCOUNTER_DOCUMENT_REQUIRED"
                    )
            DoctorQueueRepository(db).mark_done(
                done_by=done_by,
                notes=notes,
                commit=False,
                **self._repo_snapshot(canonical),
            )
            completed = CareJourneyService(db=db).complete_accounting_visit(
                accounting_invoice_id=canonical["accounting_invoice_id"],
                actor_username=done_by,
                effective_at=iran_now(),
                note=notes,
                commit=False,
            )
            db.commit()
            canonical["encounter_id"] = completed["encounter"]["encounter_id"]
            canonical["journey_id"] = completed["encounter"]["journey_id"]
            return canonical
        except Exception:
            db.rollback()
            raise
'''
if new_end not in service:
    if old_end not in service:
        raise AssertionError("A9 DoctorQueueService.end_visit anchor missing")
    service_path.write_text(service.replace(old_end, new_end, 1), encoding="utf-8")

# ---------------------------------------------------------------------------
# Routes: structured document parsing, atomic draft/sign, amendment surface.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''from src.security.permissions import Permission, has_permission
''',
    '''from src.security.permissions import (
    Permission,
    has_permission,
    permission_required,
)
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''        "campaign response is already attributed to another journey": "این پاسخ قبلاً به Journey دیگری متصل شده است.",
    }
''',
    '''        "campaign response is already attributed to another journey": "این پاسخ قبلاً به Journey دیگری متصل شده است.",
        "SIGNED_ENCOUNTER_DOCUMENT_REQUIRED": "برای پایان ویزیت، ابتدا سند Encounter را کامل و امضا کنید.",
        "ENCOUNTER_NOT_ACTIVE_FOR_DOCUMENTATION": "Encounter برای ثبت یا امضای سند فعال نیست.",
        "ENCOUNTER_NOT_COMPLETED_FOR_AMENDMENT": "اصلاح سند فقط پس از تکمیل Encounter مجاز است.",
        "STALE_ENCOUNTER_DOCUMENT": "نسخه سند تغییر کرده است؛ صفحه را تازه کنید.",
    }
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''            campaign_response_event_id=response_event_id,
        )
''',
    '''            campaign_response_event_id=response_event_id,
            require_documentation=True,
        )
''',
)

# Visit page document context.
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''    notes = RecordRepository().list_notes(pid, "exam")
    open_followups = [
''',
    '''    notes = RecordRepository().list_notes(pid, "exam")
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )
    document_repository = EncounterDocumentationRepository()
    current_document = document_repository.current_document(
        snapshot["encounter_id"]
    )
    document_history = document_repository.history(snapshot["encounter_id"])
    if current_document:
        import json
        current_document["problems"] = json.loads(
            current_document.get("problems_json") or "[]"
        )
    outcome_labels = {
        "STABLE_CONTINUE": "پایدار؛ ادامه برنامه فعلی",
        "PLAN_CHANGED": "برنامه درمانی تغییر کرد",
        "FOLLOWUP_REQUIRED": "پیگیری لازم است",
        "REFERRED": "ارجاع انجام شد",
        "URGENT_ESCALATION": "اقدام یا ارجاع فوری",
        "OTHER": "سایر",
    }
    import uuid
    document_request_id = uuid.uuid4().hex
    open_followups = [
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''        last_note=(notes[0] if notes else None),
        open_followups=open_followups,
    )
''',
    '''        last_note=(notes[0] if notes else None),
        open_followups=open_followups,
        current_document=current_document,
        document_history=document_history,
        outcome_labels=outcome_labels,
        document_request_id=document_request_id,
    )
''',
)

route_path = target("specialist_clinic/src/api/doctor_queue.py")
routes = route_path.read_text(encoding="utf-8")
save_start = '''@bp.route("/<int:invoice_id>/save", methods=["POST"])
@login_required
def save(invoice_id):
'''
if save_start not in routes:
    raise AssertionError("A9 save route start missing")
start_index = routes.index(save_start)
# Save is the last route in the current file; replace from its decorator to EOF.
new_tail = '''@bp.route("/<int:invoice_id>/save", methods=["POST"])
@permission_required(Permission.CLINICAL_DOCUMENT_WRITE)
def save(invoice_id):
    import uuid
    from src.adapters.sqlite.vitals_repo import VITAL_TYPES
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
    )
    from src.services.encounter_documentation_service import (
        EncounterDocumentationService,
        EncounterDocumentationStateError,
    )

    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

    measured = jalali_to_gregorian_str(request.form.get("measured_date", ""))
    measured_at = f"{measured} 12:00:00" if measured else None
    indicators = ClinicalRulesRepository().as_map()
    keys = set(indicators) | set(VITAL_TYPES)
    parsed: list[tuple[str, float, str | None]] = []
    invalid: list[str] = []
    for vital_type in keys:
        raw = (request.form.get(vital_type, "") or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            invalid.append(vital_type)
            continue
        unit = (indicators.get(vital_type) or {}).get("unit") or (
            VITAL_TYPES.get(vital_type, {}).get("unit")
        )
        parsed.append((vital_type, value, unit))
    if invalid:
        flash(
            "مقادیر نامعتبر ثبت نشدند: " + "، ".join(sorted(invalid)),
            "error",
        )
        return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))

    document = {
        "chief_complaint": request.form.get("chief_complaint"),
        "objective_findings": request.form.get("objective_findings"),
        "assessment": request.form.get("assessment"),
        "plan": request.form.get("plan"),
        "followup_instructions": request.form.get("followup_instructions"),
        "problems": request.form.get("problems"),
        "outcome_code": request.form.get("outcome_code"),
    }
    action = str(request.form.get("action") or "draft").lower()
    request_id = (
        request.form.get("document_request_id") or uuid.uuid4().hex
    )
    expected = request.form.get("expected_current_event_id", type=int)
    service = EncounterDocumentationService()
    try:
        if action == "sign":
            result = service.sign_and_complete(
                visit_snapshot=snapshot,
                document=document,
                readings=parsed,
                measured_at=measured_at,
                actor_username=g.user["username"],
                actor_user_id=int(g.user["id"]),
                idempotency_key=(
                    f"encounter-document:sign:{snapshot['encounter_id']}:{request_id}"
                ),
                expected_current_event_id=expected,
            )
            log_activity(
                "encounter_document_sign",
                f"signed document={result['document']['id']} encounter={snapshot['encounter_id']}",
                patient_link_id=snapshot["patient_link_id"],
            )
            flash("سند Encounter امضا و ویزیت تکمیل شد.", "success")
            return redirect(url_for("doctor_queue.index"))
        result = service.save_draft_with_vitals(
            visit_snapshot=snapshot,
            document=document,
            readings=parsed,
            measured_at=measured_at,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=(
                f"encounter-document:draft:{snapshot['encounter_id']}:{request_id}"
            ),
            expected_current_event_id=expected,
        )
        log_activity(
            "encounter_document_draft",
            f"draft document={result['document']['id']} encounter={snapshot['encounter_id']}",
            patient_link_id=snapshot["patient_link_id"],
        )
        flash("پیش‌نویس سند و شاخص‌ها به‌صورت اتمیک ذخیره شد.", "success")
    except (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
        EncounterDocumentationStateError,
        ValueError,
        LookupError,
    ) as exc:
        _queue_error(exc)
    return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))


@bp.get("/<int:invoice_id>/document")
@login_required
def document_detail(invoice_id: int):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    try:
        snapshot = DoctorQueueService().canonical_snapshot(invoice_id)
        encounter = CareJourneyRepository().encounter_for_invoice(invoice_id)
        if not encounter:
            raise LookupError("encounter not found")
        repository = EncounterDocumentationRepository()
        current = repository.current_document(encounter["encounter_id"])
        if not current:
            raise LookupError("encounter document not found")
        import json
        current["problems"] = json.loads(current.get("problems_json") or "[]")
        history = repository.history(encounter["encounter_id"])
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))
    return render_template(
        "doctor_queue/document_detail.html",
        active_page="doctor_queue",
        invoice_id=invoice_id,
        snapshot=snapshot,
        encounter=encounter,
        document=current,
        history=history,
        outcome_labels={
            "STABLE_CONTINUE": "پایدار؛ ادامه برنامه فعلی",
            "PLAN_CHANGED": "برنامه درمانی تغییر کرد",
            "FOLLOWUP_REQUIRED": "پیگیری لازم است",
            "REFERRED": "ارجاع انجام شد",
            "URGENT_ESCALATION": "اقدام یا ارجاع فوری",
            "OTHER": "سایر",
        },
    )


@bp.post("/<int:invoice_id>/document/amend")
@permission_required(Permission.CLINICAL_DOCUMENT_AMEND)
def amend_document(invoice_id: int):
    import uuid
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
    )
    from src.services.encounter_documentation_service import (
        EncounterDocumentationService,
        EncounterDocumentationStateError,
    )

    encounter = CareJourneyRepository().encounter_for_invoice(invoice_id)
    if not encounter:
        flash("Encounter یافت نشد.", "error")
        return redirect(url_for("doctor_queue.index"))
    document = {
        "chief_complaint": request.form.get("chief_complaint"),
        "objective_findings": request.form.get("objective_findings"),
        "assessment": request.form.get("assessment"),
        "plan": request.form.get("plan"),
        "followup_instructions": request.form.get("followup_instructions"),
        "problems": request.form.get("problems"),
        "outcome_code": request.form.get("outcome_code"),
    }
    try:
        event = EncounterDocumentationService().amend_completed_document(
            encounter_id=encounter["encounter_id"],
            document=document,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"encounter-document:amend:{encounter['encounter_id']}:{uuid.uuid4().hex}"
            ),
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
            amendment_reason=request.form.get("amendment_reason") or "",
        )
    except (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
        EncounterDocumentationStateError,
        ValueError,
        LookupError,
    ) as exc:
        _queue_error(exc)
    else:
        log_activity(
            "encounter_document_amend",
            f"amended document={event['id']} encounter={encounter['encounter_id']}",
            patient_link_id=encounter["patient_link_id"],
        )
        flash("اصلاحیهٔ سند با حفظ نسخه‌های قبلی ثبت شد.", "success")
    return redirect(url_for("doctor_queue.document_detail", invoice_id=invoice_id))
'''
route_path.write_text(routes[:start_index] + new_tail, encoding="utf-8")

Path(__file__).unlink()

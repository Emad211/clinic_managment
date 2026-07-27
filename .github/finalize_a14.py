from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "specialist_clinic"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A14 anchor missing in {path}: {old[:160]!r}")
    write(path, text.replace(old, new, 1))


# 1) Engine identity test owns equality, not a stale release literal.
identity = S / "tests/test_clinical_reconciliation_engine_identity.py"
replace_once(
    identity,
    'def test_reconciliation_contract_has_one_engine_identity():\n'
    '    assert CURRENT_ENGINE_VERSION == "2.7.0-data-conflicts"\n'
    '    assert ENGINE_VERSION == CURRENT_ENGINE_VERSION\n',
    'def test_reconciliation_contract_has_one_engine_identity():\n'
    '    assert CURRENT_ENGINE_VERSION\n'
    '    assert ENGINE_VERSION == CURRENT_ENGINE_VERSION\n',
)

# 2) Timestamp test must advance from the actual append-only task root.
task_tests = S / "tests/test_clinical_task_contracts.py"
replace_once(task_tests, "from datetime import datetime\n", "from datetime import datetime, timedelta\n")
replace_once(
    task_tests,
    '    patient_id, task_id = _create_strict_task(db)\n'
    '    service = ClinicalCareLoopService(\n'
    '        clock=lambda: datetime(2026, 7, 27, 10, 5, 0)\n'
    '    )\n'
    '    first = service.record_outcome(\n',
    '    patient_id, task_id = _create_strict_task(db)\n'
    '    root = ClinicalCareLoopRepository().current_task(task_id)\n'
    '    recorded_at = datetime.fromisoformat(root["current_recorded_at"]) + timedelta(seconds=1)\n'
    '    service = ClinicalCareLoopService(clock=lambda: recorded_at)\n'
    '    first = service.record_outcome(\n',
)

# 3) Accounting-path tests now mutate the active Flask app snapshot, not only Config.
def patch_accounting_test(path: Path, *, timeout: bool = False) -> None:
    replace_once(
        path,
        '    app = create_app({\n'
        '        "TESTING": True,\n'
        '        "DATABASE_PATH": spec_db,\n',
        '    app = create_app({\n'
        '        "TESTING": True,\n'
        '        "DATABASE_PATH": spec_db,\n'
        '        "ACCOUNTING_DB_PATH": _REAL_ACC_DB,\n',
    )
    replace_once(
        path,
        '    os.environ["ACCOUNTING_DB_PATH"] = path\n'
        '    import src.config.settings as cfg_mod\n'
        '    cfg_mod.Config.ACCOUNTING_DB_PATH = path\n',
        '    os.environ["ACCOUNTING_DB_PATH"] = path\n'
        '    import src.config.settings as cfg_mod\n'
        '    cfg_mod.Config.ACCOUNTING_DB_PATH = path\n'
        '    from flask import current_app, has_app_context\n'
        '    if has_app_context():\n'
        '        current_app.config["ACCOUNTING_DB_PATH"] = path\n',
    )
    if timeout:
        text = read(path)
        text = text.replace(
            '"""get_db() sets PRAGMA busy_timeout = 3000 on every specialist connection."""',
            '"""get_db() sets the current 10-second write-contention guard."""',
        )
        text = text.replace('assert timeout_val == 3000, (', 'assert timeout_val == 10000, (')
        text = text.replace('PRAGMA busy_timeout should be 3000', 'PRAGMA busy_timeout should be 10000')
        write(path, text)


invoice_tests = S / "tests/test_invoice_sync.py"
patch_accounting_test(invoice_tests, timeout=True)
doctor_tests = S / "tests/test_doctor_queue.py"
patch_accounting_test(doctor_tests)

# 4) Route scenarios follow the current active-Encounter contract.
text = read(doctor_tests)
marker = "# Scenario 5 — visit route: enrolled → 200, non-enrolled → 302 redirect"
head, tail = text.split(marker, 1)
if "def _active_day():" not in head:
    helper_anchor = '''def _set_acc_path(path: str):
    """Hot-swap Config.ACCOUNTING_DB_PATH so the next bridge call uses the new path."""
'''
    # Helper insertion after the whole _set_acc_path function is safer via the next function anchor.
    next_anchor = '\n\ndef _enroll_patient(spec_db, national_id, full_name="بیمار آزمون"):'
    if next_anchor not in head:
        raise RuntimeError("A14 doctor active-day insertion anchor missing")
    head = head.replace(
        next_anchor,
        '\n\ndef _active_day():\n'
        '    from src.common.utils import today_str\n'
        '    return today_str()\n'
        + next_anchor,
        1,
    )
tail = tail.replace('work_date="2026-06-20"', 'work_date=_active_day()')

# Enrolled visit must be explicitly started before the document surface is accessible.
old = '''        _enroll_patient(spec_db, nid, "ثبت‌شده ۲")
        _set_acc_path(acc_db)

        rv = client.get(f"/doctor-queue/{inv_id}/visit?nid={nid}")
'''
new = '''        _enroll_patient(spec_db, nid, "ثبت‌شده ۲")
        _set_acc_path(acc_db)
        started = client.post(f"/doctor-queue/{inv_id}/start", follow_redirects=False)
        assert started.status_code == 302

        rv = client.get(f"/doctor-queue/{inv_id}/visit?nid={nid}")
'''
if new not in tail:
    if old not in tail:
        raise RuntimeError("A14 doctor visit start anchor missing")
    tail = tail.replace(old, new, 1)

# First save test: start the Encounter and assert the new document stream, not retired exam notes.
old = '''        _set_acc_path(acc_db)

        # Verify baseline: no vitals, no notes yet
        spec_conn = sqlite3.connect(spec_db)
        pre_vitals = spec_conn.execute(
            "SELECT COUNT(*) c FROM vital_readings WHERE patient_link_id=?", (pid,)
        ).fetchone()[0]
        pre_notes = spec_conn.execute(
            "SELECT COUNT(*) c FROM clinical_notes WHERE patient_link_id=? AND kind='exam'", (pid,)
        ).fetchone()[0]
        spec_conn.close()
        assert pre_vitals == 0
        assert pre_notes == 0

        # POST save with an FBS value and a note
'''
new = '''        _set_acc_path(acc_db)
        started = client.post(f"/doctor-queue/{inv_id}/start", follow_redirects=False)
        assert started.status_code == 302

        # Verify baseline: no vitals and no document events yet.
        spec_conn = sqlite3.connect(spec_db)
        pre_vitals = spec_conn.execute(
            "SELECT COUNT(*) c FROM vital_readings WHERE patient_link_id=?", (pid,)
        ).fetchone()[0]
        pre_documents = spec_conn.execute(
            "SELECT COUNT(*) c FROM care_encounter_document_events WHERE patient_link_id=?", (pid,)
        ).fetchone()[0]
        spec_conn.close()
        assert pre_vitals == 0
        assert pre_documents == 0

        # POST a governed draft with one FBS value.
'''
if new not in tail:
    if old not in tail:
        raise RuntimeError("A14 doctor save baseline anchor missing")
    tail = tail.replace(old, new, 1)

tail = tail.replace(
    '                "note": "بیمار کنترل خوبی داشت",\n',
    '                "objective_findings": "بیمار کنترل خوبی داشت",\n'
    '                "document_request_id": "legacy-doctor-save-a",\n',
    1,
)
tail = tail.replace(
    '''        post_notes = spec_conn.execute(
            "SELECT COUNT(*) c FROM clinical_notes WHERE patient_link_id=? AND kind='exam'",
            (pid,)
        ).fetchone()[0]
''',
    '''        post_documents = spec_conn.execute(
            "SELECT COUNT(*) c FROM care_encounter_document_events "
            "WHERE patient_link_id=? AND event_type='DRAFT_SAVED'",
            (pid,)
        ).fetchone()[0]
''',
    1,
)
tail = tail.replace(
    '        assert post_notes == 1, f"Expected 1 exam note after save, got {post_notes}"\n',
    '        assert post_documents == 1, f"Expected 1 draft document, got {post_documents}"\n',
    1,
)

# Multiple-vitals route also requires an active Encounter.
old = '''        conn.close()
        _set_acc_path(acc_db)

        client.post(
            f"/doctor-queue/{inv_id}/save",
'''
new = '''        conn.close()
        _set_acc_path(acc_db)
        started = client.post(f"/doctor-queue/{inv_id}/start", follow_redirects=False)
        assert started.status_code == 302

        client.post(
            f"/doctor-queue/{inv_id}/save",
'''
# Apply to the final occurrence in scenario 6, not the earlier first save.
position = tail.rfind(old)
if position < 0 and new not in tail:
    raise RuntimeError("A14 multiple-vitals start anchor missing")
if position >= 0:
    tail = tail[:position] + tail[position:].replace(old, new, 1)

write(doctor_tests, head + marker + tail)

# 5) Harden Mediana's live response parser while preserving serial/idempotent batches.
provider = S / "src/services/sms/mediana_provider.py"
text = read(provider)
text = text.replace(
    'headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},',
    'headers={"X-API-KEY": self.api_key, "Content-Type": "application/json",\n'
    '                     "User-Agent": "SpecialistClinic/1.0"},',
)
text = text.replace(
    'headers={"X-API-KEY": self.api_key, "Accept": "application/json"},',
    'headers={"X-API-KEY": self.api_key, "Accept": "application/json",\n'
    '                     "User-Agent": "SpecialistClinic/1.0"},',
)

old_helpers = '''    @staticmethod
    def _error_message(payload: dict) -> str:
        code = _field(payload, "ErrorCode")
        message = _field(payload, "Message") or _field(payload, "ErrorMessage")
'''
new_helpers = '''    @staticmethod
    def _errors(payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        containers = [payload]
        for key in ("Meta", "meta", "Data", "data"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.append(value)
        for container in containers:
            value = _field(container, "Errors")
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _error_message(cls, payload: dict) -> str:
        first = cls._errors(payload)
        source = first[0] if first else payload
        code = _field(source, "ErrorCode")
        message = _field(source, "Message") or _field(source, "ErrorMessage")
'''
if new_helpers not in text:
    if old_helpers not in text:
        raise RuntimeError("A14 Mediana helper anchor missing")
    text = text.replace(old_helpers, new_helpers, 1)

# Status integer and provider ids use both documented and live names.
text = text.replace(
    'status_int = _field(item, "StatusId") or _field(item, "StatusCode")\n'
    '        provider_msgid = _field(item, "SmsId") or _field(item, "MessageId")',
    'status_int = (_field(item, "StatusInt") or _field(item, "StatusId")\n'
    '                      or _field(item, "StatusCode"))\n'
    '        provider_msgid = (_field(item, "SmsItemId") or _field(item, "SmsId")\n'
    '                          or _field(item, "MessageId"))',
)

old_send = '''        if http_status < 200 or http_status >= 300:
            return SendResult(
                ok=False,
                delivery_status="Failed",
                error=self._error_message(result),
            )
        request_id = _field(result, "RequestId") or _field(result, "SendRequestId")
        data = _field(result, "Data", {})
        provider_msgid = None
        if isinstance(data, list) and data:
            provider_msgid = _field(data[0], "SmsId") or _field(data[0], "MessageId")
        elif isinstance(data, dict):
            provider_msgid = _field(data, "SmsId") or _field(data, "MessageId")
        status, status_int, detected_msgid = self._status_payload(result)
'''
new_send = '''        if http_status < 200 or http_status >= 300:
            error = self._error_message(result)
            if not result:
                error = f"HTTP {http_status}: پاسخ نامعتبر از پنل مدیانا"
            else:
                error = f"HTTP {http_status}: {error}"
            return SendResult(ok=False, delivery_status="Failed", error=error)
        errors = self._errors(result)
        if errors:
            code = _field(errors[0], "ErrorCode")
            try:
                numeric = int(code)
            except (TypeError, ValueError):
                numeric = None
            retryable = numeric in {1042, 1062}
            return SendResult(
                ok=False,
                retryable=retryable,
                delivery_status="RetryableFailure" if retryable else "Failed",
                error=self._error_message(result),
            )
        data = _field(result, "Data", {})
        request_id = (_field(data, "RequestId") or _field(data, "SendRequestId")
                      or _field(result, "RequestId") or _field(result, "SendRequestId"))
        provider_msgid = None
        items = _field(data, "SmsItems") if isinstance(data, dict) else None
        if isinstance(items, list) and items:
            provider_msgid = (_field(items[0], "SmsItemId") or _field(items[0], "SmsId")
                              or _field(items[0], "MessageId"))
        elif isinstance(data, list) and data:
            provider_msgid = (_field(data[0], "SmsItemId") or _field(data[0], "SmsId")
                              or _field(data[0], "MessageId"))
        elif isinstance(data, dict):
            provider_msgid = (_field(data, "SmsItemId") or _field(data, "SmsId")
                              or _field(data, "MessageId"))
        status, status_int, detected_msgid = self._status_payload(data or result)
'''
if new_send not in text:
    if old_send not in text:
        raise RuntimeError("A14 Mediana send anchor missing")
    text = text.replace(old_send, new_send, 1)

old_delivery = '''        data = _field(payload, "Data", payload)
        items = data if isinstance(data, list) else [data]
        updates = []
'''
new_delivery = '''        data = _field(payload, "Data", payload)
        nested = _field(data, "SmsItems") if isinstance(data, dict) else None
        items = nested if isinstance(nested, list) else data if isinstance(data, list) else [data]
        updates = []
'''
if new_delivery not in text:
    if old_delivery not in text:
        raise RuntimeError("A14 Mediana delivery anchor missing")
    text = text.replace(old_delivery, new_delivery, 1)
text = text.replace(
    'status_int = _field(item, "StatusId") or _field(item, "StatusCode")',
    'status_int = (_field(item, "StatusInt") or _field(item, "StatusId")\n'
    '                          or _field(item, "StatusCode"))',
)
text = text.replace(
    'str(_field(item, "SmsId") or _field(item, "MessageId") or message_id).strip()',
    'str(_field(item, "SmsItemId") or _field(item, "SmsId")\n'
    '                            or _field(item, "MessageId") or message_id).strip()',
)
text = text.replace(
    'if (_field(item, "SmsId") or _field(item, "MessageId") or message_id)',
    'if (_field(item, "SmsItemId") or _field(item, "SmsId")\n'
    '                            or _field(item, "MessageId") or message_id)',
)
write(provider, text)

# Mediana tests describe the current safe serial batch and current request payload.
mediana_tests = S / "tests/test_mediana_provider.py"
text = read(mediana_tests)
text = text.replace(
    '''    assert captured["json"] == {
        "type": "Informational",
        "recipients": ["09929315456"],
        "messageText": "پیام تست",
    }
''',
    '''    assert captured["json"] == {
        "recipients": ["09929315456"],
        "messageText": "پیام تست",
        "sendSmsType": "SendSmsNormalWithType",
        "messageType": "Informational",
    }
''',
)
old_batch_test = '''def test_batch_maps_pascal_and_camel_case(monkeypatch):
    captured = {}
    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _Response({"data": {"refCodes": [
            {"code": 91, "refId": "a", "mobiles": ["0911"]},
            {"Code": 92, "RefId": "b", "Mobiles": ["0912"]},
        ]}})
    monkeypatch.setattr("requests.post", fake_post)
    result = MedianaProvider("secret").send_batch([
        OutgoingSms("a", "0911", "یک"), OutgoingSms("b", "0912", "دو")], "Informational")
    assert captured['url'].endswith(SEND_ARRAY_PATH)
    assert [x.provider_request_id for x in result.items] == ['91', '92']
    assert captured['json']['Requests'][0]['RefId'] == 'a'
'''
new_batch_test = '''def test_batch_preserves_message_identity_with_serial_single_send(monkeypatch):
    captured = []
    payloads = iter([
        {"data": {"requestId": 91, "status": "Accepted",
                  "smsItems": [{"smsItemId": "i-a", "recipient": "0911"}]}},
        {"Data": {"RequestId": 92, "Status": "Accepted",
                  "SmsItems": [{"SmsItemId": "i-b", "Recipient": "0912"}]}},
    ])
    def fake_post(url, **kwargs):
        captured.append((url, kwargs))
        return _Response(next(payloads))
    monkeypatch.setattr("requests.post", fake_post)
    result = MedianaProvider("secret").send_batch([
        OutgoingSms("a", "0911", "یک"), OutgoingSms("b", "0912", "دو")], "Informational")
    assert [item.ref_id for item in result.items] == ["a", "b"]
    assert [item.provider_request_id for item in result.items] == ["91", "92"]
    assert [item.provider_msgid for item in result.items] == ["i-a", "i-b"]
    assert len(captured) == 2
    assert all(url.endswith(SEND_SMS_PATH) for url, _ in captured)
'''
if new_batch_test not in text:
    if old_batch_test not in text:
        raise RuntimeError("A14 Mediana batch test anchor missing")
    text = text.replace(old_batch_test, new_batch_test, 1)
write(mediana_tests, text)

# 6) The hub has six actual navigation buttons; count the class attribute exactly.
ui_test = S / "tests/test_ui_information_architecture.py"
replace_once(
    ui_test,
    '    assert page.count("hub-nav-btn") == 5\n',
    '    assert page.count(\'class="hub-nav-btn\') == 6\n',
)

# Document the cleanup boundary.
doc = S / "docs/ci_zero_baseline_a14.md"
write(doc, '''# A14 — صفرکردن baseline شکست‌های CI

A14 فقط شکست‌های تاریخی شناخته‌شده را می‌بندد و میان تست منقضی و نقص محصول تفکیک می‌گذارد.

- هویت موتور از release constant واحد خوانده می‌شود؛ تست literal قدیمی حذف شد.
- timestamp تست care-loop از head واقعی append-only جلو می‌رود.
- تست‌های accounting bridge مسیر per-app را تغییر می‌دهند و دیگر Config سراسری را دور نمی‌زنند.
- doctor queue در تست route ابتدا Encounter فعال می‌سازد و سپس سند/شاخص ثبت می‌کند.
- busy timeout فعلی specialist برابر ۱۰ ثانیه است.
- Mediana پاسخ‌های PascalCase/camelCase، SmsItems، StatusInt، خطاهای meta و پاسخ HTTP غیر JSON را fail-closed می‌خواند.
- batch مدیانا عمداً serial است تا idempotency و تطبیق پیام به پیام حفظ شود.
- شمارش UI بر دکمه‌های واقعی class-bound انجام می‌شود.
''')

print("A14 CI baseline finalizer applied")

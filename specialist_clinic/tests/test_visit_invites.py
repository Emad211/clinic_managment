"""
Phase B — Doctor-initiated visit invites (#3 آزمایش+مشاوره, #7 قند+فشار) test suite.

Covers the two new manager-editable engagement events
(`lab_consult_invite`, `bp_glucose_invite`), the new
`POST /doctor-queue/<invoice_id>/invite` route, the approval-queue guardrails,
the no-real-send guarantee, and regression proof that administrative collection
continues for refill dates while high clinical readings never create outreach.

Safety contract (mirrors test_doctor_queue.py / test_invoice_outreach.py):
  - All writes go to a FRESH temp specialist DB and COPIES/temp accounting DBs,
    never the originals.
  - The real clinic_new.db is opened read-only via the bridge only where needed;
    these tests never touch it for the invite path (it resolves patients from the
    local specialist DB).
  - No real SMS is ever sent: in a fresh test DB no SMS keys are seeded, so
    get_provider() returns the NullProvider (simulated, provider_msgid='SIMULATED').
    enqueue_event_for_patient only inserts into engagement_approvals; the SMS is
    only "sent" (to the Null provider) at approve() time.

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_visit_invites.py -v
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── Patch env vars BEFORE any src import (Config is read at import time) ─────
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_REAL_ACC_DB = os.path.join(_REPO_ROOT, "webapp", "clinic_new.db")
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")

import shutil
import sqlite3
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helpers (mirror test_doctor_queue.py conventions)
# ---------------------------------------------------------------------------

def _flush_src_modules():
    """Delete all src.* modules from sys.modules so the next import re-reads
    env vars and produces a clean Config / core._initialized state."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _force_quiet_off():
    """Disable engagement quiet-hours (whole day allowed) so approve()'s wall-clock
    quiet gate never interferes with tests that exercise the SEND / opt-out paths.
    Mirrors the helper in test_end_to_end_loops.py; quiet-hours behaviour itself is
    covered by test_approval_quiet_hours.py. Call inside an app/request context."""
    try:
        from src.adapters.sqlite.sms_repo import SmsRepository
        sms = SmsRepository()
        sms.set_setting("engagement_quiet_start", "00:00")
        sms.set_setting("engagement_quiet_end", "23:59")
    except Exception:
        pass


def _make_acc_db(path: str):
    """Create a minimal accounting DB with the tables accounting_bridge needs."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, family_name TEXT, full_name TEXT,
            national_id TEXT UNIQUE, phone_number TEXT,
            birthdate TEXT, gender TEXT, insurance_type TEXT,
            insurance_expiry TEXT, address TEXT, is_foreign INTEGER DEFAULT 0,
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL, status TEXT DEFAULT 'open',
            total_amount REAL DEFAULT 0, work_date TEXT, closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER, visit_date TEXT,
            doctor_name TEXT, price REAL DEFAULT 0,
            insurance_type TEXT, supplementary_insurance TEXT
        );
        CREATE TABLE IF NOT EXISTS injections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER,
            injection_type TEXT, total_price REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER,
            procedure_type TEXT, price REAL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


def _acc_add_patient(conn, name, national_id=None, phone=None):
    cur = conn.execute(
        "INSERT INTO patients (name, family_name, full_name, national_id, phone_number)"
        " VALUES (?,?,?,?,?)", (name, "", name, national_id, phone))
    conn.commit()
    return cur.lastrowid


def _acc_add_invoice(conn, patient_id, status="open", total=1000,
                     work_date="2026-06-20", closed_at=None):
    ca = closed_at or ("2026-06-20 10:00:00" if status == "closed" else None)
    cur = conn.execute(
        "INSERT INTO invoices (patient_id, status, total_amount, work_date, closed_at)"
        " VALUES (?, ?, ?, ?, ?)", (patient_id, status, total, work_date, ca))
    conn.commit()
    return cur.lastrowid


def _acc_add_visit(conn, invoice_id, patient_id, price=500):
    cur = conn.execute(
        "INSERT INTO visits (invoice_id, patient_id, visit_date, doctor_name, price)"
        " VALUES (?, ?, '2026-06-20', 'دکتر آزمایش', ?)", (invoice_id, patient_id, price))
    conn.commit()
    return cur.lastrowid


def _set_acc_path(path: str):
    """Hot-swap the exact active test application's read-only accounting path."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path
    from flask import current_app
    current_app.config["ACCOUNTING_DB_PATH"] = path

def _enroll(national_id, full_name, phone_number=None, sms_opt_out=0):
    """Insert a patient_links row via the Flask-managed get_db() connection
    (so the schema is already bootstrapped). Returns patient_links.id.
    Must be called inside the pushed app_context."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    cur = db.execute(
        """INSERT INTO patient_links
             (national_id, full_name, phone_number, sms_opt_out, enrolled_by)
           VALUES (?, ?, ?, ?, 'test')""",
        (national_id, full_name, phone_number, sms_opt_out))
    db.commit()
    return cur.lastrowid


def _add_med(pid, drug_name, refill_due_date, is_active=1):
    """Insert an active patient_medications row (drives the refill_due collector)."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    cur = db.execute(
        """INSERT INTO patient_medications
             (patient_link_id, drug_name, refill_due_date, is_active)
           VALUES (?, ?, ?, ?)""",
        (pid, drug_name, refill_due_date, is_active))
    db.commit()
    return cur.lastrowid


def _add_vital(pid, vtype, value):
    """Insert an extreme reading to prove administrative collectors ignore it."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    db.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value) VALUES (?, ?, ?)",
        (pid, vtype, value))
    db.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="invite_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app on a fresh specialist DB. Strict env/module isolation so
    tests cannot pollute each other in the same process."""
    spec_db = os.path.join(tmp_dir, "specialist_test.db")

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }
    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB  # default; tests override

    _flush_src_modules()

    sys.path.insert(0, _SPECIALIST_ROOT)
    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "test-secret",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    # Force bootstrap: get_db() applies schema.sql + migrations + seeds once.
    from src.adapters.sqlite.core import get_db
    get_db()

    yield app, spec_db, tmp_dir

    ctx.pop()

    for key, val in _saved_env.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val
    try:
        import src.config.settings as cfg_mod
        cfg_mod.Config.ACCOUNTING_DB_PATH = _REAL_ACC_DB
    except Exception:
        pass
    try:
        import src.adapters.sqlite.core as core_mod
        core_mod._initialized = False
    except Exception:
        pass


@pytest.fixture()
def test_client(specialist_app):
    """(flask_test_client, spec_db_path, tmp_dir) with a logged-in admin session."""
    app, spec_db, tmp_dir = specialist_app
    client = app.test_client()
    client.post("/auth/login", data={"username": "admin", "password": "admin"},
                follow_redirects=True)
    return client, spec_db, tmp_dir


def _approvals(event_key=None, patient_link_id=None, status=None):
    """Fetch engagement_approvals rows (via get_db) with optional filters."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    clauses, params = [], []
    if event_key is not None:
        clauses.append("event_key=?"); params.append(event_key)
    if patient_link_id is not None:
        clauses.append("patient_link_id=?"); params.append(patient_link_id)
    if status is not None:
        clauses.append("status=?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return [dict(r) for r in db.execute(
        f"SELECT * FROM engagement_approvals {where}", params).fetchall()]


# ===========================================================================
# A — Seed: both visit-invite events present, active, sms, non-empty template
# ===========================================================================

class TestASeed:
    @pytest.mark.parametrize("event_key", ["lab_consult_invite", "bp_glucose_invite"])
    def test_visit_invite_event_seeded(self, specialist_app, event_key):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT * FROM engagement_events WHERE event_key=?", (event_key,)).fetchone()
        assert row is not None, f"{event_key} must be seeded in engagement_events"
        r = dict(row)
        assert r["channel"] == "sms", f"{event_key} channel should be 'sms', got {r['channel']}"
        assert r["is_active"] == 1, f"{event_key} must be active"
        assert r["category"] == "operational", (
            f"{event_key} category should be 'operational', got {r['category']}")
        assert (r["sms_template"] or "").strip(), f"{event_key} must have a non-empty sms_template"

    def test_invite_events_match_route_whitelist(self, specialist_app):
        """The route's VISIT_INVITE_EVENTS constant must equal the seeded set."""
        app, spec_db, _ = specialist_app
        from src.api.doctor_queue import VISIT_INVITE_EVENTS
        assert VISIT_INVITE_EVENTS == {"lab_consult_invite", "bp_glucose_invite"}


# ===========================================================================
# B — Route happy path: enrolled+phone patient → exactly one pending approval
# ===========================================================================

class TestBRouteHappyPath:
    def test_invite_creates_one_pending_approval(self, test_client, tmp_dir):
        client, spec_db, _ = test_client
        nid = "1110000001"
        from src.common.utils import today_str
        work_date = today_str()

        acc_db = os.path.join(tmp_dir, "acc_b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ دعوت", national_id=nid, phone="09120000011")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=work_date)
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)
        from src.services.patient_service import PatientService
        pid = PatientService().enroll_from_accounting(acc_pid, "admin")
        started = client.post(f"/doctor-queue/{inv_id}/start")
        assert started.status_code == 302

        rv = client.post(
            f"/doctor-queue/{inv_id}/invite",
            data={"event_key": "lab_consult_invite", "national_id": "TAMPERED"},
            follow_redirects=False)
        assert rv.status_code == 302, f"invite should redirect (302), got {rv.status_code}"
        # redirects to the visit view for that invoice
        assert "visit" in rv.headers.get("Location", "")

        rows = _approvals(event_key="lab_consult_invite", patient_link_id=pid)
        assert len(rows) == 1, f"expected exactly 1 lab_consult_invite approval, got {len(rows)}"
        r = rows[0]
        assert r["status"] == "pending", f"approval must be pending, got {r['status']}"
        assert r["channel"] == "sms", f"approval channel must be sms, got {r['channel']}"
        assert (r["message"] or "").strip(), "approval message must be non-empty"
        assert r["sent_at"] is None, "a freshly queued approval must not be sent yet"

    def test_bp_glucose_invite_also_queues(self, test_client, tmp_dir):
        """The second whitelisted event also enqueues a pending approval."""
        client, spec_db, _ = test_client
        nid = "1110000002"
        from src.common.utils import today_str
        work_date = today_str()
        acc_db = os.path.join(tmp_dir, "acc_b2.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ قند", national_id=nid, phone="09120000012")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=work_date)
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)
        from src.services.patient_service import PatientService
        pid = PatientService().enroll_from_accounting(acc_pid, "admin")
        assert client.post(f"/doctor-queue/{inv_id}/start").status_code == 302

        client.post(f"/doctor-queue/{inv_id}/invite",
                    data={"event_key": "bp_glucose_invite", "national_id": "TAMPERED"})
        rows = _approvals(event_key="bp_glucose_invite", patient_link_id=pid)
        assert len(rows) == 1, f"expected 1 bp_glucose_invite approval, got {len(rows)}"
        assert rows[0]["status"] == "pending"


# ===========================================================================
# C — Whitelist guard: non-whitelisted event_key → NO approval, no 500
# ===========================================================================

class TestCWhitelistGuard:
    @pytest.mark.parametrize("bad_key", ["refill_due", "thank_you", "evil", ""])
    def test_non_whitelisted_event_creates_no_approval(self, test_client, tmp_dir, bad_key):
        client, spec_db, _ = test_client
        nid = "1110000003"
        _enroll(nid, "بیمارِ تامپر", phone_number="09120000013")
        acc_db = os.path.join(tmp_dir, f"acc_c_{bad_key or 'empty'}.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ تامپر", national_id=nid, phone="09120000013")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)

        rv = client.post(
            f"/doctor-queue/{inv_id}/invite",
            data={"event_key": bad_key, "national_id": nid},
            follow_redirects=False)
        # Must not 500 — it redirects back to the queue index with a flash.
        assert rv.status_code == 302, (
            f"non-whitelisted invite must redirect (302), not error, got {rv.status_code}")
        # Even though 'refill_due' is a real engagement event, the route must reject it
        # because it is not in VISIT_INVITE_EVENTS — so zero approvals overall.
        assert _approvals() == [], (
            f"non-whitelisted event_key {bad_key!r} must create no approval row")

    def test_unenrolled_national_id_creates_no_approval(self, test_client, tmp_dir):
        """Valid whitelisted key but national_id not enrolled → no approval, no 500."""
        client, spec_db, _ = test_client
        nid_unknown = "9999999999"
        acc_db = os.path.join(tmp_dir, "acc_c2.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "غریبه", national_id=nid_unknown, phone="09120009999")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)

        rv = client.post(
            f"/doctor-queue/{inv_id}/invite",
            data={"event_key": "lab_consult_invite", "national_id": nid_unknown},
            follow_redirects=False)
        assert rv.status_code == 302
        assert _approvals() == [], "unenrolled patient must produce no approval"


# ===========================================================================
# D — Service-level guardrails (mirrors enqueue_event_for_patient contract)
# ===========================================================================

class TestDGuardrails:
    def test_idempotent_reenqueue_same_period_returns_none(self, specialist_app):
        app, spec_db, _ = specialist_app
        pid = _enroll("1110000101", "تکرار", phone_number="09120000101")
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        pk = "lab_consult_invite:2026-06-20"
        first = svc.enqueue_event_for_patient(pid, "lab_consult_invite", period_key=pk)
        second = svc.enqueue_event_for_patient(pid, "lab_consult_invite", period_key=pk)
        assert first is not None, "first enqueue must return an approval id"
        assert second is None, "re-enqueue of same (patient,event,period) must return None"
        rows = _approvals(event_key="lab_consult_invite", patient_link_id=pid)
        assert len(rows) == 1, f"only one approval may exist for the period, got {len(rows)}"

    def test_opted_out_patient_returns_none(self, specialist_app):
        app, spec_db, _ = specialist_app
        pid = _enroll("1110000102", "انصراف", phone_number="09120000102", sms_opt_out=1)
        from src.services.engagement_service import EngagementService
        res = EngagementService().enqueue_event_for_patient(
            pid, "lab_consult_invite", period_key="lab_consult_invite:2026-06-20")
        assert res is None, "sms_opt_out=1 patient must return None (no approval)"
        assert _approvals(patient_link_id=pid) == []

    def test_no_phone_patient_returns_none(self, specialist_app):
        app, spec_db, _ = specialist_app
        pid = _enroll("1110000103", "بدون موبایل", phone_number=None)
        from src.services.engagement_service import EngagementService
        res = EngagementService().enqueue_event_for_patient(
            pid, "bp_glucose_invite", period_key="bp_glucose_invite:2026-06-20")
        assert res is None, "patient with no phone must return None (no approval)"
        assert _approvals(patient_link_id=pid) == []


# ===========================================================================
# E — No real send: approval sits pending; approve() goes through NullProvider
# ===========================================================================

class TestENoRealSend:
    def test_provider_is_null_in_test_env(self, specialist_app):
        """In a fresh test DB no SMS keys are seeded → simulated NullProvider."""
        app, spec_db, _ = specialist_app
        from src.services.sms.provider import get_provider, NullProvider
        assert isinstance(get_provider(), NullProvider), (
            "test env must use the simulated NullProvider — never a live panel")

    def test_enqueue_does_not_send(self, specialist_app):
        """enqueue_event_for_patient must NOT dispatch — no sms_messages, no ledger row."""
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        pid = _enroll("1110000201", "بدون‌ارسال", phone_number="09120000201")
        from src.services.engagement_service import EngagementService
        aid = EngagementService().enqueue_event_for_patient(
            pid, "lab_consult_invite", period_key="lab_consult_invite:2026-06-20")
        assert aid is not None
        # pending, nothing sent
        ap = _approvals(patient_link_id=pid)[0]
        assert ap["status"] == "pending" and ap["sent_at"] is None
        assert db.execute("SELECT COUNT(*) c FROM sms_messages").fetchone()["c"] == 0, (
            "enqueue must not create an sms_messages row")
        assert db.execute(
            "SELECT COUNT(*) c FROM engagement_dispatch WHERE channel='sms'"
        ).fetchone()["c"] == 0, "enqueue must not write an sms dispatch ledger row"

    def test_approve_sends_via_simulated_provider(self, specialist_app):
        """approve() is what 'sends'. With the NullProvider it logs an sms_messages
        row marked 'accepted' with the SIMULATED msgid (proving no live provider ran),
        flips the approval to approved + sent_at, and records the dispatch."""
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        pid = _enroll("1110000202", "تأیید‌شده", phone_number="09120000202")
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        aid = svc.enqueue_event_for_patient(
            pid, "bp_glucose_invite", period_key="bp_glucose_invite:2026-06-20")
        assert aid is not None

        _force_quiet_off()  # assert the SEND path here, independent of wall-clock quiet hours
        out = svc.approve(aid, decided_by="admin")
        assert out.get("ok") is True, f"approve() should succeed via NullProvider, got {out}"

        ap = svc.repo.get_approval(aid)
        assert ap["status"] == "approved", f"approval status must be 'approved', got {ap['status']}"
        assert ap["sent_at"] is not None, "approve() must stamp sent_at"

        msgs = db.execute(
            "SELECT * FROM sms_messages WHERE patient_link_id=?", (pid,)).fetchall()
        assert len(msgs) == 1, f"approve() should log exactly one sms_messages row, got {len(msgs)}"
        m = dict(msgs[0])
        assert m["status"] == "accepted", f"panel acceptance must remain distinct from delivery, got {m['status']}"
        assert m["provider_msgid"] == "SIMULATED", (
            "msgid must be 'SIMULATED' — proves the Null/simulated provider sent it, not a live panel")
        assert db.execute(
            "SELECT COUNT(*) c FROM engagement_dispatch WHERE channel='sms' AND patient_link_id=?",
            (pid,)).fetchone()["c"] == 1, "approve() must record one sms dispatch"

    def test_approve_opted_out_rejects_without_send(self, specialist_app):
        """If the patient opted out AFTER queueing, approve() rejects and sends nothing."""
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        pid = _enroll("1110000203", "انصرافِ‌بعدی", phone_number="09120000203")
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        aid = svc.enqueue_event_for_patient(
            pid, "lab_consult_invite", period_key="lab_consult_invite:2026-06-20")
        assert aid is not None
        from src.services.sms.governance_service import SmsGovernanceService
        current = SmsGovernanceService().summary(pid)["CARE"]
        SmsGovernanceService().record(
            patient_link_id=pid,
            purpose="CARE",
            decision="REVOKED",
            actor_username="pytest-patient-request",
            actor_user_id=None,
            source_code="PATIENT_REQUEST",
            idempotency_key=f"pytest-care-revoke:{pid}",
            expected_current_event_id=int(current["id"]),
            reason_code="PATIENT_REQUEST",
        )

        _force_quiet_off()  # so consent — not quiet hours — is the rejection reason regardless of run time
        out = svc.approve(aid, decided_by="admin")
        assert out.get("ok") is False and out.get("reason") == "opt_out"
        assert db.execute("SELECT COUNT(*) c FROM sms_messages").fetchone()["c"] == 0, (
            "rejected approval must not send any SMS")
        assert svc.repo.get_approval(aid)["status"] == "rejected"


# ===========================================================================
# F — Administrative automation is independent of clinical interpretation.
# ===========================================================================

class TestFAutomaticEngagementRegression:
    def test_refill_due_collected_when_med_is_due(self, specialist_app):
        from src.common.utils import today_str
        pid = _enroll("1110000301", "تجدید دارو", phone_number="09120000301")
        _add_med(pid, "متفورمین", refill_due_date=today_str())

        from src.services.engagement_service import EngagementService
        events, config = EngagementService().collect_due_events(pid)
        assert "refill_due" in {event["event_key"] for event in events}
        assert config["refill_due"]["channel"] == "sms"

    def test_refill_not_collected_when_far_future(self, specialist_app):
        pid = _enroll("1110000302", "داروی دور", phone_number="09120000302")
        _add_med(pid, "آتورواستاتین", refill_due_date="2099-01-01")

        from src.services.engagement_service import EngagementService
        events, _ = EngagementService().collect_due_events(pid)
        assert "refill_due" not in {event["event_key"] for event in events}

    def test_high_reading_does_not_create_administrative_event(self, specialist_app):
        pid = _enroll("1110000303", "بدون تفسیر", phone_number="09120000303")
        _add_vital(pid, "bp_systolic", 250.0)

        from src.services.engagement_service import EngagementService
        events, config = EngagementService().collect_due_events(pid)
        assert "uncontrolled" not in config
        assert "uncontrolled" not in {event["event_key"] for event in events}

    def test_high_reading_does_not_create_admin_worklist_or_sms(self, specialist_app):
        pid = _enroll("1110000304", "بدون پیام", phone_number="09120000304")
        _add_vital(pid, "hba1c", 20.0)
        _add_vital(pid, "bp_systolic", 250.0)

        from src.services.engagement_service import EngagementService
        result = EngagementService().dispatch_patient(pid, dry_run=True)
        assert result["worklist"] == 0
        assert result["queued"] == 0
        assert result["sms"] == 0

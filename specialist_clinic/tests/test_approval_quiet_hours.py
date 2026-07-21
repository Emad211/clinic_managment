"""
Quiet-hours guard for EngagementService.approve() — test suite.

Background (the gap this proves is closed): approve() sends the queued SMS the
moment the physician approves it. It must honor the SAME quiet-hours window as
the dispatch/preview paths (self._quiet_now()), so a physician approving at, say,
23:00 does NOT send a patient SMS outside the allowed window (default 08:00-21:00
Tehran; settings engagement_quiet_start / engagement_quiet_end). Physician
authority is preserved via override=True, which force-sends anyway.

Proves:
  (a) approve() during quiet hours → reason 'quiet', NOTHING dispatched, and the
      approval stays 'pending' (so it can be approved later or forced).
  (b) approve(override=True) during quiet hours → sends (via the NullProvider).
  (c) approve() outside quiet hours → sends normally.
  (+) the realistic flow: a quiet-blocked approval stays queued and a later
      force-send (override) delivers it.

Safety contract (mirrors test_visit_invites.py / test_invoice_outreach.py):
  - Fresh temp specialist DB in a tmp dir; the real clinic_new.db is never touched.
  - No real SMS: a fresh test DB seeds no SMS keys → get_provider() returns the
    simulated NullProvider (provider_msgid='SIMULATED'). approve() is the only
    thing that "sends", and only ever to that Null provider.
  - The quiet window is driven through the REAL settings path (set_setting), not
    by monkeypatching, but chosen deterministically so the suite never flakes on
    wall-clock time.

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_approval_quiet_hours.py -v
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── Patch env vars BEFORE any src import (Config is read at import time) ─────
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_REAL_ACC_DB = os.path.join(_REPO_ROOT, "webapp", "clinic_new.db")
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")

import shutil
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helpers (mirror test_visit_invites.py conventions)
# ---------------------------------------------------------------------------

def _flush_src_modules():
    """Delete all src.* modules so the next import re-reads env vars and gets a
    clean Config / core._initialized state."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="quiet_test_")
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
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB  # default; not used by these tests

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


def _enroll(national_id, full_name, phone_number=None, sms_opt_out=0):
    """Insert a patient_links row via get_db() (schema already bootstrapped).
    Returns patient_links.id. Must run inside the pushed app_context."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    cur = db.execute(
        """INSERT INTO patient_links
             (national_id, full_name, phone_number, sms_opt_out, enrolled_by)
           VALUES (?, ?, ?, ?, 'test')""",
        (national_id, full_name, phone_number, sms_opt_out))
    db.commit()
    return cur.lastrowid


def _force_quiet(quiet: bool):
    """Drive EngagementService._quiet_now() to `quiet` for the current Tehran time
    via the REAL settings path (no monkeypatching). Deterministic for any
    wall-clock: _quiet_now does a naive lexicographic HH:MM compare of
    `start <= now <= end`, so we pick a window accordingly and avoid midnight wrap."""
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.common.utils import iran_now
    sms = SmsRepository()
    if not quiet:
        # Whole-day window → now is always inside → NOT quiet.
        sms.set_setting("engagement_quiet_start", "00:00")
        sms.set_setting("engagement_quiet_end", "23:59")
    else:
        # A 1-hour window that does NOT contain now (no midnight wrap either side).
        now = iran_now().strftime("%H:%M")
        start, end = ("23:00", "23:59") if now < "12:00" else ("00:00", "01:00")
        sms.set_setting("engagement_quiet_start", start)
        sms.set_setting("engagement_quiet_end", end)


def _counts(pid):
    """(sms_messages count, sms-dispatch ledger count) for a patient — both must be
    zero when nothing was sent."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    msgs = db.execute(
        "SELECT COUNT(*) c FROM sms_messages WHERE patient_link_id=?", (pid,)
    ).fetchone()["c"]
    disp = db.execute(
        "SELECT COUNT(*) c FROM engagement_dispatch WHERE channel='sms' AND patient_link_id=?",
        (pid,)).fetchone()["c"]
    return msgs, disp


def _queue_one(svc, pid, period_key):
    """Queue exactly one pending sms approval for the patient; return its id."""
    aid = svc.enqueue_event_for_patient(pid, "lab_consult_invite", period_key=period_key)
    assert aid is not None, "enqueue_event_for_patient must queue an approval"
    return aid


# ===========================================================================
# The quiet-hours guard on approve()
# ===========================================================================

class TestApproveQuietHoursGate:

    def test_provider_is_null_in_test_env(self, specialist_app):
        """Precondition: the test env never has a live SMS panel."""
        from src.services.sms.provider import get_provider, NullProvider
        assert isinstance(get_provider(), NullProvider), (
            "test env must use the simulated NullProvider — never a live panel")

    # (a) -------------------------------------------------------------------
    def test_quiet_hours_blocks_and_does_not_dispatch(self, specialist_app):
        """During quiet hours, approve() (no override) returns reason 'quiet',
        sends nothing, and leaves the approval pending and untouched."""
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        pid = _enroll("2220000001", "ساعتِ آرام", phone_number="09120000201")
        aid = _queue_one(svc, pid, "lab_consult_invite:2026-06-20")

        _force_quiet(True)
        assert svc._quiet_now() is True, "precondition: must be inside quiet hours"

        out = svc.approve(aid, decided_by="admin")

        assert out == {"ok": False, "reason": "quiet"}, (
            f"approve() during quiet hours must return reason 'quiet', got {out}")
        # Nothing dispatched.
        assert _counts(pid) == (0, 0), (
            f"quiet-blocked approve() must not send any SMS or write a dispatch row, "
            f"got (sms_messages, dispatch)={_counts(pid)}")
        # Approval untouched and still actionable later.
        ap = svc.repo.get_approval(aid)
        assert ap["status"] == "pending", (
            f"quiet-blocked approval must stay 'pending', got {ap['status']}")
        assert ap["sent_at"] is None, "quiet-blocked approval must not be stamped sent"
        assert ap["decided_by"] is None, (
            "quiet-blocked approval must not record a decision (status untouched)")

    # (b) -------------------------------------------------------------------
    def test_override_sends_during_quiet_hours(self, specialist_app):
        """override=True bypasses the quiet gate and sends (via NullProvider),
        preserving physician authority."""
        from src.adapters.sqlite.core import get_db
        from src.services.engagement_service import EngagementService
        db = get_db()
        svc = EngagementService()
        pid = _enroll("2220000002", "ارسالِ فوری", phone_number="09120000202")
        aid = _queue_one(svc, pid, "lab_consult_invite:2026-06-20")

        _force_quiet(True)
        assert svc._quiet_now() is True, "precondition: must be inside quiet hours"

        out = svc.approve(aid, decided_by="admin", override=True)

        assert out.get("ok") is True, (
            f"approve(override=True) must send even during quiet hours, got {out}")
        ap = svc.repo.get_approval(aid)
        assert ap["status"] == "approved", f"must be approved, got {ap['status']}"
        assert ap["sent_at"] is not None, "override send must stamp sent_at"
        assert _counts(pid) == (1, 1), (
            f"override send must log one sms_messages row and one sms dispatch, "
            f"got {_counts(pid)}")
        m = dict(db.execute(
            "SELECT * FROM sms_messages WHERE patient_link_id=?", (pid,)).fetchone())
        assert m["status"] == "sent" and m["provider_msgid"] == "SIMULATED", (
            "override send must go through the simulated NullProvider, not a live panel")

    # (c) -------------------------------------------------------------------
    def test_outside_quiet_hours_sends_normally(self, specialist_app):
        """Outside quiet hours, a plain approve() (no override) sends normally."""
        from src.adapters.sqlite.core import get_db
        from src.services.engagement_service import EngagementService
        db = get_db()
        svc = EngagementService()
        pid = _enroll("2220000003", "ساعتِ مجاز", phone_number="09120000203")
        aid = _queue_one(svc, pid, "lab_consult_invite:2026-06-20")

        _force_quiet(False)
        assert svc._quiet_now() is False, "precondition: must be outside quiet hours"

        out = svc.approve(aid, decided_by="admin")

        assert out.get("ok") is True, (
            f"approve() outside quiet hours must send normally, got {out}")
        ap = svc.repo.get_approval(aid)
        assert ap["status"] == "approved" and ap["sent_at"] is not None
        assert _counts(pid) == (1, 1), (
            f"normal send must log one sms_messages row and one sms dispatch, "
            f"got {_counts(pid)}")

    # (+) realistic flow ----------------------------------------------------
    def test_quiet_blocked_then_force_send_delivers(self, specialist_app):
        """The intended UX: approving during quiet hours leaves the message queued;
        a subsequent force-send (override) on the SAME approval delivers it."""
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        pid = _enroll("2220000004", "صف‌ماند‌سپس‌ارسال", phone_number="09120000204")
        aid = _queue_one(svc, pid, "lab_consult_invite:2026-06-20")

        _force_quiet(True)
        assert svc._quiet_now() is True

        # First attempt is blocked but the approval survives.
        first = svc.approve(aid, decided_by="admin")
        assert first == {"ok": False, "reason": "quiet"}
        assert svc.repo.get_approval(aid)["status"] == "pending"
        assert _counts(pid) == (0, 0)

        # Physician forces it through.
        second = svc.approve(aid, decided_by="admin", override=True)
        assert second.get("ok") is True
        assert svc.repo.get_approval(aid)["status"] == "approved"
        assert _counts(pid) == (1, 1)


class TestApprovalProductionLifecycle:

    def test_daily_cap_keeps_second_message_pending(self, specialist_app):
        from src.adapters.sqlite.sms_repo import SmsRepository
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        pid = _enroll("2220000010", "سقف روزانه", phone_number="09120000210")
        SmsRepository().set_setting("engagement_daily_cap", "1")
        _force_quiet(False)
        first = _queue_one(svc, pid, "cap:first")
        second = svc.enqueue_event_for_patient(pid, "bp_glucose_invite", "cap:second")
        assert svc.approve(first, decided_by="admin")["ok"] is True

        result = svc.approve(second, decided_by="admin")

        assert result == {"ok": False, "reason": "daily_cap"}
        assert svc.repo.get_approval(second)["status"] == "pending"
        assert _counts(pid) == (1, 1)

    def test_accepted_message_is_linked_and_second_click_is_idempotent(self, specialist_app):
        from src.adapters.sqlite.core import get_db
        from src.services.engagement_service import EngagementService
        svc = EngagementService()
        pid = _enroll("2220000011", "ارسال یکتا", phone_number="09120000211")
        aid = _queue_one(svc, pid, "unique:period")
        _force_quiet(False)

        first = svc.approve(aid, decided_by="admin")
        second = svc.approve(aid, decided_by="admin")

        ap = svc.repo.get_approval(aid)
        msg = dict(get_db().execute(
            "SELECT * FROM sms_messages WHERE id=?", (ap["sms_message_id"],)).fetchone())
        assert first["ok"] is True
        assert second == {"ok": False, "reason": "not_pending"}
        assert msg["idempotency_key"] == f"engagement:approval:{aid}"
        assert msg["source_type"] == "engagement" and msg["source_ref"] == str(aid)
        assert _counts(pid) == (1, 1)

    def test_retryable_provider_failure_stays_actionable(self, specialist_app, monkeypatch):
        from src.services.sms.provider import SmsProvider, SendResult
        from src.services.engagement_service import EngagementService
        import src.services.sms.campaign_service as campaign_service

        class RetryableProvider(SmsProvider):
            def send(self, recipient, body, message_type=None):
                return SendResult(ok=False, retryable=True,
                                  delivery_status="RetryableFailure",
                                  error="موجودی پنل کافی نیست")

        monkeypatch.setattr(campaign_service, "get_provider", lambda: RetryableProvider())
        svc = EngagementService()
        pid = _enroll("2220000012", "خطای قابل ادامه", phone_number="09120000212")
        aid = _queue_one(svc, pid, "retryable:period")
        _force_quiet(False)

        result = svc.approve(aid, decided_by="admin")

        ap = svc.repo.get_approval(aid)
        assert result["reason"] == "retryable_failure"
        assert ap["status"] == "pending"
        assert ap["last_error"] == "موجودی پنل کافی نیست"
        assert ap["sms_message_id"] is not None
        assert _counts(pid) == (1, 0)

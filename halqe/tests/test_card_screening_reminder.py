"""
test_card_screening_reminder.py — خوشهٔ J، قدم ۴۸
یادآورهای غربالگریِ بیمار-ایمن روی کارتِ عمومی.

طراحیِ قفل‌شده (GP + security — حریمِ خصوصی اولویتِ #۱):
  reminder_message یک پیامِ خنثیِ server-rendered است که از
  screening_timeline (read-only) مشتق می‌شود. هرگز نباید تشخیص/آزمایش/تاریخ/
  عددِ دقیقِ شمارش را فاش کند.

ادعاهای این فایل:
  ۱) آیتمِ overdue/due_soon → reminder_message غیرnull و خنثی.
  ۲) فقط never_done/ok → reminder_message=None.
  ۳) نوبتِ آینده موجود + آیتم → پیامِ «در نوبتِ بعدی...» (نه CTAِ تماس).
  ۴) count-cap: ۱ آیتم→«یک مورد»، ≥۲→«چند مورد» (عددِ دقیق فاش نشود).
  ۵) گاردِ نشتِ تشخیص (بحرانی): پاسخِ کامل هیچ واژهٔ بالینی/condition_code/
     item_key/label_fa ندارد.
  ۶) GUC/cross-tenant: کارتِ tenant-A یادآورِ tenant-B را نشان ندهد.
  ۷) zero-write: مسیرِ کارت با یادآور هیچ نوشتنی روی DB انجام ندهد.

این تست‌ها به Docker Postgres نیاز دارند (مثلِ سایرِ تست‌های card).
Helperها (psycopg autocommit) و teardown از قراردادِ test_patient_card_token.py
پیروی می‌کنند: همهٔ بیمارانِ accounting با national_id LIKE 'SCRN%' در teardown
پاک می‌شوند.
"""
import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

from tests.test_patient_card_token import _issue_token_via_service


pytestmark = pytest.mark.django_db(
    transaction=True, databases=["default", "accounting_read"]
)


# ---------------------------------------------------------------------------
# Helpers — superuser psycopg (autocommit) seed، مستقل از Django rollback
# ---------------------------------------------------------------------------

def _insert_scrn_patient(conn, tenant_id: int = 1) -> tuple[int, int]:
    """بیمارِ accounting + patient_link (national_id LIKE 'SCRN%')."""
    nat = secrets.token_hex(5)
    conn.execute(
        f"""INSERT INTO accounting.patients
                (tenant_id, name, family_name, national_id, phone_number)
            VALUES ({tenant_id}, 'غربال', 'تستی', 'SCRN{nat}', '09990000001')
            ON CONFLICT DO NOTHING"""
    )
    pid = conn.execute(
        f"SELECT id FROM accounting.patients WHERE national_id='SCRN{nat}'"
    ).fetchone()[0]
    conn.execute(
        f"""INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES ({tenant_id}, {pid}, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING"""
    )
    link_id = conn.execute(
        f"SELECT id FROM clinical.patient_links "
        f"WHERE tenant_id={tenant_id} AND patient_id={pid}"
    ).fetchone()[0]
    return pid, link_id


def _add_diabetes(conn, link_id: int, tenant_id: int = 1):
    """
    condition با code='diabetes' فعال می‌کند تا آیتمِ غربالگریِ a1c/eye/foot
    در screening_timeline ظاهر شود (ITEM_CONDITIONS['a1c']==['diabetes']).

    اول condition موجودِ code='diabetes' (seedِ slice2) را reuse می‌کند تا ردیفِ
    تکراری نسازد؛ فقط در نبودش یک ردیف با نامِ یکتا می‌سازد (clinical.conditions
    UNIQUE روی (tenant_id, name) است). screening_timeline با Condition.code فیلتر
    می‌کند، نه name.
    """
    row = conn.execute(
        f"SELECT id FROM clinical.conditions "
        f"WHERE tenant_id={tenant_id} AND code='diabetes' LIMIT 1"
    ).fetchone()
    if row:
        cond_id = row[0]
    else:
        # seed برای tenant-1 idها را صریح درج کرده و sequence را جلو نبرده —
        # قبل از insertِ خودکار، sequence را با max(id) همگام کن.
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('clinical.conditions','id'), "
            "(SELECT GREATEST(MAX(id), 1) FROM clinical.conditions))"
        )
        name = f"دیابت_SCRN_{secrets.token_hex(3)}"
        conn.execute(
            f"""INSERT INTO clinical.conditions
                    (tenant_id, code, name, is_chronic, display_order)
                VALUES ({tenant_id}, 'diabetes', '{name}', TRUE, 99)
                ON CONFLICT (tenant_id, name) DO NOTHING"""
        )
        cond_id = conn.execute(
            f"SELECT id FROM clinical.conditions "
            f"WHERE tenant_id={tenant_id} AND code='diabetes' LIMIT 1"
        ).fetchone()[0]
    conn.execute(
        f"""INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES ({tenant_id}, {link_id}, {cond_id}, TRUE, now())
            ON CONFLICT DO NOTHING"""
    )


def _insert_obs(conn, link_id: int, vtype: str, months_ago: float,
                tenant_id: int = 1):
    """
    یک vital_reading (clinic-entered, verified=TRUE) با measured_at در گذشته.
    این "last done" را برای آیتمِ غربالگری می‌بندد (_last_done فقط verified=TRUE
    را می‌شمارد — slice13 safety gate).

    months_ago کنترلِ status را می‌دهد (a1c interval = 6 ماه):
      - ۱۰ ماه پیش → overdue
      - ~۵.۷ ماه پیش → due_soon (next_due در < ۳۰ روز)
      - ۱ ماه پیش → ok
    months_ago کسری مجاز است (روزها = round(months_ago * 30)).
    """
    days = int(round(months_ago * 30))
    when = (timezone.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S%z")
    conn.execute(
        f"""INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at,
                 source, verified)
            VALUES ({tenant_id}, {link_id}, '{vtype}', 7.0, '%', '{when}',
                    'clinic', TRUE)"""
    )


def _insert_flag(conn, link_id: int, flag_key: str, value: str,
                 tenant_id: int = 1):
    conn.execute(
        f"""INSERT INTO clinical.patient_flags
                (tenant_id, patient_link_id, flag_key, value)
            VALUES ({tenant_id}, {link_id}, '{flag_key}', '{value}')"""
    )


def _insert_appt(conn, link_id: int, days_ahead: int = 7, tenant_id: int = 1):
    when = (timezone.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d %H:%M:%S%z")
    conn.execute(
        f"""INSERT INTO clinical.appointments
                (tenant_id, patient_link_id, scheduled_at, appt_type, status, created_at)
            VALUES ({tenant_id}, {link_id}, '{when}', 'control', 'scheduled', now())"""
    )


# ---------------------------------------------------------------------------
# Fixture — superuser connection + teardown (SCRN%)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scrn_conn():
    import psycopg
    from tests.conftest import (
        PG_HOST, PG_PORT, PG_SU_USER, PG_SU_PASSWORD, TEST_DB_NAME
    )
    conn = psycopg.connect(
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'",
        autocommit=True,
    )
    yield conn
    # teardown: همهٔ ردیف‌های SCRN% را پاک کن (autocommit → Django rollback پاک نمی‌کند)
    try:
        rows = conn.execute(
            "SELECT id FROM accounting.patients WHERE national_id LIKE 'SCRN%'"
        ).fetchall()
        pids = [r[0] for r in rows]
        if pids:
            link_subq = "SELECT id FROM clinical.patient_links WHERE patient_id = ANY(%s)"
            conn.execute(
                f"DELETE FROM clinical.patient_card_tokens WHERE patient_link_id IN ({link_subq})",
                (pids,),
            )
            for tbl in ("vital_readings", "lab_results", "patient_medications",
                        "patient_conditions", "patient_flags", "appointments"):
                conn.execute(
                    f"DELETE FROM clinical.{tbl} WHERE patient_link_id IN ({link_subq})",
                    (pids,),
                )
            conn.execute(
                "DELETE FROM clinical.patient_links WHERE patient_id = ANY(%s)", (pids,)
            )
            conn.execute(
                "DELETE FROM accounting.patients WHERE national_id LIKE 'SCRN%'"
            )
    except Exception:
        pass
    conn.close()


# ===========================================================================
# ۱) آیتمِ overdue/due_soon → reminder_message غیرnull و خنثی
# ===========================================================================

class TestReminderPresent:

    def test_overdue_item_produces_reminder(self, client, scrn_conn, seed_data):
        """دیابتی با HbA1cِ ۱۰ ماه پیش (interval=6) → overdue → reminder غیرnull."""
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)  # overdue
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body = resp.json()
        assert "reminder_message" in body
        assert body["reminder_message"] is not None
        assert "مراقبتِ دوره‌ای" in body["reminder_message"]

    def test_due_soon_item_produces_reminder(self, client, scrn_conn, seed_data):
        """HbA1cِ ~۵.۳ ماه پیش (interval=6، next_due در ۲۰ روز) → due_soon → reminder."""
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=5.7)  # next_due ~ +9d → due_soon
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        assert resp.json()["reminder_message"] is not None


# ===========================================================================
# ۲) فقط never_done/ok → reminder_message=None
# ===========================================================================

class TestReminderSuppressed:

    def test_never_done_suppressed(self, client, scrn_conn, seed_data):
        """دیابتیِ تازه (هیچ lab/flag) → آیتم‌ها never_done → reminder=None."""
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        # هیچ lab/flag → همهٔ آیتم‌ها never_done (که حذف می‌شوند)
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        assert resp.json()["reminder_message"] is None, (
            "never_done باید کاملاً suppress شود (مثبت‌کاذبِ بیمارِ تازه)"
        )

    def test_recent_done_ok_suppressed(self, client, scrn_conn, seed_data):
        """HbA1cِ ۱ ماه پیش (interval=6) → ok → reminder=None."""
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=1)  # ok (done recently)
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        assert resp.json()["reminder_message"] is None, (
            "آیتمِ ok نباید reminder تولید کند"
        )

    def test_no_conditions_no_reminder(self, client, scrn_conn, seed_data):
        """بیمارِ بدونِ هیچ condition → هیچ آیتمِ مرتبط → reminder=None."""
        _, link = _insert_scrn_patient(scrn_conn)
        # بدونِ _add_diabetes → screening_timeline خالی
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        assert resp.json()["reminder_message"] is None


# ===========================================================================
# ۳) نوبتِ آینده + آیتم → پیامِ «در نوبتِ بعدی...» (نه CTAِ تماس)
# ===========================================================================

class TestNextVisitSuppressesCTA:

    def test_next_appointment_softens_message(self, client, scrn_conn, seed_data):
        """آیتمِ overdue + نوبتِ آینده → پیامِ نرم بدونِ CTAِ تماس."""
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)  # overdue
        _insert_appt(scrn_conn, link, days_ahead=7)
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        msg = resp.json()["reminder_message"]
        assert msg is not None
        assert "در نوبتِ بعدی" in msg, "با نوبتِ آینده باید پیامِ «در نوبتِ بعدی...» باشد"
        assert "تماس بگیرید" not in msg, (
            "با نوبتِ آینده نباید CTAِ تماس داشته باشد"
        )


# ===========================================================================
# ۴) count-cap: ۱ آیتم→«یک مورد»، ≥۲→«چند مورد»
# ===========================================================================

class TestCountCap:

    def test_single_item_says_one(self, client, scrn_conn, seed_data):
        """دقیقاً ۱ آیتمِ overdue (a1c) → «یک مورد»."""
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)  # a1c overdue
        # eye/foot/renal/lipid هنوز never_done‌اند (حذف می‌شوند) → فقط a1c due
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        msg = resp.json()["reminder_message"]
        assert msg is not None
        assert "یک مورد" in msg, f"یک آیتم باید «یک مورد» بدهد، گرفت: {msg}"

    def test_multiple_items_say_chand_not_exact_count(self, client, scrn_conn, seed_data):
        """
        ≥۲ آیتمِ سررسیده → «چند مورد»، و عددِ دقیق (۲/۳/...) فاش نشود.

        a1c (lab، overdue) + eye + foot (flag-date در گذشتهٔ دور، interval=12).
        """
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)  # a1c overdue
        # eye/foot flag با تاریخِ ۲ سال پیش (interval=12 ماه) → overdue
        old = (timezone.now() - timedelta(days=730)).date().isoformat()
        _insert_flag(scrn_conn, link, "eye_exam_date", old)
        _insert_flag(scrn_conn, link, "foot_exam_date", old)
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        msg = resp.json()["reminder_message"]
        assert msg is not None
        assert "چند مورد" in msg, f"≥۲ آیتم باید «چند مورد» بدهد، گرفت: {msg}"
        # عددِ دقیق نباید فاش شود (۳ آیتم: a1c+eye+foot).
        # فقط رقم‌های مستقل (لاتین/فارسی) را چک می‌کنیم؛ واژه‌های «دو/سه»
        # عمداً چک نمی‌شوند چون به‌عنوان زیررشته در «دوره‌ای» ظاهر می‌شوند
        # (false-positive) — پیامِ hardcode هرگز شمارش را به‌صورتِ کلمه نمی‌گوید.
        import re
        assert not re.search(r"[0-9۰-۹]", msg), (
            f"هیچ رقمِ شمارشی نباید در پیام باشد؛ گرفت: {msg!r}"
        )
        # الگوی شمارشِ صریحِ کلمه‌ای هم نباشد ("دو مورد"/"سه مورد"/...)
        for phrase in ("دو مورد", "سه مورد", "چهار مورد", "دو موردِ", "سه موردِ"):
            assert phrase not in msg, (
                f"عددِ دقیقِ آیتم‌ها به‌صورتِ کلمه فاش شد؛ یافت: {phrase!r}"
            )


# ===========================================================================
# ۵) گاردِ نشتِ تشخیص (بحرانی)
# ===========================================================================

# واژه‌های ممنوعهٔ بالینی + کلیدها/کدهای آیتم که نباید روی کارتِ عمومی ظاهر شوند
_FORBIDDEN_DIAGNOSIS_TOKENS = (
    # واژه‌های بالینی فارسی/انگلیسی
    "دیابت", "کلیه", "شبکیه", "چشم", "کبد", "غربالگری",
    "HbA1c", "hba1c", "eGFR", "egfr", "uacr", "UACR",
    # item_keyهای screening_timeline
    "a1c", "renal", "lipid", "eye", "foot", "neuropathy", "masld", "tsh",
    # condition_codeها
    "diabetes", "hypertension", "ckd", "hyperlipidemia", "thyroid",
    # last_done/next_due/interval — نشانگرهای per-item
    "last_done", "next_due", "interval_months", "condition_code",
    "item_key", "label_fa",
)


class TestNoDiagnosisLeak:

    def test_full_response_has_no_diagnosis_tokens(self, client, scrn_conn, seed_data):
        """
        پاسخِ کاملِ get_public_card (با reminder فعال) هیچ واژهٔ بالینی/کلیدِ
        per-item را نداشته باشد — مثلِ گاردِ national_idِ موجود اما برای تشخیص.
        """
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)  # overdue
        old = (timezone.now() - timedelta(days=730)).date().isoformat()
        _insert_flag(scrn_conn, link, "eye_exam_date", old)
        token = _issue_token_via_service(link)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        # اطمینان از اینکه reminder واقعاً فعال است (وگرنه گارد بی‌معنی است)
        assert resp.json()["reminder_message"] is not None
        body_str = str(resp.json())
        for tok in _FORBIDDEN_DIAGNOSIS_TOKENS:
            assert tok not in body_str, (
                f"واژهٔ تشخیصی/کلیدِ per-item «{tok}» در پاسخِ کارت نشت کرد: {body_str}"
            )

    def test_projection_dict_has_no_per_item_keys(self, scrn_conn, seed_data):
        """
        گاردِ سطحِ projection: خروجیِ card_for_patient فقط کلیدهای مجاز دارد و
        هیچ ساختارِ per-item غربالگری ندارد (نشتِ قبل از سریال‌سازی).
        """
        from platform_core.tenant_context import set_tenant_guc
        from clinical.card_projection_service import card_for_patient

        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)
        set_tenant_guc(1)
        proj = card_for_patient(link, 1)
        assert proj is not None
        ALLOWED = {
            "first_name", "clinic_name", "vitals", "next_appointment",
            "framing", "reminder_message",
        }
        assert set(proj.keys()) == ALLOWED, (
            f"projection کلیدِ غیرمجاز دارد: {set(proj.keys()) - ALLOWED}"
        )
        # reminder_message یک رشته است، نه list/dict (هیچ per-item)
        assert proj["reminder_message"] is None or isinstance(
            proj["reminder_message"], str
        )
        # واژه‌های ممنوعه در dict هم نباشند
        proj_str = str(proj)
        for tok in ("a1c", "diabetes", "condition_code", "item_key", "next_due"):
            assert tok not in proj_str, (
                f"کلیدِ per-item «{tok}» در projection dict نشت کرد"
            )


# ===========================================================================
# ۶) GUC/cross-tenant — کارتِ tenant-A یادآورِ tenant-B را نشان ندهد
# ===========================================================================

class TestTenantIsolation:

    def test_tenant_a_card_ignores_tenant_b_screening(
        self, client, scrn_conn, seed_clinical_data
    ):
        """
        بیمارِ tenant-1 بدونِ هیچ آیتمِ سررسیده → reminder=None، حتی اگر tenant-2
        بیمارِ دیگری با آیتمِ overdue داشته باشد. RLS باید screening_timeline را
        به tenant-1 محدود کند.
        """
        from platform_core.tenant_context import set_tenant_guc

        # tenant-2: بیمار با HbA1cِ overdue (نباید روی کارتِ tenant-1 دیده شود)
        try:
            _, link2 = _insert_scrn_patient(scrn_conn, tenant_id=2)
        except Exception:
            pytest.skip("tenant-2 موجود نیست — seed_clinical_data اجرا نشده")
        _add_diabetes(scrn_conn, link2, tenant_id=2)
        _insert_obs(scrn_conn, link2, "hba1c", months_ago=10, tenant_id=2)

        # tenant-1: بیمارِ تازه، دیابتی اما هیچ lab → never_done → reminder=None
        _, link1 = _insert_scrn_patient(scrn_conn, tenant_id=1)
        _add_diabetes(scrn_conn, link1, tenant_id=1)

        set_tenant_guc(1)
        token1 = _issue_token_via_service(link1, tenant_id=1)
        resp = client.get(f"/api/v1/card/{token1}")
        assert resp.status_code == 200
        assert resp.json()["reminder_message"] is None, (
            "کارتِ tenant-1 نباید یادآورِ آیتمِ tenant-2 را نشان دهد (RLS)"
        )


# ===========================================================================
# ۷) zero-write — مسیرِ کارت با یادآور هیچ نوشتنی نکند
# ===========================================================================

class TestZeroWriteWithReminder:

    def test_no_write_on_card_with_reminder(self, client, scrn_conn, seed_data):
        """
        GET /card با reminder فعال نباید روی followup_tasks بنویسد.
        screening_timeline read-only است و هرگز followup_tasks نمی‌سازد.
        """
        _, link = _insert_scrn_patient(scrn_conn)
        _add_diabetes(scrn_conn, link)
        _insert_obs(scrn_conn, link, "hba1c", months_ago=10)  # overdue → reminder فعال
        token = _issue_token_via_service(link)

        before = scrn_conn.execute(
            "SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables "
            "WHERE schemaname='clinical' AND relname='followup_tasks'"
        ).fetchone()

        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        assert resp.json()["reminder_message"] is not None  # reminder واقعاً فعال

        after = scrn_conn.execute(
            "SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables "
            "WHERE schemaname='clinical' AND relname='followup_tasks'"
        ).fetchone()

        if before and after:
            assert before == after, (
                f"GET /card با reminder روی followup_tasks نوشت!\n"
                f"  قبل: {before}\n  بعد: {after}"
            )

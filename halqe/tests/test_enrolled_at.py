"""
test_enrolled_at.py — قدم ۷۸ (S6): PatientLink.enrolled_at باید settable باشد (db_default).

باگ (راستی‌آزمایی‌شده در دورِ خصمانه): `enrolled_at = DateTimeField(auto_now_add=True)` هر
مقداری که caller ست کند را **بی‌صدا** با زمانِ درج جایگزین می‌کرد → importِ آیندهٔ بیمار
نمی‌توانست تاریخِ واقعیِ نام‌نویسی را ثبت کند → پنجره‌های baselineِ cohort_outcome
(anchor روی enrolled_at ±۳۰/۹۰ روز) خراب می‌شد.

رفع: `db_default=Now()` — ستون **settable** است (مقدارِ backdatedِ import حفظ می‌شود) و وقتی
ست نشود، DEFAULT now()ِ DB (slice0:129) اعمال می‌شود (هرگز NULL).

هیچ‌جای کدبیس امروز PatientLink را با ORM می‌سازد (همهٔ ساختِ link راه SQL خام است)؛ این تست‌ها
قراردادِ ORM-createِ موردنیازِ importِ آینده (خوشهٔ V) را قفل می‌کنند — جایی که باگ واقعاً می‌گزید.

PG-only: یک بیمارِ accounting را با superuser seed می‌کند، link را با ORM می‌سازد
(رولِ app، GUC=1 از fixtureِ autouse).
"""
import os
import uuid
import datetime

import psycopg
import pytest
from django.utils import timezone as dj_timezone

_CONNINFO = (
    f"host='{os.environ.get('PG_HOST', 'localhost')}' "
    f"port='{os.environ.get('PG_PORT', '55432')}' "
    f"user='{os.environ.get('PG_USER', 'postgres')}' "
    f"password='{os.environ.get('PG_PASSWORD', 'validate_only')}' "
    f"dbname='{os.environ.get('PG_TEST_DB', 'halqe_app_test')}'"
)


def _seed_accounting_patient() -> int:
    """Insert a fresh tenant-1 accounting patient (superuser) → return its id.

    Unique uuid/national_id so it has NO existing patient_link (avoids the
    UNIQUE(tenant_id, patient_id) collision when we ORM-create the link).
    """
    u = uuid.uuid4()
    nid = f"ENR{u.hex[:9]}"
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (1, %s, 'enrolltest', 'orm', %s, '09120000099', '1980-01-01', 'male')
            """,
            (u, nid),
        )
        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (u,)
        ).fetchone()
    return row[0]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_enrolled_at_settable_via_orm_preserves_backdated_value(seed_data):
    """ORM create with an explicit backdated enrolled_at preserves it (auto_now_add
    would have silently overridden it with now())."""
    from clinical.models import PatientLink

    patient_id = _seed_accounting_patient()
    backdated = dj_timezone.now() - datetime.timedelta(days=400)

    link = PatientLink.objects.create(
        tenant_id=1, patient_id=patient_id, enrolled_at=backdated,
    )
    link.refresh_from_db()

    delta = abs((link.enrolled_at - backdated).total_seconds())
    assert delta < 2, (
        "enrolled_at must preserve the backdated value the caller set "
        "(auto_now_add would override it); "
        f"set {backdated.isoformat()}, got {link.enrolled_at.isoformat()} (Δ={delta}s)"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_enrolled_at_defaults_to_now_when_unset(seed_data):
    """ORM create WITHOUT enrolled_at → DB DEFAULT now() applies (not NULL, no error)."""
    from clinical.models import PatientLink

    patient_id = _seed_accounting_patient()
    before = dj_timezone.now() - datetime.timedelta(minutes=5)

    link = PatientLink.objects.create(tenant_id=1, patient_id=patient_id)
    link.refresh_from_db()

    assert link.enrolled_at is not None, (
        "unset enrolled_at must be populated by the DB DEFAULT now(), never NULL"
    )
    after = dj_timezone.now() + datetime.timedelta(minutes=5)
    assert before <= link.enrolled_at <= after, (
        f"unset enrolled_at must default to ~now(); got {link.enrolled_at.isoformat()}"
    )

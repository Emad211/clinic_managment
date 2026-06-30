"""
test_single_tenant_guarantee.py — قدم ۷۴ (S2): تضمینِ تک‌مستأجریِ پایلوت.

پایلوتِ MVP تک‌مستأجر است: tenant id=1 seedِ سیستمی است و کلینیکِ پایلوت اولین
مستأجرِ provision‌شده (id>=2). در PRODUCTION، `provision_tenant` از ساختِ مستأجرِ
غیرپیش‌فرضِ **دوم** امتناع می‌کند مگر `ALLOW_ADDITIONAL_TENANT` رشتهٔ ACK را داشته باشد —
کلینیکِ دوم تریگرِ T1 است. این دفاع‌در‌عمق است؛ ایزولاسیونِ ردیف را RLS تضمین می‌کند
(tests/test_rls_coverage.py). dev/test (is_production=False) دست‌نخورده می‌ماند تا
تست‌های ایزولاسیونِ چندمستأجری آزادانه provision کنند.

assertها:
  ۱) prod + مستأجرِ غیرپیش‌فرض موجود + بدونِ ACK → ProvisioningError، هیچ مستأجرِ نو.
  ۲) prod + ACK                                  → مستأجرِ دوم ساخته می‌شود (id>=2).
  ۳) prod + re-provisionِ نامِ موجود              → مجاز (مسیرِ idempotent).
  ۴) dev (is_production=False)                    → مستأجرِ دوم آزادانه ساخته می‌شود
     (اثباتِ اینکه تست‌های ایزولاسیون که ۲ مستأجر seed می‌کنند نمی‌شکنند).

PG-only (provision_tenant تابعِ SECURITY DEFINER را صدا می‌زند)؛ روی Docker PG اجرا می‌شود.
"""
from __future__ import annotations

import uuid

import pytest
from django.db import connection

from platform_core.onboarding_service import provision_tenant, ProvisioningError


def _total_tenant_count() -> int:
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM platform.tenants")
        return cur.fetchone()[0]


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


@pytest.mark.django_db(databases=["default"])
def test_prod_blocks_second_nondefault_tenant(seed_clinical_data, monkeypatch):
    """seed_clinical_data ساختِ tenant 2 را committ کرده → مستأجرِ غیرپیش‌فرض از قبل هست."""
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.delenv("ALLOW_ADDITIONAL_TENANT", raising=False)

    before = _total_tenant_count()
    with pytest.raises(ProvisioningError, match="ALLOW_ADDITIONAL_TENANT"):
        provision_tenant(
            name=_unique("کلینیکِ دوم"),
            admin_username=_unique("admin").replace(" ", "_"),
            password="Pw1!secure",
        )
    after = _total_tenant_count()
    assert after == before, (
        f"گارد نباید هیچ مستأجری بسازد وقتی بلاک می‌کند؛ before={before} after={after}"
    )


@pytest.mark.django_db(databases=["default"])
def test_prod_with_ack_allows_second_tenant(seed_clinical_data, monkeypatch):
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_ADDITIONAL_TENANT", "clinic-2-approved")

    result = provision_tenant(
        name=_unique("کلینیکِ مجاز"),
        admin_username=_unique("admin").replace(" ", "_"),
        password="Pw1!secure",
    )
    assert result["tenant_id"] >= 2


@pytest.mark.django_db(databases=["default"])
def test_prod_idempotent_reprovision_of_existing_name_allowed(seed_clinical_data, monkeypatch):
    """re-provisionِ نامِ موجود باید حتی در prod بدونِ ACK مجاز باشد (idempotent)."""
    name = _unique("کلینیکِ موجود")

    # ساختِ اول در dev (گارد فعال نیست)
    monkeypatch.delenv("PRODUCTION", raising=False)
    first = provision_tenant(
        name=name, admin_username=_unique("admin").replace(" ", "_"), password="Pw1!secure"
    )

    # حالا prod بدونِ ACK — همان نام دوباره: باید مجاز باشد (مسیرِ idempotent)
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.delenv("ALLOW_ADDITIONAL_TENANT", raising=False)
    again = provision_tenant(
        name=name, admin_username=_unique("admin2").replace(" ", "_"), password="Pw1!secure"
    )
    assert again["tenant_id"] == first["tenant_id"], (
        "re-provisionِ idempotent باید همان tenant_id را بدهد، نه بلاک شود"
    )


@pytest.mark.django_db(databases=["default"])
def test_dev_unaffected_allows_additional_tenant(seed_clinical_data, monkeypatch):
    """is_production=False → گارد no-op → مستأجرِ دوم آزادانه ساخته می‌شود."""
    monkeypatch.delenv("PRODUCTION", raising=False)
    result = provision_tenant(
        name=_unique("کلینیکِ dev"),
        admin_username=_unique("admin").replace(" ", "_"),
        password="Pw1!secure",
    )
    assert result["tenant_id"] >= 2

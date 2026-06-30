"""
test_rls_coverage.py — قدم ۷۳ (S1): RLS Coverage AUDIT.

«پوششِ RLS by-convention» را به «asserted» تبدیل می‌کند — بنیانِ ادعای ایزولاسیونِ
تک‌مستأجرِ پایلوت + تعهدِ قراردادیِ چندمستأجری.

این تست **هر** جدولِ schemaهای clinical + platform را که ستونِ tenant_id دارد
برمی‌شمارد (با همان predicateِ حلقهٔ apply-timeِ slice5) و برای هرکدام assert می‌کند:
  - relrowsecurity = true            (ENABLE)
  - relforcerowsecurity = true       (FORCE — رولِ مالک/app هم مقید؛ سوپریوزرِ واقعی BYPASSRLS دارد)
  - یک policyِ به‌نامِ tenant_isolation که هر دو عبارتِ USING و WITH CHECK آن شاملِ
    الگوی کانونیِ current_setting('app.current_tenant', …) است
    (assertِ خودِ عبارت، نه فقط وجودِ policy → از regressِ آیندهٔ «USING true» جلوگیری می‌کند).

استثناهای عمدی یک allowlistِ **دقیق** (EXEMPT) است. پس از قدم ۷۳ که RLS را inline به
platform.settings افزود، این allowlist برای clinical+platform **خالی** است — هر جدولِ
tenant_id‌دار RLS-protected است، بدونِ استثنا. یک جدولِ tenant_id‌دارِ **جدید** که RLS
نگیرد این تست را می‌شکند (تصمیمِ آگاهانه اجباری می‌شود)؛ و یک ورودیِ allowlistِ کهنه
(جدولی که حالا پوشش گرفته) هم تست را می‌شکند.

نکته‌ها:
  - platform.users علاوه بر tenant_isolation (FORCE) یک policyِ دومِ
    tenant_isolation_read (FOR SELECT USING true) برای login bootstrap دارد. این audit
    فقط وجودِ tenant_isolation + FORCE را الزام می‌کند و policyِ اضافی را منع نمی‌کند،
    پس policyِ read-bootstrap مشکلی ایجاد نمی‌کند.
  - accounting.* عمداً خارج از scope است (T1) — شمارش به schemaهای clinical+platform محدود است.
  - PG-only (از pg_catalog می‌خواند)؛ روی Docker PG با sliceهای اعمال‌شده اجرا می‌شود
    (وابسته به fixtureِ django_db_setup در conftest).
"""
from __future__ import annotations

import os

import psycopg
import pytest

# ---------------------------------------------------------------------------
# Superuser connection — needed to read pg_catalog (relforcerowsecurity, pg_policy).
# Same env defaults as conftest.py / test_e2e_tenant_isolation.py.
# ---------------------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
_SU_USER = os.environ.get("PG_USER", "postgres")
_SU_PW   = os.environ.get("PG_PASSWORD", "validate_only")

_SU_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_SU_USER}' password='{_SU_PW}' dbname='{_TEST_DB}'"
)

# Schemas in scope. accounting.* is deliberately excluded (RLS deferred to T1).
_SCHEMAS = ["clinical", "platform"]

# EXACT allowlist of tenant_id-bearing tables intentionally WITHOUT full RLS.
# After step 73 (inline RLS added to platform.settings) this is EMPTY — every
# tenant_id table in clinical+platform is RLS-protected, no exceptions.
# To add a NEW tenant_id table without RLS you MUST add it here WITH a rationale,
# or (preferred) enable RLS inline in its own slice. A new uncovered table that is
# not listed here will FAIL test_tenant_table_rls_coverage_is_complete.
EXEMPT: frozenset[tuple[str, str]] = frozenset()

# Substring both USING and WITH CHECK expressions of the tenant_isolation policy
# must contain — guards against a future redefinition to `USING (true)`.
_CANON = "app.current_tenant"

# Enumerate tenant_id-bearing base tables + their RLS state in ONE query.
# Mirrors slice5's enable-loop predicate (relkind='r', schema in scope, has a
# non-dropped tenant_id column). `has_canon_policy` is TRUE only when a policy
# named tenant_isolation exists AND both its USING and WITH CHECK expressions
# reference app.current_tenant (NULL WITH CHECK → LIKE NULL → not TRUE → fails).
_AUDIT_SQL = """
SELECT n.nspname  AS schema_name,
       c.relname  AS table_name,
       c.relrowsecurity      AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       EXISTS (
           SELECT 1 FROM pg_policy p
           WHERE p.polrelid = c.oid
             AND p.polname   = 'tenant_isolation'
             AND pg_get_expr(p.polqual,      p.polrelid) LIKE %(canon)s
             AND pg_get_expr(p.polwithcheck, p.polrelid) LIKE %(canon)s
       ) AS has_canon_policy
FROM   pg_class     c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  c.relkind = 'r'
  AND  n.nspname = ANY(%(schemas)s)
  AND  EXISTS (
           SELECT 1 FROM pg_attribute a
           WHERE a.attrelid = c.oid
             AND a.attname  = 'tenant_id'
             AND NOT a.attisdropped
       )
ORDER BY n.nspname, c.relname
"""


def _audit_rows():
    """Return list of dicts: schema_name, table_name, rls_enabled, rls_forced, has_canon_policy."""
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        rows = conn.execute(
            _AUDIT_SQL,
            {"schemas": _SCHEMAS, "canon": f"%{_CANON}%"},
        ).fetchall()
    return [
        {
            "schema": r[0],
            "table": r[1],
            "rls_enabled": r[2],
            "rls_forced": r[3],
            "has_canon_policy": r[4],
        }
        for r in rows
    ]


def _is_covered(row) -> bool:
    return bool(row["rls_enabled"] and row["rls_forced"] and row["has_canon_policy"])


# ===========================================================================
# Sanity — the audit actually found tenant tables (guard against false-green
# from a wrong/empty DB).
# ===========================================================================

def test_audit_finds_tenant_tables(django_db_setup):
    rows = _audit_rows()
    assert len(rows) >= 5, (
        f"RLS audit found only {len(rows)} tenant_id tables in {_SCHEMAS} — "
        "expected the full clinical+platform set. Wrong DB or slices not applied?"
    )


# ===========================================================================
# CORE invariant — the set of uncovered tenant tables == the EXACT allowlist.
# A new uncovered table fails here (forces a conscious decision); a stale
# allowlist entry (now covered) also fails (see test_exempt_allowlist_not_stale).
# ===========================================================================

def test_tenant_table_rls_coverage_is_complete(django_db_setup):
    rows = _audit_rows()
    uncovered = {
        (r["schema"], r["table"]) for r in rows if not _is_covered(r)
    }
    assert uncovered == set(EXEMPT), (
        "RLS coverage gap! Tenant_id tables WITHOUT full RLS "
        "(ENABLE+FORCE+canonical tenant_isolation policy):\n"
        + "\n".join(f"  - {s}.{t}" for s, t in sorted(uncovered - set(EXEMPT)))
        + (
            "\n\nFix: enable RLS inline in the owning slice (ENABLE+FORCE+"
            "tenant_isolation with the NULLIF current_setting pattern), like "
            "slices 8/9/10/12/13/16 — OR, if intentionally app-level-scoped, add "
            "the table to EXEMPT with a rationale.\n"
        )
        + (
            f"\nUnexpectedly-covered allowlist entries (remove from EXEMPT): "
            f"{sorted(set(EXEMPT) - uncovered)}"
            if set(EXEMPT) - uncovered else ""
        )
    )


# ===========================================================================
# Readable per-table assertions (better failure messages).
# ===========================================================================

def test_each_tenant_table_has_rls_enabled_and_forced(django_db_setup):
    rows = _audit_rows()
    offenders = [
        f"{r['schema']}.{r['table']} (enabled={r['rls_enabled']}, forced={r['rls_forced']})"
        for r in rows
        if (r["schema"], r["table"]) not in EXEMPT
        and not (r["rls_enabled"] and r["rls_forced"])
    ]
    assert not offenders, (
        "These tenant_id tables lack ENABLE+FORCE ROW LEVEL SECURITY:\n  "
        + "\n  ".join(offenders)
    )


def test_each_tenant_table_has_canonical_isolation_policy(django_db_setup):
    rows = _audit_rows()
    offenders = [
        f"{r['schema']}.{r['table']}"
        for r in rows
        if (r["schema"], r["table"]) not in EXEMPT and not r["has_canon_policy"]
    ]
    assert not offenders, (
        "These tenant_id tables lack a tenant_isolation policy whose USING and "
        "WITH CHECK both reference app.current_tenant (regression guard against "
        "USING true / missing WITH CHECK):\n  " + "\n  ".join(offenders)
    )


# ===========================================================================
# Keep the allowlist honest: every EXEMPT entry must (a) actually exist as a
# tenant_id table, and (b) genuinely be uncovered (else remove it).
# ===========================================================================

def test_exempt_allowlist_not_stale(django_db_setup):
    rows = _audit_rows()
    by_key = {(r["schema"], r["table"]): r for r in rows}
    for key in EXEMPT:
        assert key in by_key, (
            f"EXEMPT entry {key} is not a tenant_id table in {_SCHEMAS} — "
            "stale allowlist entry, remove it."
        )
        assert not _is_covered(by_key[key]), (
            f"EXEMPT entry {key} now HAS full RLS — it is no longer an exception. "
            "Remove it from EXEMPT so coverage stays asserted."
        )


# ===========================================================================
# clinical.observations VIEW must run with security_invoker so RLS on the
# underlying vital_readings/lab_results is applied through the VIEW.
# ===========================================================================

def test_observations_view_has_security_invoker(django_db_setup):
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT c.reloptions
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'clinical'
              AND c.relname = 'observations'
              AND c.relkind = 'v'
            """
        ).fetchone()

    if row is None:
        pytest.skip("clinical.observations VIEW absent in this schema version — skip.")

    reloptions = row[0] or []
    assert any("security_invoker" in opt and "true" in opt.lower() for opt in reloptions), (
        "clinical.observations VIEW must set security_invoker=true so RLS on "
        f"vital_readings/lab_results is enforced through it. reloptions={reloptions}"
    )

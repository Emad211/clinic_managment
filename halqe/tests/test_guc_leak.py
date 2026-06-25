"""
tests/test_guc_leak.py — GUC leak / recycled-connection simulation (ADR-0008)

Purpose:
  Verify that clear_tenant_guc() (called by TenantGucMiddleware at request
  start) actually erases a stale GUC value from a previously-used connection.
  If a stale GUC is NOT cleared, RLS would see the wrong tenant and return
  rows from the previous tenant — a silent data leak.

What "recycled connection" means here:
  With CONN_MAX_AGE=0 (the current invariant), Django closes and reopens the
  connection after each request, so the GUC is naturally gone.  These tests
  simulate the RISK scenario: what if the connection is reused (either because
  CONN_MAX_AGE>0 is mistakenly set, or because the pooler is not closing
  connections properly)?  We poison the GUC, call clear_tenant_guc(), and
  verify the poison is gone — proving the clear() is effective on a live
  connection.

Scenarios:
  1. set_tenant_guc(99) → clear_tenant_guc() → GUC must be '' on same conn.
  2. Authenticated request for tenant 1 sets GUC → clear_tenant_guc() (as
     middleware would on the *next* request) → GUC must be ''.
  3. Auth(tenant=1) → clear → RLS query: must return ZERO rows for tenant-1
     data (GUC is '', RLS sees no tenant → fail-closed).
  4. Auth(tenant=1) → GUC='1' → query returns tenant-1 rows → clear() →
     same query returns zero (confirms the GUC drives RLS, not a cached result).
  5. Sequence: auth(t1) → clear → auth(t2) → query must NOT see tenant-1 data.

Anti-false-green design:
  Tests that check "zero rows after clear" explicitly fail with the message
  "GUC LEAK — stale tenant GUC still visible after clear_tenant_guc()" if
  the query returns data.  The absence of that failure is the real assertion.
"""
from __future__ import annotations

import psycopg
import pytest

from django.db import connection as django_connection
from django.test import Client

from platform_core.tenant_context import set_tenant_guc, clear_tenant_guc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_guc() -> str:
    """Read app.current_tenant GUC on the Django default connection."""
    with django_connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_tenant', true)")
        row = cursor.fetchone()
        return (row[0] or "") if row else ""


def _count_tenant1_vitals() -> int:
    """Count vital_readings rows for tenant 1 on the Django default connection.

    With RLS enabled (slice5) and GUC='', this returns 0 (fail-closed).
    With GUC='1', this returns the real count seeded by conftest.
    """
    with django_connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM clinical.vital_readings WHERE tenant_id = 1"
        )
        row = cursor.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Scenario 1 — poison → clear → GUC is ''
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default"], transaction=True)
def test_clear_erases_stale_guc(seed_data):
    """
    Simulate a recycled connection:
      1. Poison the GUC with a fake tenant (99) — as if the previous request
         had authenticated for tenant 99 and left the connection in the pool.
      2. Call clear_tenant_guc() — as TenantGucMiddleware would at request start.
      3. Assert the GUC is now '' (empty string, missing_ok=true).

    If this fails, middleware's clear() has no effect → every subsequent
    request on this connection would see the poisoned tenant.
    """
    # Poison
    set_tenant_guc(99)
    guc_after_poison = _read_guc()
    assert guc_after_poison == "99", (
        f"Poison setup failed: expected GUC='99', got '{guc_after_poison}'"
    )

    # Clear (simulate middleware on the next request)
    clear_tenant_guc()

    guc_after_clear = _read_guc()
    assert guc_after_clear == "", (
        f"GUC LEAK — stale tenant GUC still visible after clear_tenant_guc(): "
        f"expected '', got '{guc_after_clear}'"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — auth(t1) → clear → GUC is '' (middleware-like sequence)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default"], transaction=True)
def test_clear_after_auth_leaves_empty_guc(seed_data):
    """
    Simulate the sequence: request N (authed, tenant 1) → request N+1 start.

    The autouse fixture sets GUC=1 before each test (simulating auth).
    We verify it is '1', then call clear_tenant_guc() (simulating middleware
    on the *next* request), then verify it is ''.
    """
    # autouse already set GUC=1; confirm it
    guc_before = _read_guc()
    assert guc_before == "1", (
        f"Expected GUC='1' from autouse fixture, got '{guc_before}'"
    )

    # Simulate middleware clearing for next request
    clear_tenant_guc()

    guc_after = _read_guc()
    assert guc_after == "", (
        f"GUC LEAK — GUC should be '' after clear, got '{guc_after}'"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — clear → RLS query returns 0 rows (fail-closed)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default"], transaction=True)
def test_rls_returns_zero_after_guc_cleared(seed_data):
    """
    After clear_tenant_guc(), a query on clinical.vital_readings (protected
    by RLS fail-closed policy in slice5) must return 0 rows.

    If this returns > 0 rows after clear, either:
      a) The GUC was NOT actually cleared (GUC LEAK), or
      b) RLS is not enforced (policy misconfiguration).
    Both are critical failures.
    """
    # Set GUC=1 explicitly (autouse already did this, but be explicit)
    set_tenant_guc(1)
    count_with_guc = _count_tenant1_vitals()
    assert count_with_guc > 0, (
        "Seed data sanity: expected > 0 vital_readings for tenant 1 with GUC='1'. "
        "Check that seed_data fixture inserted vitals."
    )

    # Simulate middleware clearing (next request, no auth)
    clear_tenant_guc()

    count_after_clear = _count_tenant1_vitals()
    assert count_after_clear == 0, (
        f"GUC LEAK — RLS should block all rows when GUC is '' (fail-closed), "
        f"but got {count_after_clear} rows. "
        f"Current GUC value: '{_read_guc()}'. "
        f"This means either clear_tenant_guc() did not work, or RLS policy "
        f"is not fail-closed. See ADR-0008 and slice5 RLS policy."
    )


# ---------------------------------------------------------------------------
# Scenario 4 — GUC='1' → rows visible → clear → rows gone (causal proof)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default"], transaction=True)
def test_rls_rows_appear_and_disappear_with_guc(seed_data):
    """
    Causal check: the same query returns rows when GUC='1' and zero rows
    when GUC=''.  This proves the GUC drives RLS, not a cached result.

    Flow:
      set_tenant_guc(1)   → query → count > 0   (rows visible)
      clear_tenant_guc()  → query → count == 0  (rows hidden by RLS)
    """
    set_tenant_guc(1)
    count_with = _count_tenant1_vitals()
    assert count_with > 0, (
        "Cannot run causal check: no vital_readings for tenant 1 with GUC='1'. "
        "Verify seed_data inserted vitals."
    )

    clear_tenant_guc()
    count_without = _count_tenant1_vitals()

    assert count_without == 0, (
        f"GUC LEAK — after clear_tenant_guc(), the same query returned "
        f"{count_without} rows (expected 0). "
        f"Current GUC: '{_read_guc()}'. "
        f"RLS is not enforcing the GUC contract."
    )


# ---------------------------------------------------------------------------
# Scenario 5 — auth(t1) → clear → auth(t2) — must NOT see tenant-1 data
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default"], transaction=True)
def test_tenant_switch_via_clear_then_reauth(seed_data):
    """
    Simulate two back-to-back requests on the same connection:
      Request N:   auth as tenant 1 → GUC='1' → query → sees tenant-1 rows.
      Request N+1: middleware clears → auth as tenant 2 → GUC='2' → query
                   must return 0 rows (tenant-2 has no vitals in seed).

    Proves that the clear→re-set sequence correctly isolates tenants even
    on a connection that was previously authenticated to a different tenant.
    """
    # Request N: tenant 1
    set_tenant_guc(1)
    count_t1 = _count_tenant1_vitals()
    assert count_t1 > 0, (
        "Seed sanity: no tenant-1 vitals visible with GUC='1'."
    )

    # Request N+1 start: middleware clears
    clear_tenant_guc()
    guc_cleared = _read_guc()
    assert guc_cleared == "", (
        f"Middleware clear failed: GUC='{guc_cleared}' (expected '')"
    )

    # Request N+1: auth as tenant 2 (no vitals seeded for tenant 2)
    set_tenant_guc(2)
    guc_t2 = _read_guc()
    assert guc_t2 == "2", (
        f"Re-auth for tenant 2 failed: GUC='{guc_t2}'"
    )

    # Tenant-2 must not see tenant-1 vital_readings
    count_t1_as_t2 = _count_tenant1_vitals()
    assert count_t1_as_t2 == 0, (
        f"GUC LEAK / RLS failure — tenant-2 session sees {count_t1_as_t2} "
        f"rows from tenant-1's vital_readings. "
        f"Current GUC: '{_read_guc()}'. "
        f"Cross-tenant data leak confirmed."
    )


# ---------------------------------------------------------------------------
# Invariant guard — CONN_MAX_AGE must be 0 in test environment
# ---------------------------------------------------------------------------

def test_conn_max_age_is_zero():
    """
    Structural guard: CONN_MAX_AGE must be 0 in all environments where this
    test suite runs (dev, CI, Docker).  A non-zero value would mean Django
    reuses connections across requests, making the GUC leak scenarios above
    live threats, not simulations.

    If this test fails, check settings.py and resolve_conn_max_age() in
    config/env.py — and read ADR-0008 before overriding.
    """
    from django.conf import settings
    assert settings.DATABASES["default"].get("CONN_MAX_AGE", 0) == 0, (
        "CONN_MAX_AGE must be 0 (one fresh connection per request). "
        "A non-zero value enables persistent connections which can carry "
        "stale GUC values across requests — see ADR-0008."
    )
    assert settings.DATABASES["accounting_read"].get("CONN_MAX_AGE", 0) == 0, (
        "CONN_MAX_AGE must be 0 on accounting_read too. "
        "See ADR-0008."
    )
